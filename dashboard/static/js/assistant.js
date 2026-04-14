/* ── Tab 4: AI Assistant — Jarvis-style Chat ────────
 *
 * Client state:
 *   • Keeps `_history` in localStorage so refresh preserves the chat
 *   • Sends the last N turns to /api/chat as `history`, giving the
 *     LLM multi-turn context
 *
 * UX:
 *   • Suggestion chips seed common queries (/status, /cycle, /vault, /health)
 *   • Clear button wipes localStorage + the DOM
 *   • Slash commands (/foo) are routed server-side — no LLM round-trip
 */

const Assistant = {
  _storageKey: 'shopai_chat_history',
  _maxHistory: 12,   // 6 user + 6 assistant turns, clamped by backend too
  _history: [],
  _inited: false,
  _sending: false,

  init() {
    if (this._inited) return;
    this._inited = true;

    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const clearBtn = document.getElementById('chat-clear');

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });
    sendBtn.addEventListener('click', () => this.send());
    if (clearBtn) clearBtn.addEventListener('click', () => this.clear());

    // Chips — seed messages.
    document.querySelectorAll('.chat-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        input.value = chip.dataset.prompt || chip.textContent;
        this.send();
      });
    });

    // Restore persisted history into the DOM.
    this._loadHistory();
    this._renderAll();
  },

  _loadHistory() {
    try {
      const raw = localStorage.getItem(this._storageKey);
      this._history = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(this._history)) this._history = [];
    } catch (e) {
      this._history = [];
    }
  },

  _saveHistory() {
    try {
      // Keep only the last N turns on disk.
      const trimmed = this._history.slice(-this._maxHistory);
      localStorage.setItem(this._storageKey, JSON.stringify(trimmed));
    } catch (e) {
      /* quota exceeded / disabled — best effort */
    }
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
    this._saveHistory();
  },

  clear() {
    this._history = [];
    try { localStorage.removeItem(this._storageKey); } catch (e) { /* noop */ }
    const container = document.getElementById('chat-messages');
    const keep = container.querySelector('.chat-msg.bot');
    container.innerHTML = '';
    if (keep) container.appendChild(keep);
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
    container.scrollTop = container.scrollHeight;
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
