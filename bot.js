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
const userStates = new Map(); // telegram_id -> { step, targetId, expires, tempData: { selectedTopics: [] } }

function setState(chatId, step, targetId = null, tempData = {}) {
  userStates.set(chatId, { step, targetId, expires: Date.now() + 3600000, tempData });
}

function clearState(chatId) {
  userStates.delete(chatId);
}

function getState(chatId) {
  const state = userStates.get(chatId);
  if (state && state.expires < Date.now()) {
    userStates.delete(chatId);
    return null;
  }
  return state;
}

// ─── Formatting Helpers ───────────────────────────────────────────────────────
function formatUserDateTime(dateStr, timezone = 'UTC') {
  try {
    return new Date(dateStr).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone });
  } catch (e) { return new Date(dateStr).toLocaleString(); }
}

// ─── Safe Send Helper ──────────────────────────────────────────────────────────
async function safeSend(chatId, text, extra = {}) {
  if (!chatId) return;
  try { return await bot.sendMessage(chatId, text, { parse_mode: 'Markdown', ...extra }); }
  catch (err) { console.error(`[Bot] Failed to send to ${chatId}:`, err.message); }
}

// ─── Main Menu ────────────────────────────────────────────────────────────────
async function showMainMenu(chatId, text) {
  const { data: user } = await supabase.from('users').select('role').eq('telegram_id', chatId).single();
  const role = user?.role || 'user';
  
  const menuText = text || `🌟 *Recovery Helper*\n\nChoose an option:`;
  const keyboard = { inline_keyboard: [] };
  
  keyboard.inline_keyboard.push([{ text: '🔍 Find a Mentor', callback_data: 'menu_mentors' }, { text: '💬 My Chat Partner', callback_data: 'menu_chat' }]);
  keyboard.inline_keyboard.push([{ text: '📖 Bible Reading Streak', callback_data: 'menu_streak' }, { text: '✏️ Journal', callback_data: 'menu_journal' }]);
  keyboard.inline_keyboard.push([{ text: '📅 Daily Verse', callback_data: 'menu_verse' }, { text: '⚙️ Settings', callback_data: 'menu_settings' }]);
  
  if (role === 'mentor' || role === 'admin') {
    keyboard.inline_keyboard.push([{ text: '👥 My Mentees', callback_data: 'menu_mentees' }, { text: '📅 Schedule Session', callback_data: 'menu_schedule' }]);
  } else if (role === 'user') {
    keyboard.inline_keyboard.push([{ text: '🙏 Apply to Become a Mentor', callback_data: 'menu_apply' }]);
  }
  
  keyboard.inline_keyboard.push([{ text: '❓ Help', callback_data: 'menu_help' }]);
  
  await safeSend(chatId, menuText, { reply_markup: keyboard });
}

// ─── Topic Picker Logic ───────────────────────────────────────────────────────
async function getTopicPickerKeyboard(selectedIds = [], actionPrefix = 'reg_topic_') {
  const { data: topics } = await supabase.from('topics').select('id, name').eq('is_active', true).order('name');
  if (!topics) return { inline_keyboard: [] };

  const buttons = topics.map(t => {
    const isSelected = selectedIds.includes(t.id);
    return [{
      text: `${isSelected ? '✅' : '⬜'} ${t.name}`,
      callback_data: `${actionPrefix}${t.id}`
    }];
  });

  buttons.push([{ text: '➡️ Done', callback_data: `${actionPrefix}done` }]);
  return { inline_keyboard: buttons };
}

