'use strict';

const TelegramBot = require('node-telegram-bot-api');
const { createClient } = require('@supabase/supabase-js');
require('dotenv').config();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

bot.on('polling_error', (error) => {
  if (error.code === 'ETELEGRAM' && error.message.includes('409 Conflict')) {
    console.warn('[Bot] 409 Conflict: Another bot instance is likely running with this token. Please check your Render dashboard or other active servers.');
  } else {
    console.error('[Bot] Polling error:', error.message);
  }
});

const APP_URL = process.env.MINI_APP_URL || 'https://your-app.com';

// ─── Formatting helpers ───────────────────────────────────────────────────────
function formatUserDateTime(dateStr, timezone = 'UTC') {
  try {
    return new Date(dateStr).toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: timezone
    });
  } catch (e) {
    return new Date(dateStr).toLocaleString();
  }
}

function formatUserDate(dateStr, timezone = 'UTC') {
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      dateStyle: 'medium',
      timeZone: timezone
    });
  } catch (e) {
    return new Date(dateStr).toLocaleDateString();
  }
}

// ─── Safe send helper – never throws, logs errors ────────────────────────────
async function safeSend(chatId, text, extra = {}) {
  if (!chatId) return;
  try {
    await bot.sendMessage(chatId, text, { parse_mode: 'Markdown', ...extra });
  } catch (err) {
    console.error(`[Bot] Failed to send to ${chatId}:`, err.message);
  }
}

// ─── Open App button shorthand ────────────────────────────────────────────────
function openAppBtn(url = APP_URL, label = '📱 Open App') {
  return { inline_keyboard: [[{ text: label, web_app: { url } }]] };
}

// ─── Commands ─────────────────────────────────────────────────────────────────
bot.onText(/\/start(.*)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const param = match[1]?.trim();
  const url = param ? `${APP_URL}?start=${param}` : APP_URL;

  await safeSend(chatId,
    `🙏 *Welcome to the Anonymous Christian Recovery Community.*\n\nThis is a safe, anonymous space for recovery from pornography addiction.\n\nTap below to open the app:`,
    { reply_markup: openAppBtn(url, '🌟 Open Recovery App') }
  );
});

bot.onText(/\/help/, async (msg) => {
  await safeSend(msg.chat.id,
    `📖 *Recovery App Help*\n\n` +
    `• /start – Open the recovery app\n` +
    `• /verse – Get today's Bible verse\n` +
    `• /status – Check your account status\n` +
    `• /mysessions – View your upcoming sessions\n` +
    `• /mymentor – See your assigned mentor\n\n` +
    `All interactions are anonymous. Your identity is protected.`
  );
});

bot.onText(/\/verse/, async (msg) => {
  const { data } = await supabase.from('daily_verses').select('*').eq('is_active', true);
  if (data?.length) {
    const day = Math.floor(Date.now() / 86400000);
    const verse = data[day % data.length];
    await safeSend(msg.chat.id, `📖 *${verse.reference}*\n\n_${verse.text}_`);
  } else {
    await safeSend(msg.chat.id, `📖 *Philippians 4:13*\n\n_I can do all this through him who gives me strength._`);
  }
});

bot.onText(/\/status/, async (msg) => {
  const { data: user } = await supabase
    .from('users')
    .select('anonymous_id, role, is_banned, created_at, user_settings(timezone)')
    .eq('telegram_id', msg.from.id)
    .single();

  if (!user) {
    await safeSend(msg.chat.id, '❌ Not registered. Open the app to register.', { reply_markup: openAppBtn() });
    return;
  }
  if (user.is_banned) {
    await safeSend(msg.chat.id, '🚫 Your account has been suspended. Contact support via the app.');
    return;
  }

  const tz = user.user_settings?.timezone || 'UTC';
  await safeSend(msg.chat.id,
    `✅ *Account Status*\n\n` +
    `Anonymous ID: \`${user.anonymous_id}\`\n` +
    `Role: *${user.role}*\n` +
    `Member since: ${formatUserDate(user.created_at, tz)}`
  );
});

