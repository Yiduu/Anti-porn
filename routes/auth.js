'use strict';

const express = require('express');
const { v4: uuidv4 } = require('uuid');

module.exports = function authRoutes(supabase, requireAuth) {
  const router = express.Router();

  // Generate anonymous ID like "Warrior_9XkL2"
  const adjectives = ['Warrior','Pilgrim','Seeker','Overcomer','Champion','Victor','Pilgrim','Steadfast','Faithful','Renewed','Redeemed','Freed'];
  function generateAnonId() {
    const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
    const suffix = Math.random().toString(36).substring(2, 7).toUpperCase();
    return `${adj}_${suffix}`;
  }

  // GET /api/auth/me – get or check current user
  router.get('/me', requireAuth, async (req, res) => {
    const { id: telegram_id } = req.telegramUser;
    const { data, error } = await supabase
      .from('users')
      .select('*, user_settings(*)')
      .eq('telegram_id', telegram_id)
      .single();

    if (error && error.code !== 'PGRST116') return res.status(500).json({ error: error.message });

    if (!data) return res.json({ registered: false });
    if (data.is_banned) return res.status(403).json({ error: 'Account banned' });

    // Update last_active
    await supabase.from('users').update({ last_active: new Date().toISOString() }).eq('telegram_id', telegram_id);

    res.json({ registered: true, user: data, admin_id: process.env.ADMIN_TELEGRAM_ID });
  });

  // POST /api/auth/register
  router.post('/register', requireAuth, async (req, res) => {
    const { id: telegram_id, username } = req.telegramUser;
    const { sex, age_range, education_level, chat_id } = req.body;

    // Validate
    if (!sex || !age_range || !education_level) {
      return res.status(400).json({ error: 'Missing required fields' });
    }

    // Check if already registered
    const { data: existing } = await supabase
      .from('users')
      .select('telegram_id')
      .eq('telegram_id', telegram_id)
      .single();

    if (existing) return res.status(409).json({ error: 'Already registered' });

    // Generate unique anonymous_id
    let anonymous_id;
    let attempts = 0;
    do {
      anonymous_id = generateAnonId();
      const { data: collision } = await supabase.from('users').select('anonymous_id').eq('anonymous_id', anonymous_id).single();
      if (!collision) break;
      attempts++;
    } while (attempts < 10);

    const { data: user, error } = await supabase
      .from('users')
      .insert({ telegram_id, anonymous_id, sex, age_range, education_level, chat_id: chat_id || telegram_id })
      .select()
      .single();

    if (error) return res.status(500).json({ error: error.message });

    // Create default settings
    await supabase.from('user_settings').insert({ telegram_id, display_name: anonymous_id });

    res.status(201).json({ user });
  });

  // GET /api/auth/verse – today's daily verse
  router.get('/verse', async (req, res) => {
    const dayOfYear = Math.floor((Date.now() - new Date(new Date().getFullYear(), 0, 0)) / 86400000);
    const { data, error } = await supabase
      .from('daily_verses')
      .select('*')
      .eq('is_active', true);

    if (error || !data?.length) return res.json({ reference: 'Philippians 4:13', text: 'I can do all this through him who gives me strength.' });

    const verse = data[dayOfYear % data.length];
    res.json(verse);
  });

  return router;
};
