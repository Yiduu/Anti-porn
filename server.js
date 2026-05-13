You are fixing a Telegram Mini App (Node.js + Supabase). The bot notifications (new message, session invite, mentor approved) never arrive.

**Current state:** 
- bot.js exists but is not loaded in server.js.
- Notification helper functions are never called from API routes.
- Bot uses webhook mode but no webhook endpoint is defined.

**Required fixes (only add, do not delete existing code):**

1. In server.js, at the top after other requires, add:
   const { bot, notifyMessage, notifySessionInvite, notifyMentorApproved, broadcastToAll } = require('./bot');

2. In routes/messages.js, inside POST /, after the message is inserted and before res.status(201).json(msg), add:
   const { data: sender } = await supabase.from('users').select('anonymous_id').eq('telegram_id', from_id).single();
   if (sender && !onlineUsers.has(String(to_id))) {
     await notifyMessage(to_id, sender.anonymous_id);
   }

3. In routes/sessions.js, inside POST /create, when mentee_id is provided, after inserting session_participants, add:
   const { data: mentee } = await supabase.from('users').select('chat_id').eq('telegram_id', mentee_id).single();
   if (mentee?.chat_id) {
     await notifySessionInvite(mentee_id, {
       session_id: session.id,
       host: hostUser.anonymous_id,
       title: session.title,
       scheduled_at: session.scheduled_at
     });
   }

4. In routes/admin.js, inside PATCH /applications/:id, when action === 'approved', after updating the user role, add:
   const { notifyMentorApproved } = require('./bot');
   await notifyMentorApproved(app.telegram_id);

5. In bot.js, change the bot initialization line to force polling (more reliable on free tier):
   const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

Output only the exact code changes – show each file with the new lines clearly marked.
