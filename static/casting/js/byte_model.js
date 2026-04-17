// Casting — XOR by enumeration. Mathematically equivalent to byte_model.c.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }

    function run() {
        const X = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
        const Y = [-1, 1, 1, -1];
        let hits = 0, first = -1;
        for (let m = 0; m < 512; m++) {
            let ok = true;
            for (let i = 0; i < 4 && ok; i++) {
                if (forward(m, X[i][0], X[i][1]) !== Y[i]) ok = false;
            }
            if (ok) { if (first < 0) first = m; hits++; }
        }
        const hex = first >= 0
            ? '0x' + first.toString(16).padStart(3, '0')
            : '(none)';
        const rate = (100 * hits / 512).toFixed(4);
        return (
            'search space : 512 models (9-bit bitstrings)\n' +
            'working      : ' + hits + ' solve XOR\n' +
            'hit rate     : ' + rate + '%\n' +
            'first found  : ' + hex
        );
    }

    window.Casting_byte_model = { run };
})();
