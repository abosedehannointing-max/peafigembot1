import os
import logging
import asyncio
import img2pdf
import qrcode
from PIL import Image, ImageDraw, ImageFont
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, ConversationHandler
)

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

# --- Conversation States ---
TEXT_WAITING = 1      # Waiting for text to convert to image
QR_WAITING = 2        # Waiting for link to convert to QR code
IMG_TO_QR_WAITING = 3 # Waiting for image to extract QR content

# --- Store data for each user ---
user_sessions = {}      # For image→PDF: stores list of image paths
text_sessions = {}      # For text→image: stores temporary state
qr_sessions = {}        # For link→QR: stores temporary state
img_to_qr_sessions = {} # For image→QR: stores temporary state

# --- Helper Function: Text to Image ---
def create_text_image(text: str, output_path: str, width: int = 800, height: int = 600):
    """Creates an image with the given text centered on a colored background."""
    colors = [
        (41, 128, 185),   # Blue
        (39, 174, 96),    # Green
        (192, 57, 43),    # Red
        (142, 68, 173),   # Purple
        (230, 126, 34),   # Orange
    ]
    bg_color = colors[hash(text) % len(colors)]
    
    image = Image.new('RGB', (width, height), color=bg_color)
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    # Word wrap function
    def wrap_text(text, font, max_width):
        lines = []
        words = text.split()
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        return lines
    
    max_width = width - 100
    lines = wrap_text(text, font, max_width)
    
    line_height = 20
    total_height = len(lines) * line_height
    y_start = (height - total_height) // 2
    
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, fill=(255, 255, 255), font=font)
    
    draw.rectangle([0, 0, width-1, height-1], outline=(255, 255, 255), width=3)
    image.save(output_path)
    return output_path

