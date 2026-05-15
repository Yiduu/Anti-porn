/* ============================================================
   Recovery App – Main App Logic
   ============================================================ */

const API = window.location.origin;
let socket = null;
let currentUser = null;
let currentPage = 'dashboard';
let jitsiApi = null;
let chart = null;

// ─── Helpers ──────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

function getTelegramData() {
  if (window.Telegram?.WebApp) {
    return {
      initData: window.Telegram.WebApp.initData,
      user: window.Telegram.WebApp.initDataUnsafe?.user,
    };
  }
  // Dev fallback
  return { initData: '', user: { id: 12345, first_name: 'Dev' } };
}

async function apiFetch(path, opts = {}) {
  const { initData } = getTelegramData();
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'x-telegram-init-data': initData,
      'x-telegram-id': getTelegramData().user?.id || '',
      ...(opts.headers || {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('text/csv')) return res.blob();
  return res.json();
}

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff/60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff/3600000)}h ago`;
  return `${Math.floor(diff/86400000)}d ago`;
}

function formatTime(dateStr) {
  const tz = currentUser?.user_settings?.timezone || 'UTC';
  try {
    return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: tz });
  } catch (e) {
    return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
}

function formatDateTime(dateStr) {
  const tz = currentUser?.user_settings?.timezone || 'UTC';
  try {
    return new Date(dateStr).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short', timeZone: tz });
  } catch (e) {
    return new Date(dateStr).toLocaleString();
  }
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function showToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  t.style.cssText = `
    position:fixed;top:16px;left:50%;transform:translateX(-50%);
    background:${type==='error'?'var(--danger)':type==='success'?'var(--success)':'var(--bg3)'};
    color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;
    font-size:.85rem;font-weight:700;animation:fadeIn .2s ease;
    max-width:90vw;text-align:center;
  `;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ─── Theme ────────────────────────────────────────────────────
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  const icon = $('themeIcon');
  if (icon) icon.textContent = theme === 'light' ? '🌙' : '☀️';
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  setTheme(cur === 'dark' ? 'light' : 'dark');
}
setTheme(localStorage.getItem('theme') || 'dark');

// ─── Init ─────────────────────────────────────────────────────
async function init() {
  const tg = window.Telegram?.WebApp;
  if (tg) { tg.ready(); tg.expand(); }

  try {
    const data = await apiFetch('/api/auth/me');
    window.ADMIN_ID = data.admin_id;
    if (!data.registered) {
      showOnboarding();
    } else {
      currentUser = data.user;
      if (currentUser.is_banned) {
        document.body.innerHTML = '<div style="padding:40px;text-align:center;color:#E05C5C;font-family:Cinzel,serif;font-size:1.2rem;">Account suspended.<br><br>Contact support.</div>';
        return;
      }
      startApp();
    }
    
    // Deep link handling
    const urlParams = new URLSearchParams(window.location.search);
    const startParam = urlParams.get('start');
    if (startParam && startParam.startsWith('session_')) {
      const sessionId = startParam.replace('session_', '');
      setTimeout(() => {
        joinSession(sessionId);
      }, 1000);
    }
  } catch (e) {
    console.error(e);
    showToast('Connection error', 'error');
    // Show onboarding as fallback
    showOnboarding();
  }

  $('loadingScreen')?.classList.add('hidden');
}

// ─── Socket Setup ─────────────────────────────────────────────
function connectSocket() {
  socket = io(API);
  socket.on('connect', () => {
    socket.emit('auth', getTelegramData().user?.id);
    $('reconnectBanner')?.classList.remove('show');
  });
  socket.on('disconnect', () => {
    $('reconnectBanner')?.classList.add('show');
  });
  socket.on('new_message', (msg) => {
    if (currentPage === 'chat' && window.chatState?.with === msg.from_id) {
      appendMessage(msg, false);
    } else {
      updateMessageBadge();
      showToast('New message received');
    }
  });
  socket.on('session_invite', (session) => {
    showToast(`📹 Session invite: ${session.title}`, 'info');
    if (confirm('A new session has been scheduled. Go to Sessions page to join?')) {
      navigate('sessions');
    }
  });
  socket.on('broadcast', ({ message }) => {
    showToast(`📢 ${message}`);
  });
  socket.on('typing', ({ from_id }) => {
    if (window.chatState?.with === from_id) {
      $('typingIndicator').textContent = 'typing...';
      clearTimeout(window.typingTimeout);
      window.typingTimeout = setTimeout(() => { $('typingIndicator').textContent = ''; }, 2000);
    }
  });
  socket.on('new_mentorship_request', () => {
    showToast('New mentorship request received! 🙏', 'success');
    if (currentPage === 'requests') loadRequests();
  });
}

// ─── Navigation ───────────────────────────────────────────────
function navigate(page) {
  currentPage = page;
  $$('.page').forEach(p => p.classList.remove('active'));
  $$('.nav-item').forEach(n => n.classList.remove('active'));
  $(`page-${page}`)?.classList.add('active');
  $(`nav-${page}`)?.classList.add('active');

  // Load page data
  switch (page) {
    case 'dashboard': loadDashboard(); break;
    case 'mentors': loadMentors(); break;
    case 'sessions': loadSessions(); break;
    case 'chat': 
      loadChat(); 
      // Force input row to appear after a short delay (allow loadChat to finish)
      setTimeout(forceShowChatInputRow, 200);
      break;
    case 'requests': loadRequests(); break;
    case 'settings': loadSettings(); break;
    case 'my-mentees': loadMyMentees(); break;
  }
}

// FIX: Direct force-show helper for chat input
function forceShowChatInputRow() {
  const row = document.getElementById('chatInputRow');
  if (row) {
    row.style.display = 'flex';
    row.style.visibility = 'visible';
    row.style.opacity = '1';
    console.log('[FIX] Chat input row forced visible');
  } else {
    console.error('[FIX] chatInputRow missing');
  }
}

// ─── Onboarding ───────────────────────────────────────────────
let onboardingStep = 0;

function showOnboarding() {
  $('loadingScreen')?.classList.add('hidden');
  $('onboarding').style.display = 'flex';
  showStep(0);
}

function showStep(step) {
  onboardingStep = step;
  $$('.step-dot').forEach((d, i) => {
    d.classList.toggle('active', i === step);
    d.classList.toggle('done', i < step);
  });
  $$('.onboarding-step').forEach((s, i) => s.classList.toggle('hidden', i !== step));
}

async function completeRegistration() {
  const sex = $('regSex').value;
  const age_range = $('regAge').value;
  const education_level = $('regEdu').value;
  const nickname = $('regNickname').value.trim();

  if (!sex || !age_range || !education_level || !nickname) { 
    showToast('Please complete all fields', 'error'); return; 
  }

  // Validate nickname: 3-20 chars, alphanumeric + underscores
  const nickRegex = /^[a-zA-Z0-9_]{3,20}$/;
  if (!nickRegex.test(nickname)) {
    showToast('Invalid nickname format (3-20 chars, no spaces)', 'error'); return;
  }

  const regBtn = $('regBtn');
  regBtn.disabled = true; regBtn.textContent = 'Registering...';

  try {
    const data = await apiFetch('/api/auth/register', {
      method: 'POST',
      body: { sex, age_range, education_level, nickname, chat_id: getTelegramData().user?.id },
    });
    currentUser = data.user;
    $('onboarding').style.display = 'none';
    startApp();
    showToast('Welcome! You are now registered 🙏', 'success');
  } catch (e) {
    if (e.message.includes('taken')) {
      showToast('Nickname taken, try another', 'error');
    } else {
      showToast(e.message, 'error');
    }
    regBtn.disabled = false; regBtn.textContent = 'Join the Community 🙏';
  }
}

// ─── Start App ────────────────────────────────────────────────
function startApp() {
  $('app').classList.remove('hidden');
  connectSocket();
  keepAlive();
  navigate('dashboard');
  updateMessageBadge();

  // Show admin button if current user is admin
  if (String(currentUser?.telegram_id) === String(window.ADMIN_ID)) {
    $('adminBtn')?.classList.remove('hidden');
  }

  // Show requests nav if mentor
  if (currentUser?.role === 'mentor') {
    $('nav-requests')?.classList.remove('hidden');
    $('nav-my-mentees')?.style.setProperty('display', 'flex');
  }

  // Initial translation
  applyLanguage();
}

// Keep-alive for Render free tier
function keepAlive() {
  setInterval(() => fetch(`${API}/health`).catch(() => {}), 4 * 60 * 1000);
}

// ─── Dashboard ────────────────────────────────────────────────
async function loadDashboard() {
  // Load verse
  try {
    const verse = await apiFetch('/api/auth/verse');
    $('verseText').textContent = verse.text;
    $('verseRef').textContent = verse.reference;
  } catch {}

  // Load stats
  try {
    const stats = await apiFetch('/api/users/stats');
    $('statUsers').textContent = stats.total_users;
    $('statMentors').textContent = stats.active_mentors;
    $('statSessions').textContent = stats.sessions_today;
  } catch {}

  // Load chart
  loadActivityChart();

  // Show admin button if admin
  if (String(currentUser?.telegram_id) === String(window.ADMIN_ID)) {
    $('adminBtn')?.classList.remove('hidden');
  }
}

async function loadActivityChart() {
  try {
    const data = await apiFetch('/api/users/weekly-activity');
    const ctx = $('activityChart')?.getContext('2d');
    if (!ctx) return;
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.date),
        datasets: [
          {
            label: 'Messages',
            data: data.map(d => d.messages),
            backgroundColor: 'rgba(201,168,76,0.4)',
            borderColor: 'rgba(201,168,76,0.8)',
            borderWidth: 1, borderRadius: 4,
          },
          {
            label: 'Sessions',
            data: data.map(d => d.sessions),
            backgroundColor: 'rgba(91,142,255,0.4)',
            borderColor: 'rgba(91,142,255,0.8)',
            borderWidth: 1, borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: getComputedStyle(document.documentElement).getPropertyValue('--text2').trim() } } },
        scales: {
          x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true },
        },
      },
    });
  } catch (e) { console.error('Chart error:', e); }
}

// ─── Mentors ──────────────────────────────────────────────────
async function loadMentors() {
  const container = $('mentorsList');
  container.innerHTML = '<div class="loading-spinner" style="margin:40px auto"></div>';

  try {
    const mentors = await apiFetch('/api/mentors');
    if (!mentors.length) {
      container.innerHTML = '<div class="empty-state"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg><span>No mentors available</span></div>';
      return;
    }

    container.innerHTML = mentors.map(m => {
      const name = m.user_settings?.display_name || m.anonymous_id;
      const bio = m.user_settings?.bio || 'No bio provided';
      const spec = m.user_settings?.specialization || '';
      const mentees = m.mentee_count || 0;
      const max = m.user_settings?.max_mentees || 5;
      const letter = name.charAt(0).toUpperCase();
      return `
        <div class="mentor-card">
          <div class="flex items-center gap-8">
            <div class="mentor-avatar">${letter}</div>
            <div class="mentor-info">
              <div class="mentor-id">${escapeHtml(name)}</div>
              <div class="mentor-bio">${escapeHtml(bio)}</div>
            </div>
          </div>
          <div class="mentor-meta">
            ${spec ? `<span class="mentor-badge badge-spec">${escapeHtml(spec)}</span>` : ''}
            <span class="mentor-badge badge-mentees">${mentees}/${max} mentees</span>
          </div>
          <button class="btn btn-outline btn-sm" onclick="requestMentorship(${m.telegram_id})" ${mentees >= max ? 'disabled' : ''}>
            ${mentees >= max ? 'Full' : 'Request Mentorship'}
          </button>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><span>${e.message}</span></div>`;
  }
}

async function requestMentorship(mentor_id) {
  try {
    await apiFetch('/api/mentors/request', { method: 'POST', body: { mentor_id, message: 'I would like your mentorship.' } });
    showToast('Mentorship request sent! 🙏', 'success');
    loadMentors();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ─── Mentorship Requests ──────────────────────────────────────
async function loadRequests() {
  const container = $('requestsList');
  if (!container) return;
  container.innerHTML = '<div class="loading-spinner" style="margin:40px auto"></div>';
  try {
    const requests = await apiFetch('/api/mentors/my-requests');
    if (!requests.length) {
      container.innerHTML = '<div class="empty-state"><span>No pending requests</span></div>';
      return;
    }
    container.innerHTML = requests.map(r => {
      const name = r.sender?.user_settings?.display_name || r.sender?.anonymous_id || 'Anonymous';
      return `
        <div class="mentor-card">
          <div class="mentor-info">
            <div class="mentor-id">${escapeHtml(name)}</div>
            <div class="mentor-bio" style="margin-top:4px">${escapeHtml(r.message)}</div>
          </div>
          <div class="flex gap-8 mt-12">
            <button class="btn btn-primary btn-sm flex-1" onclick="respondToRequest('${r.id}', 'accepted')">Accept</button>
            <button class="btn btn-outline btn-sm flex-1" onclick="respondToRequest('${r.id}', 'rejected')">Reject</button>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><span>${e.message}</span></div>`;
  }
}

async function respondToRequest(requestId, action) {
  try {
    await apiFetch(`/api/mentors/request/${requestId}`, {
      method: 'PATCH',
      body: { action }
    });
    showToast(`Request ${action}`, 'success');
    loadRequests();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ─── Sessions ─────────────────────────────────────────────────
async function loadSessions() {
  // Load private sessions (1-on-1 and group where user is participant)
  try {
    const mySessions = await apiFetch('/api/sessions/my');
    const privateContainer = document.getElementById('privateSessionsList');
    if (!privateContainer) return;
    if (mySessions.length === 0) {
      privateContainer.innerHTML = '<div class="empty-state">No active or upcoming private sessions.</div>';
    } else {
      privateContainer.innerHTML = mySessions.map(s => {
        const session = s.session;
        const isGroup = session.is_group;
        const title = session.title || (isGroup ? 'Group Session' : 'Private Session');
        const scheduled = formatDateTime(session.scheduled_at);
        return `
          <div class="session-item">
            <div class="session-icon">${isGroup ? '👥' : '👤'}</div>
            <div class="session-body">
              <div class="session-title">${escapeHtml(title)}</div>
              <div class="session-sub">${scheduled} • ${session.status}</div>
            </div>
            ${session.status === 'scheduled' ? `<button class="btn btn-primary btn-sm" onclick="joinSession('${session.id}')">Join</button>` : '<span class="chip chip-green">Completed</span>'}
          </div>`;
      }).join('');
    }
  } catch (e) { console.error('Error loading private sessions', e); }

  // Load upcoming group sessions
  try {
    const upcoming = await apiFetch('/api/sessions/upcoming');
    const container = document.getElementById('upcomingSessions');
    if (!container) return;
    if (!upcoming.length) {
      container.innerHTML = '<div class="empty-state"><span>No upcoming group sessions</span></div>';
      return;
    }
    container.innerHTML = upcoming.map(s => `
      <div class="session-item">
        <div class="session-icon">👥</div>
        <div class="session-body">
          <div class="session-title">${escapeHtml(s.title)}</div>
          <div class="session-sub">${formatDateTime(s.scheduled_at)}</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="joinSession('${s.id}')">Join</button>
      </div>`).join('');
  } catch (e) {
    if (document.getElementById('upcomingSessions')) {
      document.getElementById('upcomingSessions').innerHTML = `<div class="empty-state"><span>${e.message}</span></div>`;
    }
  }
}

async function joinSession(session_id) {
  try {
    const data = await apiFetch(`/api/sessions/${session_id}/join`);
    launchJitsi(data.room_name, data.room_password, data.display_name, data.jitsi_token);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function createSession(is_group = false, mentee_id = null, scheduled_at = null, customTitle = null, participant_ids = []) {
  try {
    if (!is_group && !mentee_id && currentUser?.role === 'mentor') {
      const res = await apiFetch('/api/users/chat-partner');
      if (res.type === 'single') {
        mentee_id = res.partner.telegram_id;
      } else if (res.type === 'multiple') {
        openMenteeSelectModal();
        return;
      } else {
        showToast('No active mentees to start a session with.', 'error');
        return;
      }
    }

    const title = customTitle || (is_group ? prompt('Session title (or leave blank):') : 'Private session');
    const finalScheduled = scheduled_at || new Date().toISOString();
    
    const data = await apiFetch('/api/sessions/create', {
      method: 'POST',
      body: { 
        is_group, 
        title, 
        scheduled_at: finalScheduled, 
        mentee_id: mentee_id || null,
        participant_ids: participant_ids.length ? participant_ids : undefined
      }
    });
    
    showToast(is_group ? 'Group session created!' : 'Private session created!', 'success');
    if (new Date(finalScheduled) <= new Date()) {
      launchJitsi(data.room_name, data.room_password, currentUser.anonymous_id, data.jitsi_token);
    } else {
      loadSessions();
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function showScheduleModal(is_group, mentee_id = null) {
  const modal = document.getElementById('scheduleModal');
  const titleField = document.getElementById('groupTitleField');
  const participantField = document.getElementById('groupParticipantsField');
  const menteeList = document.getElementById('menteeCheckboxes');
  const modalTitle = document.getElementById('scheduleModalTitle');
  const btn = document.getElementById('scheduleBtn');
  
  if (!modal) return;
  
  modalTitle.textContent = is_group ? 'Schedule Group Session' : 'Schedule 1-on-1 Session';
  titleField.classList.toggle('hidden', !is_group);
  participantField.classList.toggle('hidden', !is_group);
  
  if (is_group && menteeList) {
    menteeList.innerHTML = '<div class="text-xs text-dim">Loading mentees...</div>';
    apiFetch('/api/mentors/my-mentees').then(mentees => {
      if (!mentees.length) {
        menteeList.innerHTML = '<div class="text-xs text-dim">No mentees to invite.</div>';
        return;
      }
      menteeList.innerHTML = mentees.map(m => `
        <label class="flex items-center gap-8 mb-4" style="cursor:pointer">
          <input type="checkbox" name="invite_mentee" value="${m.user.telegram_id}" />
          <span class="text-sm">${escapeHtml(m.user.anonymous_id)}</span>
        </label>
      `).join('');
    }).catch(e => {
      menteeList.innerHTML = `<div class="text-danger text-xs">${e.message}</div>`;
    });
  }

  // Set default values (1 hour from now)
  const now = new Date();
  now.setHours(now.getHours() + 1);
  document.getElementById('scheduleDate').value = now.toISOString().split('T')[0];
  document.getElementById('scheduleTime').value = now.toTimeString().slice(0,5);
  
  modal.classList.add('open');
  
  btn.onclick = () => {
    const date = document.getElementById('scheduleDate').value;
    const time = document.getElementById('scheduleTime').value;
    const title = document.getElementById('scheduleTitle').value || (is_group ? 'Group Session' : '1-on-1 Session');
    
    if (!date || !time) {
      showToast('Please pick date and time', 'error');
      return;
    }

    const participant_ids = [];
    if (is_group) {
      document.querySelectorAll('input[name="invite_mentee"]:checked').forEach(cb => {
        participant_ids.push(cb.value);
      });
    }
    
    const scheduledAt = new Date(`${date}T${time}`).toISOString();
    closeScheduleModal();
    createSession(is_group, mentee_id, scheduledAt, title, participant_ids);
  };
}

function closeScheduleModal() {
  document.getElementById('scheduleModal')?.classList.remove('open');
}

function openMenteeSelectModal() {
  const modal = $('menteeSelectModal');
  const list = $('menteeSelectList');
  if (!modal || !list) return;
  list.innerHTML = '<div class="loading-spinner" style="margin:20px auto"></div>';
  modal.classList.add('open');
  
  apiFetch('/api/mentors/my-mentees').then(mentees => {
    if (!mentees.length) {
      list.innerHTML = '<p class="text-center py-20">No active mentees.</p>';
      return;
    }
    list.innerHTML = mentees.map(m => `
      <button class="btn btn-outline btn-full" style="text-align:left;justify-content:flex-start;display:block;height:auto;padding:12px" onclick="startPrivateSession('${m.user.telegram_id}')">
        <div class="font-bold">${escapeHtml(m.user.anonymous_id)}</div>
        <div class="text-xs text-dim">Joined ${new Date(m.assigned_at).toLocaleDateString()}</div>
      </button>
    `).join('');
  }).catch(e => {
    list.innerHTML = `<p class="text-danger">${e.message}</p>`;
  });
}

function closeMenteeSelectModal() {
  $('menteeSelectModal')?.classList.remove('open');
}

function startPrivateSession(menteeId) {
  closeMenteeSelectModal();
  showScheduleModal(false, menteeId);
}

function launchJitsi(roomName, roomPassword, displayName, token) {
  navigate('video');
  const container = $('jitsiContainer');
  if (!container) return;
  container.innerHTML = '';

  const initJitsi = () => {
    const options = {
      roomName,
      width: '100%',
      height: '100%',
      parentNode: container,
      userInfo: { displayName },
      configOverwrite: {
        startWithAudioMuted: true,
        startWithVideoMuted: true,
        enableClosePage: false,
        disableDeepLinking: true,
        ...(roomPassword ? { password: roomPassword } : {}),
      },
      interfaceConfigOverwrite: {
        TOOLBAR_BUTTONS: ['microphone','camera','chat','raisehand','fullscreen','tileview','hangup'],
        SHOW_JITSI_WATERMARK: false,
        MOBILE_APP_PROMO: false,
      },
      ...(token ? { jwt: token } : {}),
    };
    
    // Dispose old instance if exists
    if (window.jitsiApi) {
      try { window.jitsiApi.dispose(); } catch (e) { console.error(e); }
    }
    
    window.jitsiApi = new JitsiMeetExternalAPI('meet.jit.si', options);
    window.jitsiApi.addEventListener('videoConferenceLeft', () => navigate('sessions'));
    window.jitsiApi.addEventListener('passwordRequired', () => {
      if (roomPassword) window.jitsiApi.executeCommand('password', roomPassword);
    });
  };

  if (window.JitsiMeetExternalAPI) {
    initJitsi();
  } else {
    const script = document.createElement('script');
    script.src = 'https://meet.jit.si/external_api.js';
    script.onload = initJitsi;
    document.head.appendChild(script);
  }

  $('sessionPasswordDisplay').textContent = roomPassword ? `Password: ${roomPassword}` : '';
}

// ─── Chat ─────────────────────────────────────────────────────
window.chatState = {};

async function loadChat() {
  try {
    const targetId = window.pendingChatPartner;
    window.pendingChatPartner = null;

    const res = await apiFetch('/api/users/chat-partner');
    console.log('[Chat] partner response:', res);
    const selector = $('chatPartnerSelect');
    
    if (res.type === 'none') {
      $('chatMessages').innerHTML = '<div class="empty-state"><span>No active mentorship.</span></div>';
      $('chatInputRow').style.display = 'none';
      $('chatWith').style.display = 'block';
      $('chatWith').textContent = 'Messages';
      selector.style.display = 'none';
      return;
    }

    // Partner confirmed
    if (res.type === 'single') {
      selector.style.display = 'none';
      $('chatWith').style.display = 'block';
      $('chatWith').textContent = res.partner.display_name;
      window.chatState = { with: res.partner.telegram_id, name: res.partner.anonymous_id };
      loadMessages(res.partner.telegram_id);
    } else {
      // Multiple mentees (mentor)
      $('chatWith').style.display = 'none';
      selector.style.display = 'block';
      selector.innerHTML = res.mentees.map(m => `<option value="${m.telegram_id}">${escapeHtml(m.display_name)}</option>`).join('');
      
      const selectedId = targetId || res.mentees[0].telegram_id;
      selector.value = selectedId;
      
      const partner = res.mentees.find(m => String(m.telegram_id) === String(selectedId)) || res.mentees[0];
      window.chatState = { with: partner.telegram_id, name: partner.anonymous_id };
      loadMessages(partner.telegram_id);
    }

    // Ensure input row is visible when a partner exists
    const inputRow = document.getElementById('chatInputRow');
    if (inputRow) {
      inputRow.style.display = 'flex';
      inputRow.style.visibility = 'visible';
      inputRow.style.opacity = '1';
      console.log('[Chat] Input row set to flex');
    }

    // Safety check: force visibility after a short delay
    setTimeout(() => {
      const row = document.getElementById('chatInputRow');
      if (row && getComputedStyle(row).display === 'none' && res.type !== 'none') {
        row.style.display = 'flex';
        console.log('[Chat] forced input row visible via safety check');
      }
    }, 300);

  } catch (e) {
    console.error('[Chat] Error:', e);
    $('chatMessages').innerHTML = `<div class="empty-state"><span>${e.message}</span></div>`;
    if (e.message.includes('No active mentorship')) {
      $('chatInputRow').style.display = 'none';
    }
    $('chatWith').textContent = 'Error loading chat';
  }
}

function switchChatPartner(tid) {
  window.chatState.with = tid;
  forceShowChatInputRow(); // FIX: ensure input row visible
  loadMessages(tid);
}

function openChat(partnerId) {
  window.pendingChatPartner = partnerId;
  navigate('chat');
}

async function loadMessages(with_id) {
  try {
    const messages = await apiFetch(`/api/messages/${with_id}`);
    const container = $('chatMessages');
    container.innerHTML = messages.map(m => renderMessage(m)).join('');
    container.scrollTop = container.scrollHeight;
  } catch (e) { console.error(e); }
}

function renderMessage(msg) {
  const isSent = msg.from_id === currentUser?.telegram_id;
  return `<div class="message-bubble ${isSent ? 'sent' : 'received'}">
    ${escapeHtml(msg.content)}
    <div class="message-time">${formatTime(msg.created_at)}</div>
  </div>`;
}

function appendMessage(msg, isSent) {
  const container = $('chatMessages');
  const div = document.createElement('div');
  div.innerHTML = renderMessage(msg);
  container.appendChild(div.firstChild);
  container.scrollTop = container.scrollHeight;
}

async function sendMessage() {
  const input = $('chatInput');
  const content = input.value.trim();
  if (!content || !window.chatState.with) return;

  input.value = '';
  try {
    const msg = await apiFetch('/api/messages', {
      method: 'POST',
      body: { to_id: window.chatState.with, content }
    });
    appendMessage(msg, true);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function handleChatTyping() {
  if (socket && window.chatState.with) {
    socket.emit('typing', { to_id: window.chatState.with });
  }
}

async function updateMessageBadge() {
  try {
    const { count } = await apiFetch('/api/messages/unread/count');
    const badge = $('chatBadge');
    if (badge) {
      badge.textContent = count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    }
  } catch {}
}

// ─── Settings ─────────────────────────────────────────────────
async function loadSettings() {
  try {
    const s = await apiFetch('/api/users/settings');
    $('settingDisplayName').value = s.display_name || '';
    $('settingTimezone').value = s.timezone || 'UTC';
    $('toggleMessages').classList.toggle('on', s.notify_messages !== false);
    $('toggleSessions').classList.toggle('on', s.notify_sessions !== false);
    $('toggleVerse').classList.toggle('on', s.notify_daily_verse !== false);

    if (currentUser?.role === 'mentor') {
      $('mentorSettings').classList.remove('hidden');
      $('settingBio').value = s.bio || '';
      $('settingSpecialization').value = s.specialization || '';
      $('settingMaxMentees').value = s.max_mentees || 5;
    }

    $('userAnonId').textContent = currentUser?.anonymous_id || '';
    $('userRole').textContent = currentUser?.role || '';
  } catch (e) { showToast(e.message, 'error'); }
}

async function saveSettings() {
  const body = {
    display_name: $('settingDisplayName').value,
    timezone: $('settingTimezone').value,
    notify_messages: $('toggleMessages').classList.contains('on'),
    notify_sessions: $('toggleSessions').classList.contains('on'),
    notify_daily_verse: $('toggleVerse').classList.contains('on'),
    bio: $('settingBio')?.value,
    specialization: $('settingSpecialization')?.value,
    max_mentees: parseInt($('settingMaxMentees')?.value) || 5,
  };
  try {
    await apiFetch('/api/users/settings', { method: 'PATCH', body });
    showToast('Settings saved', 'success');
  } catch (e) { showToast(e.message, 'error'); }
}

function toggleNotif(id) {
  const el = $(id);
  el.classList.toggle('on');
}

// ─── Mentor Application ───────────────────────────────────────
function openApplyModal() {
  $('applyModal').classList.add('open');
}
function closeApplyModal() {
  $('applyModal').classList.remove('open');
}
async function submitApplication() {
  const q1 = $('applyQ1').value.trim();
  const q2 = $('applyQ2').value.trim();
  if (!q1 || !q2) { showToast('Please answer all questions', 'error'); return; }

  try {
    await apiFetch('/api/users/apply-mentor', { method: 'POST', body: { answer_q1: q1, answer_q2: q2 } });
    showToast('Application submitted! 🙏', 'success');
    closeApplyModal();
  } catch (e) { showToast(e.message, 'error'); }
}

// ─── Support Ticket ───────────────────────────────────────────
async function submitTicket() {
  const subject = $('ticketSubject').value.trim();
  const description = $('ticketDesc').value.trim();
  if (!subject || !description) { showToast('Fill in all fields', 'error'); return; }

  try {
    await apiFetch('/api/support', { method: 'POST', body: { subject, description } });
    showToast('Ticket submitted', 'success');
    $('ticketSubject').value = ''; $('ticketDesc').value = '';
  } catch (e) { showToast(e.message, 'error'); }
}

// ─── Localization ─────────────────────────────────────────────
const I18N = {
  en: {
    'Home': 'Home',
    'Mentors': 'Mentors',
    'Sessions': 'Sessions',
    'Chat': 'Chat',
    'Requests': 'Requests',
    'Settings': 'Settings',
    'My Mentees': 'My Mentees',
    'Active Clients': 'Active Clients',
    'Language': 'Language',
    'Identity': 'Identity',
    'Display': 'Display',
    'Notifications': 'Notifications',
    'Save': 'Save',
    'Join the Community 🙏': 'Join the Community 🙏',
    'Anonymous ID': 'Anonymous ID',
    'Role': 'Role',
    'Display Name (still anonymous)': 'Display Name (still anonymous)',
    'Timezone': 'Timezone',
    'Theme': 'Theme',
    'Toggle Dark/Light': 'Toggle Dark/Light',
    'New Messages': 'New Messages',
    'Session Reminders': 'Session Reminders',
    'Daily Bible Verse': 'Daily Bible Verse',
    'Mentor Profile': 'Mentor Profile',
    'Bio': 'Bio',
    'Specialization': 'Specialization',
    'Max Mentees': 'Max Mentees',
    'No active mentees yet': 'No active mentees yet',
    'Joined': 'Joined',
    'Sessions:': 'Sessions:',
    'End': 'End',
    'Message': 'Message',
    'Schedule': 'Schedule',
    'Private note about this mentee...': 'Private note about this mentee...',
    'Pending mentorship applications from users.': 'Pending mentorship applications from users.',
  },
  am: {
    'Home': 'መነሻ',
    'Mentors': 'አማካሪዎች',
    'Sessions': 'ክፍለ-ጊዜዎች',
    'Chat': 'ውይይት',
    'Requests': 'ጥያቄዎች',
    'Settings': 'ቅንብሮች',
    'My Mentees': 'የእኔ ተማሪዎች',
    'Active Clients': 'ንቁ ተማሪዎች',
    'Language': 'ቋንቋ',
    'Identity': 'ማንነት',
    'Display': 'እይታ',
    'Notifications': 'ማሳወቂያዎች',
    'Save': 'አስቀምጥ',
    'Join the Community 🙏': 'ማህበረሰቡን ይቀላቀሉ 🙏',
    'Anonymous ID': 'ስም-አልባ መታወቂያ',
    'Role': 'ሚና',
    'Display Name (still anonymous)': 'የማሳያ ስም',
    'Timezone': 'የሰዓት ቀጠና',
    'Theme': 'ገጽታ',
    'Toggle Dark/Light': 'ቀን/ማታ ቀይር',
    'New Messages': 'አዲስ መልዕክቶች',
    'Session Reminders': 'የክፍለ-ጊዜ ማሳሰቢያዎች',
    'Daily Bible Verse': 'ዕለታዊ የመጽሐፍ ቅዱስ ጥቅስ',
    'Mentor Profile': 'የአማካሪ መገለጫ',
    'Bio': 'ስለ እኔ',
    'Specialization': 'ልዩ ችሎታ',
    'Max Mentees': 'ከፍተኛ የተማሪዎች ብዛት',
    'No active mentees yet': 'እስካሁን ምንም ንቁ ተማሪዎች የሉም',
    'Joined': 'የተቀላቀሉበት',
    'Sessions:': 'ክፍለ-ጊዜዎች:',
    'End': 'አቁም',
    'Message': 'መልዕክት',
    'Schedule': 'ቀጠሮ',
    'Private note about this mentee...': 'ስለ ተማሪው የግል ማስታወሻ...',
    'Pending mentorship applications from users.': 'ከተጠቃሚዎች የቀረቡ የአማካሪነት ጥያቄዎች።',
  }
};

let currentLanguage = localStorage.getItem('language') || 'en';

function applyLanguage() {
  const dict = I18N[currentLanguage] || I18N.en;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const translated = dict[key] || key;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      el.placeholder = translated;
    } else {
      el.textContent = translated;
    }
  });
  // Sync dropdown
  const langSelect = $('settingLanguage');
  if (langSelect) langSelect.value = currentLanguage;
}

function changeLanguage(lang) {
  currentLanguage = lang;
  localStorage.setItem('language', lang);
  applyLanguage();
  // We can't translate the Bible verse on the fly anymore without the API
  // but we can reload the dashboard if needed
  loadDashboard();
}

// ─── Mentor Management ────────────────────────────────────────
async function loadMyMentees() {
  const container = $('menteesList');
  container.innerHTML = '<div class="loading-spinner" style="margin:40px auto"></div>';
  try {
    const mentees = await apiFetch('/api/mentors/my-mentees');
    const stats = await apiFetch('/api/mentors/my-mentees/stats');
    
    $('activeMenteeCount').textContent = mentees.length;
    if (!mentees.length) {
      container.innerHTML = '<div class="empty-state"><span>No active mentees yet</span></div>';
      return;
    }

    let html = '';
    for (const m of mentees) {
      const { user, assigned_at, id: assignId } = m;
      const sessionCount = stats[user.telegram_id] || 0;
      
      html += `
        <div class="card mb-12">
          <div class="flex justify-between items-start mb-8">
            <div>
              <div class="font-bold" style="color:var(--gold)">${escapeHtml(user.anonymous_id)}</div>
              <div class="text-xs text-dim">Joined ${new Date(assigned_at).toLocaleDateString()}</div>
              <div class="text-xs text-dim">Sessions: ${sessionCount}</div>
            </div>
            <button class="btn btn-ghost btn-sm" onclick="endMentorship('${assignId}')">End</button>
          </div>
          <div class="flex gap-8 mb-8">
            <button class="btn btn-outline btn-sm flex-1" onclick="openChat('${user.telegram_id}', '${escapeHtml(user.anonymous_id)}')">Message</button>
            <button class="btn btn-outline btn-sm flex-1" onclick="createSession(false, '${user.telegram_id}')">Session</button>
          </div>
          <div class="form-group mb-0">
            <textarea id="note-${user.telegram_id}" class="form-control text-sm" placeholder="Private note about this mentee..." rows="2" onblur="saveMentorNote('${user.telegram_id}')"></textarea>
          </div>
        </div>`;
    }
    container.innerHTML = html;
    
    // Load notes
    for (const m of mentees) {
      const note = await apiFetch(`/api/mentors/notes/${m.user.telegram_id}`);
      if (note.content) $(`note-${m.user.telegram_id}`).value = note.content;
    }
  } catch (e) { showToast(e.message, 'error'); }
}

async function saveMentorNote(menteeId) {
  const content = $(`note-${menteeId}`).value.trim();
  try {
    await apiFetch('/api/mentors/notes', { method: 'POST', body: { mentee_id: menteeId, content } });
  } catch (e) { showToast(e.message, 'error'); }
}

async function endMentorship(assignId) {
  if (!confirm('End this mentorship assignment?')) return;
  try {
    await apiFetch(`/api/mentors/end-mentorship/${assignId}`, { method: 'DELETE' });
    showToast('Mentorship ended', 'success');
    loadMyMentees();
  } catch (e) { showToast(e.message, 'error'); }
}

// ─── Boot ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
