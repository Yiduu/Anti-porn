import os
import jwt
from datetime import datetime, timedelta
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL", "https://anti-porn.onrender.com")
SECRET_KEY = os.getenv("SECRET_KEY")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = jwt.encode(
        {"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET_KEY,
        algorithm="HS256"
    )
    mini_app_url = f"{RENDER_URL}/recovery?token={token}"
    keyboard = [[InlineKeyboardButton("Open Recovery App", web_app=WebAppInfo(url=mini_app_url))]]
    await update.message.reply_text(
        "🙏 Welcome to the Christian Recovery Companion.\n\n"
        "Tap the button below to open your dashboard.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Bot started polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
