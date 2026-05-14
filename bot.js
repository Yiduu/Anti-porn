'use strict';

const TelegramBot = require('node-telegram-bot-api');
const { createClient } = require('@supabase/supabase-js');
const axios = require('axios');
const { v4: uuidv4 } = require('uuid');
require('dotenv').config();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);
const bot = new TelegramBot(process.env.TELEGRAM_BOT_TOKEN, { polling: true });

const APP_URL = process.env.MINI_APP_URL || 'https://your-app.com';

// ─── State Management ─────────────────────────────────────────────────────────
const userStates = new Map(); // telegram_id -> { step: string, targetId: bigint, tempData: object }
const lastReplyTarget = new Map(); // telegram_id -> partner_telegram_id

function setState(chatId, step, targetId = null, tempData = {}) {
  userStates.set(chatId, { step, targetId, tempData });
}

function clearState(chatId) {
  userStates.delete(chatId);
}

function getState(chatId) {
  return userStates.get(chatId);
}

// ─── Formatting Helpers ───────────────────────────────────────────────────────
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

// ─── Safe Send Helper ──────────────────────────────────────────────────────────
async function safeSend(chatId, text, extra = {}) {
  if (!chatId) return;
  try {
    return await bot.sendMessage(chatId, text, { parse_mode: 'Markdown', ...extra });
  } catch (err) {
    console.error(`[Bot] Failed to send to ${chatId}:`, err.message);
  }
}

// ─── Main Menu ────────────────────────────────────────────────────────────────
async function showMainMenu(chatId, text = null) {
  const menuText = text || `🌟 *Recovery Helper*\n\nChoose an option:`;
  const keyboard = {
    inline_keyboard: [
      [{ text: '🔍 Find a Mentor', callback_data: 'menu_mentors' }, { text: '💬 My Chat Partner', callback_data: 'menu_chat' }],
      [{ text: '📖 Bible Reading Streak', callback_data: 'menu_streak' }, { text: '✏️ Journal', callback_data: 'menu_journal' }],
      [{ text: '📅 Daily Verse', callback_data: 'menu_verse' }, { text: '⚙️ Settings', callback_data: 'menu_settings' }],
      [{ text: '❓ Help', callback_data: 'menu_help' }]
    ]
  };
  await safeSend(chatId, menuText, { reply_markup: keyboard });
}

// ─── Registration Wizard ──────────────────────────────────────────────────────
async function startRegistration(chatId) {
  setState(chatId, 'reg_sex');
  await safeSend(chatId, "Welcome! Let's get you set up. First, what is your sex?", {
    reply_markup: {
      inline_keyboard: [
        [{ text: 'Male', callback_data: 'reg_sex_M' }, { text: 'Female', callback_data: 'reg_sex_F' }],
        [{ text: 'Prefer not to say', callback_data: 'reg_sex_prefer_not' }]
      ]
    }
  });
}

// ─── Chat Logic ───────────────────────────────────────────────────────────────

async function getActiveChatPartners(chatId) {
    // Check if user is a mentee (has active mentor)
    const { data: mentorAss } = await supabase
        .from('mentorship_assignments')
        .select('mentor_id')
        .eq('user_id', chatId)
        .eq('is_active', true);
    
    if (mentorAss?.length > 0) {
        return { role: 'mentee', partners: mentorAss.map(a => a.mentor_id) };
    }

    // Check if user is a mentor (has active mentees)
    const { data: menteeAss } = await supabase
        .from('mentorship_assignments')
        .select('user_id')
        .eq('mentor_id', chatId)
        .eq('is_active', true);

    if (menteeAss?.length > 0) {
        return { role: 'mentor', partners: menteeAss.map(a => a.user_id) };
    }

    return null;
}

