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
  return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
    showToast(`📹 Session invite: ${session.title}`);
    if (currentPage === 'sessions') loadSessions();
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
    case 'chat': loadChat(); break;
    case 'requests': loadRequests(); break;
    case 'settings': loadSettings(); break;
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
  }
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
  try {
    const upcoming = await apiFetch('/api/sessions/upcoming');
    const container = $('upcomingSessions');
    if (!upcoming.length) {
      container.innerHTML = '<div class="empty-state"><span>No upcoming group sessions</span></div>';
      return;
    }
    container.innerHTML = upcoming.map(s => `
      <div class="session-item">
        <div class="session-icon">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
        </div>
        <div class="session-body">
          <div class="session-title">${escapeHtml(s.title)}</div>
          <div class="session-sub">${new Date(s.scheduled_at).toLocaleString()}</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="joinSession('${s.id}')">Join</button>
      </div>`).join('');
  } catch (e) {
    $('upcomingSessions').innerHTML = `<div class="empty-state"><span>${e.message}</span></div>`;
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

async function createSession(is_group = false) {
  try {
    const title = is_group ? prompt('Session title (or leave blank):') : undefined;
    const data = await apiFetch('/api/sessions/create', {
      method: 'POST',
      body: { is_group, title, scheduled_at: new Date().toISOString() }
    });
    showToast('Session created!', 'success');
    launchJitsi(data.room_name, data.room_password, currentUser.anonymous_id, data.jitsi_token);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function launchJitsi(roomName, roomPassword, displayName, token) {
  navigate('video');
  const container = $('jitsiContainer');
  container.innerHTML = '';

  const script = document.createElement('script');
  script.src = 'https://meet.jit.si/external_api.js';
  script.onload = () => {
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
    jitsiApi = new JitsiMeetExternalAPI('meet.jit.si', options);
    jitsiApi.addEventListener('videoConferenceLeft', () => navigate('sessions'));
    jitsiApi.addEventListener('passwordRequired', () => {
      jitsiApi.executeCommand('password', roomPassword);
    });
  };
  document.head.appendChild(script);

  $('sessionPasswordDisplay').textContent = roomPassword ? `Password: ${roomPassword}` : '';
}

// ─── Chat ─────────────────────────────────────────────────────
window.chatState = {};

async function loadChat() {
  // Load assigned mentor or mentee
  try {
    const assignment = await apiFetch('/api/users/my-mentor');
    if (!assignment) {
      $('chatMessages').innerHTML = '<div class="empty-state"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span>No active mentorship.<br>Request a mentor first.</span></div>';
      $('chatInputRow').style.display = 'none';
      return;
    }
    const mentor = assignment.mentor;
    window.chatState = { with: mentor.telegram_id, name: mentor.anonymous_id };
    $('chatWith').textContent = mentor.user_settings?.display_name || mentor.anonymous_id;
    $('chatInputRow').style.display = 'flex';
    loadMessages(mentor.telegram_id);
  } catch (e) {
    console.error(e);
  }
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

// ─── Boot ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
