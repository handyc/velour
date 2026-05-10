/* officemoe.c — Mixture-of-Experts dispatcher with two routing modes.
 *
 * Reads a prompt from stdin (or argv), picks one of four domain
 * specialists, and execve's the matching officesoulflt_* binary
 * with the prompt + any pass-through flags.  Specialist inherits
 * stdin/stdout/stderr — officemoe is a router, not a wrapper.
 *
 * Routing:
 *   Default = best-of-N likelihood.  Forks each specialist in
 *   --score mode, captures their 4-byte IEEE-float scores
 *   (= log P(top1 next token), so higher = more confident on this
 *   prompt), picks the max.  Each forward pass is ~30-100 ms;
 *   four serially is ~0.2 s.
 *
 *   --keyword forces the legacy keyword classifier.
 *   --score-only just prints "name=<f> name=<f> ..." for inspection.
 *
 * Specialists:
 *   chat   — greetings, farewells, identity, locale.
 *   apps   — "what is X" for project apps.
 *   theory — "what is X" for CS concepts.
 *   mood   — "i'm Y" / "my Z" / advice / comfort.
 *
 * Sibling binaries are resolved relative to /proc/self/exe.
 *
 * Build:  cc -Os -nostdlib -fno-builtin -static -o officemoe officemoe.c
 */

typedef long  ssize_t;
typedef unsigned long size_t;
typedef int   pid_t;

static long sys1(long n, long a) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys2(long n, long a, long b) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys4(long n, long a, long b, long c, long d) {
    long r;
    register long r10 __asm__("r10") = d;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10)
                      : "rcx", "r11", "memory");
    return r;
}

#define SYS_read       0
#define SYS_write      1
#define SYS_close      3
#define SYS_pipe2      293
#define SYS_dup2       33
#define SYS_clone      56
#define SYS_execve     59
#define SYS_wait4      61
#define SYS_readlink   89
#define SYS_exit_group 231

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))


/* ── string helpers ────────────────────────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static char tolow(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

static int contains_word(const char *hay, int hlen, const char *needle) {
    int nlen = slen(needle);
    for (int i = 0; i + nlen <= hlen; i++) {
        int eq = 1;
        for (int j = 0; j < nlen; j++) {
            char c = tolow(hay[i + j]);
            if (c != needle[j]) { eq = 0; break; }
        }
        if (!eq) continue;
        char pre  = (i == 0)             ? ' ' : hay[i - 1];
        char post = (i + nlen == hlen)   ? ' ' : hay[i + nlen];
        int pre_alpha  = (pre  >= 'a' && pre  <= 'z')
                      || (pre  >= 'A' && pre  <= 'Z')
                      || (pre  >= '0' && pre  <= '9');
        int post_alpha = (post >= 'a' && post <= 'z')
                      || (post >= 'A' && post <= 'Z')
                      || (post >= '0' && post <= '9');
        if (!pre_alpha && !post_alpha) return 1;
    }
    return 0;
}

static int starts_with(const char *hay, int hlen, const char *prefix) {
    int plen = slen(prefix);
    if (hlen < plen) return 0;
    for (int i = 0; i < plen; i++)
        if (tolow(hay[i]) != prefix[i]) return 0;
    return 1;
}


/* Specialist registry — defined here so route_via_router and
 * classify_keyword can see KINDS / N_KINDS.  Add new specialists
 * at the end. */
#define N_KINDS 6
static const char *KINDS[N_KINDS] = {
    "greet", "farewell", "apps", "fleet", "theory", "mood"
};