async function forwardMessage(fromId, toId, text) {
  // Store in messages table
  await supabase.from('messages').insert({ from_id: fromId, to_id: toId, content: text });

  // Get sender's anonymous name
  const { data: sender } = await supabase.from('users').select('anonymous_id, role').eq('telegram_id', fromId).single();
  const senderName = sender?.anonymous_id || 'Anonymous';
  const roleLabel = sender?.role === 'mentor' ? 'mentor' : 'mentee';

  // Get recipient's chat_id
  const { data: recipient } = await supabase.from('users').select('chat_id').eq('telegram_id', toId).single();
  if (recipient?.chat_id) {
    await safeSend(recipient.chat_id, `💬 *Message from your ${roleLabel}:*\n\n${text}`, {
        reply_markup: {
            inline_keyboard: [[{ text: '↩️ Reply', callback_data: `reply_to_${fromId}` }]]
        }
    });
    // Update last reply target for the recipient
    lastReplyTarget.set(toId, fromId);
  }
}

// ─── Translation Helper ───────────────────────────────────────────────────────
async function translateToAmharic(text) {
  try {
    const res = await axios.get(`https://api.mymemory.translated.net/get?q=${encodeURIComponent(text)}&langpair=en|am`);
    return res.data.responseData.translatedText || text;
  } catch (err) {
    console.error('[Bot] Translation error:', err.message);
    return text;
  }
}

// ─── Bot Interaction Handlers ─────────────────────────────────────────────────

bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text;
  const state = getState(chatId);

  if (!text) return;

  // Handle Commands
  if (text.startsWith('/')) {
    const command = text.split(' ')[0].toLowerCase();
    
    if (command === '/start') {
      const { data: user } = await supabase.from('users').select('*').eq('telegram_id', chatId).single();
      if (!user) {
        await startRegistration(chatId);
      } else {
        await showMainMenu(chatId, `Welcome back, *${user.anonymous_id}*!`);
      }
      return;
    }

    if (command === '/menu') {
      await showMainMenu(chatId);
      return;
    }

    if (command === '/reply') {
        // Handle /reply @nickname message
        const args = text.split(' ');
        if (args.length < 3) {
            await safeSend(chatId, "Usage: `/reply @nickname message` or just type normally if you have one partner.");
            return;
        }
        const nickname = args[1].replace('@', '');
        const message = args.slice(2).join(' ');
        
        const { data: targetUser } = await supabase.from('users').select('telegram_id').eq('anonymous_id', nickname).single();
        if (!targetUser) {
            await safeSend(chatId, "User not found.");
            return;
        }

        // Verify mentorship
        const partners = await getActiveChatPartners(chatId);
        if (!partners || !partners.partners.includes(targetUser.telegram_id)) {
            await safeSend(chatId, "This user is not your active mentorship partner.");
            return;
        }

        await forwardMessage(chatId, targetUser.telegram_id, message);
        await safeSend(chatId, "✅ Message sent!");
        return;
    }
    // Allow other commands to fall through if needed, or ignore
    return;
  }

  // Handle multi-step states (Registration, Journaling, etc.)
  if (state && state.step !== 'chat_reply') {
    if (state.step === 'reg_nickname') {
      const nickname = text.trim();
      if (nickname.length < 3 || nickname.length > 20 || !/^[a-zA-Z0-9_]+$/.test(nickname)) {
        await safeSend(chatId, "❌ Invalid nickname. Use 3-20 letters, numbers, or underscores.");
        return;
      }
      const { data: existing } = await supabase.from('users').select('telegram_id').eq('anonymous_id', nickname).single();
      if (existing) {
        await safeSend(chatId, "❌ This nickname is already taken. Please try another one:");
        return;
      }
      const { error } = await supabase.from('users').insert({
        telegram_id: chatId, chat_id: chatId, anonymous_id: nickname,
        sex: state.tempData.sex, age_range: state.tempData.age_range, education_level: state.tempData.education_level, role: 'user'
      });
      if (error) { await safeSend(chatId, "❌ Error creating profile. Please try /start again."); clearState(chatId); return; }
      await supabase.from('user_settings').insert({ telegram_id: chatId });
      clearState(chatId);
      await showMainMenu(chatId, `🎉 *Registration Complete!*\n\nWelcome, *${nickname}*.`);
      return;
    }

    if (state.step === 'journal_new') {
      const { error } = await supabase.from('journal_entries').insert({ telegram_id: chatId, content: text.trim() });
      if (error) await safeSend(chatId, "❌ Failed to save journal entry.");
      else await safeSend(chatId, "✅ Journal entry saved!");
      clearState(chatId);
      await showMainMenu(chatId);
      return;
    }

    if (state.step === 'mentor_req_msg') {
      const mentorId = state.tempData.mentorId;
      const message = text === '/skip' ? '' : text.trim();
      const { error } = await supabase.from('mentorship_requests').insert({ user_id: chatId, mentor_id: mentorId, message });
      if (error) await safeSend(chatId, "❌ Request failed. You might already have a pending request.");
      else {
        const { data: user } = await supabase.from('users').select('anonymous_id').eq('telegram_id', chatId).single();
        await safeSend(mentorId, `🙏 *New Mentorship Request!*\n\nFrom: *${user.anonymous_id}*\nMessage: ${message || '_No message_'}\n\nDo you accept?`, {
          reply_markup: { inline_keyboard: [[{ text: '✅ Accept', callback_data: `mentor_accept_${chatId}` }, { text: '❌ Reject', callback_data: `mentor_reject_${chatId}` }]] }
        });
        await safeSend(chatId, "✅ Request sent!");
      }
      clearState(chatId);
      await showMainMenu(chatId);
      return;
    }

    if (state.step === 'set_verse_time') {
      const hour = parseInt(text);
      if (isNaN(hour) || hour < 0 || hour > 23) { await safeSend(chatId, "❌ Please enter a number between 0 and 23."); return; }
      await supabase.from('user_settings').update({ verse_time: hour }).eq('telegram_id', chatId);
      await safeSend(chatId, `✅ Daily verse time set to ${hour}:00 UTC.`);
      clearState(chatId);
      await showMainMenu(chatId);
      return;
    }
  }

  // Handle Normal Chat Forwarding
  const partnersInfo = await getActiveChatPartners(chatId);
  if (!partnersInfo) {
    await safeSend(chatId, "You don't have an active mentorship partner. Use the menu to find a mentor or wait for a request.");
    return;
  }

  const partners = partnersInfo.partners;
  let targetId = null;

  if (partners.length === 1) {
    targetId = partners[0];
  } else {
    // Multiple partners (Mentor case)
    // Check if we have a state target or last target
    if (state && state.step === 'chat_reply' && state.targetId) {
        targetId = state.targetId;
    } else if (lastReplyTarget.has(chatId)) {
        targetId = lastReplyTarget.get(chatId);
    } else {
        // Ask to choose
        const { data: mentees } = await supabase.from('users').select('telegram_id, anonymous_id').in('telegram_id', partners);
        const buttons = mentees.map(m => [{ text: `Message ${m.anonymous_id}`, callback_data: `reply_to_${m.telegram_id}` }]);
        await safeSend(chatId, "You have multiple mentees. Who would you like to message?", {
            reply_markup: { inline_keyboard: buttons }
        });
        // Store the text in tempData so we can forward it once they pick a partner
        setState(chatId, 'awaiting_partner_selection', null, { pendingMessage: text });
        return;
    }
  }

  if (targetId) {
    await forwardMessage(chatId, targetId, text.trim());
    await safeSend(chatId, "✅ Message sent.");
  }
});

