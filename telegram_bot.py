import os
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://your-app.onrender.com/miniapp')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Open Counseling App 🎯", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Welcome to the Counseling Platform!\n\n"
        "Click the button below to open the Mini App.\n"
        "Register, chat with your mentor, schedule video meetings, and more.",
        reply_markup=reply_markup
    )

def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set. Bot will not run.")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("🤖 Telegram bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