/* ── keyword classifier (fallback) ─────────────────────── */
static const char *classify_keyword(const char *prompt, int plen) {
    if (starts_with(prompt, plen, "i'm")
     || starts_with(prompt, plen, "i am")
     || starts_with(prompt, plen, "my ")
     || starts_with(prompt, plen, "i found")
     || starts_with(prompt, plen, "i fixed")
     || starts_with(prompt, plen, "i need")
     || starts_with(prompt, plen, "tell me something")
     || starts_with(prompt, plen, "give me"))
        return "mood";

    static const char *farewell_kw[] = {
        "bye", "goodbye", "thanks", "thank", "love", "later",
        "farewell", "cheers", "peace", 0
    };
    static const char *greet_kw[] = {
        "hi", "hello", "hey", "yo", "morning", "afternoon",
        "howdy", "greetings", "sup", "you", 0
    };
    static const char *fleet_kw[] = {
        "esp", "gary", "mabel", "hazel", "terry", "leiden", "lora",
        "wifi", "uart", "spi", "gpio", "oled", "node", "fleet", 0
    };
    static const char *apps_kw[] = {
        "velour", "office", "supercell", "xpg", "rpg", "hxhnt",
        "lsys", "coder", "tinydb", "soul", "helix", "taxon",
        "forge", "naiad", "chronos", "bodymap", "aether", "fork", 0
    };
    static const char *theory_kw[] = {
        "hex", "ca", "ga", "transformer", "attention", "softmax",
        "rmsnorm", "bpe", "int", "token", "layer", "weight", "bias",
        "gradient", "loss", "entropy", "adam", "relu", "dropout",
        "head", "kernel", "tensor", "epoch", "training", 0
    };

    int hits[6] = {0,0,0,0,0,0};
    for (int i = 0; greet_kw[i]; i++)
        if (contains_word(prompt, plen, greet_kw[i])) { hits[0] = 1; break; }
    for (int i = 0; farewell_kw[i]; i++)
        if (contains_word(prompt, plen, farewell_kw[i])) { hits[1] = 1; break; }
    for (int i = 0; apps_kw[i]; i++)
        if (contains_word(prompt, plen, apps_kw[i])) { hits[2] = 1; break; }
    for (int i = 0; fleet_kw[i]; i++)
        if (contains_word(prompt, plen, fleet_kw[i])) { hits[3] = 1; break; }
    for (int i = 0; theory_kw[i]; i++)
        if (contains_word(prompt, plen, theory_kw[i])) { hits[4] = 1; break; }

    /* Priority: farewell > apps > fleet > theory > greet > mood. */
    if (hits[1]) return "farewell";
    if (hits[2]) return "apps";
    if (hits[3]) return "fleet";
    if (hits[4]) return "theory";
    if (hits[0]) return "greet";
    if (contains_word(prompt, plen, "what")
     || contains_word(prompt, plen, "tell")) return "apps";
    return "greet";
}


/* ── path resolution ───────────────────────────────────── */
static char exe_path[1024];

static int resolve_specialist(const char *kind, char *out, int cap) {
    long n = sys3(SYS_readlink, (long)"/proc/self/exe",
                  (long)exe_path, sizeof exe_path - 1);
    if (n <= 0) return -1;
    exe_path[n] = 0;
    int slash = -1;
    for (int i = 0; i < n; i++) if (exe_path[i] == '/') slash = i;
    if (slash < 0) return -1;
    int dlen = slash + 1;
    static const char prefix[] = "officesoulflt_";
    int pl = (int)sizeof prefix - 1;
    int kl = slen(kind);
    if (dlen + pl + kl + 1 > cap) return -1;
    for (int i = 0; i < dlen; i++) out[i] = exe_path[i];
    for (int i = 0; i < pl;   i++) out[dlen + i] = prefix[i];
    for (int i = 0; i < kl;   i++) out[dlen + pl + i] = kind[i];
    out[dlen + pl + kl] = 0;
    return 0;
}


/* ── invoke one specialist, capturing its stdout ───────── */
/* Forks officesoulflt_<kind> with the given extra-args, reads its
 * stdout into out_buf (cap bytes).  Returns the number of bytes
 * read on success (could be 0), or -1 on failure to spawn.  Used
 * both by score_specialist (to capture the 4-byte float) and by
 * route_via_router (to capture a few text bytes of "apps\n"). */
