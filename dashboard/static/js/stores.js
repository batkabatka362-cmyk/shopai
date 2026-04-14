/* ── Store selector — Option N ─────────────────────────
 *
 * Fetches /api/stores once on boot, populates the topbar <select>
 * with every known store, and exposes Stores.current() for other
 * modules to append "?store_id=..." to their API calls.
 *
 * Persists the operator's choice in localStorage so a page reload
 * keeps the same view. Falls back to the server-suggested default
 * when the cached id is no longer known.
 */

const Stores = {
  _key: 'shopai_active_store',
  _list: [],
  _current: '',
  _default: '',
  _inited: false,
  _listeners: new Set(),

  async init() {
    if (this._inited) return;
    this._inited = true;

    const wrap = document.getElementById('store-selector-wrap');
    const select = document.getElementById('store-selector');

    let data;
    try {
      const r = await fetch('/api/stores');
      data = await r.json();
    } catch (e) {
      data = { stores: [], default: '' };
    }
    this._list = data.stores || [];
    this._default = data.default || '';

    // Only show the selector when there's more than one store —
    // single-store operators shouldn't see noise.
    if (this._list.length > 1 && wrap) {
      wrap.removeAttribute('hidden');
    }

    if (select) {
      // Rebuild options from the server response.
      select.innerHTML = [
        '<option value="">All stores</option>',
        ...this._list.map(s =>
          `<option value="${this._esc(s.store_id)}">${this._esc(s.name || s.store_id)}</option>`),
      ].join('');

      // Restore the cached pick if it's still valid.
      let cached = '';
      try { cached = localStorage.getItem(this._key) || ''; } catch (e) { /* */ }
      const valid = cached && this._list.some(s => s.store_id === cached);
      this._current = valid ? cached : '';
      select.value = this._current;

      select.addEventListener('change', () => {
        this._current = select.value;
        try {
          if (this._current) localStorage.setItem(this._key, this._current);
          else localStorage.removeItem(this._key);
        } catch (e) { /* private mode */ }
        this._fire();
      });
    }
  },

  current() {
    return this._current || '';
  },

  default() {
    return this._default;
  },

  onChange(fn) {
    this._listeners.add(fn);
  },

  _fire() {
    for (const fn of this._listeners) {
      try { fn(this._current); } catch (e) { /* swallow */ }
    }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
};

document.addEventListener('DOMContentLoaded', () => Stores.init());

window.Stores = Stores;