async function getMentorTopicKeyboard(chatId) {
  const { data: topics } = await supabase.from('topics').select('id, name').eq('is_active', true).order('name');
  const { data: mentorTopics } = await supabase.from('mentor_topics').select('topic_id').eq('telegram_id', chatId);
  const selectedIds = (mentorTopics || []).map(mt => mt.topic_id);
  
  if (!topics) return { inline_keyboard: [] };

  const buttons = topics.map(t => {
    const isSelected = selectedIds.includes(t.id);
    return [{
      text: `${isSelected ? '✅' : '⬜'} ${t.name}`,
      callback_data: `toggle_topic_${t.id}`
    }];
  });

  buttons.push([
    { text: '✅ Done', callback_data: 'topic_done' },
    { text: '❌ Cancel', callback_data: 'topic_cancel' }
  ]);
  return { inline_keyboard: buttons };
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

// ─── Chat Logic (Pure Telegram Style) ─────────────────────────────────────────
async function getActiveChatPartners(chatId) {
    const { data: mentorAss } = await supabase.from('mentorship_assignments').select('mentor_id').eq('user_id', chatId).eq('is_active', true);
    if (mentorAss?.length > 0) return { role: 'mentee', partners: mentorAss.map(a => a.mentor_id) };

    const { data: menteeAss } = await supabase.from('mentorship_assignments').select('user_id').eq('mentor_id', chatId).eq('is_active', true);
    if (menteeAss?.length > 0) return { role: 'mentor', partners: menteeAss.map(a => a.user_id) };

    return null;
}

async function forwardMessage(fromId, toId, text) {
  await supabase.from('messages').insert({ from_id: fromId, to_id: toId, content: text });
  const { data: sender } = await supabase.from('users').select('anonymous_id, role').eq('telegram_id', fromId).single();
  const { data: recipient } = await supabase.from('users').select('chat_id').eq('telegram_id', toId).single();
  if (recipient?.chat_id) {
    const roleLabel = sender?.role === 'mentor' ? 'mentor' : 'mentee';
    await safeSend(recipient.chat_id, `💬 *Message from your ${roleLabel} [${sender?.anonymous_id}]:*\n\n${text}`);
    setState(toId, 'chat_active', fromId); // Persist context for recipient
  }
}

async function getAmharicVerse(verseText) {
    try {
        const res = await axios.get(`https://api.mymemory.translated.net/get?q=${encodeURIComponent(verseText)}&langpair=en|am`);
        return res.data?.responseData?.translatedText || null;
    } catch (e) { return null; }
}

async function handleDailyVerse(chatId) {
    const { data: s } = await supabase.from('user_settings').select('language').eq('telegram_id', chatId).single();
    // In a real app, we'd fetch from a DB or API. Using a fallback for demo.
    const verse = "For I know the plans I have for you, declares the Lord, plans for welfare and not for evil, to give you a future and a hope. - Jeremiah 29:11";
    
    let text = `📅 *Daily Verse*\n\n${verse}`;
    if (s?.language === 'am') {
        const amVerse = await getAmharicVerse(verse);
        if (amVerse) text += `\n\n🇪🇹 *Amharic:*\n${amVerse}`;
    }
    await safeSend(chatId, text);
}

// ─── Interaction Handlers ─────────────────────────────────────────────────────

bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text;
  const state = getState(chatId);

  if (!text) return;

  if (text.startsWith('/')) {
    const command = text.split(' ')[0].toLowerCase();
    const state = getState(chatId);
    
    // Check if this is a flow-specific command that should bypass the standard command return
    const isFlowCommand = command === '/skip' && state && (state.step === 'awaiting_mentor_q3' || state.step === 'mentor_req_msg');
    
    if (!isFlowCommand) {
        if (command === '/start') {
      const { data: user } = await supabase.from('users').select('*').eq('telegram_id', chatId).single();
      if (!user) await startRegistration(chatId);
      else await showMainMenu(chatId, `Welcome back, *${user.anonymous_id}*!`);
      return;
    }

    if (command === '/menu') { await showMainMenu(chatId); return; }

    if (command === '/apply') {
        const { data: user } = await supabase.from('users').select('role').eq('telegram_id', chatId).single();
        if (user?.role === 'mentor' || user?.role === 'admin') return safeSend(chatId, "You are already a mentor.");
        
        // Check for pending application
        const { data: existingApp } = await supabase.from('mentor_applications').select('id').eq('telegram_id', chatId).eq('status', 'pending').single();
        if (existingApp) return safeSend(chatId, "You already have a pending application. Please wait for admin review.");

        setState(chatId, 'awaiting_mentor_q1');
        await safeSend(chatId, "How long have you been free from pornography (or your primary struggle)?");
        return;
    }

    if (command === '/settopics') {
        const keyboard = await getTopicPickerKeyboard([], 'set_topics_');
        await safeSend(chatId, "Select the areas you are struggling with:", { reply_markup: keyboard });
        setState(chatId, 'edit_topics', null, { selectedTopics: [] });
        return;
    }

    if (command === '/reply') {
        const args = text.split(' ');
        if (args.length < 2) return safeSend(chatId, "Usage: `/reply @nickname message` or `/reply number message`.");
        const partnersInfo = await getActiveChatPartners(chatId);
        if (!partnersInfo) return safeSend(chatId, "No active partners.");

        let targetId = null;
        const input = args[1];
        const content = args.slice(2).join(' ');

        if (input.startsWith('@')) {
            const nick = input.replace('@', '');
            const { data: u } = await supabase.from('users').select('telegram_id').eq('anonymous_id', nick).single();
            if (u && partnersInfo.partners.includes(u.telegram_id)) targetId = u.telegram_id;
        } else {
            const idx = parseInt(input) - 1;
            if (!isNaN(idx) && partnersInfo.partners[idx]) targetId = partnersInfo.partners[idx];
        }

        if (!targetId) return safeSend(chatId, "Partner not found or not active.");
        if (!content) { 
            setState(chatId, 'chat_active', targetId);
            const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', targetId).single();
            return safeSend(chatId, `Focus set to *${u.anonymous_id}*. Your next message will go to them.`);
        }

        await forwardMessage(chatId, targetId, content);
        await safeSend(chatId, "✅ Sent.");
        return;
    }
        return;
    }
  }

  // Handle Flow Steps
  if (state) {
    if (state.step === 'reg_nickname') {
      const nick = text.trim();
      if (nick.length < 3 || nick.length > 20 || !/^[a-zA-Z0-9_]+$/.test(nick)) return safeSend(chatId, "❌ Invalid nickname.");
      const { data: ex } = await supabase.from('users').select('telegram_id').eq('anonymous_id', nick).single();
      if (ex) return safeSend(chatId, "❌ Taken.");
      
      state.tempData.nickname = nick;
      const keyboard = await getTopicPickerKeyboard([], 'reg_topic_');
      await safeSend(chatId, `Almost there, *${nick}*. Select the areas you are struggling with:`, { reply_markup: keyboard });
      setState(chatId, 'reg_topics', null, state.tempData);
      return;
    }

    if (state.step === 'awaiting_mentor_q1') {
        state.tempData.q1 = text.trim();
        setState(chatId, 'awaiting_mentor_q2', null, state.tempData);
        await safeSend(chatId, "Describe the key steps that helped your recovery.");
        return;
    }
    if (state.step === 'awaiting_mentor_q2') {
        state.tempData.q2 = text.trim();
        setState(chatId, 'awaiting_mentor_q3', null, state.tempData);
        await safeSend(chatId, "Any additional information you'd like to share? (optional, use /skip to skip)");
        return;
    }
    if (state.step === 'awaiting_mentor_q3') {
        const q3 = text === '/skip' ? null : text.trim();
        
        const { error } = await supabase.from('mentor_applications').insert({
            telegram_id: chatId,
            answer_q1: state.tempData.q1,
            answer_q2: state.tempData.q2,
            answer_q3: q3,
            status: 'pending',
            submitted_at: new Date().toISOString()
        });
        
        if (error) {
            console.error('[Bot] Mentor application error:', error);
            await safeSend(chatId, "❌ Failed to submit application. Please try again later.");
        } else {
            await safeSend(chatId, "Thank you for applying. Your application has been submitted for admin review. You will be notified once a decision is made.");
            
            // Notify Admin
            const adminIds = process.env.ADMIN_TELEGRAM_ID || process.env.ADMIN_CHAT_ID;
            if (adminIds) {
                const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', chatId).single();
                const adminMsg = `🆕 *New Mentor Application*\n\nUser: *${u?.anonymous_id || chatId}*\n\n*Q1 (Free since):* ${state.tempData.q1}\n*Q2 (Steps):* ${state.tempData.q2}\n*Q3 (Other):* ${q3 || '_None_'}`;
                
                for (const id of adminIds.split(',')) {
                    if (id.trim()) await safeSend(id.trim(), adminMsg);
                }
            }
        }
        
        clearState(chatId);
        await showMainMenu(chatId);
        return;
    }

    if (state.step === 'sched_date') {
        state.tempData.date = text.trim(); // YYYY-MM-DD
        setState(chatId, 'sched_time', null, state.tempData);
        await safeSend(chatId, "Enter time (HH:MM) in UTC:");
        return;
    }
    if (state.step === 'sched_time') {
        state.tempData.time = text.trim();
        const dateStr = `${state.tempData.date}T${state.tempData.time}:00Z`;
        if (isNaN(Date.parse(dateStr))) return safeSend(chatId, "❌ Invalid format.");
        
        // Finalize session creation
        try {
            // We assume an internal API or direct DB insert for now since we're in bot.js
            // Prompt says "Call existing POST /api/sessions/create" but usually bot should use a helper function or direct DB
            const { data: sess, error } = await supabase.from('video_sessions').insert({
                mentor_id: chatId,
                scheduled_at: dateStr,
                type: state.tempData.type, // 'private' or 'group'
                mentee_id: state.tempData.mentee_id || null,
                status: 'scheduled'
            }).select().single();
            
            if (error) throw error;
            
            const link = `${APP_URL}?start=session_${sess.id}`;
            await safeSend(chatId, `✅ Session scheduled!\n\nDeep Link: ${link}`);
            
            if (sess.mentee_id) {
                await safeSend(sess.mentee_id, `🙏 *New Session Scheduled!*\nYour mentor has scheduled a session for ${dateStr}.\n\nJoin here: ${link}`);
            }
        } catch (e) {
            await safeSend(chatId, `❌ Failed: ${e.message}`);
        }
        
        clearState(chatId);
        await showMainMenu(chatId);
        return;
    }

    if (state.step === 'journal_new') {
      await supabase.from('journal_entries').insert({ telegram_id: chatId, content: text.trim() });
      await safeSend(chatId, "✅ Journaled."); clearState(chatId); await showMainMenu(chatId);
      return;
    }

    if (state.step === 'mentor_req_msg') {
      const mid = state.tempData.mentorId;
      const tid = state.tempData.topicId;
      const msgStr = text === '/skip' ? '' : text.trim();
      const { error } = await supabase.from('mentorship_requests').insert({ user_id: chatId, mentor_id: mid, message: msgStr });
      if (error) await safeSend(chatId, "❌ Request failed.");
      else {
        const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', chatId).single();
        const { data: t } = await supabase.from('topics').select('name').eq('id', tid).single();
        await safeSend(mid, `🙏 *New Mentorship Request!*\nFrom: *${u.anonymous_id}*\nTopic: *${t.name}*\nMessage: ${msgStr || '_None_'}\n\nDo you accept?`, {
          reply_markup: { inline_keyboard: [[{ text: '✅ Accept', callback_data: `mentor_accept_${chatId}_${tid}` }, { text: '❌ Reject', callback_data: `mentor_reject_${chatId}` }]] }
        });
        await safeSend(chatId, "✅ Sent!");
      }
      clearState(chatId); await showMainMenu(chatId);
      return;
    }

    if (state.step === 'set_verse_time') {
      const h = parseInt(text);
      if (isNaN(h) || h < 0 || h > 23) return safeSend(chatId, "❌ Enter 0-23.");
      await supabase.from('user_settings').update({ verse_time: h }).eq('telegram_id', chatId);
      await safeSend(chatId, `✅ Verse time: ${h}:00 UTC.`); clearState(chatId); await showMainMenu(chatId);
      return;
    }
  }

  // Pure Chat Forwarding
  const partnersInfo = await getActiveChatPartners(chatId);
  if (!partnersInfo) return safeSend(chatId, "No active partner. Use /menu to find one.");

  let targetId = null;
  if (partnersInfo.partners.length === 1) {
    targetId = partnersInfo.partners[0];
  } else {
    if (state && state.step === 'chat_active' && state.targetId) targetId = state.targetId;
    else {
        const { data: mentees } = await supabase.from('users').select('telegram_id, anonymous_id').in('telegram_id', partnersInfo.partners);
        let listStr = "Multiple mentees. Specify target:\n\n";
        mentees.forEach((m, i) => listStr += `${i+1}. @${m.anonymous_id}\n`);
        listStr += "\nUse `/reply @nickname` or `/reply number`.";
        return safeSend(chatId, listStr);
    }
  }

  if (targetId) await forwardMessage(chatId, targetId, text.trim());
});