static int invoke_specialist_capture(const char *kind, const char *prompt,
                                     const char *extra_arg,
                                     char *out_buf, int cap) {
    static char target[1024];
    if (resolve_specialist(kind, target, sizeof target) < 0) return -1;

    int pipefd[2];
    if (sys2(SYS_pipe2, (long)pipefd, 0) < 0) return -1;

    long pid = sys4(SYS_clone, 17 /* SIGCHLD */, 0, 0, 0);
    if (pid < 0) {
        sys1(SYS_close, pipefd[0]);
        sys1(SYS_close, pipefd[1]);
        return -1;
    }
    if (pid == 0) {
        sys1(SYS_close, pipefd[0]);
        sys2(SYS_dup2, pipefd[1], 1);
        sys1(SYS_close, pipefd[1]);
        char *argv2[8];
        int an = 0;
        argv2[an++] = target;
        if (extra_arg) {
            /* extra_arg may be a space-delimited list ("--temp 0 --max 6"). */
            static char tmp[256];
            int tn = 0;
            for (int i = 0; extra_arg[i] && tn < (int)sizeof tmp - 1; i++)
                tmp[tn++] = extra_arg[i];
            tmp[tn] = 0;
            int s = 0;
            for (int i = 0; i <= tn && an < 6; i++) {
                if (tmp[i] == ' ' || tmp[i] == 0) {
                    if (i > s) {
                        tmp[i] = 0;
                        argv2[an++] = tmp + s;
                    }
                    s = i + 1;
                }
            }
        }
        argv2[an++] = (char *)prompt;
        argv2[an]   = 0;
        char *envp[1] = { 0 };
        sys3(SYS_execve, (long)target, (long)argv2, (long)envp);
        sys1(SYS_exit_group, 127);
    }
    sys1(SYS_close, pipefd[1]);
    int got = 0;
    while (got < cap) {
        long n = rd(pipefd[0], out_buf + got, cap - got);
        if (n <= 0) break;
        got += (int)n;
    }
    sys1(SYS_close, pipefd[0]);
    int status = 0;
    sys4(SYS_wait4, pid, (long)&status, 0, 0);
    return got;
}


static int score_specialist(const char *kind, const char *prompt,
                            float *out_score) {
    char buf[8];
    int got = invoke_specialist_capture(kind, prompt, "--score",
                                        buf, sizeof buf);
    if (got != 4) return 0;
    /* IEEE little-endian on x86_64 — copy the 4 bytes as a float. */
    union { char b[4]; float f; } u;
    for (int i = 0; i < 4; i++) u.b[i] = buf[i];
    *out_score = u.f;
    return 1;
}


/* ── route via router-soul ─────────────────────────────── */
/* Forks officesoulflt_router with greedy decoding (--temp 0 --max 6),
 * captures its text output, finds the first occurrence of one of the
 * four kind names.  Returns the kind on success or 0 if no kind name
 * appeared in the output (caller falls back).  One forward pass —
 * ~25-100 ms vs 4× that for best-of-N. */
static const char *route_via_router(const char *prompt) {
    char buf[64];
    int got = invoke_specialist_capture("router", prompt,
                                        "--temp 0 --max 8",
                                        buf, sizeof buf - 1);
    if (got <= 0) return 0;
    buf[got] = 0;
    /* Find first occurrence of any kind name in buf. */
    int best_pos = 9999;
    const char *best = 0;
    for (int k = 0; k < N_KINDS; k++) {
        int kl = slen(KINDS[k]);
        for (int i = 0; i + kl <= got; i++) {
            int eq = 1;
            for (int j = 0; j < kl; j++)
                if (buf[i + j] != KINDS[k][j]) { eq = 0; break; }
            if (eq && i < best_pos) {
                best_pos = i;
                best = KINDS[k];
                break;
            }
        }
    }
    return best;
}


