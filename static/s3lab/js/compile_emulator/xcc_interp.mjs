// xcc_interp.mjs — tree-walking interpreter for the xcc700 dialect
// of C. Sized for /s3lab/compile/'s slot kernels (step / render /
// gpio / fitness), NOT for arbitrary C — same constraints xcc700 has:
//
//   - only // comments
//   - declarations must initialise (int i = 0;)
//   - no for / do / switch / struct / union / typedef / float / double
//   - no preprocessor
//   - while, if/else, return, function definitions
//   - int / char / pointers / arrays
//   - the usual operators, including bitwise (& | ^ << >>)
//
// Memory model:
//   - int values  → JS Number (clamped to int32 on shifts)
//   - char values → JS Number (0..255)
//   - char *      → { buf: Uint8Array, off: int }
//   - int *       → { buf: Int32Array, off: int } (rare in slot kernels)
//   - locals      → an "env" object stack; each function call pushes
//                   a fresh frame
//
// Public entry: parseProgram(src) → AST · runFunction(ast, name, args)
// → JS-typed return value (int slot returns Number, void returns null).


// ── Lexer ──────────────────────────────────────────────────────────

const SINGLE_CHAR_TOKS = new Set([
    '(', ')', '{', '}', '[', ']', ';', ',',
    '+', '-', '*', '/', '%', '!', '~', '?', ':', '=',
    '<', '>', '&', '|', '^',
]);

const KEYWORDS = new Set([
    'int', 'char', 'void', 'if', 'else', 'while', 'return', 'enum',
]);

export function tokenize(src) {
    const toks = [];
    let i = 0;
    let line = 1;
    const N = src.length;

    while (i < N) {
        const c = src[i];

        // whitespace
        if (c === ' ' || c === '\t' || c === '\r') { i++; continue; }
        if (c === '\n') { line++; i++; continue; }

        // // comment
        if (c === '/' && src[i + 1] === '/') {
            while (i < N && src[i] !== '\n') i++;
            continue;
        }

        // identifier / keyword
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c === '_') {
            let j = i;
            while (j < N) {
                const cc = src[j];
                if ((cc >= 'a' && cc <= 'z') || (cc >= 'A' && cc <= 'Z') ||
                    (cc >= '0' && cc <= '9') || cc === '_') j++;
                else break;
            }
            const word = src.slice(i, j);
            if (KEYWORDS.has(word)) {
                toks.push({ type: word, line });
            } else {
                toks.push({ type: 'IDENT', value: word, line });
            }
            i = j;
            continue;
        }

        // numeric literal — hex (0x...) or decimal
        if (c >= '0' && c <= '9') {
            let j = i;
            let value;
            if (c === '0' && (src[i + 1] === 'x' || src[i + 1] === 'X')) {
                j = i + 2;
                while (j < N && /[0-9a-fA-F]/.test(src[j])) j++;
                value = parseInt(src.slice(i, j), 16);
            } else {
                while (j < N && src[j] >= '0' && src[j] <= '9') j++;
                value = parseInt(src.slice(i, j), 10);
            }
            toks.push({ type: 'NUM', value, line });
            i = j;
            continue;
        }

        // char literal
        if (c === "'") {
            let j = i + 1;
            let v;
            if (src[j] === '\\') {
                j++;
                const esc = src[j];
                v = esc === 'n' ? 10 : esc === 't' ? 9 : esc === 'r' ? 13 :
                    esc === '0' ? 0 : esc === '\\' ? 92 : esc === "'" ? 39 :
                    esc.charCodeAt(0);
                j++;
            } else {
                v = src.charCodeAt(j); j++;
            }
            if (src[j] === "'") j++;
            toks.push({ type: 'NUM', value: v, line });
            i = j;
            continue;
        }

        // string literal — unused by slot kernels but cheap to support
        if (c === '"') {
            let j = i + 1;
            let s = '';
            while (j < N && src[j] !== '"') {
                if (src[j] === '\\' && j + 1 < N) {
                    const esc = src[j + 1];
                    s += esc === 'n' ? '\n' : esc === 't' ? '\t' :
                         esc === 'r' ? '\r' : esc === '0' ? '\0' :
                         esc === '\\' ? '\\' : esc;
                    j += 2;
                } else {
                    s += src[j]; j++;
                }
            }
            if (src[j] === '"') j++;
            toks.push({ type: 'STR', value: s, line });
            i = j;
            continue;
        }

        // multi-char operators
        const two = src.slice(i, i + 2);
        if (two === '==' || two === '!=' || two === '<=' || two === '>=' ||
            two === '&&' || two === '||' || two === '<<' || two === '>>' ||
            two === '++' || two === '--' || two === '+=' || two === '-=' ||
            two === '*=' || two === '/=' || two === '&=' || two === '|=' ||
            two === '^=' || two === '%=') {
            toks.push({ type: two, line });
            i += 2;
            continue;
        }

        // single-char punctuation / operator
        if (SINGLE_CHAR_TOKS.has(c)) {
            toks.push({ type: c, line });
            i++;
            continue;
        }

        throw new InterpError(`unexpected char ${JSON.stringify(c)}`, line);
    }
    toks.push({ type: 'EOF', line });
    return toks;
}