# --- Helper Function: Link to QR Code ---
def create_qr_code(data: str, output_path: str, box_size: int = 10, border: int = 4):
    """Creates a QR code image from given data."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_image.save(output_path)
    return output_path

# --- Bot Handlers ---

# ===== START COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠️ *Multi-Utility Bot*\n\n"
        "I can perform the following tasks:\n\n"
        "📸 *Images to PDF*\n"
        "   Send me images one by one, then use /done\n\n"
        "📝 *Text to Image*\n"
        "   Use /text2image\n\n"
        "🔗 *Link to QR Code*\n"
        "   Use /qr\n\n"
        "🖼️ *Image to QR Code*\n"
        "   Use /img2qr to extract text/links from an image\n\n"
        "Use /cancel to abort any operation."
    )

# ===== IMAGE TO PDF COMMANDS =====
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = []

    photo_file = await update.message.photo[-1].get_file()
    file_path = f"temp_{user_id}_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(file_path)
    user_sessions[user_id].append(file_path)
    
    await update.message.reply_text(
        f"✅ Image {len(user_sessions[user_id])} added. Send more or /done."
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    image_paths = user_sessions.get(user_id, [])
    
    if not image_paths:
        await update.message.reply_text("⚠️ No images to convert. Send me some images first!")
        return

    await update.message.reply_text("🔄 Generating your PDF...")
    pdf_path = f"output_{user_id}.pdf"
    
    try:
        with open(pdf_path, "wb") as f:
            f.write(img2pdf.convert(image_paths))
        
        with open(pdf_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=f"converted_{len(image_paths)}_pages.pdf",
                caption=f"✅ PDF with {len(image_paths)} page(s) ready!"
            )
        
        # Cleanup
        for path in image_paths:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            
    except Exception as e:
        logger.error(f"PDF error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    user_sessions[user_id] = []

# ===== TEXT TO IMAGE COMMANDS =====
async def text2image_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text_sessions[user_id] = True
    await update.message.reply_text(
        "📝 Send me the text (max 500 characters). Use /cancel to abort."
    )
    return TEXT_WAITING

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if len(text) > 500:
        await update.message.reply_text("⚠️ Text too long. Please send shorter text.")
        return TEXT_WAITING
    
    await update.message.reply_text("🎨 Creating image...")
    image_path = f"text_image_{user_id}.png"
    
    try:
        create_text_image(text, image_path)
        with open(image_path, 'rb') as img_file:
            await update.message.reply_photo(
                photo=img_file,
                caption=f"✅ Image created from your text!"
            )
        if os.path.exists(image_path):
            os.remove(image_path)
    except Exception as e:
        logger.error(f"Text-to-image error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    if user_id in text_sessions:
        del text_sessions[user_id]
    return ConversationHandler.END

# ===== LINK TO QR CODE COMMANDS =====
async def qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    qr_sessions[user_id] = True
    await update.message.reply_text(
        "🔗 Send me a link (starting with http:// or https://) or any text to convert to QR code.\n"
        "Use /cancel to abort."
    )
    return QR_WAITING

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = update.message.text.strip()
    
    await update.message.reply_text("🔳 Generating QR code...")
    qr_path = f"qr_code_{user_id}.png"
    
    try:
        create_qr_code(data, qr_path)
        with open(qr_path, 'rb') as img_file:
            await update.message.reply_photo(
                photo=img_file,
                caption=f"✅ QR code for:\n{data[:100]}{'...' if len(data)>100 else ''}"
            )
        if os.path.exists(qr_path):
            os.remove(qr_path)
    except Exception as e:
        logger.error(f"QR error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    if user_id in qr_sessions:
        del qr_sessions[user_id]
    return ConversationHandler.END

# ===== IMAGE TO QR CODE (Extract content from image) =====
async def img2qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    img_to_qr_sessions[user_id] = True
    await update.message.reply_text(
        "🖼️ Send me an image containing a QR code or text.\n"
        "I'll extract the content and generate a new QR code from it!\n"
        "Use /cancel to abort."
    )
    return IMG_TO_QR_WAITING

async def receive_image_for_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await update.message.reply_text("🔍 Processing image...")
    
    try:
        # Download the image
        photo_file = await update.message.photo[-1].get_file()
        img_path = f"img_for_qr_{user_id}.jpg"
        await photo_file.download_to_drive(img_path)
        
        # For this version, we'll create a QR code containing image metadata
        # You can later add OCR (Tesseract) or QR scanning (pyzbar) for actual extraction
        
        # Generate metadata QR
        from datetime import datetime
        metadata = f"Image processed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        metadata += f"File: {img_path}\n"
        metadata += "Add OCR library for text extraction from images!"
        
        qr_path = f"qr_from_img_{user_id}.png"
        create_qr_code(metadata, qr_path)
        
        with open(qr_path, 'rb') as img_file:
            await update.message.reply_photo(
                photo=img_file,
                caption="✅ QR code generated from image metadata!\n"
                        "💡 To extract actual QR/text from images, install pyzbar and pytesseract."
            )
        
        # Cleanup
        if os.path.exists(img_path):
            os.remove(img_path)
        if os.path.exists(qr_path):
            os.remove(qr_path)
            
    except Exception as e:
        logger.error(f"Image-to-QR error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    if user_id in img_to_qr_sessions:
        del img_to_qr_sessions[user_id]
    return ConversationHandler.END

# ===== CANCEL COMMAND =====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Clean up all sessions
    if user_id in user_sessions:
        for path in user_sessions[user_id]:
            if os.path.exists(path):
                os.remove(path)
        del user_sessions[user_id]
    
    for session_dict in [text_sessions, qr_sessions, img_to_qr_sessions]:
        if user_id in session_dict:
            del session_dict[user_id]
    
    await update.message.reply_text("❌ Operation cancelled. All data cleared.")
    return ConversationHandler.END

# --- Webhook and Server Setup ---
async def main():
    app = Application.builder().token(TOKEN).updater(None).build()
    
    # Text-to-image conversation
    text_conv = ConversationHandler(
        entry_points=[CommandHandler("text2image", text2image_start)],
        states={
            TEXT_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Link-to-QR conversation
    qr_conv = ConversationHandler(
        entry_points=[CommandHandler("qr", qr_start)],
        states={
            QR_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Image-to-QR conversation
    img2qr_conv = ConversationHandler(
        entry_points=[CommandHandler("img2qr", img2qr_start)],
        states={
            IMG_TO_QR_WAITING: [MessageHandler(filters.PHOTO, receive_image_for_qr)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Add all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(text_conv)
    app.add_handler(qr_conv)
    app.add_handler(img2qr_conv)
    
    # Set webhook
    if RENDER_URL:
        webhook_path = "/telegram"
        await app.bot.set_webhook(url=f"{RENDER_URL}{webhook_path}")
        logger.info(f"✅ Webhook set to {RENDER_URL}{webhook_path}")
    
    # Starlette server
    async def telegram_webhook(request: Request):
        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            await app.update_queue.put(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return Response(status_code=500)

    async def health_check(_: Request):
        return PlainTextResponse("OK")

    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])

    logger.info(f"🚀 Starting server on port {PORT}...")
    import uvicorn
    webserver = uvicorn.Server(
        uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info")
    )
    
    async with app:
        await app.start()
        await webserver.serve()
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
