'use strict';

const express = require('express');

const PROFANITY_LIST = ['fuck','shit','ass','bitch','damn','crap','bastard','hell','piss'];

function containsProfanity(text) {
  const lower = text.toLowerCase();
  return PROFANITY_LIST.some(word => lower.includes(word));
}

module.exports = function messageRoutes(supabase, requireAuth, io, onlineUsers) {
  const router = express.Router();

  // GET /api/messages/:with – conversation with a user
  router.get('/:with', requireAuth, async (req, res) => {
    const { id: my_id } = req.telegramUser;
    const other_id = parseInt(req.params.with);

    // Verify they have an assignment together
    const { data: assign } = await supabase
      .from('mentorship_assignments')
      .select('id')
      .or(`user_id.eq.${my_id},mentor_id.eq.${my_id}`)
      .or(`user_id.eq.${other_id},mentor_id.eq.${other_id}`)
      .eq('is_active', true)
      .single();

    if (!assign) return res.status(403).json({ error: 'No active mentorship with this user' });

    const { data, error } = await supabase
      .from('messages')
      .select('*')
      .or(`and(from_id.eq.${my_id},to_id.eq.${other_id}),and(from_id.eq.${other_id},to_id.eq.${my_id})`)
      .order('created_at', { ascending: true })
      .limit(100);

    if (error) return res.status(500).json({ error: error.message });

    // Mark as read
    await supabase.from('messages').update({ is_read: true }).eq('to_id', my_id).eq('from_id', other_id).eq('is_read', false);

    res.json(data || []);
  });

  // POST /api/messages – send message
  router.post('/', requireAuth, async (req, res) => {
    const { id: from_id } = req.telegramUser;
    const { to_id, content } = req.body;

    if (!to_id || !content?.trim()) return res.status(400).json({ error: 'to_id and content required' });
    if (content.length > 2000) return res.status(400).json({ error: 'Message too long' });

    // Verify active assignment between sender and receiver
    const { data: assign } = await supabase
      .from('mentorship_assignments')
      .select('id')
      .or(`and(user_id.eq.${from_id},mentor_id.eq.${to_id}),and(user_id.eq.${to_id},mentor_id.eq.${from_id})`)
      .eq('is_active', true)
      .single();

    if (!assign) return res.status(403).json({ error: 'No active mentorship with this user' });

    const is_flagged = containsProfanity(content);

    const { data: msg, error } = await supabase
      .from('messages')
      .insert({ from_id, to_id, content: content.trim(), is_flagged })
      .select()
      .single();

    if (error) return res.status(500).json({ error: error.message });

    // Real-time push to recipient
    const recipientSocket = onlineUsers.get(String(to_id));
    if (recipientSocket) {
      io.to(recipientSocket).emit('new_message', msg);
    }

    res.status(201).json(msg);
  });

  // GET /api/messages/unread/count
  router.get('/unread/count', requireAuth, async (req, res) => {
    const { id } = req.telegramUser;
    const { count } = await supabase.from('messages').select('id', { count: 'exact', head: true }).eq('to_id', id).eq('is_read', false);
    res.json({ count: count || 0 });
  });

  return router;
};
