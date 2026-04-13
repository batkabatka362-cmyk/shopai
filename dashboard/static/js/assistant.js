/* ── Tab 4: AI Assistant — Jarvis-style Chat ──────── */

const Assistant = {
  init() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });

    sendBtn.addEventListener('click', () => this.send());
  },

  async send() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    this.addMessage('user', message);
    this.addTyping();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });

      const data = await response.json();
      this.removeTyping();
      this.addMessage('bot', data.response || 'No response received.');
    } catch (e) {
      this.removeTyping();
      this.addMessage('bot', 'Connection error. Please check if the server is running.');
    }
  },

  addMessage(role, text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;

    const avatar = role === 'bot' ? 'AI' : 'You';
    const formattedText = this.formatMarkdown(text);

    div.innerHTML = `
      <div class="chat-avatar">${avatar}</div>
      <div class="chat-bubble">${formattedText}</div>
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
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

    // Add typing animation CSS if not exists
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
    // Simple markdown: **bold**, `code`, \n→<br>, - items→list
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');

    // Convert "- item" lines to styled list
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
