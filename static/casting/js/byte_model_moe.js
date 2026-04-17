// Casting — Mixture of tiny experts. Mathematically equivalent to byte_model_moe.c
// (minus the on-disk checkpoint — the JS version runs once, fresh).
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

    function searchSolver(id) {
        for (let m = 0; m < 512; m++) {
            let ok = true;
            for (let row = 0; row < 4 && ok; row++) {
                const a = (row & 2) ? 1 : -1;
                const b = (row & 1) ? 1 : -1;
                if (forward(m, a, b) !== taskTruth(id, a, b)) ok = false;
            }
            if (ok) return m;
        }
        return -1;
    }

    const NAMES = [
        'FALSE', 'NOR', 'a AND !b', '!b', '!a AND b', '!a', 'XOR', 'NAND',
        'AND', 'XNOR', 'a', 'a OR !b', 'b', '!a OR b', 'OR', 'TRUE'
    ];

    function run() {
        const lines = ['growing the pool...'];
        let covered = 0;
        for (let id = 0; id < 16; id++) {
            const m = searchSolver(id);
            const name = NAMES[id].padEnd(12);
            if (m >= 0) {
                covered++;
                const hex = '0x' + m.toString(16).padStart(3, '0');
                lines.push('  + task 0x' + id.toString(16) + ' ' + name + ' weights=' + hex);
            } else {
                lines.push('  task 0x' + id.toString(16) + ' ' + name +
                           ' no 9-bit solver exists');
            }
        }
        lines.push('');
        lines.push('coverage: ' + covered + '/16 boolean functions');
        lines.push('(the C version also checkpoints atomically between steps;');
        lines.push('the JS version runs once, fresh, per click.)');
        return lines.join('\n');
    }

    window.Casting_byte_model_moe = { run };
})();
