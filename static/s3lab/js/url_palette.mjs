// Shared client helpers for the "🖼 Image(s) → palettes" and
// "🌐 URL → palette" features across the s3lab sublabs.
//
// fetchUrlPalette / wireUrlPalette: POST a URL to /s3lab/style-palette/,
// decode the returned 256×256 PNG into a usable Image, and pipe it
// into each sublab's image-palette pipeline.
//
// makeImageThumbnail / renderSourceRail: capture a 64×64 dataURL of a
// just-loaded image and render a horizontal rail of those thumbnails
// (with names) under the sublab's canvas, so users always see what
// the live palettes were derived from.

function csrfToken() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
}

export async function fetchUrlPalette(url) {
    const fd = new FormData();
    fd.append('url', url);
    const resp = await fetch('/s3lab/style-palette/', {
        method: 'POST',
        headers: {'X-CSRFToken': csrfToken()},
        body: fd,
        credentials: 'same-origin',
    });
    if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(txt || `HTTP ${resp.status}`);
    }
    const count = parseInt(resp.headers.get('X-Style-Palette-Count') || '0', 10);
    const blob  = await resp.blob();
    const objUrl = URL.createObjectURL(blob);
    let img;
    try {
        img = await new Promise((resolve, reject) => {
            const im = new Image();
            im.onload  = () => resolve(im);
            im.onerror = () => reject(new Error('palette PNG decode failed'));
            im.src = objUrl;
        });
    } finally {
        URL.revokeObjectURL(objUrl);
    }
    let host;
    try { host = new URL(url, window.location.href).host; }
    catch (_) { host = url; }
    // Synthetic File so callers expecting a File-shaped input (e.g.
    // Classic's applyImagePalette) can use this without branching.
    const file = new File([blob], `url-${host}.png`, {type: 'image/png'});
    return {img, file, host, count, blob};
}

// Wire a (input, button, statusEl, onPalette) tuple to the URL flow.
// `onPalette({img, file, host, count})` is called when the fetch
// succeeds — sublab-specific code goes there. `statusEl` is updated
// throughout. Last URL is persisted under `storageKey` so refreshing
// or revisiting keeps the chosen URL.
export function wireUrlPalette({input, button, statusEl, storageKey,
                                onPalette}) {
    if (!input || !button) return;
    if (storageKey) {
        const cached = localStorage.getItem(storageKey);
        if (cached && !input.value) input.value = cached;
    }
    function setStatus(msg, color) {
        if (!statusEl) return;
        if (color) statusEl.style.color = color;
        statusEl.textContent = msg;
    }
    const submit = async () => {
        const url = (input.value || '').trim();
        if (!url) { input.focus(); return; }
        if (storageKey) localStorage.setItem(storageKey, url);
        button.disabled = true;
        setStatus(`fetching ${url}…`, '#8b949e');
        try {
            const result = await fetchUrlPalette(url);
            await onPalette(result);
            setStatus(`palette from ${result.host} (${result.count} CSS colours found)`,
                      '#3fb950');
        } catch (err) {
            setStatus(`URL palette failed: ${err.message || err}`, '#cf222e');
            console.error('URL palette failed', err);
        } finally {
            button.disabled = false;
        }
    };
    button.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
}

// 64×64 centre-cropped thumbnail dataURL — small enough to keep in
// state across many sources without bloating memory.
export function makeImageThumbnail(img, size = 64) {
    const w = img.naturalWidth, h = img.naturalHeight;
    const side = Math.min(w, h);
    const cx = ((w - side) / 2) | 0, cy = ((h - side) / 2) | 0;
    const off = document.createElement('canvas');
    off.width = size; off.height = size;
    const ctx = off.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(img, cx, cy, side, side, 0, 0, size, size);
    return off.toDataURL('image/png');
}

// Render an array of {name, dataURL} into a rail element. Hides the
// rail when the array is empty so the row collapses cleanly.
export function renderSourceRail(railEl, sourceImages, opts = {}) {
    if (!railEl) return;
    railEl.innerHTML = '';
    if (!sourceImages || !sourceImages.length) {
        railEl.style.display = 'none';
        return;
    }
    railEl.style.display = '';
    const label = opts.label !== undefined ? opts.label
                                          : `Sources (${sourceImages.length})`;
    if (label) {
        const lbl = document.createElement('span');
        lbl.textContent = label;
        lbl.style.cssText = 'color:#6e7681; font-size:0.7rem; ' +
                            'margin-right:0.6rem; vertical-align:top; ' +
                            'display:inline-block; padding-top:1.5rem; ' +
                            'font-family:ui-monospace,Menlo,monospace;';
        railEl.appendChild(lbl);
    }
    for (const im of sourceImages) {
        const wrap = document.createElement('div');
        wrap.style.cssText = 'display:inline-block; margin-right:0.4rem; ' +
                             'vertical-align:top; text-align:center; ' +
                             'font-size:0.7rem; color:#8b949e; ' +
                             'font-family:ui-monospace,Menlo,monospace;';
        const img = document.createElement('img');
        img.src = im.dataURL;
        img.style.cssText = 'width:64px; height:64px; object-fit:cover; ' +
                            'border:1px solid #30363d; border-radius:3px; ' +
                            'image-rendering:pixelated; display:block; ' +
                            'margin:0 auto;';
        img.title = im.name;
        wrap.appendChild(img);
        const cap = document.createElement('div');
        cap.textContent = im.name.length > 14 ? im.name.slice(0, 13) + '…' : im.name;
        cap.style.cssText = 'max-width:64px; overflow:hidden; ' +
                            'white-space:nowrap; text-overflow:ellipsis; ' +
                            'margin-top:0.15rem;';
        wrap.appendChild(cap);
        railEl.appendChild(wrap);
    }
}
