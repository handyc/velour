// identity_wave.js — the consciousness sine wave.
//
// Renders a small canvas at requestAnimationFrame's natural rate (the
// browser caps this at ~60fps and pauses it when the tab is in the
// background — so it's effectively zero CPU when you're not looking).
// The underlying STATE is fetched from /identity/state.json on a slow
// poll (default 60 seconds), not per-frame. Frame-by-frame the wave
// just animates a phase counter using the cached state.
//
// Wave parameters are derived from Identity:
//   amplitude     mood_intensity (0-1) → 0.2-0.85 of canvas height
//   frequency     load_1 → 0.5-3.5 Hz (low load = slow calm wave)
//   color         identity color_preference
//   harmonic_mix  small extra harmonic for visual texture; muted
//
// Designed to be quiet: no setInterval at high frequencies, no DOM
// thrash, no per-frame allocations beyond a couple of numbers.

(function () {
    'use strict';

    const canvas = document.getElementById('identity-wave');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // Size the canvas to its CSS box, retina-aware.
    function resize() {
        const cssW = canvas.clientWidth;
        const cssH = canvas.clientHeight;
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);

    // The cached state from the most recent /state.json fetch.
    let state = {
        mood: 'contemplative',
        mood_intensity: 0.5,
        color: '#58a6ff',
        load: 0.5,
        hour: 12,
        tod: 'afternoon',
    };

    // Phase accumulator for the wave. Increments by frame delta * freq.
    let phase = 0;
    let lastFrame = performance.now();

    function intensityToAmp(intensity) {
        // 0.0 → 0.20, 1.0 → 0.85 of half-canvas-height
        return 0.20 + 0.65 * Math.max(0, Math.min(1, intensity));
    }

    function loadToFreq(load) {
        // 0.0 → 0.5 Hz, 4.0 → 3.5 Hz
        return 0.5 + Math.min(load, 4) * 0.75;
    }

    function paint(now) {
        const dt = (now - lastFrame) / 1000;
        lastFrame = now;

        const w = canvas.clientWidth;
        const h = canvas.clientHeight;

        const amp = intensityToAmp(state.mood_intensity) * (h / 2);
        const freq = loadToFreq(state.load);
        phase += dt * freq * Math.PI * 2;

        ctx.clearRect(0, 0, w, h);

        // Fill background subtly so the line stands out.
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, w, h);

        // Reference baseline.
        ctx.strokeStyle = '#21262d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h / 2);
        ctx.lineTo(w, h / 2);
        ctx.stroke();

        // The main wave.
        ctx.strokeStyle = state.color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 1) {
            const t = x / w;
            // Two harmonics, the second much smaller. Adds visual
            // texture without straying from a sine.
            const y = (h / 2)
                + amp * Math.sin(phase + t * Math.PI * 4)
                + amp * 0.18 * Math.sin(phase * 1.7 + t * Math.PI * 8);
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // A subtle dot tracking the right edge of the wave — gives the
        // eye something to lock onto.
        const tipY = (h / 2)
            + amp * Math.sin(phase + Math.PI * 4)
            + amp * 0.18 * Math.sin(phase * 1.7 + Math.PI * 8);
        ctx.fillStyle = state.color;
        ctx.beginPath();
        ctx.arc(w - 3, tipY, 2.4, 0, Math.PI * 2);
        ctx.fill();

        requestAnimationFrame(paint);
    }
    requestAnimationFrame(paint);

    // Slow poll of the server state. Default 60 seconds — adjust the
    // interval if Identity is more interesting to look at, but never
    // poll faster than the tick engine actually runs.
    function fetchState() {
        fetch('/identity/state.json', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                state = data;
                // If a label exists, update the small caption.
                const cap = document.getElementById('identity-wave-caption');
                if (cap && data.mood) {
                    cap.textContent = data.mood + ' · ' +
                        (data.mood_intensity * 100).toFixed(0) + '%';
                }
            })
            .catch(function () { /* offline; keep last state */ });
    }
    fetchState();
    setInterval(fetchState, 60 * 1000);
})();
