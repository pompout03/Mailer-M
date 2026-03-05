/* MailMind — Client-Side Application
   Handles all API calls, rendering, filtering, calendar, and auto-refresh */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
    emails: [],
    filteredEmails: [],
    activeFilter: 'all',
    selectedEmailId: null,
    meetings: [],         // all meetings
    todayMeetings: [],    // today's meetings
    activity: [],
    stats: { total: 0, urgent: 0, meeting: 0, action: 0, newsletter: 0, fyi: 0, unread: 0 },
    calendar: {
        year: new Date().getFullYear(),
        month: new Date().getMonth(),
        selectedDay: new Date().getDate(),
        eventDays: new Set(),
    },
    syncing: false,
};

// ── API Helpers ───────────────────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
    const res = await fetch(url, { credentials: 'same-origin', ...options });
    if (res.status === 401) {
        window.location.href = '/login_page';
        return null;
    }
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }
    return res.json();
}

// ── Toast Notifications ───────────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> ${message}`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

// ── Skeleton Loaders ──────────────────────────────────────────────────────────
function renderEmailSkeletons(count = 4) {
    const list = document.getElementById('email-list');
    list.innerHTML = Array.from({ length: count }, () => `
    <div class="skeleton-card skeleton">
      <div class="skeleton-line w40 skeleton"></div>
      <div class="skeleton-line w80 skeleton"></div>
      <div class="skeleton-line w60 skeleton"></div>
    </div>
  `).join('');
}

function renderActivitySkeletons(count = 4) {
    const list = document.getElementById('activity-list');
    list.innerHTML = Array.from({ length: count }, () => `
    <div class="activity-item">
      <div class="skeleton" style="width:28px;height:28px;border-radius:6px;flex-shrink:0"></div>
      <div style="flex:1">
        <div class="skeleton skeleton-line w80"></div>
        <div class="skeleton skeleton-line w60"></div>
      </div>
    </div>
  `).join('');
}

// ── Data Loaders ──────────────────────────────────────────────────────────────
async function loadEmails() {
    renderEmailSkeletons();
    try {
        const data = await apiFetch('/api/emails');
        if (!data) return;
        state.emails = data;
        applyFilter(state.activeFilter);
        updateStats();
    } catch (e) {
        document.getElementById('email-list').innerHTML = `
      <div class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>
        <h3>Failed to load emails</h3>
        <p>${e.message}</p>
      </div>`;
    }
}

async function loadStats() {
    try {
        const data = await apiFetch('/api/emails/stats');
        if (!data) return;
        state.stats = data;
        updateFilterCounts();
    } catch (e) { /* non-critical, ignore */ }
}

async function loadTodayMeetings() {
    try {
        const data = await apiFetch('/api/meetings/today');
        if (!data) return;
        state.todayMeetings = data;
        renderMeetingBanner();
    } catch (e) { /* non-critical */ }
}

async function loadAllMeetings() {
    try {
        const data = await apiFetch('/api/meetings');
        if (!data) return;
        state.meetings = data;
        // Mark days that have meetings for the calendar dot indicators
        state.calendar.eventDays = new Set(
            data
                .filter(m => m.date)
                .map(m => {
                    const d = new Date(m.date);
                    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
                })
        );
        renderCalendar();
    } catch (e) { /* non-critical */ }
}

async function loadActivity() {
    renderActivitySkeletons();
    try {
        const data = await apiFetch('/api/activity');
        if (!data) return;
        state.activity = data;
        renderActivity();
    } catch (e) {
        document.getElementById('activity-list').innerHTML =
            '<div style="padding:12px;color:var(--muted);font-size:12px;text-align:center">Could not load activity</div>';
    }
}

// ── Sync Emails ───────────────────────────────────────────────────────────────
async function syncEmails() {
    if (state.syncing) return;
    state.syncing = true;
    const btn = document.getElementById('sync-btn');
    if (btn) btn.classList.add('spinning');
    showToast('Syncing emails from Gmail…', 'info');
    try {
        const result = await apiFetch('/api/emails/sync', { method: 'POST' });
        if (!result) return;
        showToast(result.message, 'success');
        await Promise.all([loadEmails(), loadStats(), loadTodayMeetings(), loadAllMeetings(), loadActivity()]);
    } catch (e) {
        showToast(`Sync failed: ${e.message}`, 'error');
    } finally {
        state.syncing = false;
        if (btn) btn.classList.remove('spinning');
    }
}

// ── Email List Rendering ──────────────────────────────────────────────────────
const categoryColors = {
    urgent: '#ff4d6d', meeting: '#00c6ff', action: '#f59e0b',
    newsletter: '#a78bfa', fyi: '#34d399',
};

