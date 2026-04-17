// Casting — Parity by routing. Mathematically equivalent to byte_model_parity.c.
(function () {
    const sgn = v => v >= 0 ? 1 : -1;
    const w = (m, i) => ((m >> i) & 1) ? 1 : -1;

    function forward(m, x1, x2) {
        const h0 = sgn(w(m, 0) * x1 + w(m, 1) * x2 + w(m, 2));
        const h1 = sgn(w(m, 3) * x1 + w(m, 4) * x2 + w(m, 5));
        return     sgn(w(m, 6) * h0 + w(m, 7) * h1 + w(m, 8));
    }

    function findXor() {
        const X = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
        const Y = [-1, 1, 1, -1];
        for (let m = 0; m < 512; m++) {
            let ok = true;
            for (let i = 0; i < 4 && ok; i++) {
                if (forward(m, X[i][0], X[i][1]) !== Y[i]) ok = false;
            }
            if (ok) return m;
        }
        return -1;
    }

    function compileLut(m) {
        const lut = [[0, 0], [0, 0]];
        for (let ai = 0; ai < 2; ai++) {
            for (let bi = 0; bi < 2; bi++) {
                lut[ai][bi] = forward(m, ai ? 1 : -1, bi ? 1 : -1);
            }
        }
        return lut;
    }

    const apply    = (lut, a, b) => lut[a > 0 ? 1 : 0][b > 0 ? 1 : 0];
    const parity3  = (lut, a, b, c) => apply(lut, apply(lut, a, b), c);
    const parity4  = (lut, a, b, c, d) =>
        apply(lut, apply(lut, a, b), apply(lut, c, d));

    function run() {
        const m = findXor();
        if (m < 0) return 'no XOR solver found (impossible).';
        const lut = compileLut(m);
        const hex = '0x' + m.toString(16).padStart(3, '0');
        const signed = v => v >= 0 ? '+' + v : String(v);

        let errors3 = 0;
        for (let mask = 0; mask < 8; mask++) {
            const a = (mask >> 0) & 1, b = (mask >> 1) & 1, c = (mask >> 2) & 1;
            const pred  = parity3(lut, a ? 1 : -1, b ? 1 : -1, c ? 1 : -1);
            const truth = ((a ^ b ^ c) ? +1 : -1);
            if (pred !== truth) errors3++;
        }
        let errors4 = 0;
        for (let mask = 0; mask < 16; mask++) {
            const a = (mask >> 0) & 1, b = (mask >> 1) & 1;
            const c = (mask >> 2) & 1, d = (mask >> 3) & 1;
            const pred  = parity4(lut, a ? 1 : -1, b ? 1 : -1, c ? 1 : -1, d ? 1 : -1);
            const truth = ((a ^ b ^ c ^ d) ? +1 : -1);
            if (pred !== truth) errors4++;
        }

        return (
            'discovered 9-bit XOR solver: ' + hex + '\n' +
            'compiled truth table:\n' +
            '              b=-1  b=+1\n' +
            '      a=-1 :  ' + signed(lut[0][0]) + '    ' + signed(lut[0][1]) + '\n' +
            '      a=+1 :  ' + signed(lut[1][0]) + '    ' + signed(lut[1][1]) + '\n\n' +
            'parity3 (2 blocks, 18 bits, 2 lookups per decision): ' +
            (8 - errors3) + '/8 correct\n' +
            'parity4 (3 blocks, 27 bits, 3 lookups per decision): ' +
            (16 - errors4) + '/16 correct\n\n' +
            'same 9-bit block, wired differently, computes different functions.\n' +
            'the capability comes from the routing, not the parameters.'
        );
    }

    window.Casting_byte_model_parity = { run };
})();
