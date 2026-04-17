// Casting — Chain or ensemble. Mathematically equivalent to byte_model_chain.c.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }

    function findN(N) {
        const X = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
        const Y = [-1, 1, 1, -1];
        const found = [];
        for (let m = 0; m < 512 && found.length < N; m++) {
            let ok = true;
            for (let i = 0; i < 4 && ok; i++) {
                if (forward(m, X[i][0], X[i][1]) !== Y[i]) ok = false;
            }
            if (ok) found.push(m);
        }
        return found;
    }

    function ensemble(models, x1, x2) {
        let s = 0;
        for (const m of models) s += forward(m, x1, x2);
        return sgn(s);
    }

    function deepChain(models, x1, x2) {
        let y = x1;
        for (const m of models) y = forward(m, y, x2);
        return y;
    }

    function evaluate(name, models, combiner) {
        const X = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
        const Y = [-1, 1, 1, -1];
        const cells = [];
        let ok = 0;
        for (let i = 0; i < 4; i++) {
            const y = combiner(models, X[i][0], X[i][1]);
            const s = v => (v >= 0 ? '+1' : '-1');
            cells.push('(' + s(X[i][0]) + ',' + s(X[i][1]) + ')→' + s(y));
            if (y === Y[i]) ok++;
        }
        const mark = ok === 4 ? ' ✓' : '';
        return '  ' + name.padEnd(11) + ': ' + cells.join('  ') + '  [' + ok + '/4' + mark + ']';
    }

    function run() {
        const N = 10;
        const models = findN(N);
        const hex = m => '0x' + m.toString(16).padStart(3, '0');
        const list = models.map((m, i) => '  [' + i + '] ' + hex(m)).join('\n');
        return (
            'collected ' + models.length + ' working models (target N = ' + N + '):\n' +
            list + '\n\n' +
            'chained behaviour on XOR truth table:\n' +
            evaluate('ensemble',   models, ensemble)  + '\n' +
            evaluate('deep chain', models, deepChain) + '\n\n' +
            'size accounting:\n' +
            '  single model : 9 bits\n' +
            '  chain total  : ' + (9 * models.length) + ' bits (' +
            models.length + '× the parameter budget)'
        );
    }

    window.Casting_byte_model_chain = { run };
})();