bot.onText(/\/mysessions/, async (msg) => {
  const { data: user } = await supabase
    .from('users')
    .select('telegram_id, user_settings(timezone)')
    .eq('telegram_id', msg.from.id)
    .single();

  if (!user) { await safeSend(msg.chat.id, '❌ Not registered.'); return; }

  const tz = user.user_settings?.timezone || 'UTC';

  const { data: parts } = await supabase
    .from('session_participants')
    .select('session:session_id(id, title, scheduled_at, status, is_group)')
    .eq('telegram_id', user.telegram_id);

  const upcoming = (parts || [])
    .map(p => p.session)
    .filter(s => s && ['scheduled', 'active'].includes(s.status))
    .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at))
    .slice(0, 5);

  if (!upcoming.length) {
    await safeSend(msg.chat.id, '📅 You have no upcoming sessions.\n\nOpen the app to join or schedule one.', { reply_markup: openAppBtn() });
    return;
  }

  const lines = upcoming.map((s, i) =>
    `${i + 1}. *${s.title}*\n   📅 ${formatUserDateTime(s.scheduled_at, tz)}\n   ${s.is_group ? '👥 Group' : '👤 1-on-1'} · ${s.status}`
  ).join('\n\n');

  await safeSend(msg.chat.id, `📹 *Your Upcoming Sessions*\n\n${lines}`, { reply_markup: openAppBtn(APP_URL, '📱 Join Session') });
});

bot.onText(/\/mymentor/, async (msg) => {
  const { data: assignment } = await supabase
    .from('mentorship_assignments')
    .select('mentor:mentor_id(anonymous_id, user_settings(display_name, bio, specialization)), assigned_at, user:user_id(user_settings(timezone))')
    .eq('user_id', msg.from.id)
    .eq('is_active', true)
    .single();

  if (!assignment) {
    await safeSend(msg.chat.id, '🙏 You don\'t have an assigned mentor yet.\n\nOpen the app to browse mentors.', { reply_markup: openAppBtn() });
    return;
  }

  const m = assignment.mentor;
  const name = m.user_settings?.display_name || m.anonymous_id;
  const bio = m.user_settings?.bio || 'No bio provided';
  const spec = m.user_settings?.specialization ? `\nSpecialization: ${m.user_settings.specialization}` : '';
  const tz = assignment.user?.user_settings?.timezone || 'UTC';

  await safeSend(msg.chat.id,
    `👤 *Your Mentor*\n\n` +
    `Name: *${name}*\n` +
    `${bio}${spec}\n\n` +
    `Assigned: ${formatUserDate(assignment.assigned_at, tz)}`,
    { reply_markup: openAppBtn(APP_URL, '💬 Message Mentor') }
  );
});

// ─── Notification Helpers ─────────────────────────────────────────────────────

/**
 * Notify user of a new message from their mentor/mentee.
 */