function avatarColor(name) {
    const colors = ['#00c6ff', '#ff4d6d', '#a78bfa', '#f59e0b', '#34d399', '#fb923c', '#38bdf8'];
    let h = 0;
    for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) % colors.length;
    return colors[h];
}

function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : '')).toUpperCase();
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    if (isNaN(d)) return '';
    const now = new Date();
    const diff = now - d;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function renderEmailCard(email) {
    const initials = getInitials(email.sender_name || email.sender_email);
    const color = avatarColor(email.sender_name || email.sender_email);
    const cat = (email.category || 'fyi').toLowerCase();
    const time = formatTime(email.created_at || email.date_str);
    const isActive = email.id === state.selectedEmailId ? 'active' : '';
    const isUnread = !email.is_read ? 'unread' : '';

    return `
    <div class="email-card ${isActive} ${isUnread}" data-id="${email.id}" onclick="openEmail('${email.id}')">
      <div class="card-row1">
        <div class="avatar" style="background:${color}22;color:${color}">${initials}</div>
        <div class="card-sender">${escHtml(email.sender_name || email.sender_email || 'Unknown')}</div>
        <div class="card-time">${time}</div>
      </div>
      <div class="card-subject">${escHtml(email.subject || '(No Subject)')}</div>
      <div class="card-summary">${escHtml(email.summary || email.snippet || '')}</div>
      <div class="card-tags">
        <span class="tag tag-${cat}">${cat}</span>
        ${email.meeting_detected ? '<span class="tag tag-meeting">📅 meeting</span>' : ''}
        ${(email.action_items || []).length > 0 ? `<span class="tag tag-action">✓ ${email.action_items.length} tasks</span>` : ''}
      </div>
    </div>`;
}

function applyFilter(filter) {
    state.activeFilter = filter;
    state.filteredEmails = filter === 'all'
        ? state.emails
        : state.emails.filter(e => (e.category || 'fyi').toLowerCase() === filter);
    renderEmailList();
    updateFilterTabs();
}

function renderEmailList() {
    const list = document.getElementById('email-list');
    if (!state.filteredEmails.length) {
        const noSync = !state.emails.length;
        list.innerHTML = `
      <div class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
        <h3>${noSync ? 'No emails yet' : 'Nothing here'}</h3>
        <p>${noSync ? 'Sync your Gmail to get started.' : `No ${state.activeFilter} emails.`}</p>
        ${noSync ? '<button class="sync-btn" onclick="syncEmails()">⟳ Sync Now</button>' : ''}
      </div>`;
        return;
    }
    list.innerHTML = state.filteredEmails.map(renderEmailCard).join('');
}

function updateFilterCounts() {
    const s = state.stats;
    const counts = { all: s.total, urgent: s.urgent, meeting: s.meeting, action: s.action, newsletter: s.newsletter, fyi: s.fyi };
    document.querySelectorAll('.filter-tab').forEach(tab => {
        const f = tab.dataset.filter;
        const countEl = tab.querySelector('.count');
        if (countEl && counts[f] !== undefined) countEl.textContent = counts[f];
    });
}

function updateStats() {
    // Update from already-loaded emails if stats API not called yet
    const counts = { total: 0, urgent: 0, meeting: 0, action: 0, newsletter: 0, fyi: 0, unread: 0 };
    state.emails.forEach(e => {
        counts.total++;
        if (!e.is_read) counts.unread++;
        const cat = (e.category || 'fyi').toLowerCase();
        if (counts[cat] !== undefined) counts[cat]++;
    });
    state.stats = counts;
    updateFilterCounts();
    // Update unread badge in sidebar
    const badge = document.querySelector('#btn-inbox .badge');
    if (badge) badge.textContent = counts.unread || '';
}

function updateFilterTabs() {
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.filter === state.activeFilter);
    });
}

// ── Email Detail ──────────────────────────────────────────────────────────────
async function openEmail(id) {
    // Optimistically highlight card
    state.selectedEmailId = id;
    document.querySelectorAll('.email-card').forEach(c => {
        c.classList.toggle('active', c.dataset.id === id);
        if (c.dataset.id === id) c.classList.remove('unread');
    });

    showDetailLoading();

    try {
        const email = await apiFetch(`/api/emails/${id}`);
        if (!email) return;

        // Update in state
        const idx = state.emails.findIndex(e => e.id === id);
        if (idx !== -1) { state.emails[idx] = email; state.emails[idx].is_read = true; }
        updateStats();

        renderEmailDetail(email);
    } catch (e) {
        document.getElementById('email-detail-panel').innerHTML = `
      <div class="empty-state">
        <h3>Failed to load email</h3><p>${e.message}</p>
      </div>`;
    }
}