// ── Errors ─────────────────────────────────────────────────────────

export class InterpError extends Error {
    constructor(msg, line) {
        super(line ? `Line ${line}: ${msg}` : msg);
        this.line = line;
    }
}


// ── Parser ─────────────────────────────────────────────────────────
//
// Recursive descent. Returns: { functions: Map<name, fnNode> }.
// Function node: { name, returnType, params: [{ type, name }], body }
// Statement nodes: 'block', 'while', 'if', 'return', 'expr', 'decl'
// Expression nodes: 'num', 'ident', 'binop', 'unop', 'index', 'call',
//                   'assign', 'cast', 'paren'

export function parse(tokens) {
    let pos = 0;
    const peek = (off = 0) => tokens[pos + off];
    const eat  = (type) => {
        const t = tokens[pos];
        if (type && t.type !== type) {
            throw new InterpError(
                `expected ${type}, got ${tokTag(t)}`, t.line);
        }
        pos++;
        return t;
    };
    const tokTag = (t) =>
        t.type === 'NUM' ? `NUM(${t.value})`
      : t.type === 'IDENT' ? `IDENT(${t.value})`
      : t.type === 'STR' ? `STR`
      : t.type;

    function parseType() {
        // int / char / void [*]?
        const t = peek();
        if (t.type !== 'int' && t.type !== 'char' && t.type !== 'void') {
            throw new InterpError(`expected type, got ${tokTag(t)}`, t.line);
        }
        eat();
        let isPtr = false;
        if (peek().type === '*') { eat('*'); isPtr = true; }
        return { base: t.type, ptr: isPtr };
    }

    function parseProgram() {
        const functions = new Map();
        while (peek().type !== 'EOF') {
            // We accept top-level enum {} blocks just by skipping them
            // — slot kernels don't need them, but xcc700 dialect allows.
            if (peek().type === 'enum') {
                eat('enum'); eat('{');
                while (peek().type !== '}') eat();
                eat('}'); eat(';');
                continue;
            }
            const fn = parseFunction();
            functions.set(fn.name, fn);
        }
        return { functions };
    }

    function parseFunction() {
        const returnType = parseType();
        const nameTok = eat('IDENT');
        eat('(');
        const params = [];
        if (peek().type !== ')') {
            do {
                if (peek().type === 'void' && peek(1).type === ')') {
                    // void-only param list (rare in slot kernels)
                    eat('void');
                    break;
                }
                const ptype = parseType();
                const pname = eat('IDENT').value;
                params.push({ type: ptype, name: pname });
                if (peek().type === ',') eat(',');
                else break;
            } while (true);
        }
        eat(')');
        const body = parseBlock();
        return { name: nameTok.value, returnType, params, body,
                 line: nameTok.line };
    }

    function parseBlock() {
        eat('{');
        const stmts = [];
        while (peek().type !== '}') stmts.push(parseStatement());
        eat('}');
        return { type: 'block', stmts };
    }

    function parseStatement() {
        const t = peek();
        if (t.type === '{') return parseBlock();
        if (t.type === 'while') return parseWhile();
        if (t.type === 'if')    return parseIf();
        if (t.type === 'return') {
            eat('return');
            let val = null;
            if (peek().type !== ';') val = parseExpression();
            eat(';');
            return { type: 'return', value: val, line: t.line };
        }
        if (t.type === 'int' || t.type === 'char' || t.type === 'void') {
            return parseDecl();
        }
        // expression statement
        const e = parseExpression();
        eat(';');
        return { type: 'expr', expr: e, line: t.line };
    }

    function parseWhile() {
        const t = eat('while');
        eat('(');
        const cond = parseExpression();
        eat(')');
        const body = parseStatement();
        return { type: 'while', cond, body, line: t.line };
    }

    function parseIf() {
        const t = eat('if');
        eat('(');
        const cond = parseExpression();
        eat(')');
        const then_ = parseStatement();
        let else_ = null;
        if (peek().type === 'else') { eat('else'); else_ = parseStatement(); }
        return { type: 'if', cond, then: then_, else: else_, line: t.line };
    }

    function parseDecl() {
        const t = peek();
        const declType = parseType();
        // We allow: int x = e; int x[N] = ...; char *p = e;  (only init-on-decl)
        const name = eat('IDENT').value;
        let arraySize = null;
        if (peek().type === '[') {
            eat('[');
            arraySize = parseExpression();
            eat(']');
        }
        let init = null;
        if (peek().type === '=') {
            eat('=');
            init = parseExpression();
        }
        eat(';');
        return { type: 'decl', declType, name, arraySize, init, line: t.line };
    }

    // expression — Pratt-ish with explicit precedence levels.
    function parseExpression() { return parseAssign(); }

    function parseAssign() {
        const left = parseLogical();
        const t = peek();
        if (t.type === '=' || t.type === '+=' || t.type === '-=' ||
            t.type === '*=' || t.type === '/=' || t.type === '%=' ||
            t.type === '&=' || t.type === '|=' || t.type === '^=') {
            eat();
            const right = parseAssign();
            return { type: 'assign', op: t.type, target: left, value: right,
                     line: t.line };
        }
        return left;
    }

    function parseLogical() {
        let left = parseBitOr();
        while (peek().type === '&&' || peek().type === '||') {
            const op = eat().type;
            const right = parseBitOr();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseBitOr() {
        let left = parseBitXor();
        while (peek().type === '|') {
            eat('|');
            const right = parseBitXor();
            left = { type: 'binop', op: '|', left, right };
        }
        return left;
    }

    function parseBitXor() {
        let left = parseBitAnd();
        while (peek().type === '^') {
            eat('^');
            const right = parseBitAnd();
            left = { type: 'binop', op: '^', left, right };
        }
        return left;
    }

    function parseBitAnd() {
        let left = parseEquality();
        while (peek().type === '&') {
            eat('&');
            const right = parseEquality();
            left = { type: 'binop', op: '&', left, right };
        }
        return left;
    }

    function parseEquality() {
        let left = parseComparison();
        while (peek().type === '==' || peek().type === '!=') {
            const op = eat().type;
            const right = parseComparison();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseComparison() {
        let left = parseShift();
        while (peek().type === '<' || peek().type === '>' ||
               peek().type === '<=' || peek().type === '>=') {
            const op = eat().type;
            const right = parseShift();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseShift() {
        let left = parseAdditive();
        while (peek().type === '<<' || peek().type === '>>') {
            const op = eat().type;
            const right = parseAdditive();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseAdditive() {
        let left = parseMultiplicative();
        while (peek().type === '+' || peek().type === '-') {
            const op = eat().type;
            const right = parseMultiplicative();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseMultiplicative() {
        let left = parseUnary();
        while (peek().type === '*' || peek().type === '/' || peek().type === '%') {
            const op = eat().type;
            const right = parseUnary();
            left = { type: 'binop', op, left, right };
        }
        return left;
    }

    function parseUnary() {
        const t = peek();
        if (t.type === '-' || t.type === '!' || t.type === '~') {
            eat();
            return { type: 'unop', op: t.type, value: parseUnary() };
        }
        if (t.type === '*') {
            // pointer deref read: *p
            eat('*');
            return { type: 'unop', op: '*', value: parseUnary() };
        }
        if (t.type === '&') {
            // address-of: &x — rare in slot kernels but cheap to support
            eat('&');
            return { type: 'unop', op: '&', value: parseUnary() };
        }
        if (t.type === '++' || t.type === '--') {
            eat();
            return { type: 'unop', op: 'pre' + t.type, value: parseUnary() };
        }
        return parsePostfix();
    }

    function parsePostfix() {
        let node = parsePrimary();
        while (true) {
            const t = peek();
            if (t.type === '[') {
                eat('[');
                const idx = parseExpression();
                eat(']');
                node = { type: 'index', target: node, index: idx };
            } else if (t.type === '(') {
                eat('(');
                const args = [];
                if (peek().type !== ')') {
                    args.push(parseExpression());
                    while (peek().type === ',') { eat(','); args.push(parseExpression()); }
                }
                eat(')');
                node = { type: 'call', target: node, args };
            } else if (t.type === '++' || t.type === '--') {
                eat();
                node = { type: 'unop', op: 'post' + t.type, value: node };
            } else {
                break;
            }
        }
        return node;
    }

    function parsePrimary() {
        const t = peek();
        if (t.type === 'NUM') { eat(); return { type: 'num', value: t.value }; }
        if (t.type === 'STR') { eat(); return { type: 'str', value: t.value }; }
        if (t.type === 'IDENT') { eat(); return { type: 'ident', name: t.value, line: t.line }; }
        if (t.type === '(') {
            eat('(');
            // Could be a cast — (int)x or (char *)p — but we punt on
            // casts for V1 since slot kernels don't use them.
            const e = parseExpression();
            eat(')');
            return e;
        }
        throw new InterpError(`unexpected ${tokTag(t)}`, t.line);
    }

    return parseProgram();
}


// ── Interpreter ───────────────────────────────────────────────────

export function parseProgram(src) {
    return parse(tokenize(src));
}


// Truncate for int32 semantics on shifts / overflows.
const I32 = (x) => x | 0;

// A Pointer is { buf, off, isInt32 }. Indexing reads buf[off + i].
function makeCharPtr(buf, off = 0) { return { buf, off, isInt32: false }; }

function readPtr(p) {
    return p.isInt32 ? p.buf[p.off] : p.buf[p.off];
}
function writePtr(p, v) {
    if (p.isInt32) p.buf[p.off] = I32(v);
    else p.buf[p.off] = v & 0xFF;
}

function ptrAdd(p, delta) {
    return { buf: p.buf, off: p.off + delta, isInt32: p.isInt32 };
}


export class Env {
    constructor(parent = null) {
        this.vars = new Map();
        this.parent = parent;
    }
    declare(name, value) {
        this.vars.set(name, { value });
    }
    lookup(name) {
        let env = this;
        while (env) {
            if (env.vars.has(name)) return env.vars.get(name);
            env = env.parent;
        }
        throw new InterpError(`undefined identifier: ${name}`);
    }
    set(name, value) {
        const slot = this.lookup(name);
        slot.value = value;
    }
}


// Sentinel thrown by `return` to unwind to the call site.
class ReturnSignal {
    constructor(value) { this.value = value; }
}


function evalNode(node, env, prog) {
    if (!node) return null;
    switch (node.type) {
    case 'block': {
        const inner = new Env(env);
        for (const s of node.stmts) evalNode(s, inner, prog);
        return null;
    }
    case 'expr':
        evalExpr(node.expr, env, prog);
        return null;
    case 'decl': {
        // int x = expr;  int arr[N] = expr;  char *p = expr;
        let init = null;
        if (node.init) init = evalExpr(node.init, env, prog);
        if (node.arraySize) {
            const n = evalExpr(node.arraySize, env, prog);
            const isInt = node.declType.base === 'int' && !node.declType.ptr;
            const buf = isInt ? new Int32Array(n) : new Uint8Array(n);
            // Slot kernels don't use array initializers; if init is set
            // we ignore for arrays (could be added later).
            env.declare(node.name, { buf, off: 0, isInt32: isInt });
        } else {
            env.declare(node.name, init);
        }
        return null;
    }
    case 'while': {
        while (toBool(evalExpr(node.cond, env, prog))) {
            try { evalNode(node.body, env, prog); }
            catch (e) { if (e instanceof ReturnSignal) throw e; else throw e; }
        }
        return null;
    }
    case 'if': {
        if (toBool(evalExpr(node.cond, env, prog))) {
            evalNode(node.then, env, prog);
        } else if (node.else) {
            evalNode(node.else, env, prog);
        }
        return null;
    }
    case 'return': {
        const v = node.value ? evalExpr(node.value, env, prog) : null;
        throw new ReturnSignal(v);
    }
    default:
        throw new InterpError(`unhandled stmt type: ${node.type}`, node.line);
    }
}


function toBool(v) {
    if (typeof v === 'number') return v !== 0;
    if (v && typeof v === 'object' && 'buf' in v) return true;  // ptr
    return !!v;
}


function evalExpr(e, env, prog) {
    switch (e.type) {
    case 'num': return e.value;
    case 'str': return e.value;
    case 'ident': {
        const slot = env.lookup(e.name);
        return slot.value;
    }
    case 'paren': return evalExpr(e.value, env, prog);
    case 'unop': {
        if (e.op === '*') {
            const p = evalExpr(e.value, env, prog);
            return readPtr(p);
        }
        if (e.op === '&') {
            // address-of: only for plain idents → returns a pointer
            if (e.value.type !== 'ident') {
                throw new InterpError('& only supported on identifiers');
            }
            const slot = env.lookup(e.value.name);
            // If the value is already a pointer, just return it; otherwise
            // wrap a single-int-cell view (rare).
            if (slot.value && typeof slot.value === 'object' && 'buf' in slot.value) {
                return slot.value;
            }
            const buf = new Int32Array(1); buf[0] = I32(slot.value || 0);
            return { buf, off: 0, isInt32: true };
        }
        if (e.op === '-') return -evalExpr(e.value, env, prog);
        if (e.op === '!') return toBool(evalExpr(e.value, env, prog)) ? 0 : 1;
        if (e.op === '~') return I32(~evalExpr(e.value, env, prog));
        if (e.op === 'pre++' || e.op === 'pre--' ||
            e.op === 'post++' || e.op === 'post--') {
            const delta = (e.op === 'pre++' || e.op === 'post++') ? 1 : -1;
            // target must be ident or index
            if (e.value.type === 'ident') {
                const slot = env.lookup(e.value.name);
                const before = slot.value;
                slot.value = before + delta;
                return e.op.startsWith('pre') ? slot.value : before;
            }
            if (e.value.type === 'index') {
                const p = evalExpr(e.value.target, env, prog);
                const i = evalExpr(e.value.index, env, prog);
                const off = p.off + i;
                const before = p.isInt32 ? p.buf[off] : p.buf[off];
                const after = before + delta;
                if (p.isInt32) p.buf[off] = I32(after); else p.buf[off] = after & 0xFF;
                return e.op.startsWith('pre') ? after : before;
            }
            throw new InterpError(`++/-- target must be lvalue`);
        }
        throw new InterpError(`unhandled unop ${e.op}`);
    }
    case 'binop': return doBinop(e, env, prog);
    case 'index': {
        const p = evalExpr(e.target, env, prog);
        const i = evalExpr(e.index, env, prog);
        if (!p || !('buf' in p)) {
            throw new InterpError(`indexing non-pointer`);
        }
        const off = p.off + i;
        if (off < 0 || off >= p.buf.length) {
            throw new InterpError(
                `array index ${i} out of bounds [0, ${p.buf.length - p.off})`);
        }
        return p.isInt32 ? p.buf[off] : p.buf[off];
    }
    case 'call': {
        if (e.target.type !== 'ident') {
            throw new InterpError('only direct function calls supported');
        }
        const fn = prog.functions.get(e.target.name);
        if (!fn) throw new InterpError(`undefined function: ${e.target.name}`);
        const argv = e.args.map((a) => evalExpr(a, env, prog));
        return callFunction(fn, argv, prog);
    }
    case 'assign': {
        const value = evalExpr(e.value, env, prog);
        const op = e.op;
        const t = e.target;
        const apply = (cur, v) => {
            if (op === '=')  return v;
            if (op === '+=') return cur + v;
            if (op === '-=') return cur - v;
            if (op === '*=') return cur * v;
            if (op === '/=') return I32(cur / v);
            if (op === '%=') return I32(cur % v);
            if (op === '&=') return cur & v;
            if (op === '|=') return cur | v;
            if (op === '^=') return cur ^ v;
            throw new InterpError(`unknown assign ${op}`);
        };
        if (t.type === 'ident') {
            const slot = env.lookup(t.name);
            const next = apply(slot.value, value);
            slot.value = next;
            return next;
        }
        if (t.type === 'index') {
            const p = evalExpr(t.target, env, prog);
            const i = evalExpr(t.index, env, prog);
            const off = p.off + i;
            if (off < 0 || off >= p.buf.length) {
                throw new InterpError(
                    `array index ${i} out of bounds [0, ${p.buf.length - p.off})`);
            }
            const cur = p.isInt32 ? p.buf[off] : p.buf[off];
            const next = apply(cur, value);
            if (p.isInt32) p.buf[off] = I32(next); else p.buf[off] = next & 0xFF;
            return next;
        }
        if (t.type === 'unop' && t.op === '*') {
            const p = evalExpr(t.value, env, prog);
            const cur = readPtr(p);
            const next = apply(cur, value);
            writePtr(p, next);
            return next;
        }
        throw new InterpError(`unsupported assignment target type ${t.type}`);
    }
    default:
        throw new InterpError(`unhandled expr ${e.type}`);
    }
}


function doBinop(e, env, prog) {
    const op = e.op;
    // short-circuit
    if (op === '&&') {
        const L = evalExpr(e.left, env, prog);
        if (!toBool(L)) return 0;
        return toBool(evalExpr(e.right, env, prog)) ? 1 : 0;
    }
    if (op === '||') {
        const L = evalExpr(e.left, env, prog);
        if (toBool(L)) return 1;
        return toBool(evalExpr(e.right, env, prog)) ? 1 : 0;
    }
    const L = evalExpr(e.left, env, prog);
    const R = evalExpr(e.right, env, prog);
    // pointer arithmetic: ptr + int / ptr - int / ptr - ptr
    if (L && typeof L === 'object' && 'buf' in L) {
        if (op === '+') return ptrAdd(L, R | 0);
        if (op === '-') {
            if (R && typeof R === 'object' && 'buf' in R) return L.off - R.off;
            return ptrAdd(L, -(R | 0));
        }
        throw new InterpError(`pointer op ${op} not supported`);
    }
    if (R && typeof R === 'object' && 'buf' in R) {
        if (op === '+') return ptrAdd(R, L | 0);
        throw new InterpError(`int ${op} ptr not supported`);
    }
    switch (op) {
    case '+': return L + R;
    case '-': return L - R;
    case '*': return L * R;
    case '/': return I32(L / R);
    case '%': return I32(L % R);
    case '<': return L < R ? 1 : 0;
    case '>': return L > R ? 1 : 0;
    case '<=': return L <= R ? 1 : 0;
    case '>=': return L >= R ? 1 : 0;
    case '==': return L === R ? 1 : 0;
    case '!=': return L !== R ? 1 : 0;
    case '&':  return L & R;
    case '|':  return L | R;
    case '^':  return L ^ R;
    case '<<': return I32(L << (R & 31));
    case '>>': return L >> (R & 31);
    }
    throw new InterpError(`unhandled binop ${op}`);
}


function callFunction(fn, argv, prog) {
    const env = new Env();
    for (let i = 0; i < fn.params.length; i++) {
        env.declare(fn.params[i].name, argv[i]);
    }
    try {
        evalNode(fn.body, env, prog);
    } catch (e) {
        if (e instanceof ReturnSignal) return e.value;
        throw e;
    }
    return null;
}


export function runFunction(prog, name, argv) {
    const fn = prog.functions.get(name);
    if (!fn) throw new InterpError(`function ${name} not found`);
    return callFunction(fn, argv, prog);
}


// Convenience: build a char* into an existing Uint8Array for slot
// invocation. The interpreter reads/writes the same backing memory
// the caller passed in, so post-call the buffer holds the result.
export function asCharPtr(uint8) { return makeCharPtr(uint8, 0); }
