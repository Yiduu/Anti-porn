import os
import time
import uuid
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

# States for Conversations
REG_NAME, REG_EMAIL, REG_ROLE, CHAT_MODE = range(4)
EDIT_NAME, EDIT_EMAIL = range(4, 6)
MEET_TITLE, MEET_TIME, MEET_CLIENT = range(6, 9)

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
                return await show_main_menu(update, context, user)
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
        [KeyboardButton("🏠 My Dashboard"), KeyboardButton("💬 Chat Hub")],
        [KeyboardButton("📅 Meetings"), KeyboardButton("👤 My Profile")]
    ]
    if user.role == 'admin':
        keyboard.append([KeyboardButton("🛠️ Admin Panel")])
    elif user.role == 'mentor':
        keyboard.append([KeyboardButton("👥 My Clients"), KeyboardButton("➕ Create Meeting")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = (
        f"👋 Welcome back, **{user.full_name or user.username}**!\n"
        f"Role: `{user.role.capitalize()}`\n\n"
        "How can we help you today?"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # If called from a callback, we might need to send a new message
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
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
    await update.message.reply_text("What is your role in the community?", reply_markup=reply_markup)
    return REG_ROLE

async def reg_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = 'user' if query.data == 'role_user' else 'mentor'
    
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        new_user = User(
            username=update.effective_user.username or f"user_{update.effective_user.id}",
            email=context.user_data['email'],
            full_name=context.user_data['full_name'],
            role=role,
            telegram_id=str(update.effective_user.id)
        )
        new_user.set_password(os.urandom(12).hex())
        db.session.add(new_user)
        db.session.commit()
        
        await query.edit_message_text(f"✅ Registration complete! You are now set up as a **{role.capitalize()}**.")
        return await show_main_menu(update, context, new_user)

# Dashboard & Features
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=user_id).first()
        if not user: return await start(update, context)

        if text == "🏠 My Dashboard":
            mentor_name = "None"
            if user.role == 'user' and user.assigned_mentor_id:
                mentor = User.query.get(user.assigned_mentor_id)
                mentor_name = mentor.full_name or mentor.username
            
            dashboard_text = (
                f"📊 **System Status**\n\n"
                f"👤 **Name:** {user.full_name}\n"
                f"🏷️ **Role:** {user.role.capitalize()}\n"
                f"🤝 **Mentor:** {mentor_name}\n"
                f"📅 **Member Since:** {user.created_at.strftime('%B %Y')}"
            )
            await update.message.reply_text(dashboard_text, parse_mode='Markdown')

        elif text == "💬 Chat Hub":
            if user.role == 'user':
                if not user.assigned_mentor_id:
                    await update.message.reply_text("❌ You don't have an assigned mentor yet. Please wait for an admin to assign one.")
                    return
                context.user_data['chat_partner_id'] = user.assigned_mentor_id
                context.user_data['chat_active'] = True
                mentor = User.query.get(user.assigned_mentor_id)
                await update.message.reply_text(f"💬 **Chatting with Mentor:** {mentor.full_name}\nType your message below. Type **/exit** to stop.")
                return CHAT_MODE
            else:
                await update.message.reply_text("Use '👥 My Clients' to select someone to chat with.")

        elif text == "📅 Meetings":
            await show_meetings(update, context, user)

        elif text == "👤 My Profile":
            msg = f"👤 **Profile Info**\n\nName: {user.full_name}\nEmail: {user.email}\n\nUse buttons below to edit:"
            keyboard = [[InlineKeyboardButton("Edit Name", callback_data='edit_name'), InlineKeyboardButton("Edit Email", callback_data='edit_email')]]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif text == "👥 My Clients" and user.role == 'mentor':
            await show_mentor_clients(update, context, user)

        elif text == "➕ Create Meeting" and user.role == 'mentor':
            await update.message.reply_text("What is the **Title** of the meeting?")
            return MEET_TITLE

        elif text == "🛠️ Admin Panel" and user.role == 'admin':
            await show_admin_panel(update, context)

# Profile Editing
async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Enter your new **Full Name**:")
    return EDIT_NAME

async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        user = User.query.filter_by(telegram_id=str(update.effective_user.id)).first()
        user.full_name = update.message.text
        db.session.commit()
        await update.message.reply_text(f"✅ Name updated to: {user.full_name}")
        return await show_main_menu(update, context, user)

# Meeting Creation Flow (Mentor)
async def meet_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['meet_title'] = update.message.text
    await update.message.reply_text("When should the meeting start? (Format: YYYY-MM-DD HH:MM)\nExample: 2024-12-25 15:30")
    return MEET_TIME

async def meet_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dt = datetime.strptime(update.message.text, '%Y-%m-%d %H:%M')
        context.user_data['meet_time'] = dt
    except:
        await update.message.reply_text("❌ Invalid format. Please use YYYY-MM-DD HH:MM")
        return MEET_TIME
    
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        user = User.query.filter_by(telegram_id=str(update.effective_user.id)).first()
        clients = User.query.filter_by(assigned_mentor_id=user.id).all()
        keyboard = [[InlineKeyboardButton("Global (All Clients)", callback_data='meet_c_0')]]
        for c in clients:
            keyboard.append([InlineKeyboardButton(f"Private: {c.full_name}", callback_data=f"meet_c_{c.id}")])
        
        await update.message.reply_text("Who is this meeting for?", reply_markup=InlineKeyboardMarkup(keyboard))
        return MEET_CLIENT

async def meet_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    client_id = int(query.data.split('_')[-1])
    
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        mentor = User.query.filter_by(telegram_id=str(update.effective_user.id)).first()
        room_name = f"counseling_{uuid.uuid4().hex[:8]}"
        new_meeting = Meeting(
            mentor_id=mentor.id,
            client_id=client_id if client_id != 0 else None,
            is_global=(client_id == 0),
            title=context.user_data['meet_title'],
            start_time=context.user_data['meet_time'],
            meeting_link=f"https://meet.jit.si/{room_name}"
        )
        db.session.add(new_meeting)
        db.session.commit()
        
        await query.edit_message_text(f"✅ **Meeting Scheduled!**\n\nTitle: {new_meeting.title}\nTime: {new_meeting.start_time}\nLink: {new_meeting.meeting_link}")
        
        # Notify Client
        if client_id != 0:
            client = User.query.get(client_id)
            if client.telegram_id:
                try:
                    await context.bot.send_message(
                        chat_id=client.telegram_id,
                        text=f"📅 **New Meeting Scheduled with your Mentor!**\n\nTitle: {new_meeting.title}\nTime: {new_meeting.start_time}\n[Join Link]({new_meeting.meeting_link})",
                        parse_mode='Markdown'
                    )
                except: pass
        return await show_main_menu(update, context, mentor)

# Administrative Features
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Assign Mentors", callback_data='admin_assign')],
        [InlineKeyboardButton("List All Users", callback_data='admin_list')],
        [InlineKeyboardButton("Global Broadcast", callback_data='admin_broadcast')]
    ]
    await update.message.reply_text("🛠️ **Admin Management Hub**", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_admin_queries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        if query.data == 'admin_list':
            users = User.query.all()
            msg = "👥 **System Users**\n\n"
            for u in users:
                msg += f"`ID:{u.id}` | {u.full_name} | {u.role}\n"
            await query.message.reply_text(msg, parse_mode='Markdown')
        elif query.data == 'admin_assign':
            # Logic from previous update
            users = User.query.filter_by(role='user').all()
            keyboard = [[InlineKeyboardButton(f"Assign: {u.full_name}", callback_data=f"assign_u_{u.id}")] for u in users]
            await query.message.reply_text("Select a client:", reply_markup=InlineKeyboardMarkup(keyboard))

# Chat System
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/exit":
        context.user_data['chat_active'] = False
        await update.message.reply_text("Exit chat mode.")
        return await start(update, context)
    
    partner_id = context.user_data.get('chat_partner_id')
    if not partner_id: return
    
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        me = User.query.filter_by(telegram_id=str(update.effective_user.id)).first()
        partner = User.query.get(partner_id)
        
        # Save & Forward
        new_msg = Message(sender_id=me.id, recipient_id=partner.id, content=update.message.text)
        db.session.add(new_msg)
        db.session.commit()
        
        if partner.telegram_id:
            try:
                await context.bot.send_message(
                    chat_id=partner.telegram_id,
                    text=f"✉️ **Message from {me.full_name}:**\n\n{update.message.text}",
                    parse_mode='Markdown'
                )
            except: pass
    await update.message.reply_text("✅")

async def show_meetings(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        if user.role == 'mentor':
            meetings = Meeting.query.filter_by(mentor_id=user.id).order_by(Meeting.start_time).all()
        else:
            meetings = Meeting.query.filter((Meeting.is_global == True) | (Meeting.client_id == user.id)).order_by(Meeting.start_time).all()
        
        if not meetings:
            await update.message.reply_text("No upcoming meetings.")
            return
        
        msg = "📅 **Your Meetings**\n\n"
        for m in meetings:
            msg += f"🔹 **{m.title}**\n⏰ {m.start_time.strftime('%Y-%m-%d %H:%M')}\n🔗 [Join Jitsi]({m.meeting_link})\n\n"
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)

async def show_mentor_clients(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    app, db, User, Message, Meeting = get_db()
    with app.app_context():
        clients = User.query.filter_by(assigned_mentor_id=user.id).all()
        if not clients:
            await update.message.reply_text("No clients assigned.")
            return
        msg = "👥 **Your Clients**\nSelect one to start chatting:"
        keyboard = [[InlineKeyboardButton(f"💬 {c.full_name}", callback_data=f"chat_with_{c.id}")] for c in clients]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    app, db, User, Message, Meeting = get_db()
    
    with app.app_context():
        if data.startswith('chat_with_'):
            await query.answer()
            c_id = int(data.split('_')[-1])
            context.user_data['chat_partner_id'] = c_id
            context.user_data['chat_active'] = True
            client = User.query.get(c_id)
            await query.message.reply_text(f"💬 **Chatting with Client:** {client.full_name}\nType your message below. Type **/exit** to stop.")
            return CHAT_MODE
        elif data == 'edit_name':
            await query.answer()
            await query.message.reply_text("Enter your new **Full Name**:")
            return EDIT_NAME
        # ... other admin/role handlers ...
        return await handle_admin_queries(update, context)

def main():
    if not TOKEN: return
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
            REG_ROLE: [CallbackQueryHandler(reg_role, pattern='^role_')],
            CHAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)],
            MEET_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, meet_title)],
            MEET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, meet_time)],
            MEET_CLIENT: [CallbackQueryHandler(meet_client, pattern='^meet_c_')],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("exit", start)],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🤖 Full-Service Bot Polling...")
    app.run_polling()

if __name__ == '__main__':
    main()
