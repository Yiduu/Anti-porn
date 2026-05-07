import os
import jwt
import logging
from datetime import datetime, timedelta
from telegram import (
    Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, MenuButtonWebApp
)
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL", "https://anti-porn.onrender.com")
SECRET_KEY = os.getenv("SECRET_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_webapp_url(user_id: str) -> str:
    """Generate a signed JWT token and return the full WebApp URL."""
    token = jwt.encode(
        {"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET_KEY,
        algorithm="HS256"
    )
    return f"{RENDER_URL}/recovery?token={token}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with a WebApp button."""
    user_id = update.effective_user.id
    webapp_url = generate_webapp_url(user_id)
    
    # Inline keyboard button (in the message)
    inline_keyboard = [[InlineKeyboardButton("🌐 Open Recovery App", web_app=WebAppInfo(url=webapp_url))]]
    
    # Reply keyboard button (persistent in the typing area)
    reply_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("🌐 Open Recovery App", web_app=WebAppInfo(url=webapp_url))]],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )
    
    await update.message.reply_text(
        "🙏 *Christian Recovery Companion*\n\n"
        "This is a safe, anonymous space for your journey.\n\n"
        "Tap the button below to open your dashboard.",
        reply_markup=reply_keyboard,
        parse_mode="Markdown"
    )
    
    # Also send the inline button as a fallback
    await update.message.reply_text(
        "Or use this button:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard)
    )

async def set_persistent_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the bot's permanent menu button (bottom of chat) to open the mini app."""
    user_id = update.effective_user.id
    webapp_url = generate_webapp_url(user_id)
    await context.bot.set_chat_menu_button(
        chat_id=user_id,
        menu_button=MenuButtonWebApp(text="Recovery App", web_app=WebAppInfo(url=webapp_url))
    )
    await update.message.reply_text("✅ Menu button updated! Now you can open the app from the bottom menu.")

def main():
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set. Exiting.")
        return
    if not SECRET_KEY:
        logger.error("❌ SECRET_KEY not set. Exiting.")
        return
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmenu", set_persistent_menu_button))  # optional: let user set menu button
    
    logger.info("✅ Bot started polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