/* ── float printer for verbose / --score-only ─────────── */
static int int_to_str(int x, char *out) {
    char tmp[16]; int tn = 0;
    int neg = (x < 0);
    unsigned int u = neg ? (unsigned int)-x : (unsigned int)x;
    if (u == 0) tmp[tn++] = '0';
    while (u) { tmp[tn++] = '0' + (u % 10); u /= 10; }
    int n = 0;
    if (neg) out[n++] = '-';
    while (tn > 0) out[n++] = tmp[--tn];
    return n;
}
static int float_fmt(float f, char *out) {
    /* fixed-point 4 decimals, range ~ [-99, 0]. */
    int n = 0;
    if (f != f) { for (const char *s = "nan"; *s; ) out[n++] = *s++; return n; }
    if (f < 0) { out[n++] = '-'; f = -f; }
    int whole = (int)f;
    float frac = f - (float)whole;
    n += int_to_str(whole, out + n);
    out[n++] = '.';
    int frac_int = (int)(frac * 10000.0f + 0.5f);
    /* zero-pad */
    char fbuf[8]; int fn = 0;
    if (frac_int == 0) fbuf[fn++] = '0';
    else { int t = frac_int; while (t) { fbuf[fn++] = '0' + (t % 10); t /= 10; } }
    while (fn < 4) fbuf[fn++] = '0';
    while (fn > 0) out[n++] = fbuf[--fn];
    return n;
}


/* ── hex CA-based routing (experimental, --ca-route) ────────
 * 8x8 toroidal hex grid (pointy-top, odd rows shifted), K=4 colors.
 * State persists across invocations via /tmp/officemoe_ca_state.bin.
 * Per query:
 *   1. Load grid + step count.  Initialise on first run.
 *   2. Step CA once with a hardcoded weighted-vote rule.
 *   3. Count cells of each color.  Dominant color picks the
 *      specialist GROUP; step parity picks within the group when
 *      a group has 2 specialists.
 *   4. Save state.
 *
 * Specialist groups (1+2+2+1 = 6):
 *   color 0 → greet
 *   color 1 → farewell (even step) | mood (odd step)
 *   color 2 → apps     (even step) | fleet (odd step)
 *   color 3 → theory
 *
 * Routing is *prompt-independent* by design — the CA holds session
 * state, so two queries asked at different times in the same session
 * route differently even if the prompt is identical.  This is the
 * stateful-conversation framing the user picked over per-prompt
 * routing.
 *
 * V1 uses a hardcoded weighted-vote rule.  The GA-evolution work
 * (search rule space for "good" routing on a held-out conversation)
 * is queued and not in this commit.
 */

#define CA_W 8
#define CA_H 8
#define CA_N (CA_W * CA_H)
#define CA_STATE_FILE "/tmp/officemoe_ca_state.bin"

#ifndef SYS_open
#define SYS_open  2
#endif
#ifndef O_RDONLY
#define O_RDONLY 0
#endif
#ifndef O_WRONLY
#define O_WRONLY 1
#endif
#ifndef O_CREAT
#define O_CREAT  64
#endif
#ifndef O_TRUNC
#define O_TRUNC  512
#endif

#define op(p, fl, m)  sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)         sys1(SYS_close, (long)(f))

static unsigned char ca_grid[CA_N];
static unsigned int ca_step_count;
static int ca_neighbors_xy[CA_N][6][2];
static int ca_neighbors_inited;

/* Hardcoded asymmetric rule.  For each (self, n0, n1, n2, n3) where
 * ni = neighbor count of color i (sum=6), the next color is a hash
 * of those plus self.  Picked deliberately asymmetric so cells don't
 * synchronize into a period-4 limit cycle.  GA-evolved successors
 * will replace this with a real Class-4 rule. */
static unsigned char ca_rule_apply(int self_c, int n0, int n1,
                                   int n2, int n3) {
    /* V1: pure deterministic hash of (self, n0..n3).  Won't freeze,
     * not Class-4 either — just varied so all 4 colors keep showing
     * up in the count distribution.  GA-evolved replacements queued. */
    unsigned int h = (unsigned int)self_c * 0x9E3779B9u
                   + (unsigned int)n0     * 0x85EBCA6Bu
                   + (unsigned int)n1     * 0xC2B2AE35u
                   + (unsigned int)n2     * 0x27D4EB2Fu
                   + (unsigned int)n3     * 0x165667B1u;
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return (unsigned char)(h & 3);
}

