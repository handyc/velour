// Casting — XOR search by unbounded random sampling.
// Watches the hit-rate converge toward 16/512 = 3.125%.
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

    function isXorSolver(m) {
        for (let i = 0; i < 4; i++) {
            if (forward(m, X[i][0], X[i][1]) !== Y[i]) return false;
        }
        return true;
    }

    let state = null;
    let timer = null;

    function start(onUpdate) {
        stop();  // defensive: reset any previous run
        state = {
            samples: 0, hits: 0,
            uniqueSolvers: new Set(),
            startTime: performance.now(),
        };
        function tick() {
            const batch = 5000;
            for (let i = 0; i < batch; i++) {
                const m = Math.floor(Math.random() * 512);
                state.samples++;
                if (isXorSolver(m)) {
                    state.hits++;
                    state.uniqueSolvers.add(m);
                }
            }
            render();
            timer = setTimeout(tick, 30);
        }
        function render() {
            const rate = (100 * state.hits / state.samples).toFixed(3);
            const elapsed = ((performance.now() - state.startTime) / 1000).toFixed(1);
            const solvers = [...state.uniqueSolvers].sort((a, b) => a - b)
                .map(m => '0x' + m.toString(16).padStart(3, '0'));
            onUpdate(
                'random 9-bit draws, looking for XOR solvers\n\n' +
                '  samples drawn : ' + state.samples.toLocaleString() + '\n' +
                '  hits          : ' + state.hits.toLocaleString() + '\n' +
                '  hit rate      : ' + rate + '%   (target 3.125% = 16/512)\n' +
                '  unique found  : ' + state.uniqueSolvers.size + '/16\n' +
                '  elapsed       : ' + elapsed + 's\n\n' +
                '  solvers       : ' + (solvers.length ? solvers.join(' ') : '(none yet)')
            );
        }
        tick();
    }

    function stop() {
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    window.Casting_byte_model_continuous = { start, stop };
})();