// ─── Callback Query Handler ───────────────────────────────────────────────────

bot.on('callback_query', async (query) => {
  const chatId = query.message.chat.id;
  const data = query.data;

  // Registration
  if (data.startsWith('reg_sex_')) {
    setState(chatId, 'reg_age', null, { sex: data.replace('reg_sex_', '') });
    await bot.editMessageText("What is your age range?", { chat_id: chatId, message_id: query.message.message_id,
      reply_markup: { inline_keyboard: [[{ text: '13-17', callback_data: 'reg_age_13-17' }, { text: '18-24', callback_data: 'reg_age_18-24' }], [{ text: '25-34', callback_data: 'reg_age_25-34' }, { text: '35-44', callback_data: 'reg_age_35-44' }], [{ text: '45-54', callback_data: 'reg_age_45-54' }, { text: '55+', callback_data: 'reg_age_55+' }]] }
    });
  } else if (data.startsWith('reg_age_')) {
    setState(chatId, 'reg_edu', null, { ...getState(chatId).tempData, age_range: data.replace('reg_age_', '') });
    await bot.editMessageText("Education level?", { chat_id: chatId, message_id: query.message.message_id,
      reply_markup: { inline_keyboard: [[{ text: 'Primary', callback_data: 'reg_edu_primary' }, { text: 'Secondary', callback_data: 'reg_edu_secondary' }], [{ text: 'Undergraduate', callback_data: 'reg_edu_undergraduate' }, { text: 'Graduate', callback_data: 'reg_edu_graduate' }], [{ text: 'Postgraduate', callback_data: 'reg_edu_postgraduate' }, { text: 'None', callback_data: 'reg_edu_none' }]] }
    });
  } else if (data.startsWith('reg_edu_')) {
    setState(chatId, 'reg_nickname', null, { ...getState(chatId).tempData, education_level: data.replace('reg_edu_', '') });
    await bot.editMessageText("Choose a unique **nickname** (letters/numbers/underscores):", { chat_id: chatId, message_id: query.message.message_id });
  }

  // Mentorship Requests
  else if (data.startsWith('mentor_req_')) {
    setState(chatId, 'mentor_req_msg', null, { mentorId: data.replace('mentor_req_', '') });
    await safeSend(chatId, "Send a short message to the mentor (optional), or type /skip:");
  } else if (data.startsWith('mentor_accept_')) {
    await acceptMentorship(chatId, data.replace('mentor_accept_', ''));
  } else if (data.startsWith('mentor_reject_')) {
    await rejectMentorship(chatId, data.replace('mentor_reject_', ''));
  }

  // Chat/Reply logic
  else if (data.startsWith('reply_to_')) {
    const targetId = data.replace('reply_to_', '');
    const state = getState(chatId);
    if (state && state.step === 'awaiting_partner_selection' && state.tempData.pendingMessage) {
        await forwardMessage(chatId, targetId, state.tempData.pendingMessage);
        await safeSend(chatId, "✅ Message sent.");
        clearState(chatId);
    } else {
        setState(chatId, 'chat_reply', targetId);
        const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', targetId).single();
        await safeSend(chatId, `Now messaging *${u.anonymous_id}*. Type your message:`);
    }
    lastReplyTarget.set(chatId, targetId);
  }

  // Menu Navigation
  else if (data === 'menu_mentors') await listMentors(chatId);
  else if (data === 'menu_chat') {
    const p = await getActiveChatPartners(chatId);
    if (!p) await safeSend(chatId, "No active partners. Find a mentor first!");
    else await safeSend(chatId, "You can chat by just typing in this chat. It will be forwarded to your partner automatically.");
  }
  else if (data === 'menu_streak') await handleStreakFlow(chatId);
  else if (data === 'menu_journal') await handleJournalFlow(chatId);
  else if (data === 'menu_verse') await handleDailyVerse(chatId);
  else if (data === 'menu_settings') await handleSettingsFlow(chatId);
  else if (data === 'menu_help') await safeSend(chatId, "🙏 *Help*\nJust type a message to chat with your partner. Use /menu for features.");

  // Other features
  else if (data === 'streak_mark') await markStreakAsRead(chatId);
  else if (data === 'journal_new') { setState(chatId, 'journal_new'); await safeSend(chatId, "Write your journal entry below:"); }
  else if (data.startsWith('journal_view_')) await viewJournalEntries(chatId, parseInt(data.replace('journal_view_', '')));
  else if (data.startsWith('journal_read_')) await readJournalEntry(chatId, data.replace('journal_read_', ''));
  else if (data.startsWith('settings_toggle_')) await toggleSetting(chatId, data.replace('settings_toggle_', ''));
  else if (data === 'settings_time') { setState(chatId, 'set_verse_time'); await safeSend(chatId, "Enter hour (0-23 UTC):"); }
  else if (data === 'settings_lang') await safeSend(chatId, "Language:", { reply_markup: { inline_keyboard: [[{ text: 'English', callback_data: 'set_lang_en' }, { text: 'Amharic', callback_data: 'set_lang_am' }]] } });
  else if (data.startsWith('set_lang_')) { await supabase.from('user_settings').update({ language: data.replace('set_lang_', '') }).eq('telegram_id', chatId); await handleSettingsFlow(chatId); }

  bot.answerCallbackQuery(query.id);
});