static void ca_init_neighbors(void) {
    if (ca_neighbors_inited) return;
    for (int y = 0; y < CA_H; y++) {
        for (int x = 0; x < CA_W; x++) {
            int idx = y * CA_W + x;
            int odd = y & 1;
            ca_neighbors_xy[idx][0][0] = (x - 1 + CA_W) % CA_W;
            ca_neighbors_xy[idx][0][1] = y;
            ca_neighbors_xy[idx][1][0] = (x + 1) % CA_W;
            ca_neighbors_xy[idx][1][1] = y;
            int nw_x = odd ? x : (x - 1 + CA_W) % CA_W;
            int ne_x = odd ? (x + 1) % CA_W : x;
            ca_neighbors_xy[idx][2][0] = nw_x;
            ca_neighbors_xy[idx][2][1] = (y - 1 + CA_H) % CA_H;
            ca_neighbors_xy[idx][3][0] = ne_x;
            ca_neighbors_xy[idx][3][1] = (y - 1 + CA_H) % CA_H;
            ca_neighbors_xy[idx][4][0] = nw_x;
            ca_neighbors_xy[idx][4][1] = (y + 1) % CA_H;
            ca_neighbors_xy[idx][5][0] = ne_x;
            ca_neighbors_xy[idx][5][1] = (y + 1) % CA_H;
        }
    }
    ca_neighbors_inited = 1;
}

static void ca_init_default(void) {
    /* Pseudo-random seed (hash per cell index) so initial pattern
     * doesn't have block-synchronisation symmetries that make the
     * rule degenerate to a uniform period-4 cycle. */
    for (int i = 0; i < CA_N; i++) {
        unsigned int h = (unsigned int)i * 0x9E3779B9u;
        h ^= h >> 13;
        ca_grid[i] = (unsigned char)((h >> 28) & 3);
    }
    ca_step_count = 0;
}

static int ca_load(void) {
    int fd = (int)op(CA_STATE_FILE, O_RDONLY, 0);
    if (fd < 0) {
        ca_init_default();
        return 0;
    }
    long n = rd(fd, ca_grid, CA_N);
    if (n != CA_N) { cl(fd); ca_init_default(); return 0; }
    rd(fd, &ca_step_count, 4);
    cl(fd);
    return 0;
}