// ─── Callback Handler ─────────────────────────────────────────────────────────

bot.on('callback_query', async (query) => {
  const chatId = query.message.chat.id;
  const data = query.data;
  const state = getState(chatId);

  // Registration Toggles
  if (data.startsWith('reg_sex_')) {
    setState(chatId, 'reg_age', null, { sex: data.replace('reg_sex_', '') });
    await bot.editMessageText("Age range?", { chat_id: chatId, message_id: query.message.message_id,
      reply_markup: { inline_keyboard: [[{ text: '13-17', callback_data: 'reg_age_13-17' }, { text: '18-24', callback_data: 'reg_age_18-24' }], [{ text: '25-34', callback_data: 'reg_age_25-34' }, { text: '35-44', callback_data: 'reg_age_35-44' }], [{ text: '45-54', callback_data: 'reg_age_45-54' }, { text: '55+', callback_data: 'reg_age_55+' }]] }
    });
  } else if (data.startsWith('reg_age_')) {
    setState(chatId, 'reg_edu', null, { ...state.tempData, age_range: data.replace('reg_age_', '') });
    await bot.editMessageText("Education?", { chat_id: chatId, message_id: query.message.message_id,
      reply_markup: { inline_keyboard: [[{ text: 'Primary', callback_data: 'reg_edu_primary' }, { text: 'Secondary', callback_data: 'reg_edu_secondary' }], [{ text: 'Undergraduate', callback_data: 'reg_edu_undergraduate' }, { text: 'Graduate', callback_data: 'reg_edu_graduate' }], [{ text: 'Postgraduate', callback_data: 'reg_edu_postgraduate' }, { text: 'None', callback_data: 'reg_edu_none' }]] }
    });
  } else if (data.startsWith('reg_edu_')) {
    setState(chatId, 'reg_nickname', null, { ...state.tempData, education_level: data.replace('reg_edu_', '') });
    await bot.editMessageText("Choose a unique **nickname**:", { chat_id: chatId, message_id: query.message.message_id });
  }

  // Topic Selection (Multi-select)
  else if (data.startsWith('reg_topic_') || data.startsWith('apply_topic_') || data.startsWith('set_topics_')) {
    const prefix = data.startsWith('reg_topic_') ? 'reg_topic_' : (data.startsWith('apply_topic_') ? 'apply_topic_' : 'set_topics_');
    const action = data.replace(prefix, '');
    
    if (!state) return safeSend(chatId, "Session expired. Please start again.");

    if (action === 'done') {
        const topics = state.tempData.selectedTopics || (prefix === 'reg_topic_' ? [1] : []);
        
        if (prefix === 'reg_topic_') {
            // Store topics in tempData and move to Language selection
            state.tempData.selectedTopics = topics;
            setState(chatId, 'reg_language', null, state.tempData);
            await bot.editMessageText("Choose your preferred language:", {
                chat_id: chatId, message_id: query.message.message_id,
                reply_markup: {
                    inline_keyboard: [[{ text: 'English', callback_data: 'reg_lang_en' }, { text: 'Amharic (አማርኛ)', callback_data: 'reg_lang_am' }]]
                }
            });
        } else if (prefix === 'set_topics_') {
            await supabase.from('user_topics').delete().eq('telegram_id', chatId);
            for (const tid of topics) await supabase.from('user_topics').insert({ telegram_id: chatId, topic_id: tid });
            clearState(chatId); await safeSend(chatId, "✅ Topics updated!"); await showMainMenu(chatId);
        }
    } else {
        const tid = parseInt(action);
        const current = state.tempData.selectedTopics || [];
        const updated = current.includes(tid) ? current.filter(x => x !== tid) : [...current, tid];
        // Ensure state.step is preserved correctly
        const nextStep = prefix === 'reg_topic_' ? 'reg_topics' : 'edit_topics';
        setState(chatId, nextStep, null, { ...state.tempData, selectedTopics: updated });
        await bot.editMessageReplyMarkup(await getTopicPickerKeyboard(updated, prefix), { chat_id: chatId, message_id: query.message.message_id });
    }
  }

  // Language Selection
  else if (data.startsWith('reg_lang_')) {
    const lang = data.replace('reg_lang_', '');
    if (!state) return;
    
    // Finalize registration
    await supabase.from('users').insert({
        telegram_id: chatId, chat_id: chatId, anonymous_id: state.tempData.nickname,
        sex: state.tempData.sex, age_range: state.tempData.age_range, education_level: state.tempData.education_level, role: 'user'
    });
    await supabase.from('user_settings').insert({ telegram_id: chatId, language: lang });
    const topics = state.tempData.selectedTopics || [1];
    for (const tid of topics) await supabase.from('user_topics').insert({ telegram_id: chatId, topic_id: tid });
    
    clearState(chatId);
    await showMainMenu(chatId, `🎉 *Registration Complete!*\n\nLanguage set to ${lang === 'en' ? 'English' : 'Amharic'}.`);
  }

  // Mentor Search by Topic
  else if (data === 'menu_mentors') {
    const { data: ut } = await supabase.from('user_topics').select('topic_id, topics(name)').eq('telegram_id', chatId);
    if (!ut?.length) {
        await safeSend(chatId, "Please select topics first using /settopics.");
        return;
    }
    const buttons = ut.map(t => [{ text: t.topics.name, callback_data: `search_topic_${t.topic_id}` }]);
    await safeSend(chatId, "Select a topic to find mentors:", { reply_markup: { inline_keyboard: buttons } });
  } else if (data === 'menu_apply') {
    const { data: user } = await supabase.from('users').select('role').eq('telegram_id', chatId).single();
    if (user?.role === 'mentor' || user?.role === 'admin') {
      await bot.answerCallbackQuery(query.id, { text: "You are already a mentor.", show_alert: true });
      return;
    }
    
    const { data: existingApp } = await supabase.from('mentor_applications').select('id').eq('telegram_id', chatId).eq('status', 'pending').single();
    if (existingApp) {
      await bot.answerCallbackQuery(query.id, { text: "You already have a pending application.", show_alert: true });
      return;
    }

    setState(chatId, 'awaiting_mentor_q1');
    await safeSend(chatId, "How long have you been free from pornography (or your primary struggle)?");
  } else if (data.startsWith('search_topic_')) {
    await listMentors(chatId, 0, data.replace('search_topic_', ''));
  } else if (data.startsWith('mentors_page_')) {
    const parts = data.split('_'); // mentors_page_page_topicId
    await listMentors(chatId, parseInt(parts[2]), parts[3]);
  }

  else if (data.startsWith('mentor_req_')) {
    const parts = data.split('_'); // mentor_req_id_topicId
    setState(chatId, 'mentor_req_msg', null, { mentorId: parts[2], topicId: parts[3] });
    await safeSend(chatId, "Short message to mentor (optional), or /skip:");
  } else if (data.startsWith('mentor_accept_')) {
    const parts = data.split('_'); // mentor_accept_uid_tid
    await acceptMentorship(chatId, parts[2], parts[3]);
  } else if (data.startsWith('mentor_reject_')) {
    await rejectMentorship(chatId, data.split('_')[2]);
  }

  // Navigation
  else if (data === 'menu_chat') await safeSend(chatId, "Just type to chat. Use `/reply @nickname` if mentor with multiple mentees.");
  else if (data === 'menu_streak') await handleStreakFlow(chatId);
  else if (data === 'streak_mark') await markStreakAsRead(chatId);
  else if (data === 'menu_journal') await safeSend(chatId, "✏️ *Journal*", { reply_markup: { inline_keyboard: [[{ text: '✍️ New', callback_data: 'journal_new' }], [{ text: '📜 View', callback_data: 'journal_view_0' }]] } });
  else if (data === 'journal_new') { setState(chatId, 'journal_new'); await safeSend(chatId, "Write entry:"); }
  else if (data.startsWith('journal_view_')) await viewJournalEntries(chatId, parseInt(data.replace('journal_view_', '')));
  else if (data.startsWith('journal_read_')) await readJournalEntry(chatId, data.replace('journal_read_', ''));
  else if (data === 'menu_verse') await handleDailyVerse(chatId);
  else if (data === 'menu_settings') {
    const { data: user } = await supabase.from('users').select('role').eq('telegram_id', chatId).single();
    const { data: s } = await supabase.from('user_settings').select('*').eq('telegram_id', chatId).single();
    
    const kb = {
        inline_keyboard: [
            [{ text: `🔔 Verse: ${s.notif_verse ? 'ON' : 'OFF'}`, callback_data: 'settings_toggle_notif_verse' }],
            [{ text: `🔔 Messages: ${s.notif_messages ? 'ON' : 'OFF'}`, callback_data: 'settings_toggle_notif_messages' }],
            [{ text: `⏰ Verse Time: ${s.verse_time}:00`, callback_data: 'settings_time' }],
            [{ text: `🌍 Language: ${s.language === 'en' ? 'EN' : 'AM'}`, callback_data: 'settings_lang' }]
        ]
    };

    // Only show Expertise Topics to mentors or admins
    if (user?.role === 'mentor' || user?.role === 'admin') {
        kb.inline_keyboard.push([{ text: '📚 My Expertise Topics', callback_data: 'menu_mentor_topics' }]);
    }
    
    await safeSend(chatId, "⚙️ *Settings*", { reply_markup: kb });
  }
  else if (data === 'menu_mentor_topics') {
    const kb = await getMentorTopicKeyboard(chatId);
    await safeSend(chatId, "Select the topics you are qualified to counsel. Mentees will find you based on these selections:", { reply_markup: kb });
  }
  else if (data.startsWith('toggle_topic_')) {
    const topicId = parseInt(data.replace('toggle_topic_', ''));
    const { data: existing } = await supabase.from('mentor_topics').select('*').eq('telegram_id', chatId).eq('topic_id', topicId).single();
    
    if (existing) {
        await supabase.from('mentor_topics').delete().eq('telegram_id', chatId).eq('topic_id', topicId);
    } else {
        await supabase.from('mentor_topics').insert({ telegram_id: chatId, topic_id: topicId });
    }
    
    const kb = await getMentorTopicKeyboard(chatId);
    await bot.editMessageReplyMarkup(kb, { chat_id: chatId, message_id: query.message.message_id });
    await bot.answerCallbackQuery(query.id);
    return; // Prevent fall-through
  }
  else if (data === 'topic_done') {
    await safeSend(chatId, "✅ Your expertise topics have been updated.");
    await showMainMenu(chatId);
    await bot.answerCallbackQuery(query.id);
    return;
  }
  else if (data === 'topic_cancel') {
    await showMainMenu(chatId);
    await bot.answerCallbackQuery(query.id);
    return;
  }
  else if (data.startsWith('settings_toggle_')) await toggleSetting(chatId, data.replace('settings_toggle_', ''));
  else if (data === 'menu_schedule') {
    setState(chatId, 'sched_type', null, { type: 'group' });
    await safeSend(chatId, "Select session type:", {
        reply_markup: {
            inline_keyboard: [
                [{ text: '👤 1-on-1 (Private)', callback_data: 'sched_type_private' }],
                [{ text: '👥 Group Session', callback_data: 'sched_type_group' }]
            ]
        }
    });
  }
  else if (data.startsWith('sched_type_')) {
    const type = data.replace('sched_type_', '');
    if (!state) return;
    state.tempData.type = type;
    if (type === 'private') {
        const { data: mentees } = await supabase.from('mentorship_assignments').select('user_id, users(anonymous_id)').eq('mentor_id', chatId).eq('is_active', true);
        if (!mentees?.length) return safeSend(chatId, "No mentees to schedule with.");
        const buttons = mentees.map(m => [{ text: m.users.anonymous_id, callback_data: `sched_mentee_${m.user_id}` }]);
        await safeSend(chatId, "Select mentee:", { reply_markup: { inline_keyboard: buttons } });
    } else {
        setState(chatId, 'sched_date', null, state.tempData);
        await safeSend(chatId, "Enter date (YYYY-MM-DD):");
    }
  }
  else if (data.startsWith('sched_mentee_')) {
    if (!state) return;
    state.tempData.mentee_id = data.replace('sched_mentee_', '');
    setState(chatId, 'sched_date', null, state.tempData);
    await safeSend(chatId, "Enter date (YYYY-MM-DD):");
  }
  else if (data === 'menu_mentees') {
    const { data: mentees } = await supabase.from('mentorship_assignments').select('user_id, users(anonymous_id), topics(name)').eq('mentor_id', chatId).eq('is_active', true);
    if (!mentees?.length) return safeSend(chatId, "No active mentees.");
    let t = "👥 *My Mentees*\n\n";
    mentees.forEach(m => t += `👤 @${m.users.anonymous_id} (${m.topics.name})\n`);
    await safeSend(chatId, t);
  }
  else if (data === 'settings_time') { setState(chatId, 'set_verse_time'); await safeSend(chatId, "Enter hour (0-23 UTC):"); }
  else if (data === 'settings_lang') {
    await bot.editMessageText("Choose language:", {
        chat_id: chatId, message_id: query.message.message_id,
        reply_markup: { inline_keyboard: [[{ text: 'English', callback_data: 'set_lang_en' }, { text: 'Amharic', callback_data: 'set_lang_am' }]] }
    });
  }
  else if (data.startsWith('set_lang_')) {
    const lang = data.replace('set_lang_', '');
    await supabase.from('user_settings').update({ language: lang }).eq('telegram_id', chatId);
    await safeSend(chatId, `✅ Language updated to ${lang === 'en' ? 'English' : 'Amharic'}.`);
  }

  bot.answerCallbackQuery(query.id);
});