// ─── Implementation Functions ───────────────────────────────────────────────

async function listMentors(chatId, page = 0) {
  const limit = 5;
  const { data: mentors } = await supabase.from('users').select('telegram_id, anonymous_id, user_settings(display_name, bio, specialization)').eq('role', 'mentor').eq('is_banned', false).range(page * limit, (page + 1) * limit - 1);
  if (!mentors?.length) return safeSend(chatId, "No mentors available.");
  let text = `🔍 *Mentors*\n\n`;
  const buttons = mentors.map(m => {
    text += `👤 *${m.user_settings?.display_name || m.anonymous_id}*\nBio: ${m.user_settings?.bio || 'None'}\n\n`;
    return [{ text: `Request ${m.anonymous_id}`, callback_data: `mentor_req_${m.telegram_id}` }];
  });
  const nav = [];
  if (page > 0) nav.push({ text: '⬅️', callback_data: `mentors_page_${page - 1}` });
  if (mentors.length === limit) nav.push({ text: '➡️', callback_data: `mentors_page_${page + 1}` });
  if (nav.length) buttons.push(nav);
  await safeSend(chatId, text, { reply_markup: { inline_keyboard: buttons } });
}

async function acceptMentorship(mentorId, userId) {
  const { data: existing } = await supabase.from('mentorship_assignments').select('id').eq('user_id', userId).eq('is_active', true).single();
  if (existing) return safeSend(mentorId, "User already has a mentor.");
  await supabase.from('mentorship_assignments').insert({ mentor_id: mentorId, user_id: userId });
  await supabase.from('mentorship_requests').update({ status: 'accepted' }).eq('mentor_id', mentorId).eq('user_id', userId);
  await safeSend(userId, "✅ Mentorship Accepted! You can now chat by typing normally here.");
  await safeSend(mentorId, "✅ Accepted.");
}

