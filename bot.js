'use strict';

const TelegramBot = require('node-telegram-bot-api');
const { createClient } = require('@supabase/supabase-js');
require('dotenv').config();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

const APP_URL = process.env.MINI_APP_URL || 'https://your-app.com';
const BOT_USERNAME = process.env.BOT_USERNAME || 'RecoveryBot';

// ─── Commands ─────────────────────────────────────────────────────────────────
bot.onText(/\/start(.*)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const param = match[1]?.trim();

  let text = `🙏 Welcome to the Anonymous Christian Recovery Community.\n\nThis is a safe, anonymous space for recovery.\n\nTap below to open the app:`;

  const keyboard = {
    inline_keyboard: [[{
      text: '🌟 Open Recovery App',
      web_app: { url: param ? `${APP_URL}?start=${param}` : APP_URL }
    }]]
  };

  await bot.sendMessage(chatId, text, { reply_markup: keyboard, parse_mode: 'Markdown' });
});

bot.onText(/\/help/, async (msg) => {
  await bot.sendMessage(msg.chat.id,
    `📖 *Recovery App Help*\n\n` +
    `• /start – Open the recovery app\n` +
    `• /verse – Get today's Bible verse\n` +
    `• /status – Check your account status\n\n` +
    `All interactions are anonymous. Your identity is protected.`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/verse/, async (msg) => {
  const { data } = await supabase.from('daily_verses').select('*').eq('is_active', true);
  if (data?.length) {
    const day = Math.floor(Date.now() / 86400000);
    const verse = data[day % data.length];
    await bot.sendMessage(msg.chat.id, `📖 *${verse.reference}*\n\n_${verse.text}_`, { parse_mode: 'Markdown' });
  }
});

bot.onText(/\/status/, async (msg) => {
  const { data: user } = await supabase.from('users').select('anonymous_id, role').eq('telegram_id', msg.from.id).single();
  if (!user) {
    await bot.sendMessage(msg.chat.id, '❌ Not registered. Open the app to register.');
    return;
  }
  await bot.sendMessage(msg.chat.id,
    `✅ *Account Status*\n\nAnonymous ID: \`${user.anonymous_id}\`\nRole: ${user.role}`,
    { parse_mode: 'Markdown' }
  );
});

// ─── Notification Helpers ─────────────────────────────────────────────────────
async function notifyMessage(to_telegram_id, from_anonymous_id) {
  const { data: settings } = await supabase.from('user_settings').select('notify_messages').eq('telegram_id', to_telegram_id).single();
  if (settings?.notify_messages === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  try {
    await bot.sendMessage(user.chat_id,
      `💬 New message from *${from_anonymous_id}*\n\nTap to reply:`,
      {
        parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: [[{ text: '📱 Open App', web_app: { url: APP_URL } }]] }
      }
    );
  } catch (err) {
    console.error('Bot notify error:', err.message);
  }
}

async function notifySessionInvite(to_telegram_id, sessionInfo) {
  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  const deepLink = `${APP_URL}?start=session_${sessionInfo.session_id}`;
  try {
    await bot.sendMessage(user.chat_id,
      `📹 *Session Invitation*\n\n` +
      `From: *${sessionInfo.host}*\n` +
      `Title: ${sessionInfo.title}\n` +
      `Scheduled: ${new Date(sessionInfo.scheduled_at).toLocaleString()}\n\n` +
      `Room password will be shown in the app.`,
      {
        parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: [[{ text: '🎥 Join Session', web_app: { url: deepLink } }]] }
      }
    );
  } catch (err) {
    console.error('Bot session notify error:', err.message);
  }
}

async function notifyMentorApproved(telegram_id) {
  const { data: user } = await supabase.from('users').select('chat_id, anonymous_id').eq('telegram_id', telegram_id).single();
  if (!user?.chat_id) return;
  try {
    await bot.sendMessage(user.chat_id,
      `🎉 *Congratulations, ${user.anonymous_id}!*\n\nYour mentor application has been approved. You are now a mentor in the recovery community.\n\nMay God use you to help others find freedom! 🙏`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) { console.error('Bot approve notify error:', err.message); }
}

async function broadcastToAll(message, role_filter) {
  let query = supabase.from('users').select('chat_id').eq('is_banned', false);
  if (role_filter) query = query.eq('role', role_filter);
  const { data: users } = await query;

  for (const user of users || []) {
    if (!user.chat_id) continue;
    try {
      await bot.sendMessage(user.chat_id, `📢 *Announcement*\n\n${message}`, { parse_mode: 'Markdown' });
      await new Promise(r => setTimeout(r, 50)); // Rate limit
    } catch {}
  }
}

// ─── Session reminder job ──────────────────────────────────────────────────────
async function sendSessionReminders() {
  const in30 = new Date(Date.now() + 30 * 60 * 1000).toISOString();
  const in31 = new Date(Date.now() + 31 * 60 * 1000).toISOString();

  const { data: sessions } = await supabase
    .from('video_sessions')
    .select('*, session_participants(telegram_id)')
    .eq('status', 'scheduled')
    .gte('scheduled_at', in30)
    .lt('scheduled_at', in31);

  for (const session of sessions || []) {
    for (const { telegram_id } of session.session_participants || []) {
      const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', telegram_id).single();
      if (!user?.chat_id) continue;
      try {
        await bot.sendMessage(user.chat_id,
          `⏰ *Session Starting Soon!*\n\n${session.title}\nBegins in 30 minutes.\n\nTap to join:`,
          {
            parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '🎥 Join Now', web_app: { url: `${APP_URL}?start=session_${session.id}` } }]] }
          }
        );
      } catch {}
    }
  }
}

// Run reminders every minute
setInterval(sendSessionReminders, 60 * 1000);

module.exports = { bot, notifyMessage, notifySessionInvite, notifyMentorApproved, broadcastToAll };
