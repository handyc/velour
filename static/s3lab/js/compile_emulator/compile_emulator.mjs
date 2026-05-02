// compile_emulator.mjs — entry point for the in-page emulator on
// /s3lab/compile/. Mounts a DevicePanel into the page's emulator slot,
// wires "Run in emulator" + slot-aware loading, and listens for the
// existing slot picker so the right kernel is invoked.

import { DevicePanel } from './device_panel.mjs';


function detectActiveSlot(src) {
    // Cheap heuristic: pick whichever slot signature appears in the
    // source; first match wins. The interpreter does the real work.
    const slots = ['step', 'render', 'gpio', 'fitness'];
    for (const s of slots) {
        const re = new RegExp(`\\b(?:int|void)\\s+${s}\\s*\\(`);
        if (re.test(src)) return s;
    }
    return null;
}


function init() {
    const mount = document.getElementById('compile-emulator-mount');
    if (!mount) return;
    const sourceEl = document.getElementById('source');
    const slotEl   = document.getElementById('slot');     // existing dropdown
    const runBtn   = document.getElementById('emulator-run-btn');
    if (!sourceEl) return;

    const panel = new DevicePanel(mount, { zoom: 4 });

    function reload() {
        const src = sourceEl.value;
        const slot = (slotEl && slotEl.value && slotEl.value !== 'auto')
            ? slotEl.value
            : detectActiveSlot(src);
        panel.activeSlot = slot;
        if (panel.loadSource(src)) {
            // Auto-tick once so the panel shows non-default state for
            // render/gpio kernels (otherwise the canvas is identical
            // to a freshly-reset device).
            if (slot === 'render' || slot === 'gpio' || slot === 'fitness') {
                panel.tick();
            }
        }
    }

    if (runBtn) runBtn.addEventListener('click', reload);
    if (slotEl) slotEl.addEventListener('change', reload);

    // Don't auto-load on page open — user might be staring at the
    // C source and not want the panel to start ticking yet. They
    // click ▶ Run in emulator when they're ready.
}


if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