async function rejectMentorship(mentorId, userId) {
  await supabase.from('mentorship_requests').update({ status: 'rejected' }).eq('mentor_id', mentorId).eq('user_id', userId);
  await safeSend(userId, "📋 Request rejected.");
  await safeSend(mentorId, "✅ Rejected.");
}

async function handleStreakFlow(chatId) {
  const { data: streak } = await supabase.from('bible_streaks').select('*').eq('telegram_id', chatId).single();
  const { data: verses } = await supabase.from('daily_verses').select('*').eq('is_active', true);
  const day = Math.floor(Date.now() / 86400000);
  const v = verses?.[day % verses.length] || { reference: 'Philippians 4:13', text: '...' };
  const text = `🔥 Streak: *${streak?.current_streak || 0}*\n🏆 Longest: *${streak?.longest_streak || 0}*\n\nToday:\n*${v.reference}*\n_${v.text}_`;
  const buttons = streak?.last_read_date === new Date().toISOString().split('T')[0] ? [] : [[{ text: '✅ Mark Read', callback_data: 'streak_mark' }]];
  await safeSend(chatId, text, { reply_markup: { inline_keyboard: [...buttons, [{ text: '🔙', callback_data: 'menu_help' }]] } });
}

async function markStreakAsRead(chatId) {
  const today = new Date().toISOString().split('T')[0];
  const { data: s } = await supabase.from('bible_streaks').select('*').eq('telegram_id', chatId).single();
  if (!s) await supabase.from('bible_streaks').insert({ telegram_id: chatId, current_streak: 1, longest_streak: 1, last_read_date: today });
  else {
    const yest = new Date(); yest.setDate(yest.getDate() - 1);
    const isConsecutive = s.last_read_date === yest.toISOString().split('T')[0];
    const n = isConsecutive ? s.current_streak + 1 : 1;
    await supabase.from('bible_streaks').update({ current_streak: n, longest_streak: Math.max(n, s.longest_streak), last_read_date: today }).eq('telegram_id', chatId);
  }
  await safeSend(chatId, "✅ Marked!");
  await handleStreakFlow(chatId);
}

