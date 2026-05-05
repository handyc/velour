/* viralyst Brainfuck runner — pure JS, no server.
 *
 * The page provides:
 *   <textarea id="vy-source"  hidden>...</textarea>   the program
 *   <textarea id="vy-input"           >...</textarea>   stdin (',' reads)
 *   <pre      id="vy-output"  ></pre>                  capture buffer
 *   <button   id="vy-run"     ></button>
 *   <button   id="vy-reset"   ></button>
 *   <span     id="vy-stat"    ></span>                ops count + status
 *
 * 30000-cell tape, 8-bit wraparound on +/- (no wrap on </>).
 * Step cap defaults to 10M — enough for Hello-World, low enough to
 * keep a runaway from locking the tab. */

(function () {
  const STEP_CAP = 10_000_000;
  const TAPE_SIZE = 30000;

  const $ = (id) => document.getElementById(id);

  function preMatch(src) {
    /* Pre-compute jump table so loops are O(1). Stack of unmatched
     * '[' positions; on ']' pop and link both ways. */
    const m = new Int32Array(src.length);
    const stack = [];
    for (let i = 0; i < src.length; i++) {
      const c = src[i];
      if (c === '[') stack.push(i);
      else if (c === ']') {
        if (stack.length === 0) {
          throw new SyntaxError(`unmatched ']' at offset ${i}`);
        }
        const j = stack.pop();
        m[i] = j;
        m[j] = i;
      }
    }
    if (stack.length) {
      throw new SyntaxError(`unmatched '[' at offset ${stack[0]}`);
    }
    return m;
  }

  function run(src, stdin) {
    const tape = new Uint8Array(TAPE_SIZE);
    const match = preMatch(src);
    let dp = 0, ip = 0, steps = 0, inp = 0;
    let out = '';
    while (ip < src.length) {
      if (++steps > STEP_CAP) {
        return { out, steps, status: `step cap (${STEP_CAP}) reached` };
      }
      const c = src[ip];
      switch (c) {
        case '+': tape[dp] = (tape[dp] + 1) & 0xff; break;
        case '-': tape[dp] = (tape[dp] - 1) & 0xff; break;
        case '>':
          dp++;
          if (dp >= TAPE_SIZE) return { out, steps, status: 'tape overflow (dp >= 30000)' };
          break;
        case '<':
          dp--;
          if (dp < 0) return { out, steps, status: 'tape underflow (dp < 0)' };
          break;
        case '.': out += String.fromCharCode(tape[dp]); break;
        case ',':
          tape[dp] = inp < stdin.length ? stdin.charCodeAt(inp++) & 0xff : 0;
          break;
        case '[': if (tape[dp] === 0) ip = match[ip]; break;
        case ']': if (tape[dp] !== 0) ip = match[ip]; break;
        /* anything else is a comment per spec */
      }
      ip++;
    }
    return { out, steps, status: 'ok' };
  }

  function wire() {
    const src = $('vy-source');
    const input = $('vy-input');
    const out = $('vy-output');
    const stat = $('vy-stat');
    const btn = $('vy-run');
    const reset = $('vy-reset');
    if (!src || !btn || !out) return;

    btn.addEventListener('click', () => {
      stat.textContent = 'running…';
      out.textContent = '';
      /* yield to the browser so the spinner can paint before we
       * lock the thread for the run. */
      setTimeout(() => {
        try {
          const r = run(src.value, input ? input.value : '');
          out.textContent = r.out;
          stat.textContent = `${r.status} · ${r.steps.toLocaleString()} ops · ${r.out.length} chars output`;
        } catch (e) {
          out.textContent = '';
          stat.textContent = `error: ${e.message}`;
        }
      }, 0);
    });
    if (reset) reset.addEventListener('click', () => {
      out.textContent = '';
      stat.textContent = 'reset';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
