// Casting — random tree-wirings for parity-N.
// Each tick samples random (A,B) and (A,B,G) triples of 9-bit blocks,
// checks whether the composed tree realises 3-bit or 4-bit parity.
// Over time the hit rates stabilise, revealing how many tree-wirings
// out of 512^2 and 512^3 actually compute parity.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }

    // parity3 via tree (A, B): out = forward(B, forward(A, a, b), c)
    function tryParity3(A, B) {
        for (let mask = 0; mask < 8; mask++) {
            const a = (mask & 1) ? 1 : -1;
            const b = (mask & 2) ? 1 : -1;
            const c = (mask & 4) ? 1 : -1;
            const p = ((mask & 1) ^ ((mask >> 1) & 1) ^ ((mask >> 2) & 1));
            const truth = p ? 1 : -1;
            if (forward(B, forward(A, a, b), c) !== truth) return false;
        }
        return true;
    }
    // parity4 via tree (A, B, G): out = forward(G, forward(A, a, b), forward(B, c, d))
    function tryParity4(A, B, G) {
        for (let mask = 0; mask < 16; mask++) {
            const a = (mask & 1) ? 1 : -1;
            const b = (mask & 2) ? 1 : -1;
            const c = (mask & 4) ? 1 : -1;
            const d = (mask & 8) ? 1 : -1;
            const p = ((mask & 1) ^ ((mask >> 1) & 1) ^
                       ((mask >> 2) & 1) ^ ((mask >> 3) & 1));
            const truth = p ? 1 : -1;
            if (forward(G, forward(A, a, b), forward(B, c, d)) !== truth) return false;
        }
        return true;
    }

    let state = null;
    let timer = null;

    function start(onUpdate) {
        stop();
        state = {
            p3Samples: 0, p3Hits: 0,
            p4Samples: 0, p4Hits: 0,
            startTime: performance.now(),
        };
        function tick() {
            for (let i = 0; i < 2000; i++) {
                const A = Math.floor(Math.random() * 512);
                const B = Math.floor(Math.random() * 512);
                const G = Math.floor(Math.random() * 512);
                state.p3Samples++;
                if (tryParity3(A, B)) state.p3Hits++;
                state.p4Samples++;
                if (tryParity4(A, B, G)) state.p4Hits++;
            }
            render();
            timer = setTimeout(tick, 30);
        }
        function render() {
            const pct = (h, n) => n > 0 ? (100 * h / n).toFixed(4) + '%' : '—';
            const rate3 = state.p3Samples ? state.p3Hits / state.p3Samples : 0;
            const rate4 = state.p4Samples ? state.p4Hits / state.p4Samples : 0;
            // expected full-coverage size for parity3 = 512^2 = 262144, parity4 = 512^3 ≈ 134M
            const estP3 = rate3 > 0 ? Math.round(rate3 * 262144) : 0;
            const estP4 = rate4 > 0 ? Math.round(rate4 * 134217728) : 0;
            const elapsed = ((performance.now() - state.startTime) / 1000).toFixed(1);
            onUpdate(
                'random (A,B) and (A,B,G) tree wirings, looking for parity realisers\n\n' +
                '  parity3 tree, space = 512 x 512 = 262,144 pairs\n' +
                '    samples drawn : ' + state.p3Samples.toLocaleString() + '\n' +
                '    hits          : ' + state.p3Hits.toLocaleString() + '\n' +
                '    hit rate      : ' + pct(state.p3Hits, state.p3Samples) + '\n' +
                '    estimated total parity3-realisers : ~' + estP3.toLocaleString() + '\n\n' +
                '  parity4 tree, space = 512 x 512 x 512 ≈ 134M triples\n' +
                '    samples drawn : ' + state.p4Samples.toLocaleString() + '\n' +
                '    hits          : ' + state.p4Hits.toLocaleString() + '\n' +
                '    hit rate      : ' + pct(state.p4Hits, state.p4Samples) + '\n' +
                '    estimated total parity4-realisers : ~' + estP4.toLocaleString() + '\n\n' +
                '  elapsed         : ' + elapsed + 's\n\n' +
                '  known exact: all XOR^k tree positions work, but some non-XOR\n' +
                '  blocks compose accidentally into parity too. the running rate\n' +
                '  is an unbiased estimate of how many such wirings exist.'
            );
        }
        tick();
    }

    function stop() {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    window.Casting_byte_model_parity_continuous = { start, stop };
})();
