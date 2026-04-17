/* Casting: byte_model_tiny_dt continuous — walk through every input row
 * and show which path each hand-built DT takes.
 */
(function () {
  function makeBuilder() {
    const nodes = [];
    function leaf(v) { nodes.push({ leaf: true, value: v }); return nodes.length - 1; }
    function split(feat, z, o) {
      nodes.push({ leaf: false, feature: feat, zero: z, one: o });
      return nodes.length - 1;
    }
    function walk(root, inputs) {
      const path = [];
      let idx = root;
      while (!nodes[idx].leaf) {
        const feat = nodes[idx].feature;
        const bit = inputs[feat] > 0 ? 1 : 0;
        path.push({ feat, bit });
        idx = bit ? nodes[idx].one : nodes[idx].zero;
      }
      return { path, leaf: nodes[idx].value };
    }
    return { nodes, leaf, split, walk };
  }

  function buildMaj3() {
    const b = makeBuilder();
    const lp = b.leaf(+1), ln = b.leaf(-1);
    const a0b1 = b.split(2, ln, lp);
    const a1b0 = b.split(2, ln, lp);
    const a0 = b.split(1, ln, a0b1);
    const a1 = b.split(1, a1b0, lp);
    return { b, root: b.split(0, a0, a1) };
  }
  function buildMux3() {
    const b = makeBuilder();
    const lp = b.leaf(+1), ln = b.leaf(-1);
    const pickC = b.split(2, ln, lp);
    const pickB = b.split(1, ln, lp);
    return { b, root: b.split(0, pickC, pickB) };
  }

  let timer = null;
  let row = 0;
  const maj = buildMaj3();
  const mux = buildMux3();
  const VAR = ['a','b','c'];

  function fmtPath(p) {
    return p.path.map(s => `x${s.feat}=${s.bit}`).join(' → ');
  }

  function tick(emit) {
    const a = (row >> 2) & 1, b = (row >> 1) & 1, c = row & 1;
    const inputs = [a ? 1 : -1, b ? 1 : -1, c ? 1 : -1];

    const mw = maj.b.walk(maj.root, inputs);
    const xw = mux.b.walk(mux.root, inputs);

    const majTruth = ((a + b + c) >= 2) ? +1 : -1;
    const muxTruth = a ? (b ? +1 : -1) : (c ? +1 : -1);

    const lines = [
      `tiny decision trees — walking input rows`,
      `row ${row} of 8:  a=${a}  b=${b}  c=${c}`,
      ``,
      `MAJ(a,b,c):  path ${fmtPath(mw)}  →  leaf ${mw.leaf >= 0 ? '+1' : '-1'}   target=${majTruth >= 0 ? '+1' : '-1'}   ${mw.leaf === majTruth ? 'OK' : 'FAIL'}`,
      `MUX(a?b:c):  path ${fmtPath(xw)}  →  leaf ${xw.leaf >= 0 ? '+1' : '-1'}   target=${muxTruth >= 0 ? '+1' : '-1'}   ${xw.leaf === muxTruth ? 'OK' : 'FAIL'}`,
      ``,
      `(each step tests one bit; evaluation cost = path length)`,
    ];
    emit(lines.join('\n'));
    row = (row + 1) % 8;
  }

  function start(emit) {
    if (timer) return;
    row = 0;
    emit('starting row walk...');
    timer = setInterval(function () { tick(emit); }, 700);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.Casting_byte_model_tiny_dt_continuous = { start, stop };
})();
