/* Casting: byte_model_tiny_dt — hand-crafted tiny decision trees.
 * Mirrors static/casting/sources/byte_model_tiny_dt.c.
 */
(function () {
  function makeBuilder() {
    const nodes = [];
    function leaf(v) { nodes.push({ leaf: true, value: v }); return nodes.length - 1; }
    function split(feat, z, o) {
      nodes.push({ leaf: false, feature: feat, zero: z, one: o });
      return nodes.length - 1;
    }
    function evalTree(root, inputs) {
      let idx = root;
      while (!nodes[idx].leaf) {
        const bit = inputs[nodes[idx].feature] > 0 ? 1 : 0;
        idx = bit ? nodes[idx].one : nodes[idx].zero;
      }
      return nodes[idx].value;
    }
    function printTree(idx, depth, axis, out) {
      const pad = '  '.repeat(depth);
      if (nodes[idx].leaf) {
        out.push(`${pad}${axis} leaf ${nodes[idx].value >= 0 ? '+1' : '-1'}`);
        return;
      }
      out.push(`${pad}${axis} split on x${nodes[idx].feature}`);
      printTree(nodes[idx].zero, depth + 1, '  0 →', out);
      printTree(nodes[idx].one,  depth + 1, '  1 →', out);
    }
    return { nodes, leaf, split, evalTree, printTree };
  }

  function buildXor2() {
    const b = makeBuilder();
    const lp = b.leaf(+1), ln = b.leaf(-1);
    const a0 = b.split(1, ln, lp);
    const a1 = b.split(1, lp, ln);
    const root = b.split(0, a0, a1);
    return { b, root };
  }
  function buildMaj3() {
    const b = makeBuilder();
    const lp = b.leaf(+1), ln = b.leaf(-1);
    const a0b1 = b.split(2, ln, lp);
    const a1b0 = b.split(2, ln, lp);
    const a0 = b.split(1, ln, a0b1);
    const a1 = b.split(1, a1b0, lp);
    const root = b.split(0, a0, a1);
    return { b, root };
  }
  function buildMux3() {
    const b = makeBuilder();
    const lp = b.leaf(+1), ln = b.leaf(-1);
    const pickC = b.split(2, ln, lp);
    const pickB = b.split(1, ln, lp);
    const root = b.split(0, pickC, pickB);
    return { b, root };
  }

  function evaluate(b, root, nInputs, truthTable) {
    const rows = 1 << nInputs;
    let correct = 0;
    for (let row = 0; row < rows; ++row) {
      const inputs = new Array(nInputs);
      for (let i = 0; i < nInputs; ++i)
        inputs[i] = ((row >> (nInputs - 1 - i)) & 1) ? 1 : -1;
      const y = b.evalTree(root, inputs);
      const desired = ((truthTable >> row) & 1) ? 1 : -1;
      if (y === desired) correct++;
    }
    return correct;
  }

  const CASES = [
    { name: 'XOR(a,b)     ', n: 2, table: 0x6,  build: buildXor2 },
    { name: 'MAJ(a,b,c)   ', n: 3, table: 0xe8, build: buildMaj3 },
    { name: 'MUX(a?b:c)   ', n: 3, table: 0xca, build: buildMux3 },
  ];

  function run() {
    const lines = [];
    lines.push('tiny decision trees: hand-crafted, evaluated row-by-row');
    lines.push('');
    for (const c of CASES) {
      const { b, root } = c.build();
      const rows = 1 << c.n;
      const correct = evaluate(b, root, c.n, c.table);
      lines.push(`target ${c.name}   accuracy ${correct} / ${rows}   nodes=${b.nodes.length}`);
      b.printTree(root, 1, 'root:', lines);
      lines.push('');
    }
    lines.push('all three are exact — DTs are universal for small boolean targets.');
    lines.push('The substrate: a node is either a leaf ±1 or a split on x_i.');
    lines.push('This substrate is reused by induction, forest, boosting, feedback.');
    return lines.join('\n');
  }

  window.Casting_byte_model_tiny_dt = { run };
})();
