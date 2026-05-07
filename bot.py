import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
RENDER_URL = os.getenv("RENDER_URL", "https://your-app.onrender.com")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = jwt.encode({"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)}, os.getenv("SECRET_KEY"))
    mini_app_url = f"{RENDER_URL}/recovery?token={token}"
    keyboard = [[InlineKeyboardButton("Open Recovery App", web_app=WebAppInfo(url=mini_app_url))]]
    await update.message.reply_text(
        "🙏 Welcome to the Christian Recovery Companion.\n\n"
        "This bot will send you reminders and notifications, but all services are inside the web app.\n"
        "Tap the button below to access your dashboard.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    logger.info("Recovery bot started (polling).")
    app.run_polling()

if __name__ == "__main__":
    main()