function showDetailLoading() {
    document.getElementById('email-detail-panel').innerHTML = `
    <div class="detail-header">
      <div class="skeleton skeleton-line w80" style="height:24px;margin-bottom:12px"></div>
      <div class="skeleton skeleton-line w60" style="height:16px"></div>
    </div>
    <div id="detail-scroll" style="padding:24px">
      <div class="skeleton skeleton-line w100" style="height:80px;margin-bottom:16px"></div>
      <div class="skeleton skeleton-line w100" style="height:200px"></div>
    </div>`;
}

function renderEmailDetail(email) {
    const cat = (email.category || 'fyi').toLowerCase();
    const initials = getInitials(email.sender_name || email.sender_email);
    const color = avatarColor(email.sender_name || email.sender_email);
    const items = email.action_items || [];
    const time = email.date_str ||
        (email.created_at ? new Date(email.created_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '');

    const actionHtml = items.length ? `
    <div class="action-items-box">
      <div class="action-label">
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        Action Items
      </div>
      ${items.map((item, i) => `
        <div class="action-item">
          <div class="action-check" id="check-${i}" onclick="toggleCheck(${i})"></div>
          <span>${escHtml(item)}</span>
        </div>`).join('')}
    </div>` : '';

    const meetingHtml = email.meeting_detected ? `
    <div class="ai-summary-box" style="border-color:rgba(0,198,255,0.3);margin-bottom:0">
      <div class="ai-label">
        📅 Meeting Detected
      </div>
      <div class="ai-summary-text">
        <strong>${escHtml(email.meeting_title || 'Meeting')}</strong><br>
        ${email.meeting_date ? `Date: ${email.meeting_date}` : ''}
        ${email.meeting_time ? ` at ${email.meeting_time}` : ''}
      </div>
    </div>` : '';

    document.getElementById('email-detail-panel').innerHTML = `
    <div class="detail-header">
      <div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:10px">
        <div class="detail-subject" style="flex:1">${escHtml(email.subject || '(No Subject)')}</div>
        <span class="tag tag-${cat}" style="margin-top:4px;flex-shrink:0">${cat}</span>
      </div>
      <div class="detail-meta">
        <div class="detail-avatar" style="background:${color}22;color:${color}">${initials}</div>
        <div>
          <div class="detail-sender-name">${escHtml(email.sender_name || email.sender_email || 'Unknown')}</div>
          <div class="detail-sender-email">${escHtml(email.sender_email || '')}</div>
        </div>
        <div class="detail-time-badge">${escHtml(time)}</div>
      </div>
    </div>

    <div id="detail-scroll">
      <div class="ai-summary-box" style="margin:16px 0 12px">
        <div class="ai-label">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
          AI Summary
        </div>
        <div class="ai-summary-text">${escHtml(email.summary || 'No summary available.')}</div>
      </div>

      ${meetingHtml}
      ${meetingHtml ? '<div style="margin-bottom:12px"></div>' : ''}
      ${actionHtml}

      <div class="email-body-section">
        <div class="body-label">Original Email</div>
        <div class="email-body-text">${escHtml(email.body || email.snippet || '(No body content)')}</div>
      </div>
    </div>

    <div class="reply-bar">
      <input class="reply-input" type="text" placeholder="Reply to ${escHtml(email.sender_name || 'sender')}…" id="reply-input">
      <button class="reply-send-btn" onclick="sendReply('${email.sender_email}')">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
      </button>
    </div>`;
}

function toggleCheck(idx) {
    const el = document.getElementById(`check-${idx}`);
    if (el) el.classList.toggle('checked');
}

function sendReply(to) {
    const input = document.getElementById('reply-input');
    if (input && input.value.trim()) {
        showToast(`Reply queued (Gmail send not yet wired up)`, 'info');
        input.value = '';
    }
}

// ── Meeting Banner ────────────────────────────────────────────────────────────
function renderMeetingBanner() {
    const banner = document.getElementById('meeting-banner');
    if (!state.todayMeetings.length) {
        if (banner) banner.classList.remove('visible');
        return;
    }
    const m = state.todayMeetings[0];
    if (banner) {
        banner.classList.add('visible');
        banner.innerHTML = `
      <div class="banner-label">📅 Today</div>
      <div class="banner-title">${escHtml(m.title)}</div>
      ${m.time ? `<div class="banner-time">${escHtml(m.time)}</div>` : ''}`;
    }
}

// ── Calendar ──────────────────────────────────────────────────────────────────
function renderCalendar() {
    const { year, month, selectedDay, eventDays } = state.calendar;
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];
    document.getElementById('calendar-month').textContent = `${monthNames[month]} ${year}`;

    const grid = document.getElementById('calendar-grid');
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const daysInPrev = new Date(year, month, 0).getDate();
    const today = new Date();

    let cells = '';
    // Previous month overflow
    for (let i = firstDay - 1; i >= 0; i--) {
        cells += `<div class="cal-day other-month">${daysInPrev - i}</div>`;
    }
    // Current month
    for (let d = 1; d <= daysInMonth; d++) {
        const isToday = d === today.getDate() && month === today.getMonth() && year === today.getFullYear();
        const isSelected = d === selectedDay && !isToday;
        const key = `${year}-${month}-${d}`;
        const hasEvent = eventDays.has(key);
        cells += `
      <div class="cal-day ${isToday ? 'today' : ''} ${isSelected ? 'selected' : ''}"
           onclick="selectDay(${d})">
        ${d}
        ${hasEvent ? '<span class="event-dot"></span>' : ''}
      </div>`;
    }
    // Fill remaining cells
    const totalCells = Math.ceil((firstDay + daysInMonth) / 7) * 7;
    let nextDay = 1;
    while (firstDay + daysInMonth + nextDay - 1 < totalCells) {
        cells += `<div class="cal-day other-month">${nextDay++}</div>`;
    }

    grid.innerHTML = cells;
    renderDayEvents(selectedDay);
}

