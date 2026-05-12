import os
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from datetime import datetime

load_dotenv()

# States for Registration
REG_NAME, REG_EMAIL, REG_ROLE, CHAT_MODE = range(4)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

# Helper to get DB models safely
def get_db():
    from app import app, db
    from models import User, Message, Meeting
    return app, db, User, Message, Meeting

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        
        if not user:
            # Check if user exists by username (if they used Mini App before)
            user = User.query.filter_by(username=update.effective_user.username).first()
            if user:
                user.telegram_id = user_id
                db.session.commit()
            else:
                await update.message.reply_text(
                    "👋 Welcome to the Counseling Hub!\n\n"
                    "It looks like you're not registered yet. Let's get you set up.\n"
                    "What is your **Full Name**?"
                )
                return REG_NAME

        return await show_main_menu(update, context, user)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    keyboard = [
        [KeyboardButton("🏠 My Dashboard"), KeyboardButton("💬 Chat with Mentor")],
        [KeyboardButton("📅 Meetings"), KeyboardButton("👤 My Profile")]
    ]
    if user.role == 'admin':
        keyboard.append([KeyboardButton("🛠️ Admin Panel")])
    elif user.role == 'mentor':
        keyboard.append([KeyboardButton("👥 My Clients")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = f"Welcome back, {user.full_name or user.username}! 🎯\nRole: **{user.role.capitalize()}**\n\nHow can we help you today?"
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

# Registration Flow
async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Great! Now, please provide your **Email Address**:")
    return REG_EMAIL

async def reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['email'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("Client (Seeking help)", callback_query_data='role_user')],
        [InlineKeyboardButton("Mentor (Professional)", callback_query_data='role_mentor')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("What is your role?", reply_markup=reply_markup)
    return REG_ROLE

async def reg_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = 'user' if query.data == 'role_user' else 'mentor'
    
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        # Create user
        new_user = User(
            username=update.effective_user.username or f"user_{update.effective_user.id}",
            email=context.user_data['email'],
            full_name=context.user_data['full_name'],
            role=role,
            telegram_id=str(update.effective_user.id)
        )
        new_user.set_password(os.urandom(12).hex()) # Random password for security
        db.session.add(new_user)
        db.session.commit()
        
        await query.edit_message_text(f"✅ Registration successful! You are now registered as a **{role}**.")
        return await show_main_menu(update, context, new_user)

# Dashboard & Features
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if not user:
            return await start(update, context)

        if text == "🏠 My Dashboard":
            mentor_name = "None"
            if user.role == 'user' and user.assigned_mentor_id:
                mentor = User.query.get(user.assigned_mentor_id)
                mentor_name = mentor.full_name or mentor.username
            
            dashboard_text = (
                f"📊 **Dashboard**\n\n"
                f"👤 Name: {user.full_name}\n"
                f"🏷️ Role: {user.role.capitalize()}\n"
                f"🤝 Mentor: {mentor_name}\n"
                f"📅 Join Date: {user.created_at.strftime('%Y-%m-%d')}"
            )
            await update.message.reply_text(dashboard_text, parse_mode='Markdown')

        elif text == "💬 Chat with Mentor":
            if user.role == 'user' and not user.assigned_mentor_id:
                await update.message.reply_text("❌ You don't have an assigned mentor yet. Please contact an admin.")
                return
            
            context.user_data['chat_active'] = True
            await update.message.reply_text(
                "💬 **Chat Mode Active**\n"
                "Everything you type now will be sent to your mentor/client.\n"
                "Type **/exit** to stop chatting and return to menu."
            )
            return CHAT_MODE

        elif text == "📅 Meetings":
            if user.role == 'mentor':
                meetings = Meeting.query.filter_by(mentor_id=user.id).all()
            else:
                meetings = Meeting.query.filter(
                    (Meeting.is_global == True) | (Meeting.client_id == user.id)
                ).all()
            
            if not meetings:
                await update.message.reply_text("No upcoming meetings found.")
                return
            
            msg = "📅 **Upcoming Meetings**\n\n"
            for m in meetings:
                msg += f"🔹 {m.title}\n⏰ {m.start_time.strftime('%Y-%m-%d %H:%M')}\n🔗 [Join Link]({m.meeting_link})\n\n"
            await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)

        elif text == "👥 My Clients" and user.role == 'mentor':
            clients = User.query.filter_by(assigned_mentor_id=user.id).all()
            if not clients:
                await update.message.reply_text("You have no assigned clients yet.")
                return
            msg = "👥 **Your Assigned Clients**\n\n"
            keyboard = []
            for c in clients:
                msg += f"• {c.full_name} (@{c.username})\n"
                keyboard.append([InlineKeyboardButton(f"Chat with {c.full_name}", callback_data=f"chat_with_{c.id}")])
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif text == "🛠️ Admin Panel" and user.role == 'admin':
            await show_admin_panel(update, context)

# Admin Handlers
async def handle_admin_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        if query.data == 'admin_list':
            users = User.query.all()
            msg = "👥 **All Users**\n\n"
            for u in users:
                msg += f"ID: {u.id} | {u.username} | {u.role}\n"
            await query.message.reply_text(msg, parse_mode='Markdown')
            
        elif query.data == 'admin_assign':
            users = User.query.filter_by(role='user').all()
            if not users:
                await query.message.reply_text("No users found to assign.")
                return
            
            keyboard = []
            for u in users:
                keyboard.append([InlineKeyboardButton(f"Assign: {u.full_name}", callback_data=f"assign_u_{u.id}")])
            await query.message.reply_text("Select a **User** to assign a mentor to:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif query.data.startswith('assign_u_'):
            u_id = int(query.data.split('_')[-1])
            context.user_data['assigning_user_id'] = u_id
            mentors = User.query.filter_by(role='mentor').all()
            keyboard = []
            for m in mentors:
                keyboard.append([InlineKeyboardButton(f"To Mentor: {m.full_name}", callback_data=f"assign_m_{m.id}")])
            await query.edit_message_text(f"Now select a **Mentor** for User ID {u_id}:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif query.data.startswith('assign_m_'):
            m_id = int(query.data.split('_')[-1])
            u_id = context.user_data.get('assigning_user_id')
            if not u_id:
                await query.message.reply_text("Assignment session expired. Try again.")
                return
            
            user = User.query.get(u_id)
            mentor = User.query.get(m_id)
            user.assigned_mentor_id = mentor.id
            db.session.commit()
            await query.edit_message_text(f"✅ Successfully assigned **{mentor.full_name}** as mentor for **{user.full_name}**.")

        elif query.data.startswith('chat_with_'):
            target_id = int(query.data.split('_')[-1])
            context.user_data['chat_partner_id'] = target_id
            context.user_data['chat_active'] = True
            target = User.query.get(target_id)
            await query.message.reply_text(
                f"💬 **Chat Mode Active** with {target.full_name}\n"
                "Type **/exit** to stop."
            )
            return CHAT_MODE

# Chat System
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/exit":
        context.user_data['chat_active'] = False
        await update.message.reply_text("Chat mode deactivated.")
        return await start(update, context)
    
    user_id = str(update.effective_user.id)
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        recipient_id = context.user_data.get('chat_partner_id')
        
        if not recipient_id:
            if user.role == 'user':
                recipient_id = user.assigned_mentor_id
            else:
                await update.message.reply_text("Please select a client to chat with from 'My Clients'.")
                return
            
        if not recipient_id:
            await update.message.reply_text("Could not find a chat partner.")
            return
        
        recipient = User.query.get(recipient_id)
        
        # Save message
        new_msg = Message(sender_id=user.id, recipient_id=recipient_id, content=update.message.text)
        db.session.add(new_msg)
        db.session.commit()
        
        # Forward to Telegram
        if recipient.telegram_id:
            try:
                await context.bot.send_message(
                    chat_id=recipient.telegram_id,
                    text=f"✉️ **New Message from {user.full_name}:**\n\n{update.message.text}",
                    parse_mode='Markdown'
                )
                await update.message.reply_text("✅ Sent")
            except:
                await update.message.reply_text("✅ Saved (Recipient currently offline)")
        else:
            await update.message.reply_text("✅ Saved (Recipient has no Telegram linked)")

async def assign_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        admin = User.query.filter_by(telegram_id=user_id, role='admin').first()
        if not admin: return
        
        try:
            u_id = int(context.args[0])
            m_id = int(context.args[1])
            user = User.query.get(u_id)
            mentor = User.query.get(m_id)
            
            if user and mentor and mentor.role == 'mentor':
                user.assigned_mentor_id = mentor.id
                db.session.commit()
                await update.message.reply_text(f"✅ Assigned {mentor.full_name} to {user.full_name}")
            else:
                await update.message.reply_text("❌ Invalid IDs or role.")
        except:
            await update.message.reply_text("Usage: `/assign [user_id] [mentor_id]`")

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Assign Mentors", callback_data='admin_assign')],
        [InlineKeyboardButton("List All Users", callback_data='admin_list')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛠️ **Admin Management**", reply_markup=reply_markup)

def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set.")
        return
    
    app = Application.builder().token(TOKEN).build()
    
    # Registration Conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
            REG_ROLE: [CallbackQueryHandler(reg_role, pattern='^role_')],
            CHAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("exit", start)],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("assign", assign_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    app.add_handler(CallbackQueryHandler(handle_admin_query, pattern='^admin_'))
    app.add_handler(CallbackQueryHandler(reg_role, pattern='^role_')) # Global fallback for role
    
    print("🤖 Telegram bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
