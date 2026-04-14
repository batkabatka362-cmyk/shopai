/* ── Tab 4: AI Assistant — Jarvis-style Chat ────────
 *
 * Client state:
 *   • In-memory `_history` kept in sync with a server-side session
 *     (Option J). `_sessionId` tracks which row we're editing.
 *   • `localStorage` caches (a) the active session id so a hard refresh
 *     reopens the same thread, and (b) a one-turn buffer so we don't
 *     lose anything if the save round-trip is in flight.
 *
 * UX:
 *   • Sidebar lists saved sessions — click to load, × to delete, + New
 *     to start fresh.
 *   • Suggestion chips seed common queries.
 *   • Clear button wipes the current session (local + server).
 *   • Slash commands (/foo) are routed server-side — no LLM round-trip.
 */

const Assistant = {
  _activeSessionKey: 'shopai_active_session_id',
  _maxHistory: 12,   // 6 user + 6 assistant turns, clamped by backend too
  _history: [],
  _sessionId: null,
  _inited: false,
  _sending: false,
  _saveTimer: null,

  init() {
    if (this._inited) return;
    this._inited = true;

    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const clearBtn = document.getElementById('chat-clear');
    const newBtn = document.getElementById('chat-new');

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });
    sendBtn.addEventListener('click', () => this.send());
    if (clearBtn) clearBtn.addEventListener('click', () => this.clear());
    if (newBtn) newBtn.addEventListener('click', () => this._startNewSession());

    // Chips — seed messages.
    document.querySelectorAll('.chat-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        input.value = chip.dataset.prompt || chip.textContent;
        this.send();
      });
    });

    // Session bootstrap: refresh the sidebar, then load the last
    // active session (or start fresh if none).
    this._loadActiveId();
    this._refreshSidebar();
    if (this._sessionId) {
      this._loadSession(this._sessionId);
    } else {
      this._renderAll();
    }
  },

  _loadActiveId() {
    try {
      this._sessionId = localStorage.getItem(this._activeSessionKey) || null;
    } catch (e) {
      this._sessionId = null;
    }
  },

  _persistActiveId() {
    try {
      if (this._sessionId) {
        localStorage.setItem(this._activeSessionKey, this._sessionId);
      } else {
        localStorage.removeItem(this._activeSessionKey);
      }
    } catch (e) { /* private mode / quota */ }
  },

  // ── Server-side session sync ────────────────────────

  async _refreshSidebar() {
    let sessions = [];
    try {
      const r = await fetch('/api/chat/sessions');
      const data = await r.json();
      sessions = (data.sessions || []);
    } catch (e) { /* offline */ }
    this._renderSidebar(sessions);
  },

  _renderSidebar(sessions) {
    const list = document.getElementById('chat-session-list');
    if (!list) return;
    if (!sessions.length) {
      list.innerHTML = `<div class="empty-state muted">No saved chats yet.</div>`;
      return;
    }
    list.innerHTML = sessions.map(s => {
      const active = s.id === this._sessionId ? ' active' : '';
      const title = this._esc(s.title || 'Untitled');
      const meta = `${s.turn_count} turn${s.turn_count === 1 ? '' : 's'} · ${this._relTime(s.updated_at)}`;
      return `
        <div class="chat-session${active}" data-id="${this._esc(s.id)}">
          <div class="chat-session-title" title="${title}">${title}</div>
          <div class="chat-session-meta muted">${meta}</div>
          <button class="chat-session-del" data-id="${this._esc(s.id)}" title="Delete">×</button>
        </div>`;
    }).join('');
    // Wire up click + delete — per-row because the list re-renders often.
    list.querySelectorAll('.chat-session').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.classList.contains('chat-session-del')) return;
        this._loadSession(el.dataset.id);
      });
    });
    list.querySelectorAll('.chat-session-del').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        this._deleteSession(el.dataset.id);
      });
    });
  },

  async _loadSession(sid) {
    if (!sid) return;
    let session;
    try {
      const r = await fetch('/api/chat/session?id=' + encodeURIComponent(sid));
      if (!r.ok) throw new Error('not found');
      session = await r.json();
    } catch (e) {
      // The session disappeared server-side — fall back to a blank one.
      this._startNewSession();
      return;
    }
    this._sessionId = session.id;
    this._history = (session.turns || []).map(t => ({
      role: t.role, content: t.content,
    }));
    this._persistActiveId();
    this._renderAll();
    this._refreshSidebar();
  },

  _startNewSession() {
    this._sessionId = null;
    this._history = [];
    this._persistActiveId();
    this._renderAll();
    this._refreshSidebar();
  },

  async _deleteSession(sid) {
    if (!sid) return;
    if (!window.confirm('Delete this chat?')) return;
    try {
      await fetch('/api/chat/session?id=' + encodeURIComponent(sid),
                  { method: 'DELETE' });
    } catch (e) { /* offline */ }
    if (sid === this._sessionId) {
      this._startNewSession();
    } else {
      this._refreshSidebar();
    }
  },

  // Debounced save — fires 400ms after the last mutation so a rapid
  // user + assistant turn pair coalesces into one round-trip.
  _scheduleSave() {
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this._saveNow(), 400);
  },

  async _saveNow() {
    this._saveTimer = null;
    if (!this._history.length) return;
    try {
      const r = await fetch('/api/chat/session', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          id: this._sessionId,
          turns: this._history.map(t => ({
            role: t.role, content: t.content,
          })),
        }),
      });
      const data = await r.json();
      if (data.id && data.id !== this._sessionId) {
        this._sessionId = data.id;
        this._persistActiveId();
      }
      this._refreshSidebar();
    } catch (e) { /* offline — client keeps the buffer */ }
  },

  _renderAll() {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    // Preserve the built-in greeting (first child) and replace anything after.
    const keep = container.querySelector('.chat-msg.bot');
    container.innerHTML = '';
    if (keep) container.appendChild(keep);
    for (const turn of this._history) {
      this._appendMessage(turn.role === 'user' ? 'user' : 'bot', turn.content);
    }
    container.scrollTop = container.scrollHeight;
  },

  async send() {
    if (this._sending) return;
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    // Local slash: clear doesn't need a round-trip.
    if (message === '/clear') {
      input.value = '';
      this.clear();
      return;
    }

    this._sending = true;
    this._toggleSend(false);

    input.value = '';
    this._pushTurn('user', message);
    this._appendMessage('user', message);

    // Try streaming first; fall back to single-shot on any failure.
    try {
      const ok = await this._streamResponse(message);
      if (!ok) await this._singleShotResponse(message);
    } catch (e) {
      await this._singleShotResponse(message);
    } finally {
      this._sending = false;
      this._toggleSend(true);
    }
  },

  async _streamResponse(message) {
    // Create the bot bubble up front so we can append deltas to it.
    this.addTyping();
    let resp;
    try {
      resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          history: this._history.slice(0, -1),
        }),
      });
    } catch (e) {
      this.removeTyping();
      return false;
    }
    if (!resp.ok || !resp.body) {
      this.removeTyping();
      return false;
    }

    this.removeTyping();
    const bubble = this._startStreamingBubble();
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let accumulated = '';
    let done = false;

    while (!done) {
      const { value, done: readerDone } = await reader.read();
      if (readerDone) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() || '';
      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        let data;
        try { data = JSON.parse(payload); }
        catch (e) { continue; }
        if (data.delta) {
          accumulated += data.delta;
          bubble.innerHTML = this.formatMarkdown(accumulated);
          const container = document.getElementById('chat-messages');
          container.scrollTop = container.scrollHeight;
        }
        if (data.done) { done = true; break; }
        if (data.error) {
          accumulated = accumulated + '\n\n[error: ' + data.error + ']';
          bubble.innerHTML = this.formatMarkdown(accumulated);
          done = true;
          break;
        }
      }
    }

    // Strip the "still streaming" caret now that we're done.
    bubble.classList.remove('streaming');
    if (!accumulated) return false;
    this._pushTurn('assistant', accumulated);
    // Attach feedback bar now that the full response is in hand.
    const msgDiv = bubble.closest('.chat-msg.bot');
    if (msgDiv) this._attachFeedback(msgDiv, accumulated);
    return true;
  },

  _startStreamingBubble() {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg bot';
    div.innerHTML = `
      <div class="chat-avatar">AI</div>
      <div class="chat-bubble streaming"></div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div.querySelector('.chat-bubble');
  },

  async _singleShotResponse(message) {
    this.addTyping();
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          history: this._history.slice(0, -1),
        }),
      });
      const data = await response.json();
      this.removeTyping();
      const reply = data.response || 'No response received.';
      this._pushTurn('assistant', reply);
      this._appendMessage('bot', reply);
    } catch (e) {
      this.removeTyping();
      this._appendMessage(
        'bot',
        'Connection error. Please check if the server is running.',
      );
    }
  },

  _toggleSend(enabled) {
    const btn = document.getElementById('chat-send');
    if (btn) btn.disabled = !enabled;
  },

  _pushTurn(role, content) {
    this._history.push({ role, content });
    if (this._history.length > this._maxHistory) {
      this._history.splice(0, this._history.length - this._maxHistory);
    }
    this._scheduleSave();
  },

  async clear() {
    // Wipe the current session on both ends — server and DOM.
    const sid = this._sessionId;
    this._history = [];
    this._sessionId = null;
    this._persistActiveId();
    const container = document.getElementById('chat-messages');
    const keep = container.querySelector('.chat-msg.bot');
    container.innerHTML = '';
    if (keep) container.appendChild(keep);
    if (sid) {
      try {
        await fetch('/api/chat/session?id=' + encodeURIComponent(sid),
                    { method: 'DELETE' });
      } catch (e) { /* offline */ }
    }
    this._refreshSidebar();
  },

  _appendMessage(role, text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    const avatar = role === 'bot' ? 'AI' : 'You';
    div.innerHTML = `
      <div class="chat-avatar">${avatar}</div>
      <div class="chat-bubble">${this.formatMarkdown(text)}</div>
    `;
    container.appendChild(div);
    if (role === 'bot') this._attachFeedback(div, text);
    container.scrollTop = container.scrollHeight;
  },

  // ── Feedback loop ───────────────────────────────────

  _attachFeedback(msgDiv, responseText) {
    // Skip the built-in greeting — only real bot replies get feedback.
    if (!responseText || responseText.length < 4) return;
    const prior = this._lastUserMessage();
    if (!prior) return;
    const bar = document.createElement('div');
    bar.className = 'chat-feedback';
    bar.innerHTML = `
      <button class="fb-btn" data-rating="up" title="Helpful">▲</button>
      <button class="fb-btn" data-rating="down" title="Not helpful">▼</button>
      <span class="fb-status"></span>
    `;
    msgDiv.appendChild(bar);
    bar.querySelectorAll('.fb-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._submitFeedback(bar, btn.dataset.rating, prior, responseText);
      });
    });
  },

  _lastUserMessage() {
    for (let i = this._history.length - 1; i >= 0; i--) {
      if (this._history[i].role === 'user') return this._history[i].content;
    }
    return '';
  },

  async _submitFeedback(bar, rating, message, response) {
    const status = bar.querySelector('.fb-status');
    // Only collect a note on thumbs-down — keep the happy path frictionless.
    let note = '';
    if (rating === 'down') {
      note = window.prompt('What was wrong with this reply? (optional)') || '';
    }
    bar.querySelectorAll('.fb-btn').forEach(b => { b.disabled = true; });
    try {
      const r = await fetch('/api/chat/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rating, message, response, note}),
      });
      const data = await r.json();
      if (data.status === 'ok') status.textContent = 'thanks!';
      else if (data.status === 'accepted') status.textContent = 'noted (vault off)';
      else status.textContent = 'error';
      // Fade the bar out after a moment to reduce visual noise.
      setTimeout(() => { bar.classList.add('faded'); }, 1500);
    } catch (e) {
      status.textContent = 'offline';
    }
  },

  // Kept for backward compat with any code that still calls addMessage().
  addMessage(role, text) {
    this._pushTurn(role === 'user' ? 'user' : 'assistant', text);
    this._appendMessage(role, text);
  },

  addTyping() {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg bot';
    div.id = 'typing-indicator';
    div.innerHTML = `
      <div class="chat-avatar">AI</div>
      <div class="chat-bubble" style="display:flex;gap:4px;padding:14px 20px">
        <span class="typing-dot" style="animation-delay:0s"></span>
        <span class="typing-dot" style="animation-delay:0.2s"></span>
        <span class="typing-dot" style="animation-delay:0.4s"></span>
      </div>
    `;

    if (!document.getElementById('typing-style')) {
      const style = document.createElement('style');
      style.id = 'typing-style';
      style.textContent = `
        .typing-dot {
          width: 7px; height: 7px; border-radius: 50%;
          background: var(--accent); display: inline-block;
          animation: typingBounce 1.2s ease-in-out infinite;
        }
        @keyframes typingBounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-8px); opacity: 1; }
        }
      `;
      document.head.appendChild(style);
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  },

  removeTyping() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
  },

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },

  _relTime(ts) {
    if (!ts) return '';
    const now = Date.now() / 1000;
    const diff = Math.max(0, now - Number(ts));
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
    const d = new Date(Number(ts) * 1000);
    return d.toLocaleDateString();
  },

  formatMarkdown(text) {
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');

    html = html.replace(/((?:^|<br>)- .+(?:<br>- .+)*)/g, (match) => {
      const items = match.split('<br>').filter(l => l.startsWith('- ')).map(l =>
        `<div style="padding:2px 0 2px 12px;border-left:2px solid var(--accent-dim)">${l.substring(2)}</div>`
      );
      return items.join('');
    });

    return `<p>${html}</p>`;
  },
};

document.addEventListener('DOMContentLoaded', () => Assistant.init());

window.Assistant = Assistant;