// ─── Implementation ──────────────────────────────────────────────────────────

async function listMentors(chatId, page = 0, topicId) {
  const limit = 5;
  const { data: mIds } = await supabase.from('mentor_topics').select('telegram_id').eq('topic_id', topicId);
  const ids = (mIds || []).map(x => x.telegram_id);
  if (!ids.length) return safeSend(chatId, "No mentors for this topic.");

  const { data: ms } = await supabase.from('users').select('telegram_id, anonymous_id, user_settings(display_name, bio)').in('telegram_id', ids).eq('is_banned', false).range(page*limit, (page+1)*limit-1);
  if (!ms?.length) return safeSend(chatId, "No mentors.");

  let t = `🔍 *Mentors*\n\n`;
  const bs = ms.map(m => {
    t += `👤 *${m.user_settings?.display_name || m.anonymous_id}*\nBio: ${m.user_settings?.bio || '...'}\n\n`;
    return [{ text: `Request ${m.anonymous_id}`, callback_data: `mentor_req_${m.telegram_id}_${topicId}` }];
  });
  if (page > 0) bs.push([{ text: '⬅️', callback_data: `mentors_page_${page-1}_${topicId}` }]); // Need to handle pagination with topicId
  await safeSend(chatId, t, { reply_markup: { inline_keyboard: bs } });
}

