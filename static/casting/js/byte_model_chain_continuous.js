// Casting — chain-vs-ensemble statistics by repeated random sampling.
// Each round: pick N random XOR solvers (N drawn 1..20), evaluate chain + ensemble.
// Watches the N-parity pattern emerge for deep chain; ensemble is flat.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }
    const X = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
    const Y = [-1, 1, 1, -1];

    function isXor(m) {
        for (let i = 0; i < 4; i++) {
            if (forward(m, X[i][0], X[i][1]) !== Y[i]) return false;
        }
        return true;
    }
    // All 16 XOR solvers enumerated once at load.
    const SOLVERS = (() => {
        const s = [];
        for (let m = 0; m < 512; m++) if (isXor(m)) s.push(m);
        return s;
    })();

    function pickSolvers(n) {
        const out = [];
        for (let i = 0; i < n; i++) {
            out.push(SOLVERS[Math.floor(Math.random() * SOLVERS.length)]);
        }
        return out;
    }

    function evalPair(models) {
        let chainOk = 0, ensembleOk = 0;
        for (let i = 0; i < 4; i++) {
            const x1 = X[i][0], x2 = X[i][1];
            let y = x1;
            for (const m of models) y = forward(m, y, x2);
            if (y === Y[i]) chainOk++;
            let s = 0;
            for (const m of models) s += forward(m, x1, x2);
            if (sgn(s) === Y[i]) ensembleOk++;
        }
        return [chainOk, ensembleOk];
    }

    let state = null;
    let timer = null;

    function start(onUpdate) {
        stop();
        state = {
            byN: Array.from({ length: 21 }, () =>
                ({ runs: 0, chainHits: 0, ensembleHits: 0 })),
            totalRuns: 0,
            startTime: performance.now(),
        };
        function tick() {
            for (let i = 0; i < 500; i++) {
                const N = 1 + Math.floor(Math.random() * 20);
                const models = pickSolvers(N);
                const [chainOk, ensembleOk] = evalPair(models);
                const slot = state.byN[N];
                slot.runs++;
                if (chainOk === 4) slot.chainHits++;
                if (ensembleOk === 4) slot.ensembleHits++;
                state.totalRuns++;
            }
            render();
            timer = setTimeout(tick, 30);
        }
        function render() {
            const pct = (h, n) => n > 0 ? (100 * h / n).toFixed(0) + '%' : '—';
            const lines = [
                'random XOR-solvers chained or ensembled (N drawn uniformly 1..20)',
                '',
                '   N    runs     chain=4/4    ensemble=4/4',
            ];
            for (let N = 1; N <= 20; N++) {
                const s = state.byN[N];
                lines.push(
                    '  ' + String(N).padStart(2) + '   ' +
                    String(s.runs).padStart(6) + '     ' +
                    pct(s.chainHits, s.runs).padStart(5) + '         ' +
                    pct(s.ensembleHits, s.runs).padStart(5)
                );
            }
            const elapsed = ((performance.now() - state.startTime) / 1000).toFixed(1);
            lines.push('');
            lines.push('  total runs : ' + state.totalRuns.toLocaleString());
            lines.push('  elapsed    : ' + elapsed + 's');
            lines.push('');
            lines.push('  ensemble is 100% at every N; deep chain is 100% iff N is odd.');
            onUpdate(lines.join('\n'));
        }
        tick();
    }

    function stop() {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    window.Casting_byte_model_chain_continuous = { start, stop };
})();