function selectDay(d) {
    state.calendar.selectedDay = d;
    renderCalendar();
}

function renderDayEvents(day) {
    const { year, month } = state.calendar;
    const dayStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const dayMeetings = state.meetings.filter(m => m.date === dayStr);
    const container = document.getElementById('day-events');
    if (!dayMeetings.length) {
        container.innerHTML = `<div style="color:var(--muted);font-size:11px;padding:4px 0">No events</div>`;
        return;
    }
    container.innerHTML = dayMeetings.map(m => `
    <div class="day-event-item">
      <div class="day-event-dot"></div>
      <div class="day-event-name">${escHtml(m.title)}</div>
      ${m.time ? `<div class="day-event-time">${escHtml(m.time)}</div>` : ''}
    </div>`).join('');
}

function prevMonth() {
    let { year, month } = state.calendar;
    month--;
    if (month < 0) { month = 11; year--; }
    state.calendar = { ...state.calendar, year, month, selectedDay: 1 };
    renderCalendar();
}

function nextMonth() {
    let { year, month } = state.calendar;
    month++;
    if (month > 11) { month = 0; year++; }
    state.calendar = { ...state.calendar, year, month, selectedDay: 1 };
    renderCalendar();
}

// ── Activity Feed ─────────────────────────────────────────────────────────────
const iconMap = {
    calendar: '📅',
    alert: '🚨',
    'check-circle': '✅',
    mail: '📧',
};
const badgeClassMap = {
    meeting: 'badge-meeting',
    urgent: 'badge-urgent',
    action: 'badge-action',
    fyi: 'badge-fyi',
    newsletter: 'badge-newsletter',
};

function renderActivity() {
    const list = document.getElementById('activity-list');
    if (!state.activity.length) {
        list.innerHTML = '<div style="padding:20px;color:var(--muted);font-size:12px;text-align:center">No recent activity</div>';
        return;
    }
    list.innerHTML = state.activity.map(item => {
        const iconClass = `icon-${item.icon}`;
        const badgeClass = badgeClassMap[item.badge.toLowerCase()] || 'badge-fyi';
        return `
      <div class="activity-item">
        <div class="activity-icon ${iconClass}">${iconMap[item.icon] || '📧'}</div>
        <div class="activity-content">
          <div class="activity-title">${escHtml(item.title)}</div>
          <div class="activity-desc">${escHtml(item.description)}</div>
          <div class="activity-footer">
            <span class="activity-time">${formatTime(item.time)}</span>
            <span class="activity-badge ${badgeClass}">${escHtml(item.badge)}</span>
          </div>
        </div>
      </div>`;
    }).join('');
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function escHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Auto-refresh every 5 minutes ──────────────────────────────────────────────
function startAutoRefresh() {
    setInterval(async () => {
        await Promise.all([loadEmails(), loadStats(), loadTodayMeetings(), loadAllMeetings(), loadActivity()]);
    }, 5 * 60 * 1000);
}

// ── Initialisation ────────────────────────────────────────────────────────────
async function init() {
    // Render calendar immediately (no API needed)
    renderCalendar();

    // Start all data fetches in parallel
    await Promise.all([
        loadEmails(),
        loadStats(),
        loadTodayMeetings(),
        loadAllMeetings(),
        loadActivity(),
    ]);

    startAutoRefresh();
}

// Kick off when the DOM is ready
document.addEventListener('DOMContentLoaded', init);
