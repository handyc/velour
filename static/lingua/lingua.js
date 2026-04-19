/* Lingua hover-translate.
 *
 * Loaded from base.html only when the user has lingua prefs set.
 * On Alt+hover (configurable) over any text node we:
 *   1. Extract the innermost text span under the cursor.
 *   2. POST it to /lingua/translate/ with the user's primary target.
 *   3. Render a small tooltip near the cursor.
 *
 * The goal is maximum non-intrusiveness — nothing is translated
 * unless the user actively holds the modifier. A per-tab memory map
 * prevents re-translating the same string within the page.
 */
(function () {
    'use strict';

    const cfg = window.LINGUA_CFG || {};
    if (!cfg.active || !cfg.primary) return;

    const MOD = cfg.hover_modifier || 'alt';
    const DEBOUNCE_MS = 140;

    const memo = new Map();  // text → {translation, backend, cached}
    let tooltip = null;
    let hoverTimer = null;
    let lastKey = '';
    let abortController = null;

    function makeTooltip() {
        const el = document.createElement('div');
        el.id = 'lingua-tooltip';
        el.style.cssText = [
            'position: fixed',
            'z-index: 99999',
            'background: #161b22',
            'border: 1px solid #58a6ff',
            'border-radius: 4px',
            'padding: 0.4rem 0.6rem',
            'max-width: 320px',
            'font: 0.82rem ui-monospace, SFMono-Regular, Menlo, monospace',
            'color: #c9d1d9',
            'line-height: 1.3',
            'box-shadow: 0 2px 8px rgba(0,0,0,0.5)',
            'pointer-events: none',
            'display: none',
        ].join(';');
        document.body.appendChild(el);
        return el;
    }

    function modDown(ev) {
        if (MOD === 'none') return true;
        if (MOD === 'alt')   return ev.altKey;
        if (MOD === 'ctrl')  return ev.ctrlKey || ev.metaKey;
        if (MOD === 'shift') return ev.shiftKey;
        return false;
    }

    function grabSnippet(ev) {
        /* Prefer a user selection if one exists — otherwise fall back
         * to the smallest ancestor that contains text at the cursor. */
        const sel = window.getSelection();
        if (sel && sel.toString().trim()) return sel.toString().trim();

        const target = ev.target;
        if (!target || !target.innerText) return '';
        const txt = target.innerText.trim();
        if (!txt) return '';
        // Skip script/style/very long blocks.
        if (/^(script|style|textarea|input)$/i.test(target.tagName)) return '';
        if (txt.length > 400) return '';
        return txt;
    }

    function show(ev, html) {
        if (!tooltip) tooltip = makeTooltip();
        tooltip.innerHTML = html;
        const pad = 12;
        let x = ev.clientX + pad;
        let y = ev.clientY + pad;
        tooltip.style.display = 'block';
        const rect = tooltip.getBoundingClientRect();
        if (x + rect.width > window.innerWidth - 8) {
            x = ev.clientX - rect.width - pad;
        }
        if (y + rect.height > window.innerHeight - 8) {
            y = ev.clientY - rect.height - pad;
        }
        tooltip.style.left = Math.max(4, x) + 'px';
        tooltip.style.top  = Math.max(4, y) + 'px';
    }

    function hide() {
        if (tooltip) tooltip.style.display = 'none';
        if (abortController) { abortController.abort(); abortController = null; }
        if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
    }

    function escapeHTML(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function translate(text, ev) {
        const key = cfg.primary + '::' + text;
        if (memo.has(key)) {
            const m = memo.get(key);
            show(ev, renderOut(m));
            return;
        }
        if (abortController) abortController.abort();
        abortController = new AbortController();
        show(ev, '<em style="color:#8b949e;">translating…</em>');
        try {
            const resp = await fetch('/lingua/translate/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text, target_lang: cfg.primary }),
                signal: abortController.signal,
            });
            const data = await resp.json();
            if (data.error) {
                show(ev, '<em style="color:#f85149;">' + escapeHTML(data.error) + '</em>');
                return;
            }
            memo.set(key, data);
            show(ev, renderOut(data));
        } catch (e) {
            if (e.name !== 'AbortError') {
                show(ev, '<em style="color:#f85149;">network error</em>');
            }
        }
    }

    function renderOut(d) {
        const tag = d.cached ? 'cached' : 'fresh';
        return escapeHTML(d.translation) +
            '<div style="color:#6e7681;font-size:0.7rem;margin-top:0.25rem;">' +
            '→ ' + escapeHTML(cfg.primary) + ' · ' + tag + ' · ' +
            escapeHTML(d.backend || '—') +
            '</div>';
    }

    document.addEventListener('mousemove', function (ev) {
        if (!modDown(ev)) { hide(); lastKey = ''; return; }
        const text = grabSnippet(ev);
        if (!text) { hide(); return; }
        const key = cfg.primary + '::' + text;
        if (key === lastKey) return;
        lastKey = key;
        if (hoverTimer) clearTimeout(hoverTimer);
        hoverTimer = setTimeout(function () { translate(text, ev); }, DEBOUNCE_MS);
    }, { passive: true });

    document.addEventListener('keyup', function (ev) {
        if (!modDown(ev)) hide();
    });
    window.addEventListener('blur', hide);

})();