static void ca_save(void) {
    int fd = (int)op(CA_STATE_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    wr(fd, ca_grid, CA_N);
    wr(fd, &ca_step_count, 4);
    cl(fd);
}

static void ca_step(void) {
    static unsigned char shadow[CA_N];
    for (int y = 0; y < CA_H; y++) {
        for (int x = 0; x < CA_W; x++) {
            int idx = y * CA_W + x;
            int self_c = ca_grid[idx];
            int counts[4] = { 0, 0, 0, 0 };
            for (int k = 0; k < 6; k++) {
                int nx = ca_neighbors_xy[idx][k][0];
                int ny = ca_neighbors_xy[idx][k][1];
                int nc = ca_grid[ny * CA_W + nx];
                counts[nc]++;
            }
            shadow[idx] = ca_rule_apply(self_c, counts[0], counts[1],
                                        counts[2], counts[3]);
        }
    }
    for (int i = 0; i < CA_N; i++) ca_grid[i] = shadow[i];
    ca_step_count++;
}

static const char *route_via_ca(int verbose) {
    ca_init_neighbors();
    ca_load();
    ca_step();
    int counts[4] = { 0, 0, 0, 0 };
    for (int i = 0; i < CA_N; i++) counts[ca_grid[i]]++;
    int dom = 0; int dom_v = counts[0];
    for (int t = 1; t < 4; t++)
        if (counts[t] > dom_v) { dom_v = counts[t]; dom = t; }
    int parity = ca_step_count & 1;
    const char *kind;
    switch (dom) {
        case 0:  kind = "greet"; break;
        case 1:  kind = parity ? "mood"  : "farewell"; break;
        case 2:  kind = parity ? "fleet" : "apps";     break;
        case 3:  kind = "theory"; break;
        default: kind = "greet";
    }
    if (verbose) {
        wr(2, "[ca step=", 9);
        char nb[16]; int nl = 0;
        unsigned int v = ca_step_count;
        if (v == 0) nb[nl++] = '0';
        else { while (v) { nb[nl++] = '0' + (v % 10); v /= 10; } }
        for (int i = nl; i > 0; i--) wr(2, &nb[i - 1], 1);
        wr(2, " counts=", 8);
        for (int i = 0; i < 4; i++) {
            char d[4]; int dn = 0;
            int c = counts[i];
            if (c == 0) d[dn++] = '0';
            else { while (c) { d[dn++] = '0' + (c % 10); c /= 10; } }
            for (int j = dn; j > 0; j--) wr(2, &d[j - 1], 1);
            if (i < 3) wr(2, ",", 1);
        }
        wr(2, "] ", 2);
    }
    ca_save();
    return kind;
}


/* ── main ──────────────────────────────────────────────── */
static char prompt_buf[4096];

int main_c(int argc, char **argv) {
    int plen = 0;
    int verbose = 0;
    int use_keyword = 0;
    int use_bofN = 0;
    int use_ca = 0;
    int score_only = 0;
    int is_prompt_arg[64];
    for (int i = 0; i < 64; i++) is_prompt_arg[i] = 0;
    int n_args = argc < 64 ? argc : 64;

    for (int i = 1; i < n_args; i++) {
        const char *a = argv[i];
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) {
            verbose = 1; continue;
        }
        if (scmp(a, "--keyword") == 0) {
            use_keyword = 1; continue;
        }
        if (scmp(a, "--bofN") == 0 || scmp(a, "--bestofn") == 0) {
            use_bofN = 1; continue;
        }
        if (scmp(a, "--ca-route") == 0 || scmp(a, "--ca") == 0) {
            use_ca = 1; continue;
        }
        if (scmp(a, "--score-only") == 0) {
            score_only = 1; continue;
        }
        if (scmp(a, "--help") == 0 || scmp(a, "-h") == 0) {
            static const char H[] =
                "officemoe — router-soul dispatcher (default)\n"
                "  echo PROMPT | ./officemoe [--verbose] [--temp Q] [--max N]\n"
                "  ./officemoe [--verbose] PROMPT...\n"
                "Modes:\n"
                "  (default)      router-soul: 1 forward pass picks specialist\n"
                "  --bofN         best-of-N: each specialist scores prompt, max wins\n"
                "  --keyword      legacy keyword router\n"
                "  --ca-route     hex CA holds session state, dominant color picks group\n"
                "  --score-only   print specialist=<f> table (forces --bofN)\n"
                "Specialists: greet | farewell | apps | fleet | theory | mood\n";
            wr(1, H, sizeof H - 1);
            return 0;
        }
        if (scmp(a, "--") == 0) break;
        if (scmp(a, "--temp") == 0 || scmp(a, "--max") == 0
         || scmp(a, "--seed") == 0) { i++; continue; }
        if (a[0] == '-') continue;
        is_prompt_arg[i] = 1;
    }

    int any_prompt_arg = 0;
    for (int i = 1; i < n_args; i++) if (is_prompt_arg[i]) any_prompt_arg = 1;

    if (any_prompt_arg) {
        for (int i = 1; i < n_args; i++) {
            if (!is_prompt_arg[i]) continue;
            int n = slen(argv[i]);
            if (plen + n + 2 >= (int)sizeof prompt_buf) break;
            if (plen > 0) prompt_buf[plen++] = ' ';
            for (int j = 0; j < n; j++) prompt_buf[plen++] = argv[i][j];
        }
    } else {
        long n;
        while (plen < (int)sizeof prompt_buf - 1
            && (n = rd(0, prompt_buf + plen,
                       sizeof prompt_buf - 1 - plen)) > 0) {
            plen += (int)n;
        }
        while (plen > 0 && (prompt_buf[plen - 1] == '\n'
                         || prompt_buf[plen - 1] == '\r')) plen--;
    }
    prompt_buf[plen] = 0;

    /* Pick the kind. */
    const char *kind = 0;
    float scores[N_KINDS];
    int got_score[N_KINDS];
    for (int i = 0; i < N_KINDS; i++) { scores[i] = 0; got_score[i] = 0; }
    int actually_bofN = use_bofN || score_only;
    if (use_ca) {
        kind = route_via_ca(verbose);
    } else if (use_keyword) {
        kind = classify_keyword(prompt_buf, plen);
    } else if (actually_bofN) {
        float best = -1e30f;
        int best_i = 0;
        for (int i = 0; i < N_KINDS; i++) {
            float s;
            if (score_specialist(KINDS[i], prompt_buf, &s)) {
                scores[i] = s; got_score[i] = 1;
                if (s > best) { best = s; best_i = i; }
            } else {
                scores[i] = -1e30f;
            }
        }
        kind = KINDS[best_i];

        if (score_only) {
            char line[512]; int ln = 0;
            for (int i = 0; i < N_KINDS; i++) {
                int kl = slen(KINDS[i]);
                for (int j = 0; j < kl; j++) line[ln++] = KINDS[i][j];
                line[ln++] = '=';
                if (got_score[i]) ln += float_fmt(scores[i], line + ln);
                else { line[ln++] = 'N'; line[ln++] = 'A'; }
                line[ln++] = (i == N_KINDS - 1) ? '\n' : ' ';
            }
            wr(1, line, ln);
            return 0;
        }
    } else {
        /* Default: router-soul. */
        kind = route_via_router(prompt_buf);
        if (kind == 0) {
            /* Router-soul didn't emit a kind name; fall back to keyword. */
            kind = classify_keyword(prompt_buf, plen);
        }
    }

    if (verbose) {
        wr(2, "[moe->", 6);
        wr(2, kind, slen(kind));
        if (actually_bofN) {
            wr(2, " ", 1);
            char line[512]; int ln = 0;
            for (int i = 0; i < N_KINDS; i++) {
                int kl = slen(KINDS[i]);
                for (int j = 0; j < kl; j++) line[ln++] = KINDS[i][j];
                line[ln++] = '=';
                if (got_score[i]) ln += float_fmt(scores[i], line + ln);
                else { line[ln++] = 'N'; line[ln++] = 'A'; }
                if (i < N_KINDS - 1) line[ln++] = ' ';
            }
            wr(2, line, ln);
        }
        wr(2, "] ", 2);
        wr(2, prompt_buf, plen);
        wr(2, "\n", 1);
    }

    static char target[1024];
    if (resolve_specialist(kind, target, sizeof target) < 0) {
        static const char err[] = "officemoe: cannot resolve specialist path\n";
        wr(2, err, sizeof err - 1);
        return 1;
    }

    char *new_argv[32];
    int na = 0;
    new_argv[na++] = target;
    new_argv[na++] = prompt_buf;
    for (int i = 1; i < n_args && na < 30; i++) {
        const char *a = argv[i];
        if (is_prompt_arg[i]) continue;
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) continue;
        if (scmp(a, "--keyword") == 0) continue;
        if (scmp(a, "--bofN") == 0 || scmp(a, "--bestofn") == 0) continue;
        if (scmp(a, "--ca-route") == 0 || scmp(a, "--ca") == 0) continue;
        if (scmp(a, "--score-only") == 0) continue;
        if (scmp(a, "--") == 0) continue;
        new_argv[na++] = argv[i];
    }
    new_argv[na] = 0;

    char *envp[1] = { 0 };
    sys3(SYS_execve, (long)target, (long)new_argv, (long)envp);
    static const char err2[] = "officemoe: execve failed\n";
    wr(2, err2, sizeof err2 - 1);
    return 127;
}


__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