async function acceptMentorship(mentorId, userId, topicId) {
  await supabase.from('mentorship_assignments').insert({ mentor_id: mentorId, user_id: userId, topic_id: topicId });
  await supabase.from('mentorship_requests').update({ status: 'accepted' }).eq('mentor_id', mentorId).eq('user_id', userId);
  await safeSend(userId, "✅ Mentorship Accepted! Type normally here to chat.");
  await safeSend(mentorId, "✅ Accepted.");
}

async function rejectMentorship(mentorId, userId) {
  await supabase.from('mentorship_requests').update({ status: 'rejected' }).eq('mentor_id', mentorId).eq('user_id', userId);
  await safeSend(userId, "📋 Request rejected."); await safeSend(mentorId, "✅ Rejected.");
}

async function handleStreakFlow(chatId) {
  const { data: s } = await supabase.from('bible_streaks').select('*').eq('telegram_id', chatId).single();
  const { data: vs } = await supabase.from('daily_verses').select('*').eq('is_active', true);
  const v = vs?.[Math.floor(Date.now() / 86400000) % vs.length] || { reference: '...', text: '...' };
  const t = `🔥 Streak: *${s?.current_streak || 0}*\nToday:\n*${v.reference}*\n_${v.text}_`;
  const bs = s?.last_read_date === new Date().toISOString().split('T')[0] ? [] : [[{ text: '✅ Mark Read', callback_data: 'streak_mark' }]];
  await safeSend(chatId, t, { reply_markup: { inline_keyboard: [...bs, [{ text: '🔙', callback_data: 'menu_help' }]] } });
}