async function handleJournalFlow(chatId) {
  await safeSend(chatId, `✏️ *Journal*\nPrivate reflections.`, { reply_markup: { inline_keyboard: [[{ text: '✍️ New Entry', callback_data: 'journal_new' }], [{ text: '📜 View My Entries', callback_data: 'journal_view_0' }]] } });
}

async function viewJournalEntries(chatId, page = 0) {
  const limit = 5;
  const { data: entries } = await supabase.from('journal_entries').select('id, content, created_at').eq('telegram_id', chatId).order('created_at', { ascending: false }).range(page * limit, (page + 1) * limit - 1);
  if (!entries?.length) return safeSend(chatId, "No entries.");
  const buttons = entries.map(e => [{ text: `${new Date(e.created_at).toLocaleDateString()}: ${e.content.substring(0, 15)}...`, callback_data: `journal_read_${e.id}` }]);
  const nav = [];
  if (page > 0) nav.push({ text: '⬅️', callback_data: `journal_view_${page - 1}` });
  if (entries.length === limit) nav.push({ text: '➡️', callback_data: `journal_view_${page + 1}` });
  if (nav.length) buttons.push(nav);
  await safeSend(chatId, "📜 *Journal*", { reply_markup: { inline_keyboard: buttons } });
}

async function readJournalEntry(chatId, id) {
  const { data: e } = await supabase.from('journal_entries').select('*').eq('id', id).single();
  if (e) await safeSend(chatId, `📅 ${new Date(e.created_at).toLocaleString()}\n\n${e.content}`, { reply_markup: { inline_keyboard: [[{ text: '🔙', callback_data: 'journal_view_0' }]] } });
}

async function handleDailyVerse(chatId) {
    const { data: verses } = await supabase.from('daily_verses').select('*').eq('is_active', true);
    const v = verses?.[Math.floor(Date.now() / 86400000) % verses.length];
    if (v) {
        let t = `📖 *Verse*\n*${v.reference}*\n\n${v.text}`;
        const { data: s } = await supabase.from('user_settings').select('language').eq('telegram_id', chatId).single();
        if (s?.language === 'am') t += `\n\n🇪🇹 *Amharic:*\n_${await translateToAmharic(v.text)}_`;
        await safeSend(chatId, t);
    }
}

async function handleSettingsFlow(chatId) {
  const { data: s } = await supabase.from('user_settings').select('*').eq('telegram_id', chatId).single();
  const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', chatId).single();
  const t = `⚙️ *Settings*\n\nNick: ${u.anonymous_id}\nLang: ${s?.language === 'am' ? 'Amharic' : 'English'}\nVerse: ${s?.verse_time}:00 UTC`;
  await safeSend(chatId, t, { reply_markup: { inline_keyboard: [[{ text: '🔔 Toggle Notifications', callback_data: 'settings_toggle_notify_messages' }], [{ text: '⏰ Set Verse Time', callback_data: 'settings_time' }], [{ text: '🌐 Language', callback_data: 'settings_lang' }], [{ text: '🔙', callback_data: 'menu_help' }]] } });
}

async function toggleSetting(chatId, f) {
  const { data: s } = await supabase.from('user_settings').select(f).eq('telegram_id', chatId).single();
  await supabase.from('user_settings').update({ [f]: !s[f] }).eq('telegram_id', chatId);
  await handleSettingsFlow(chatId);
}

// ─── Scheduler ────────────────────────────────────────────────────────────────
setInterval(async () => {
    const now = new Date();
    if (now.getUTCMinutes() === 0) {
        const h = now.getUTCHours();
        const { data: opted } = await supabase.from('user_settings').select('telegram_id, language').eq('notify_daily_verse', true).eq('verse_time', h);
        const { data: verses } = await supabase.from('daily_verses').select('*').eq('is_active', true);
        const v = verses?.[Math.floor(Date.now() / 86400000) % verses.length];
        if (v && opted?.length) {
            for (const u of opted) {
                let t = `📖 *Daily Verse*\n*${v.reference}*\n\n${v.text}`;
                if (u.language === 'am') t += `\n\n🇪🇹 *Amharic:*\n_${await translateToAmharic(v.text)}_`;
                await safeSend(u.telegram_id, t);
            }
        }
    }
}, 60 * 1000);

module.exports = { bot, forwardMessage };
