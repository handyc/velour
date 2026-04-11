// Chronos clock ticker.
//
// Two responsibilities:
//   1. Tick the topbar clock (#chronos-topbar) every second using
//      Date.now() offset by the server-provided epoch_ms baseline.
//   2. Tick every .clock-card on the /chronos/ home page the same way.
//   3. Periodically re-sync against /chronos/now.json so JS drift never
//      accumulates past the user's configured interval.
//
// All time formatting happens client-side using Intl.DateTimeFormat with
// the card's data-clock-tz, so the JS doesn't need to know per-tz offsets.

(function () {
    'use strict';

    function fmtDate(d, tz) {
        // "Sat 11 Apr 2026" — en-GB renders "Sat, 11 Apr 2026" with a comma
        // after the weekday by default, so strip it for parity with the
        // server-side strftime('%a %d %b %Y') format.
        return new Intl.DateTimeFormat('en-GB', {
            timeZone: tz,
            weekday: 'short',
            day: '2-digit',
            month: 'short',
            year: 'numeric',
        }).format(d).replace(',', '');
    }

    function fmtTime(d, tz, format24, showSeconds) {
        const opts = {
            timeZone: tz,
            hour: '2-digit',
            minute: '2-digit',
            hour12: !format24,
        };
        if (showSeconds) opts.second = '2-digit';
        return new Intl.DateTimeFormat('en-GB', opts).format(d);
    }

    // --- topbar -----------------------------------------------------
    const topbar = document.getElementById('chronos-topbar');
    let topbarOffset = 0;  // serverNow - clientNow at last sync
    let topbarTz = null;
    let topbarFormat24 = true;
    let topbarShowSeconds = true;
    let topbarAutoSyncMs = 0;

    function paintTopbar() {
        if (!topbar) return;
        const d = new Date(Date.now() + topbarOffset);
        const dateEl = document.getElementById('chronos-date');
        const timeEl = document.getElementById('chronos-time');
        if (dateEl) dateEl.textContent = fmtDate(d, topbarTz);
        if (timeEl) timeEl.textContent = fmtTime(d, topbarTz, topbarFormat24, topbarShowSeconds);
    }

    if (topbar) {
        topbarTz = topbar.dataset.tz;
        // NB: must use data-hour-format and not data-format-24h. Per HTML5,
        // a dash followed by a digit (the "2" in 24h) is NOT collapsed in
        // the dataset conversion, so the property name retains the dash
        // (`dataset["format-24h"]`), which dot-notation can't reach. The
        // result was a silent default to 12h for both topbar and every
        // world clock card on /chronos/.
        topbarFormat24 = topbar.dataset.hourFormat === '24';
        topbarShowSeconds = topbar.dataset.showSeconds === '1';
        topbarAutoSyncMs = parseInt(topbar.dataset.autoSyncMs || '0', 10);
        const baseline = parseInt(topbar.dataset.epochMs || '0', 10);
        if (baseline) topbarOffset = baseline - Date.now();
        paintTopbar();
        setInterval(paintTopbar, topbarShowSeconds ? 1000 : 15000);
    }

    // --- world clock cards on /chronos/ -----------------------------
    const cards = document.querySelectorAll('.clock-card[data-clock-tz]');
    cards.forEach(function (card) {
        const tz = card.dataset.clockTz;
        const baseline = parseInt(card.dataset.clockEpochMs || '0', 10);
        const offset = baseline ? baseline - Date.now() : 0;
        const dateEl = card.querySelector('.js-clock-date');
        const timeEl = card.querySelector('.js-clock-time');

        function paint() {
            const d = new Date(Date.now() + offset);
            if (dateEl) dateEl.textContent = fmtDate(d, tz);
            if (timeEl) timeEl.textContent = fmtTime(d, tz, topbarFormat24, topbarShowSeconds);
        }
        paint();
        setInterval(paint, topbarShowSeconds ? 1000 : 15000);
    });

    // --- periodic re-sync against the server ------------------------
    function resyncTopbar() {
        if (!topbar) return;
        fetch('/chronos/now.json', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.epoch_ms) {
                    topbarOffset = data.epoch_ms - Date.now();
                    paintTopbar();
                }
            })
            .catch(function () { /* swallow — try again next interval */ });
    }
    if (topbar && topbarAutoSyncMs > 0) {
        setInterval(resyncTopbar, topbarAutoSyncMs);
    }
})();