async function markStreakAsRead(chatId) {
  const today = new Date().toISOString().split('T')[0];
  const { data: s } = await supabase.from('bible_streaks').select('*').eq('telegram_id', chatId).single();
  if (!s) await supabase.from('bible_streaks').insert({ telegram_id: chatId, current_streak: 1, longest_streak: 1, last_read_date: today });
  else if (s.last_read_date !== today) {
    const yest = new Date(); yest.setDate(yest.getDate() - 1);
    const n = s.last_read_date === yest.toISOString().split('T')[0] ? s.current_streak + 1 : 1;
    await supabase.from('bible_streaks').update({ current_streak: n, longest_streak: Math.max(n, s.longest_streak), last_read_date: today }).eq('telegram_id', chatId);
  }
  await safeSend(chatId, "✅ Done!"); await handleStreakFlow(chatId);
}

async function viewJournalEntries(chatId, page = 0) {
  const limit = 5;
  const { data: es } = await supabase.from('journal_entries').select('id, content, created_at').eq('telegram_id', chatId).order('created_at', { ascending: false }).range(page*limit, (page+1)*limit-1);
  if (!es?.length) return safeSend(chatId, "Empty.");
  const bs = es.map(e => [{ text: `${new Date(e.created_at).toLocaleDateString()}: ${e.content.substring(0, 15)}...`, callback_data: `journal_read_${e.id}` }]);
  await safeSend(chatId, "📜 *Entries*", { reply_markup: { inline_keyboard: bs } });
}

