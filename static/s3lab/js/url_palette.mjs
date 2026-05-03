// Shared client helper for the "🌐 URL → palette" feature.
//
// POSTs a URL to /s3lab/style-palette/, decodes the returned 256×256
// PNG into a usable Image, and returns it along with metadata. Each
// sublab calls this then hands the Image to its own image-palette
// pipeline (applyImagePalette in Classic, applyImagePalettesToStrip
// in Filmstrip, applyImagePalettes in Cellular, applyImagePalettesTo-
// Library in Stratum/Strateta).

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
