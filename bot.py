import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from PIL import Image, ImageDraw, ImageFont
import qrcode
import io
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store user sessions for PDF collection
user_sessions = {}

# Start command - WITH REDIRECT WELCOME MESSAGE
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.first_name
    
    # Create inline keyboard button for the sports channel
    keyboard = [
        [InlineKeyboardButton("🔥 JOIN SPORTS COMMUNITY 🔥", url="https://t.me/nba_nfl_mlb_basketball_bets")],
        [InlineKeyboardButton("⚡ CONTINUE TO BOT ⚡", callback_data="continue_to_bot")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Welcome message with redirect
    welcome_text = f"""
👋 Welcome {username}!

📊 *Sports Discussion & Match Analysis*

Join an active community of sports fans!

⚽ 🏀 🏈 ⚾ 🎾

`-18+ | For entertainment purposes only`

---
🛠️ *Bot Features available after joining:*
• Images to PDF
• Text to Image  
• Link to QR Code
• Image to QR Code
"""
    
    await update.message.reply_text(
        welcome_text, 
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Handle button callback
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "continue_to_bot":
        bot_features = """
🛠️ *Multi-Utility Bot - Now Active!*

Here's what I can do for you:

📸 *Images to PDF*
   Send me images one by one, then use /done

📝 *Text to Image*
   Use /text2image <your text>

🔗 *Link to QR Code*
   Use /qr <your link>

🖼️ *Image to QR Code*
   Send me an image with QR code

Use /cancel to abort any operation.

⚠️ *Reminder:* Join our sports community for match analysis!
👉 @nba_nfl_mlb_basketball_bets
"""
        await query.edit_message_text(bot_features, parse_mode='Markdown')

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await update.message.reply_text("✅ Operation cancelled.")

# Handle images for PDF
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {'mode': 'collecting_images', 'images': []}
    
    if user_sessions[user_id].get('mode') == 'collecting_images':
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        user_sessions[user_id]['images'].append(photo_bytes)
        await update.message.reply_text(f"✅ Image {len(user_sessions[user_id]['images'])} received. Send more or use /done")

# Create PDF from collected images
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_sessions or not user_sessions[user_id].get('images'):
        await update.message.reply_text("❌ No images to convert. Send images first, then use /done")
        return
    
    images = user_sessions[user_id]['images']
    await update.message.reply_text(f"📝 Converting {len(images)} images to PDF...")
    
    try:
        pdf_images = []
        for img_bytes in images:
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            pdf_images.append(img)
        
        pdf_bytes = io.BytesIO()
        pdf_images[0].save(pdf_bytes, format='PDF', save_all=True, append_images=pdf_images[1:])
        pdf_bytes.seek(0)
        
        await update.message.reply_document(
            document=pdf_bytes,
            filename='converted.pdf',
            caption=f"✅ Converted {len(images)} images to PDF"
        )
        
        del user_sessions[user_id]
        
        # Add reminder about sports channel
        await update.message.reply_text(
            "⚡ *Enjoyed this?* Join our sports community for more!\n👉 @nba_nfl_mlb_basketball_bets",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"PDF creation error: {e}")
        await update.message.reply_text("❌ Failed to create PDF. Please try again.")

# Text to Image
async def text2image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide text. Usage: /text2image <your text>")
        return
    
    text = ' '.join(context.args)
    await update.message.reply_text(f"🖼️ Converting to image...")
    
    try:
        img = Image.new('RGB', (800, 400), color='white')
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
        
        # Word wrap
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            line_text = ' '.join(current_line)
            bbox = draw.textbbox((0, 0), line_text, font=font)
            if bbox[2] - bbox[0] > 750:
                current_line.pop()
                lines.append(' '.join(current_line))
                current_line = [word]
        if current_line:
            lines.append(' '.join(current_line))
        
        y = 50
        for line in lines:
            draw.text((50, y), line, fill='black', font=font)
            y += 35
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        await update.message.reply_photo(
            photo=img_bytes,
            caption="✅ Text converted to image"
        )
        
    except Exception as e:
        logger.error(f"Text2Image error: {e}")
        await update.message.reply_text("❌ Failed to convert text to image")

# Generate QR from text/link
async def generate_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide text/link. Usage: /qr <text or link>")
        return
    
    text = ' '.join(context.args)
    await update.message.reply_text(f"🔲 Generating QR code...")
    
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(text)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format='PNG')
        qr_bytes.seek(0)
        
        await update.message.reply_photo(
            photo=qr_bytes,
            caption="✅ QR Code generated"
        )
        
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        await update.message.reply_text("❌ Failed to generate QR code")

# Extract text from QR in image
async def qr_from_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("❌ Please send an image containing a QR code")
        return
    
    await update.message.reply_text("🔍 Scanning QR code from image...")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        files = {'file': ('qr.jpg', photo_bytes, 'image/jpeg')}
        response = requests.post('https://api.qrserver.com/v1/read-qr-code/', files=files)
        
        if response.status_code == 200:
            data = response.json()
            if data and data[0]['symbol'][0]['data']:
                qr_text = data[0]['symbol'][0]['data']
                await update.message.reply_text(f"✅ QR Code contains:\n\n`{qr_text}`", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ No QR code found in the image")
        else:
            await update.message.reply_text("❌ Failed to read QR code")
            
    except Exception as e:
        logger.error(f"QR decode error: {e}")
        await update.message.reply_text("❌ Failed to read QR code from image")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ An error occurred. Please try again.")

# Main function
def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("❌ No token found! Set TELEGRAM_BOT_TOKEN environment variable")
        return
    
    logger.info("🤖 Starting bot...")
    
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("text2image", text2image))
    application.add_handler(CommandHandler("qr", generate_qr))
    application.add_handler(CommandHandler("img2qr", qr_from_image))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_image))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("✅ Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