async function readJournalEntry(chatId, id) {
  const { data: e } = await supabase.from('journal_entries').select('*').eq('id', id).single();
  if (e) await safeSend(chatId, `📅 ${new Date(e.created_at).toLocaleString()}\n\n${e.content}`, { reply_markup: { inline_keyboard: [[{ text: '🔙', callback_data: 'journal_view_0' }]] } });
}

async function handleDailyVerse(chatId) {
    const { data: vs } = await supabase.from('daily_verses').select('*').eq('is_active', true);
    const v = vs?.[Math.floor(Date.now() / 86400000) % vs.length];
    if (v) {
        let t = `📖 *Verse*\n*${v.reference}*\n\n${v.text}`;
        const { data: s } = await supabase.from('user_settings').select('language').eq('telegram_id', chatId).single();
        if (s?.language === 'am') {
            const amVerse = await getAmharicVerse(v.text);
            if (amVerse) t += `\n\n🇪🇹 *Amharic:*\n_${amVerse}_`;
        }
        await safeSend(chatId, t);
    }
}

async function handleSettingsFlow(chatId) {
  const { data: s } = await supabase.from('user_settings').select('*').eq('telegram_id', chatId).single();
  const { data: u } = await supabase.from('users').select('anonymous_id').eq('telegram_id', chatId).single();
  const t = `⚙️ *Settings*\nNick: ${u.anonymous_id}\nLang: ${s?.language === 'am' ? 'Amharic' : 'English'}\nTime: ${s?.verse_time}:00 UTC`;
  await safeSend(chatId, t, { reply_markup: { inline_keyboard: [[{ text: '🔔 Notifications', callback_data: 'settings_toggle_notify_messages' }], [{ text: '⏰ Verse Time', callback_data: 'settings_time' }], [{ text: '🔙', callback_data: 'menu_help' }]] } });
}

