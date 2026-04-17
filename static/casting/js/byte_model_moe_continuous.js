// Casting — MoE growth by unbounded random sampling.
// Every draw is scored against all 16 two-input boolean tasks at once.
// Per-task hit count, first-discovery sample index, and total coverage
// accumulate over time.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }
    function taskTruth(id, a, b) {
        const ai = a > 0 ? 1 : 0, bi = b > 0 ? 1 : 0;
        const row = (ai << 1) | bi;
        return ((id >> row) & 1) ? 1 : -1;
    }
    function solves(m, taskId) {
        for (let row = 0; row < 4; row++) {
            const a = (row & 2) ? 1 : -1;
            const b = (row & 1) ? 1 : -1;
            if (forward(m, a, b) !== taskTruth(taskId, a, b)) return false;
        }
        return true;
    }

    const NAMES = [
        'FALSE', 'NOR', 'a AND !b', '!b', '!a AND b', '!a', 'XOR', 'NAND',
        'AND', 'XNOR', 'a', 'a OR !b', 'b', '!a OR b', 'OR', 'TRUE'
    ];

    let state = null;
    let timer = null;

    function start(onUpdate) {
        stop();
        state = {
            samples: 0,
            perTaskHits: new Array(16).fill(0),
            firstSolverAt: new Array(16).fill(null),
            startTime: performance.now(),
        };
        function tick() {
            for (let i = 0; i < 3000; i++) {
                const m = Math.floor(Math.random() * 512);
                state.samples++;
                for (let id = 0; id < 16; id++) {
                    if (solves(m, id)) {
                        state.perTaskHits[id]++;
                        if (state.firstSolverAt[id] === null) {
                            state.firstSolverAt[id] = state.samples;
                        }
                    }
                }
            }
            render();
            timer = setTimeout(tick, 30);
        }
        function render() {
            const covered = state.firstSolverAt.filter(x => x !== null).length;
            const lines = [
                'random 9-bit draws, each tested against all 16 boolean tasks',
                '',
                '  id  name          hits       first seen at       hit rate',
            ];
            for (let id = 0; id < 16; id++) {
                const hits = state.perTaskHits[id];
                const first = state.firstSolverAt[id];
                const firstStr = first !== null ? '#' + first.toLocaleString() : 'not yet';
                const rate = state.samples > 0
                    ? (100 * hits / state.samples).toFixed(2) + '%'
                    : '—';
                lines.push(
                    '  0x' + id.toString(16) + '  ' +
                    NAMES[id].padEnd(12) + '  ' +
                    String(hits).padStart(8) + '   ' +
                    firstStr.padEnd(17) + '   ' +
                    rate.padStart(7)
                );
            }
            const elapsed = ((performance.now() - state.startTime) / 1000).toFixed(1);
            lines.push('');
            lines.push('  coverage : ' + covered + '/16 tasks have at least one solver');
            lines.push('  samples  : ' + state.samples.toLocaleString());
            lines.push('  elapsed  : ' + elapsed + 's');
            lines.push('');
            lines.push('  highly asymmetric: FALSE/TRUE (bias-only) are easy,');
            lines.push('  XOR/XNOR take the longest to first-discover.');
            onUpdate(lines.join('\n'));
        }
        tick();
    }

    function stop() {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    window.Casting_byte_model_moe_continuous = { start, stop };
})();
