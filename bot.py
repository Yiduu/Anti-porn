import os
import jwt
import logging
import psycopg2
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
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

ADMIN_ID = os.getenv("ADMIN_ID")

def register_user(user_id, username):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Check if user exists
        cur.execute("SELECT user_id FROM users WHERE user_id = %s::text", (str(user_id),))
        existing = cur.fetchone()
        
        anonymous_name = username if username else f"Warrior_{str(user_id)[-4:]}"
        role = 'admin' if str(user_id) == str(ADMIN_ID) else 'user'
        
        if not existing:
            cur.execute(
                "INSERT INTO users (user_id, anonymous_name, recovery_role) VALUES (%s::text, %s, %s)",
                (str(user_id), anonymous_name, role)
            )
            logger.info(f"Registered new user: {user_id} as {role}")
        elif str(user_id) == str(ADMIN_ID):
            # Ensure the owner is ALWAYS an admin
            cur.execute("UPDATE users SET recovery_role = 'admin' WHERE user_id = %s::text", (str(user_id),))
            logger.info(f"Verified admin status for owner: {user_id}")
            
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error registering user: {e}")

def generate_webapp_url(user_id: str) -> str:
    """Generate a signed JWT token and return the landing page URL."""
    token = jwt.encode(
        {"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET_KEY,
        algorithm="HS256"
    )
    return f"{RENDER_URL}/landing?token={token}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with a WebApp button."""
    user = update.effective_user
    user_id = user.id
    
    # Register user in DB
    register_user(user_id, user.username or user.first_name)
    
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
        "Welcome to your safe, anonymous space. This journey is one of faith, strength, and renewal.\n\n"
        "Tap the button below to open your personal dashboard and start your recovery check-in.",
        reply_markup=reply_keyboard,
        parse_mode="Markdown"
    )
    
    # Also send the inline button as a fallback
    await update.message.reply_text(
        "Or access it directly here:",
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
    await update.message.reply_text("✅ Menu button updated! You can now open the app anytime from the bottom menu.")

def main():
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set. Exiting.")
        return
    if not SECRET_KEY:
        logger.error("❌ SECRET_KEY not set. Exiting.")
        return
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL not set. Exiting.")
        return
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmenu", set_persistent_menu_button))
    
    logger.info("✅ Bot started polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