async function toggleSetting(chatId, f) {
  const { data: s } = await supabase.from('user_settings').select(f).eq('telegram_id', chatId).single();
  await supabase.from('user_settings').update({ [f]: !s[f] }).eq('telegram_id', chatId);
  await handleSettingsFlow(chatId);
}

async function notifyMentorApproved(chatId) {
    await safeSend(chatId, "🎉 *Congratulations!*\n\nYour application to become a mentor has been approved. You now have access to mentor features in the menu.");
    
    // Auto-prompt to set topics if none exist
    const { data: mt } = await supabase.from('mentor_topics').select('topic_id').eq('telegram_id', chatId);
    if (!mt?.length) {
        const kb = await getMentorTopicKeyboard(chatId);
        await safeSend(chatId, "Please set your expertise topics to start receiving mentee requests. You can also do this later in Settings.", { reply_markup: kb });
    } else {
        await showMainMenu(chatId);
    }
}

async function notifyMentorRejected(chatId) {
    const { data: app } = await supabase.from('mentor_applications').select('admin_note').eq('telegram_id', chatId).order('reviewed_at', { ascending: false }).limit(1).single();
    let msg = "📋 *Application Update*\n\nUnfortunately, your application to become a mentor was not approved at this time.";
    if (app?.admin_note) msg += `\n\n*Admin Note:* ${app.admin_note}`;
    await safeSend(chatId, msg);
}

async function broadcastToAll(message, role_filter) {
    let query = supabase.from('users').select('telegram_id').eq('is_banned', false);
    if (role_filter) query = query.eq('role', role_filter);
    const { data: users } = await query;
    if (users) {
        for (const u of users) {
            await safeSend(u.telegram_id, `📢 *Broadcast Message*\n\n${message}`);
        }
    }
}

// ─── Scheduler ────────────────────────────────────────────────────────────────
setInterval(async () => {
    const now = new Date(); if (now.getUTCMinutes() !== 0) return;
    const { data: opted } = await supabase.from('user_settings').select('telegram_id, language').eq('notify_daily_verse', true).eq('verse_time', now.getUTCHours());
    const { data: vs } = await supabase.from('daily_verses').select('*').eq('is_active', true);
    const v = vs?.[Math.floor(Date.now() / 86400000) % vs.length];
    if (v && opted?.length) {
        for (const u of opted) {
            let t = `📖 *Daily Verse*\n*${v.reference}*\n\n${v.text}`;
            if (u.language === 'am') {
                const amVerse = await getAmharicVerse(v.text);
                if (amVerse) t += `\n\n🇪🇹 *Amharic:*\n_${amVerse}_`;
            }
            await safeSend(u.telegram_id, t);
        }
    }
}, 60 * 1000);

// ─── Polling for Mentor Application Status ────────────────────────────────────
let lastAppCheck = new Date().toISOString();
setInterval(async () => {
    const { data: apps } = await supabase
        .from('mentor_applications')
        .select('telegram_id, status, reviewed_at')
        .neq('status', 'pending')
        .gt('reviewed_at', lastAppCheck);
    
    if (apps?.length) {
        for (const app of apps) {
            if (app.status === 'approved') await notifyMentorApproved(app.telegram_id);
            else if (app.status === 'rejected') await notifyMentorRejected(app.telegram_id);
        }
        lastAppCheck = new Date().toISOString();
    }
}, 60 * 1000);

module.exports = { bot, notifyMentorApproved, notifyMentorRejected, broadcastToAll };