async function notifyMessage(to_telegram_id, from_anonymous_id) {
  const { data: settings } = await supabase
    .from('user_settings').select('notify_messages').eq('telegram_id', to_telegram_id).single();
  if (settings?.notify_messages === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  await safeSend(user.chat_id,
    `💬 *New message from ${from_anonymous_id}*\n\nTap to open the chat and reply.`,
    { reply_markup: openAppBtn(APP_URL, '📱 Open Chat') }
  );
}

/**
 * Notify a mentee they have been invited to a video session.
 */
async function notifySessionInvite(to_telegram_id, sessionInfo) {
  const { data: settings } = await supabase
    .from('user_settings').select('notify_sessions, timezone').eq('telegram_id', to_telegram_id).single();
  if (settings?.notify_sessions === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  const tz = settings?.timezone || 'UTC';
  const deepLink = `${APP_URL}?start=session_${sessionInfo.session_id}`;
  await safeSend(user.chat_id,
    `📹 *Session Invitation!*\n\n` +
    `From: *${sessionInfo.host}*\n` +
    `Title: ${sessionInfo.title}\n` +
    `Scheduled: ${formatUserDateTime(sessionInfo.scheduled_at, tz)}\n\n` +
    `Tap below to join. The room password will be shown inside the app.`,
    { reply_markup: openAppBtn(deepLink, '🎥 Join Session') }
  );
}

/**
 * Notify a user their session is starting soon (30-min reminder).
 */
async function notifySessionReminder(to_telegram_id, sessionInfo) {
  const { data: settings } = await supabase
    .from('user_settings').select('notify_sessions, timezone').eq('telegram_id', to_telegram_id).single();
  if (settings?.notify_sessions === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  const tz = settings?.timezone || 'UTC';
  const deepLink = `${APP_URL}?start=session_${sessionInfo.session_id}`;
  await safeSend(user.chat_id,
    `⏰ *Session Starting Soon!*\n\n` +
    `*${sessionInfo.title}* begins in 30 minutes.\n` +
    `Scheduled: ${formatUserDateTime(sessionInfo.scheduled_at, tz)}`,
    { reply_markup: openAppBtn(deepLink, '🎥 Join Now') }
  );
}

/**
 * Notify a user their session has started / is now active.
 */
async function notifySessionStarted(to_telegram_id, sessionInfo) {
  const { data: settings } = await supabase
    .from('user_settings').select('notify_sessions').eq('telegram_id', to_telegram_id).single();
  if (settings?.notify_sessions === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;

  const deepLink = `${APP_URL}?start=session_${sessionInfo.session_id}`;
  await safeSend(user.chat_id,
    `🟢 *Your session is live!*\n\n*${sessionInfo.title}* has started. Join now!`,
    { reply_markup: openAppBtn(deepLink, '🎥 Join Now') }
  );
}

/**
 * Notify mentor/mentees a session was cancelled.
 */
async function notifySessionCancelled(to_telegram_id, sessionTitle) {
  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', to_telegram_id).single();
  if (!user?.chat_id) return;
  await safeSend(user.chat_id,
    `❌ *Session Cancelled*\n\nThe session _${sessionTitle}_ has been cancelled by the host.`
  );
}

/**
 * Notify a mentor their application was approved.
 */
async function notifyMentorApproved(telegram_id) {
  const { data: user } = await supabase.from('users').select('chat_id, anonymous_id').eq('telegram_id', telegram_id).single();
  if (!user?.chat_id) return;
  await safeSend(user.chat_id,
    `🎉 *Congratulations, ${user.anonymous_id}!*\n\n` +
    `Your mentor application has been *approved*. You are now a mentor in the recovery community.\n\n` +
    `May God use you to help others find freedom! 🙏\n\n` +
    `Open the app to set up your profile and start accepting mentees.`,
    { reply_markup: openAppBtn(APP_URL, '🌟 Open App') }
  );
}

/**
 * Notify a user their mentor application was rejected.
 */
async function notifyMentorRejected(telegram_id, admin_note) {
  const { data: user } = await supabase.from('users').select('chat_id, anonymous_id').eq('telegram_id', telegram_id).single();
  if (!user?.chat_id) return;
  const note = admin_note ? `\n\nAdmin note: _${admin_note}_` : '';
  await safeSend(user.chat_id,
    `📋 *Mentor Application Update*\n\n` +
    `Dear ${user.anonymous_id}, after review your application was *not approved* at this time.${note}\n\n` +
    `You are welcome to reapply after 90 days.`
  );
}

/**
 * Notify a mentor they have a new mentorship request.
 */
async function notifyMentorshipRequest(mentor_telegram_id, requesterName) {
  const { data: settings } = await supabase
    .from('user_settings').select('notify_messages').eq('telegram_id', mentor_telegram_id).single();
  if (settings?.notify_messages === false) return;

  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', mentor_telegram_id).single();
  if (!user?.chat_id) return;

  await safeSend(user.chat_id,
    `🙏 *New Mentorship Request!*\n\n*${requesterName}* has requested your mentorship.\n\nTap below to review and accept or decline.`,
    { reply_markup: openAppBtn(APP_URL, '📱 Review Request') }
  );
}

/**
 * Notify a user their mentorship request was accepted.
 */
async function notifyMentorshipAccepted(user_telegram_id, mentorName) {
  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', user_telegram_id).single();
  if (!user?.chat_id) return;
  await safeSend(user.chat_id,
    `✅ *Mentorship Accepted!*\n\n*${mentorName}* has accepted your mentorship request! 🎉\n\nOpen the app to send your first message.`,
    { reply_markup: openAppBtn(APP_URL, '💬 Message Mentor') }
  );
}

/**
 * Notify a user their mentorship request was rejected.
 */
async function notifyMentorshipRejected(user_telegram_id, mentorName) {
  const { data: user } = await supabase.from('users').select('chat_id').eq('telegram_id', user_telegram_id).single();
  if (!user?.chat_id) return;
  await safeSend(user.chat_id,
    `📋 *Mentorship Update*\n\n*${mentorName}* was unable to accept your request at this time.\n\nPlease browse other available mentors.`,
    { reply_markup: openAppBtn(APP_URL, '🔍 Find Mentor') }
  );
}

/**
 * Notify a mentor their mentorship was ended by admin.
 */
async function notifyMentorDisqualified(telegram_id) {
  const { data: user } = await supabase.from('users').select('chat_id, anonymous_id').eq('telegram_id', telegram_id).single();
  if (!user?.chat_id) return;
  await safeSend(user.chat_id,
    `⚠️ *Mentor Status Update*\n\nYour mentor status has been reviewed by an admin. Please open the app or contact support for more information.`
  );
}

/**
 * Send daily Bible verse to all users who opted in.
 */
async function sendDailyVerses() {
  const { data: verses } = await supabase.from('daily_verses').select('*').eq('is_active', true);
  if (!verses?.length) return;

  const day = Math.floor(Date.now() / 86400000);
  const verse = verses[day % verses.length];

  const { data: users } = await supabase
    .from('users')
    .select('chat_id')
    .eq('is_banned', false)
    .in('telegram_id',
      supabase.from('user_settings').select('telegram_id').eq('notify_daily_verse', true)
    );

  // Simpler: join in app code
  const { data: opted } = await supabase
    .from('user_settings')
    .select('telegram_id, timezone, users!inner(chat_id, is_banned)')
    .eq('notify_daily_verse', true)
    .eq('users.is_banned', false);

  for (const row of opted || []) {
    const chatId = row.users?.chat_id;
    if (!chatId) continue;
    const tz = row.timezone || 'UTC';
    await safeSend(chatId, `📖 *Daily Verse – ${formatUserDate(new Date(), tz)}*\n\n*${verse.reference}*\n\n_${verse.text}_`);
    await new Promise(r => setTimeout(r, 60)); // gentle throttle
  }
}

/**
 * Broadcast an admin message to all (or filtered) users.
 */
async function broadcastToAll(message, role_filter) {
  let query = supabase.from('users').select('chat_id').eq('is_banned', false);
  if (role_filter) query = query.eq('role', role_filter);
  const { data: users } = await query;

  for (const user of users || []) {
    if (!user.chat_id) continue;
    await safeSend(user.chat_id, `📢 *Announcement*\n\n${message}`);
    await new Promise(r => setTimeout(r, 50));
  }
}

// ─── Session Reminder Job (runs every minute) ─────────────────────────────────
async function sendSessionReminders() {
  const now = Date.now();
  const in30 = new Date(now + 30 * 60 * 1000).toISOString();
  const in31 = new Date(now + 31 * 60 * 1000).toISOString();

  const { data: sessions } = await supabase
    .from('video_sessions')
    .select('id, title, scheduled_at, session_participants(telegram_id)')
    .eq('status', 'scheduled')
    .gte('scheduled_at', in30)
    .lt('scheduled_at', in31);

  for (const session of sessions || []) {
    for (const { telegram_id } of session.session_participants || []) {
      await notifySessionReminder(telegram_id, {
        session_id: session.id,
        title: session.title,
        scheduled_at: session.scheduled_at,
      });
    }
  }
}

setInterval(sendSessionReminders, 60 * 1000);

// ─── Daily verse job – fires at 07:00 UTC every day ──────────────────────────
function scheduleDailyVerses() {
  const now = new Date();
  const next7 = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 7, 0, 0, 0));
  if (next7 <= now) next7.setUTCDate(next7.getUTCDate() + 1);
  const msUntil = next7 - now;
  setTimeout(() => {
    sendDailyVerses();
    setInterval(sendDailyVerses, 24 * 60 * 60 * 1000);
  }, msUntil);
}
scheduleDailyVerses();

module.exports = {
  bot,
  notifyMessage,
  notifySessionInvite,
  notifySessionReminder,
  notifySessionStarted,
  notifySessionCancelled,
  notifyMentorApproved,
  notifyMentorRejected,
  notifyMentorshipRequest,
  notifyMentorshipAccepted,
  notifyMentorshipRejected,
  notifyMentorDisqualified,
  broadcastToAll,
};
