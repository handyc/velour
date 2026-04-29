/* Squarified treemap layout (Bruls, Huijsen, van Wijk 2000).
 *
 * Builds a strip greedily — items are added to the current row while
 * the worst aspect ratio improves; once it would worsen, the row is
 * placed and the algorithm recurses on the remaining rectangle. The
 * resulting tiles tend to be near-square and proportional to their
 * value, regardless of how skewed the value distribution is.
 *
 * Usage:
 *   import { renderTreemap } from '{% static "graphs/treemap.js" %}';
 *   renderTreemap(container, items, palette);
 *
 *   items: [{ path, size }, ...]   (size > 0)
 *   palette: array of CSS colour strings
 */
(function (root) {
    'use strict';

    function squarify(items, x, y, w, h, out) {
        if (!items.length || w <= 0 || h <= 0) return;
        if (items.length === 1) {
            out.push({ item: items[0], x: x, y: y, w: w, h: h });
            return;
        }
        var total = items.reduce(function (a, i) { return a + i.size; }, 0);
        if (total <= 0) {
            // Degenerate: spread equally.
            var eq = items.map(function (it) { return Object.assign({}, it, { size: 1 }); });
            return squarify(eq, x, y, w, h, out);
        }

        var horizontal = w >= h;       // strip on long edge
        var shortSide = Math.min(w, h);
        var scale = (w * h) / total;   // value → area

        function worst(sum, mn, mx) {
            return Math.max(
                (shortSide * shortSide * mx) / (sum * sum),
                (sum * sum) / (shortSide * shortSide * mn)
            );
        }

        var i = 0;
        var rowSum = 0, rowMin = Infinity, rowMax = -Infinity;
        var prev = Infinity;
        var row = [];
        for (; i < items.length; i++) {
            var v = items[i].size * scale;
            var ns = rowSum + v;
            var nMin = Math.min(rowMin, v);
            var nMax = Math.max(rowMax, v);
            var r = worst(ns, nMin, nMax);
            if (i > 0 && r > prev) break;
            row.push(items[i]);
            rowSum = ns; rowMin = nMin; rowMax = nMax; prev = r;
        }

        var rowFrac = row.reduce(function (a, it) { return a + it.size; }, 0) / total;
        if (horizontal) {
            var sw = w * rowFrac;
            layoutRow(row, x, y, sw, h, 'v', out);
            squarify(items.slice(i), x + sw, y, w - sw, h, out);
        } else {
            var sh = h * rowFrac;
            layoutRow(row, x, y, w, sh, 'h', out);
            squarify(items.slice(i), x, y + sh, w, h - sh, out);
        }
    }

    function layoutRow(row, x, y, w, h, orient, out) {
        var total = row.reduce(function (a, i) { return a + i.size; }, 0) || 1;
        if (orient === 'v') {
            var cy = y;
            for (var k = 0; k < row.length; k++) {
                var ih = h * (row[k].size / total);
                out.push({ item: row[k], x: x, y: cy, w: w, h: ih });
                cy += ih;
            }
        } else {
            var cx = x;
            for (var k2 = 0; k2 < row.length; k2++) {
                var iw = w * (row[k2].size / total);
                out.push({ item: row[k2], x: cx, y: y, w: iw, h: h });
                cx += iw;
            }
        }
    }

    function renderTreemap(container, items, palette) {
        if (!container) return;
        container.innerHTML = '';
        var sorted = (items || []).slice().sort(function (a, b) {
            return b.size - a.size;
        });

        if (sorted.length === 0) {
            var empty = document.createElement('div');
            empty.style.cssText =
                'position:absolute;inset:0;display:flex;align-items:center;' +
                'justify-content:center;color:#8b949e;font:0.85rem ui-monospace,monospace;' +
                'text-align:center;padding:1rem;';
            empty.textContent = 'No data — the scan returned an empty result. ' +
                'See server logs.';
            container.appendChild(empty);
            return;
        }

        var W = container.clientWidth;
        var H = container.clientHeight;
        // If the container is hidden when render is called, clientWidth
        // can be 0 — fall back to a sensible default so we still draw.
        if (W <= 0 || H <= 0) { W = W || 600; H = H || 220; }

        var placements = [];
        squarify(sorted, 0, 0, W, H, placements);

        // Skip tiles that would render too small to be visible — with
        // border + padding included via box-sizing, anything under ~5 px
        // is just dust in the corner. They're already accounted for in
        // the parent's "(other)" bucket on the server, so dropping them
        // here just cleans up the visualisation.
        var MIN_DIM = 5;
        for (var i = 0; i < placements.length; i++) {
            var p = placements[i];
            if (p.w < MIN_DIM || p.h < MIN_DIM) continue;
            var div = document.createElement('div');
            div.className = 'treemap-item';
            div.style.left   = p.x.toFixed(1) + 'px';
            div.style.top    = p.y.toFixed(1) + 'px';
            div.style.width  = Math.max(0, p.w - 1).toFixed(1) + 'px';
            div.style.height = Math.max(0, p.h - 1).toFixed(1) + 'px';
            div.style.background = palette[i % palette.length];
            div.title = p.item.path + ': ' + p.item.size + ' MB';
            // Only label tiles big enough to read.
            if (p.w >= 50 && p.h >= 16) {
                div.textContent = p.item.path.split('/').pop() + ' · ' + p.item.size + 'M';
            }
            container.appendChild(div);
        }
    }

    root.HelixTreemap = { render: renderTreemap };
}(window));
