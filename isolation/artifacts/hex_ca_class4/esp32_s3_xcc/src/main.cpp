// Hex-CA on-board full pipeline + xcc700 hot-load — ESP32-S3 SuperMini.
//
// Fork of esp32_s3_full/ that adds WiFi + HTTP + ELF upload so that
// arbitrary C compiled by Velour's /s3lab/compile/ can land on the
// board over WiFi. Phase 2 of the compile-on-device arc.
//
// What's NEW vs. esp32_s3_full/:
//   - WiFi STA from /wifi.txt (line 1 ssid, line 2 password)
//   - "hexca-setup" AP fallback when no creds are present
//   - mDNS responder at hexca.local
//   - HTTP server on :80 — GET / status, POST /wifi, POST /load-elf,
//     POST /run-elf
//
// What does NOT change:
//   - The CA hunt + run loop is byte-identical to esp32_s3_full/.
//   - WiFi runs alongside; if unreachable, CA still runs.
//
// Phase 3 (planned): /run-elf actually executes the uploaded code by
// patching a fixed function-pointer table (step_grid, fitness, etc.).
//
// Pin map (ESP32-S3 SuperMini):
//   TFT (matches esp_st7735s/): SCK=12 MOSI=11 DC=4 CS=5 RST=6 BL=7
//   Default GPIO outputs:       1, 2, 3, 8 (avoid TFT/USB/BOOT)
//   Edit /gpio_map.txt to change which cells drive which pins.

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// ── CA constants ──────────────────────────────────────────────────────
#define K            4
#define NSIT         16384
#define GBYTES       4096
#define PAL_BYTES    4
#define MAGIC_BYTES  4
#define TAIL_MAGIC   "HXC4"
#define TAIL_BYTES   (MAGIC_BYTES + PAL_BYTES + GBYTES)

#define GRID_W       16
#define GRID_H       16
#define HORIZON      25

// GA params (match hunter.c)
#define POP          30
#define GENS         40

// Runtime params
#define TICK_MS            300        // 3 Hz default
#define MAX_BINDINGS       64
#define MAX_INPUT_BINDINGS 32

// ── TFT pin map / geometry ────────────────────────────────────────────
#define PIN_SCK      12
#define PIN_MOSI     11
#define PIN_DC        4
#define PIN_CS        5
#define PIN_RST       6
#define PIN_BL        7
#define SPI_HZ       27000000UL

#define CELL          4         // 16*4 = 64 logical px (was 14*5 = 70)
#define XPAD         46         // centres the 64-wide grid in the 160-wide panel
#define YPAD          7         // centres the 64-tall grid in the 80-tall panel

typedef uint8_t u8;

struct GpioBinding {
    int  cell_x;
    int  cell_y;
    int  gpio_pin;
    u8   state_mask;     // bit N set ⇒ pin HIGH when cell value == N
};

// Input binding — pin drives cell. Pin uses INPUT_PULLUP, so a button
// shorting to GND reads LOW. When pin is LOW, cell is forced to
// low_state; HIGH ⇒ high_state. Per-tick order: read inputs ⇒ clamp
// cells in cur grid ⇒ step CA ⇒ apply outputs ⇒ render.
struct InputBinding {
    int gpio_pin;
    int cell_x;
    int cell_y;
    u8  low_state;
    u8  high_state;
};

// ── BSS arenas ────────────────────────────────────────────────────────
//
// Peak memory is during the hunt. After hunt completes, pool/pals/fit/
// tmp_* sit unused. They live in BSS so they're "free" once allocated.

static u8     pool[POP][GBYTES];
static u8     pals[POP][PAL_BYTES];
static double fit[POP];

static u8 seed_genome[GBYTES];
static u8 seed_pal[PAL_BYTES];

static u8 genome[GBYTES];        // winner / runtime
static u8 palette[PAL_BYTES];

static u8 grid_a[GRID_W * GRID_H];
static u8 grid_b[GRID_W * GRID_H];

static u8 tmp_genome[GBYTES];
static u8 tmp_pal[PAL_BYTES];

static GpioBinding  bindings[MAX_BINDINGS];
static int          n_bindings = 0;
static InputBinding input_bindings[MAX_INPUT_BINDINGS];
static int          n_input_bindings = 0;

// Hex offset deltas
static const int DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6] = {  0,  1, -1,  1, -1,  0 };
static const int DXO[6] = { -1,  0, -1,  1,  0,  1 };

static double last_activity_tail = 0.0;

static Adafruit_ST7735 tft(PIN_CS, PIN_DC, PIN_MOSI, PIN_SCK, PIN_RST);
static uint16_t pal_rgb565[PAL_BYTES];

// ── PRNG (xorshift32 — fast, deterministic) + grid LCG ───────────────

static uint32_t prng_state = 0x9E3779B9u;
static inline uint32_t prng() {
    uint32_t x = prng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return prng_state = x;
}
static inline double prng_unit() {
    return (double)prng() / (double)UINT32_MAX;
}

static uint32_t lcg_state;
static inline uint32_t lcg() {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}

// ── Engine ────────────────────────────────────────────────────────────

static inline int g_get(const u8 *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static inline void g_set(u8 *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}
static inline int sit_idx(int s, const int *n) {
    int i = s;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

static void seed_grid(u8 *g, uint32_t s) {
    lcg_state = s ? s : 1;
    for (int i = 0; i < GRID_W * GRID_H; i++)
        g[i] = lcg() & 3;
}

static void step_grid(const u8 *g, const u8 *in, u8 *out) {
    for (int y = 0; y < GRID_H; y++) {
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < GRID_W; x++) {
            int self = in[y * GRID_W + x];
            int n[6];
            for (int k = 0; k < 6; k++) {
                int yy = y + DY[k];
                int xx = x + dx[k];
                n[k] = (yy >= 0 && yy < GRID_H
                     && xx >= 0 && xx < GRID_W) ? in[yy * GRID_W + xx] : 0;
            }
            out[y * GRID_W + x] = g_get(g, sit_idx(self, n));
        }
    }
}

static double fitness(const u8 *gnm, uint32_t grid_seed) {
    seed_grid(grid_a, grid_seed);
    double act[HORIZON];
    int colour_counts_final[K] = {0};
    for (int t = 0; t < HORIZON; t++) {
        step_grid(gnm, grid_a, grid_b);
        int changed = 0;
        for (int i = 0; i < GRID_W * GRID_H; i++)
            if (grid_a[i] != grid_b[i]) changed++;
        act[t] = (double)changed / (GRID_W * GRID_H);
        memcpy(grid_a, grid_b, GRID_W * GRID_H);
    }
    int uniform = 1;
    for (int i = 1; i < GRID_W * GRID_H; i++)
        if (grid_a[i] != grid_a[0]) { uniform = 0; break; }
    for (int i = 0; i < GRID_W * GRID_H; i++)
        colour_counts_final[grid_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts_final[c] * 100 >= GRID_W * GRID_H) diversity++;
    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    last_activity_tail = avg;
    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;
    else             activity_reward = (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}

// ── GA helpers (match hunter.c) ───────────────────────────────────────

static void identity_genome(u8 *g) {
    memset(g + 0 * 1024, 0x00, 1024);
    memset(g + 1 * 1024, 0x55, 1024);
    memset(g + 2 * 1024, 0xAA, 1024);
    memset(g + 3 * 1024, 0xFF, 1024);
}

static void invent_palette(u8 *pal) {
    for (int i = 0; i < K; ) {
        int c = ((prng() % 10) < 9)
              ? (16  + (int)(prng() % 216))
              : (232 + (int)(prng() % 24));
        int ok = 1;
        for (int j = 0; j < i; j++) if (pal[j] == c) { ok = 0; break; }
        if (ok) pal[i++] = (u8)c;
    }
}

static void mutate(u8 *dst, const u8 *src, double rate) {
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++) {
        if (prng_unit() < rate)
            g_set(dst, i, prng() & 3);
    }
}

static void cross(u8 *dst, const u8 *a, const u8 *b) {
    int cut = 1 + (int)(prng() % (GBYTES - 1));
    memcpy(dst, a, cut);
    memcpy(dst + cut, b + cut, GBYTES - cut);
}

static void palette_inherit(u8 *dst, const u8 *a, const u8 *b) {
    const u8 *src = (prng() & 1) ? a : b;
    memcpy(dst, src, PAL_BYTES);
    if ((prng() % 100) < 8) {
        int slot = prng() % K;
        int c = ((prng() % 10) < 9)
              ? (16  + (int)(prng() % 216))
              : (232 + (int)(prng() % 24));
        dst[slot] = (u8)c;
    }
}

static void sort_pop() {
    for (int i = 1; i < POP; i++) {
        double fv = fit[i];
        memcpy(tmp_genome, pool[i], GBYTES);
        memcpy(tmp_pal,    pals[i], PAL_BYTES);
        int j = i - 1;
        while (j >= 0 && fit[j] < fv) {
            fit[j + 1] = fit[j];
            memcpy(pool[j + 1], pool[j], GBYTES);
            memcpy(pals[j + 1], pals[j], PAL_BYTES);
            j--;
        }
        fit[j + 1] = fv;
        memcpy(pool[j + 1], tmp_genome, GBYTES);
        memcpy(pals[j + 1], tmp_pal,    PAL_BYTES);
    }
}

// ── ANSI 256 → RGB565 (matches the ANSI palette indices the hunter
//                       evolves) ────────────────────────────────────

static uint16_t ansi256_to_rgb565(uint8_t idx) {
    uint8_t r, g, b;
    if (idx < 16) {
        static const uint8_t std[16][3] = {
            {0,0,0},{128,0,0},{0,128,0},{128,128,0},
            {0,0,128},{128,0,128},{0,128,128},{192,192,192},
            {128,128,128},{255,0,0},{0,255,0},{255,255,0},
            {0,0,255},{255,0,255},{0,255,255},{255,255,255},
        };
        r = std[idx][0]; g = std[idx][1]; b = std[idx][2];
    } else if (idx < 232) {
        int i = idx - 16;
        int rr = i / 36, gg = (i % 36) / 6, bb = i % 6;
        static const uint8_t lvl[6] = {0, 95, 135, 175, 215, 255};
        r = lvl[rr]; g = lvl[gg]; b = lvl[bb];
    } else {
        int v = 8 + (idx - 232) * 10;
        if (v > 255) v = 255;
        r = g = b = (uint8_t)v;
    }
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}

static void rebuild_palette_rgb() {
    for (int i = 0; i < K; i++)
        pal_rgb565[i] = ansi256_to_rgb565(palette[i]);
}

// ── TFT rendering ─────────────────────────────────────────────────────

static inline void draw_cell(int x, int y, u8 c) {
    int px = XPAD + x * CELL + ((y & 1) ? (CELL / 2) : 0);
    int py = YPAD + y * CELL;
    tft.fillRect(px, py, CELL, CELL, pal_rgb565[c]);
}

static void render_full(const u8 *g) {
    for (int y = 0; y < GRID_H; y++)
        for (int x = 0; x < GRID_W; x++)
            draw_cell(x, y, g[y * GRID_W + x]);
}

static void render_diff(const u8 *prev, const u8 *cur) {
    for (int y = 0; y < GRID_H; y++)
        for (int x = 0; x < GRID_W; x++)
            if (prev[y * GRID_W + x] != cur[y * GRID_W + x])
                draw_cell(x, y, cur[y * GRID_W + x]);
}

// Hunt-phase TFT: text status + bottom progress bar
static void hunt_status_paint(int gen, int total, double best, double mean) {
    tft.fillRect(0, 0, 160, 26, ST77XX_BLACK);
    tft.setTextColor(ST77XX_WHITE, ST77XX_BLACK);
    tft.setTextSize(1);
    tft.setCursor(2, 2);
    tft.print("HUNTING");
    tft.setCursor(2, 14);
    tft.printf("gen %d/%d", gen, total);
    tft.setCursor(80, 2);
    tft.printf("best %.2f", best);
    tft.setCursor(80, 14);
    tft.printf("mean %.2f", mean);

    int bar_y = 70, bar_h = 6;
    int w = (160 * gen) / total;
    if (w > 160) w = 160;
    uint16_t c = (best > 4.0) ? ST77XX_GREEN
              : (best > 3.0) ? ST77XX_YELLOW
              :                ST77XX_RED;
    tft.fillRect(0, bar_y, 160, bar_h, ST77XX_BLACK);
    tft.fillRect(0, bar_y, w,   bar_h, c);
}

// ── GPIO bindings parser ──────────────────────────────────────────────

static int parse_int_or_hex(const char *s) {
    while (*s == ' ' || *s == '\t') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        int v = 0;
        for (s += 2; *s; s++) {
            int d;
            if      (*s >= '0' && *s <= '9') d = *s - '0';
            else if (*s >= 'a' && *s <= 'f') d = 10 + *s - 'a';
            else if (*s >= 'A' && *s <= 'F') d = 10 + *s - 'A';
            else return -1;
            v = v * 16 + d;
        }
        return v;
    }
    return atoi(s);
}

static int parse_binding(const char *line, GpioBinding *out) {
    char buf[64];
    strncpy(buf, line, sizeof buf - 1);
    buf[sizeof buf - 1] = 0;
    char *fields[4] = {0};
    int   nf = 0;
    fields[nf++] = buf;
    for (char *p = buf; *p && nf < 4; p++) {
        if (*p == ',') {
            *p = 0;
            fields[nf++] = p + 1;
        }
    }
    if (nf != 4) return -1;
    out->cell_x   = atoi(fields[0]);
    out->cell_y   = atoi(fields[1]);
    out->gpio_pin = atoi(fields[2]);
    int mask      = parse_int_or_hex(fields[3]);
    if (mask < 0 || mask > 0xF) return -1;
    if (out->cell_x < 0 || out->cell_x >= GRID_W) return -1;
    if (out->cell_y < 0 || out->cell_y >= GRID_H) return -1;
    if (out->gpio_pin < 0 || out->gpio_pin > 48)  return -1;
    out->state_mask = (u8)mask;
    return 0;
}

// Parse one input binding line: "input,gpio_pin,cell_x,cell_y,low_state,high_state"
static int parse_input_binding(const char *line, InputBinding *out) {
    char buf[64];
    strncpy(buf, line + 6, sizeof buf - 1);   // skip "input,"
    buf[sizeof buf - 1] = 0;
    char *fields[5] = {0};
    int   nf = 0;
    fields[nf++] = buf;
    for (char *p = buf; *p && nf < 5; p++) {
        if (*p == ',') {
            *p = 0;
            fields[nf++] = p + 1;
        }
    }
    if (nf != 5) return -1;
    out->gpio_pin = atoi(fields[0]);
    out->cell_x   = atoi(fields[1]);
    out->cell_y   = atoi(fields[2]);
    int lo        = atoi(fields[3]);
    int hi        = atoi(fields[4]);
    if (lo < 0 || lo >= K) return -1;
    if (hi < 0 || hi >= K) return -1;
    if (out->cell_x < 0 || out->cell_x >= GRID_W) return -1;
    if (out->cell_y < 0 || out->cell_y >= GRID_H) return -1;
    if (out->gpio_pin < 0 || out->gpio_pin > 48)  return -1;
    out->low_state  = (u8)lo;
    out->high_state = (u8)hi;
    return 0;
}

static void load_bindings_from_fs() {
    n_bindings = 0;
    n_input_bindings = 0;
    File f = LittleFS.open("/gpio_map.txt", "r");
    if (!f) return;
    char line[128];
    int  li = 0;
    while (f.available()) {
        char c = f.read();
        bool eol = (c == '\n' || c == '\r');
        if (!eol && li < (int)sizeof line - 1) {
            line[li++] = c;
            continue;
        }
        if (eol && li == 0) continue;
        line[li] = 0; li = 0;
        char *t = line;
        while (*t == ' ' || *t == '\t') t++;
        if (*t == 0 || *t == '#') continue;

        if (strncmp(t, "input,", 6) == 0) {
            if (n_input_bindings >= MAX_INPUT_BINDINGS) {
                Serial.printf("  warn: max %d input bindings; skipping rest\n",
                              MAX_INPUT_BINDINGS);
                continue;
            }
            InputBinding b;
            if (parse_input_binding(t, &b) == 0) {
                input_bindings[n_input_bindings++] = b;
            } else {
                Serial.printf("  warn: bad input binding: %s\n", t);
            }
            continue;
        }

        if (n_bindings >= MAX_BINDINGS) {
            Serial.printf("  warn: max %d bindings; skipping rest\n",
                          MAX_BINDINGS);
            continue;
        }
        GpioBinding b;
        if (parse_binding(t, &b) == 0) {
            bindings[n_bindings++] = b;
        } else {
            Serial.printf("  warn: bad binding: %s\n", t);
        }
    }
    f.close();
}

static void write_default_gpio_map() {
    File f = LittleFS.open("/gpio_map.txt", "w");
    if (!f) return;
    f.print(
        "# CA cell <-> GPIO bindings (combined sketch).\n"
        "#\n"
        "# Output (cell drives pin):\n"
        "#   cell_x,cell_y,gpio_pin,state_mask\n"
        "# state_mask is 4-bit; bit N set => pin HIGH when cell == N.\n"
        "#\n"
        "# Input (pin drives cell):\n"
        "#   input,gpio_pin,cell_x,cell_y,low_state,high_state\n"
        "# Pin uses INPUT_PULLUP (button to GND reads LOW). Per-tick:\n"
        "# read inputs -> step CA -> drive outputs -> render.\n"
        "#\n"
        "# Avoid: GPIO 4-7 + 11-12 (TFT), 19-20 (USB), 0 (BOOT).\n"
        "# Safe defaults on the SuperMini: 1, 2, 3, 8, 9, 10, 13, 14, 21.\n"
        "3,5,1,0x8\n"
        "4,5,2,0x8\n"
        "5,5,3,0x8\n"
        "6,5,8,0x8\n"
        "#\n"
        "# Demo inputs (commented out): two buttons clamping corner cells.\n"
        "# input,9,0,0,0,3\n"
        "# input,10,13,13,0,3\n"
    );
    f.close();
}

static inline int level_for(const GpioBinding &b, int v) {
    return (b.state_mask >> v) & 1;
}

static void apply_bindings(const u8 *g) {
    for (int i = 0; i < n_bindings; i++) {
        const GpioBinding &b = bindings[i];
        int v = g[b.cell_y * GRID_W + b.cell_x];
        digitalWrite(b.gpio_pin, level_for(b, v));
    }
}

static void apply_input_bindings(u8 *g) {
    for (int i = 0; i < n_input_bindings; i++) {
        const InputBinding &b = input_bindings[i];
        int high = digitalRead(b.gpio_pin);
        g[b.cell_y * GRID_W + b.cell_x] = high ? b.high_state : b.low_state;
    }
}

// ── Persistence ───────────────────────────────────────────────────────

static int write_winner_to_fs(const u8 *pal, const u8 *gnm) {
    File f = LittleFS.open("/winner.bin", "w");
    if (!f) return -1;
    f.write((const u8 *)TAIL_MAGIC, MAGIC_BYTES);
    f.write(pal, PAL_BYTES);
    f.write(gnm, GBYTES);
    f.close();
    return 0;
}

// ── Hunt phase ────────────────────────────────────────────────────────

static void run_hunt(uint32_t grid_seed) {
    Serial.println("=== HUNT phase ===");

    // Bootstrap: random palette + identity genome
    invent_palette(seed_pal);
    identity_genome(seed_genome);

    // Initial population
    memcpy(pool[0], seed_genome, GBYTES);
    memcpy(pals[0], seed_pal,    PAL_BYTES);
    for (int i = 1; i < POP; i++) {
        mutate(pool[i], seed_genome, 0.05);
        memcpy(pals[i], seed_pal, PAL_BYTES);
    }

    uint32_t t0 = millis();

    for (int gen = 0; gen < GENS; gen++) {
        for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], grid_seed);
        sort_pop();
        double sum = 0;
        for (int i = 0; i < POP; i++) sum += fit[i];
        Serial.printf("gen %2d: best=%.2f mean=%.2f tail=%.3f\n",
                      gen + 1, fit[0], sum / POP, last_activity_tail);
        hunt_status_paint(gen + 1, GENS, fit[0], sum / POP);
        yield();   // feed the loopTask WDT

        for (int i = POP / 2; i < POP; i++) {
            int pa = (int)(prng() % (POP / 2));
            int pb = (int)(prng() % (POP / 2));
            cross(tmp_genome, pool[pa], pool[pb]);
            mutate(pool[i], tmp_genome, 0.005);
            palette_inherit(pals[i], pals[pa], pals[pb]);
        }
    }

    // Final scoring + sort
    for (int i = 0; i < POP; i++) fit[i] = fitness(pool[i], grid_seed);
    sort_pop();

    uint32_t elapsed = millis() - t0;
    Serial.printf("=== hunt done (%.2f s)  best=%.2f  pal=[%d %d %d %d] ===\n",
                  elapsed / 1000.0, fit[0],
                  pals[0][0], pals[0][1], pals[0][2], pals[0][3]);

    memcpy(genome,  pool[0], GBYTES);
    memcpy(palette, pals[0], PAL_BYTES);

    if (write_winner_to_fs(palette, genome) == 0)
        Serial.println("saved as /winner.bin");
}

// ── Hot-swap slot table (Phase 3A + 3.5) ──────────────────────────────
//
// The CA run loop calls every per-tick action through this struct so
// an uploaded ELF can replace any one entry atomically.
//
// Phase 3.5 redesign: render and gpio slots are pure-data — they
// populate output buffers, the firmware does the actual TFT blit and
// digitalWrite. This means loaded code never has to call into firmware
// symbols (which xcc700 has no idiom to express anyway), so render
// and gpio become useful slots, not just "step plus two stubs."
//
// ABIs:
//   step(genome, in, out)
//     Hex CA tick. genome is 4096 B (K=4 packed). in/out are
//     GRID_W*GRID_H = 256 cells each.
//
//   render_pixels(prev, cur, rgb565)
//     For every cell, write the desired RGB565 colour into the
//     two bytes at rgb565[idx*2..idx*2+1] (low byte then high byte).
//     The firmware reads this buffer and blits each cell to the TFT.
//     prev is provided so a "diff-only" render can skip unchanged
//     cells by writing zero to the corresponding two bytes — which
//     the firmware interprets as "skip" (see SKIP_SENTINEL below).
//
//   gpio_levels(grid, levels)
//     For every output binding (n_bindings entries; bindings[] is a
//     read-only firmware global), write the desired HIGH (1) /
//     LOW (0) into levels[i]. The firmware then digitalWrites them.

typedef void (*step_fn_t)(const u8 *genome, const u8 *in, u8 *out);
typedef void (*render_fn_t)(const u8 *prev, const u8 *cur, u8 *rgb565);
typedef void (*gpio_fn_t)(const u8 *grid, u8 *levels);

struct HotSlots {
    step_fn_t   step;
    render_fn_t render;
    gpio_fn_t   gpio;
    bool        step_default;
    bool        render_default;
    bool        gpio_default;
};

// Pixel-blit sentinel. A render_pixels slot that writes 0xFFFF (low
// byte 0xFF, high byte 0xFF) to a cell tells the firmware to leave
// the TFT pixel for that cell untouched. The default render uses
// this for cells that didn't change, mirroring render_diff.
#define RENDER_SKIP_SENTINEL 0xFFFFu

// Phase 3.5 defaults — populate output buffers, no I/O of their own.
static void render_pixels_default(const u8 *prev, const u8 *cur, u8 *rgb565) {
    for (int i = 0; i < GRID_W * GRID_H; i++) {
        if (prev != nullptr && prev[i] == cur[i]) {
            rgb565[i*2]   = 0xFF;
            rgb565[i*2+1] = 0xFF;          // SKIP sentinel
        } else {
            uint16_t c = pal_rgb565[cur[i]];
            rgb565[i*2]   = (uint8_t)(c & 0xFF);
            rgb565[i*2+1] = (uint8_t)(c >> 8);
        }
    }
}

static void gpio_levels_default(const u8 *grid, u8 *levels) {
    for (int i = 0; i < n_bindings; i++) {
        const GpioBinding &b = bindings[i];
        int v = grid[b.cell_y * GRID_W + b.cell_x];
        levels[i] = (uint8_t)((b.state_mask >> v) & 1);
    }
}

struct HotSlots HOT = {
    /* step           */ step_grid,
    /* render         */ render_pixels_default,
    /* gpio           */ gpio_levels_default,
    /* step_default   */ true,
    /* render_default */ true,
    /* gpio_default   */ true,
};

// Per-tick output buffers — file-scope so setup() can use them too.
static u8 hot_rgb_buf[GRID_W * GRID_H * 2];
static u8 hot_levels_buf[MAX_BINDINGS];

static const char *slot_state(bool is_default) {
    return is_default ? "default" : "loaded";
}

// Apply the rgb565 buffer the render slot produced to the TFT.
// SKIP sentinel cells are left untouched — same effect as render_diff.
static void blit_pixels_to_tft(const u8 *rgb565) {
    for (int y = 0; y < GRID_H; y++) {
        for (int x = 0; x < GRID_W; x++) {
            int i = y * GRID_W + x;
            uint16_t c = (uint16_t)rgb565[i*2] |
                         ((uint16_t)rgb565[i*2+1] << 8);
            if (c == RENDER_SKIP_SENTINEL) continue;
            int px = XPAD + x * CELL + ((y & 1) ? (CELL / 2) : 0);
            int py = YPAD + y * CELL;
            tft.fillRect(px, py, CELL, CELL, c);
        }
    }
}

// Apply the levels buffer the gpio slot produced to the configured
// output pins.
static void apply_levels_to_pins(const u8 *levels) {
    for (int i = 0; i < n_bindings; i++) {
        digitalWrite(bindings[i].gpio_pin, levels[i] ? HIGH : LOW);
    }
}


// ── WiFi + HTTP + ELF hot-load (Phase 2) ─────────────────────────────
//
// All comms code lives in this section so the original CA pipeline
// above remains a verbatim copy of esp32_s3_full/src/main.cpp.

#define WIFI_CRED_PATH    "/wifi.txt"
#define LOADED_ELF_PATH   "/loaded.elf"
#define MAX_ELF_BYTES     (64 * 1024)
#define AP_FALLBACK_SSID  "hexca-setup"
#define AP_FALLBACK_PASS  "helloboard"
#define HTTP_PORT         80

static WebServer server(HTTP_PORT);
static bool wifi_sta_connected = false;
static String wifi_ip_str = "";
static String wifi_ssid_str = "";

// Last upload — populated by handle_load_elf so /info + /run-elf can
// describe what's on the board without re-reading the file.
static struct {
    bool     present;
    uint32_t bytes;
    uint16_t e_machine;
    uint8_t  e_class;          // ELF32=1, ELF64=2
    uint32_t entry;
    uint32_t recv_at_ms;
} last_elf = { false, 0, 0, 0, 0, 0 };


// Read /wifi.txt. Returns true if both ssid + password were parsed.
// Format: line 1 = ssid, line 2 = password. Trailing newlines OK.
static bool read_wifi_creds(String &ssid, String &pass) {
    if (!LittleFS.exists(WIFI_CRED_PATH)) return false;
    File f = LittleFS.open(WIFI_CRED_PATH, "r");
    if (!f) return false;
    ssid = f.readStringUntil('\n'); ssid.trim();
    pass = f.readStringUntil('\n'); pass.trim();
    f.close();
    return ssid.length() > 0 && pass.length() > 0;
}


static bool write_wifi_creds(const String &ssid, const String &pass) {
    File f = LittleFS.open(WIFI_CRED_PATH, "w");
    if (!f) return false;
    f.printf("%s\n%s\n", ssid.c_str(), pass.c_str());
    f.close();
    return true;
}


static void start_ap_fallback() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_FALLBACK_SSID, AP_FALLBACK_PASS);
    wifi_ip_str = WiFi.softAPIP().toString();
    wifi_ssid_str = AP_FALLBACK_SSID;
    Serial.printf("WiFi: AP '%s' (pw '%s') at %s — POST /wifi to provision\n",
                  AP_FALLBACK_SSID, AP_FALLBACK_PASS, wifi_ip_str.c_str());
}


static void try_connect_sta(const String &ssid, const String &pass) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());
    Serial.printf("WiFi: joining '%s' …", ssid.c_str());
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 12000) {
        delay(200);
        Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
        wifi_sta_connected = true;
        wifi_ip_str = WiFi.localIP().toString();
        wifi_ssid_str = ssid;
        Serial.printf("WiFi: joined, IP %s\n", wifi_ip_str.c_str());
        if (MDNS.begin("hexca")) {
            MDNS.addService("http", "tcp", HTTP_PORT);
            Serial.println("mDNS: http://hexca.local/");
        }
    } else {
        Serial.println("WiFi: STA failed, falling back to AP");
        start_ap_fallback();
    }
}


// ── HTTP route handlers ───────────────────────────────────────────────

static void handle_root() {
    String html;
    html.reserve(1500);
    html += F("<!doctype html><html><head><title>hexca</title>"
              "<style>body{font-family:ui-monospace,Menlo,monospace;"
              "max-width:640px;margin:1rem auto;padding:0 1rem;"
              "background:#0d1117;color:#c9d1d9;line-height:1.4}"
              "h1{margin-top:0}code{background:#161b22;padding:1px 4px;border-radius:3px}"
              "table{border-collapse:collapse;width:100%}"
              "td{padding:4px 8px;border-bottom:1px solid #30363d}"
              "td:first-child{color:#8b949e}</style></head><body>");
    html += F("<h1>hexca</h1><p>ESP32-S3 supermini · hex CA + xcc700 hot-load</p>");
    html += F("<table>");
    html += "<tr><td>uptime</td><td>" + String(millis() / 1000) + " s</td></tr>";
    html += "<tr><td>free heap</td><td>" + String(ESP.getFreeHeap()) + " B</td></tr>";
    html += "<tr><td>WiFi mode</td><td>" + String(wifi_sta_connected ? "STA" : "AP") + "</td></tr>";
    html += "<tr><td>SSID</td><td>" + wifi_ssid_str + "</td></tr>";
    html += "<tr><td>IP</td><td>" + wifi_ip_str + "</td></tr>";
    html += "<tr><td>last ELF</td><td>";
    if (last_elf.present) {
        html += String(last_elf.bytes) + " B · entry=0x" +
                String(last_elf.entry, HEX) + " · machine=0x" +
                String(last_elf.e_machine, HEX);
    } else {
        html += F("(none uploaded yet)");
    }
    html += F("</td></tr>");
    html += "<tr><td>slot: step</td><td>"   + String(slot_state(HOT.step_default))   + "</td></tr>";
    html += "<tr><td>slot: render</td><td>" + String(slot_state(HOT.render_default)) + "</td></tr>";
    html += "<tr><td>slot: gpio</td><td>"   + String(slot_state(HOT.gpio_default))   + "</td></tr>";
    html += F("</table>");
    html += F("<h2>endpoints</h2><ul>"
             "<li><code>GET /info</code> — JSON status (uptime, free heap, slots, last ELF)</li>"
             "<li><code>POST /wifi</code> — body <code>ssid=…&amp;password=…</code>; saves + reboots</li>"
             "<li><code>POST /load-elf</code> — raw ELF body, saved to <code>/loaded.elf</code></li>"
             "<li><code>POST /run-elf?slot=NAME</code> — load <code>/loaded.elf</code> into slot "
                 "<code>step</code>, <code>render</code>, or <code>gpio</code>; takes effect next tick</li>"
             "<li><code>POST /reset-slots</code> — revert every slot to its baked-in default</li>"
             "</ul></body></html>");
    server.send(200, "text/html", html);
}


static void handle_info() {
    String json;
    json.reserve(400);
    json += "{\"uptime_s\":" + String(millis() / 1000);
    json += ",\"free_heap\":" + String(ESP.getFreeHeap());
    json += ",\"wifi_mode\":\"" + String(wifi_sta_connected ? "STA" : "AP") + "\"";
    json += ",\"ssid\":\"" + wifi_ssid_str + "\"";
    json += ",\"ip\":\"" + wifi_ip_str + "\"";
    json += ",\"last_elf\":";
    if (last_elf.present) {
        json += "{\"bytes\":" + String(last_elf.bytes);
        json += ",\"entry\":" + String(last_elf.entry);
        json += ",\"e_machine\":" + String(last_elf.e_machine);
        json += ",\"e_class\":" + String(last_elf.e_class);
        json += ",\"recv_at_ms\":" + String(last_elf.recv_at_ms) + "}";
    } else {
        json += "null";
    }
    json += ",\"slots\":{";
    json += "\"step\":\""   + String(slot_state(HOT.step_default))   + "\",";
    json += "\"render\":\"" + String(slot_state(HOT.render_default)) + "\",";
    json += "\"gpio\":\""   + String(slot_state(HOT.gpio_default))   + "\"}";
    json += "}";
    server.send(200, "application/json", json);
}


static void handle_wifi() {
    String ssid = server.arg("ssid");
    String pass = server.arg("password");
    if (ssid.length() == 0) {
        server.send(400, "text/plain", "missing ssid");
        return;
    }
    if (!write_wifi_creds(ssid, pass)) {
        server.send(500, "text/plain", "could not write " WIFI_CRED_PATH);
        return;
    }
    server.send(200, "text/plain",
                "saved; rebooting into STA mode in 2 s\n");
    delay(2000);
    ESP.restart();
}


// Parse the head of an ELF blob. Returns true and populates the ELF
// fields if header looks valid; false otherwise. Validates magic +
// e_machine == 0x5e (Tensilica Xtensa).
static bool parse_elf_head(const uint8_t *buf, size_t n,
                           uint16_t &e_machine, uint8_t &e_class,
                           uint32_t &entry) {
    if (n < 52) return false;                          // ELF32 header is 52 B
    if (buf[0] != 0x7f || buf[1] != 'E' ||
        buf[2] != 'L'  || buf[3] != 'F') return false;
    e_class = buf[4];                                  // 1 = ELF32, 2 = ELF64
    if (e_class != 1) return false;                    // xcc700 only emits ELF32
    e_machine = (uint16_t)buf[18] | ((uint16_t)buf[19] << 8);
    if (e_machine != 0x5e) return false;               // Tensilica Xtensa
    entry = (uint32_t)buf[24]        | ((uint32_t)buf[25] << 8) |
            ((uint32_t)buf[26] << 16) | ((uint32_t)buf[27] << 24);
    return true;
}


// ── Phase 3B: minimal native ELF loader for xcc700 output ────────────
//
// Scope (intentionally narrow):
//   - ELF32 little-endian, e_machine == 0x5e (Xtensa) only.
//   - Single .text section. No .data, no .bss, no globals.
//   - No external symbols / no relocations resolved. The loaded
//     function may only call other functions defined in the same
//     ELF (relative calls), use stack locals, and do arithmetic.
//   - Caller decides what signature to cast to. Phase 3C wires
//     specific signatures (step_fn_t, render_fn_t, gpio_fn_t) so
//     the slot table can pick up the loaded code atomically.
//
// What it does NOT do (deliberate Phase 3 backlog):
//   - R_XTENSA_32 / R_XTENSA_SLOT0_OP relocation resolution
//   - Symbol table lookups (loaded code can't call into firmware)
//   - .rodata / .data / .bss section copy + addressing
//   - Memory-protection or sandboxing
//
// Returns: pointer to the executable .text region in IRAM, or
// nullptr on failure (and writes the diagnostic to *err).

#define LE16(p, off) ((uint16_t)((p)[(off)] | ((p)[(off)+1] << 8)))
#define LE32(p, off) ((uint32_t)((p)[(off)] | ((p)[(off)+1] << 8) \
                       | ((p)[(off)+2] << 16) | ((p)[(off)+3] << 24)))

// Section header field offsets (40-byte sh entry, ELF32).
#define SH_NAME    0
#define SH_TYPE    4
#define SH_FLAGS   8
#define SH_OFFSET  16
#define SH_SIZE    20
#define SH_ENTSIZE 36

// We track everything an ELF needs to be usable as a slot.
struct LoadedElf {
    void    *exec;       // executable region in IRAM (heap_caps free()-able)
    size_t   exec_bytes;
    uint32_t entry;      // copied here for convenience; may be 0
};


// Find a section by name. Walks the section header table, looks up
// each name in .shstrtab. Returns true + populates offset/size on hit.
static bool find_section(const uint8_t *buf, size_t n,
                         const char *want,
                         uint32_t &out_off, uint32_t &out_size) {
    if (n < 52) return false;
    uint32_t e_shoff   = LE32(buf, 32);
    uint16_t e_shentsz = LE16(buf, 46);
    uint16_t e_shnum   = LE16(buf, 48);
    uint16_t e_shstrndx = LE16(buf, 50);
    if (e_shentsz != 40 || e_shnum == 0) return false;
    if ((size_t)e_shoff + (size_t)e_shnum * 40 > n) return false;
    if (e_shstrndx >= e_shnum) return false;

    // Locate the string-table section so we can resolve sh_name.
    const uint8_t *shstr_hdr = buf + e_shoff + (size_t)e_shstrndx * 40;
    uint32_t shstr_off  = LE32(shstr_hdr, SH_OFFSET);
    uint32_t shstr_size = LE32(shstr_hdr, SH_SIZE);
    if ((size_t)shstr_off + shstr_size > n) return false;
    const char *strs = (const char *)(buf + shstr_off);

    for (uint16_t i = 0; i < e_shnum; i++) {
        const uint8_t *sh = buf + e_shoff + (size_t)i * 40;
        uint32_t name_off = LE32(sh, SH_NAME);
        if (name_off >= shstr_size) continue;
        const char *name = strs + name_off;
        if (strcmp(name, want) == 0) {
            out_off  = LE32(sh, SH_OFFSET);
            out_size = LE32(sh, SH_SIZE);
            return ((size_t)out_off + out_size) <= n;
        }
    }
    return false;
}


// Load .text into executable RAM. Caller frees with heap_caps_free()
// when done. err is a short, single-line diagnostic on failure.
static bool load_elf_text(const uint8_t *buf, size_t n,
                          LoadedElf &out, const char *&err) {
    uint16_t e_machine, e_class; uint32_t entry;
    if (!parse_elf_head(buf, n, e_machine, e_class, entry)) {
        err = "ELF header invalid";
        return false;
    }
    out.entry = entry;

    uint32_t text_off = 0, text_size = 0;
    if (!find_section(buf, n, ".text", text_off, text_size)) {
        err = "no .text section";
        return false;
    }
    if (text_size == 0) {
        err = ".text is empty";
        return false;
    }
    if (text_size > 32 * 1024) {
        err = ".text exceeds 32 KiB cap";
        return false;
    }

    // Allocate from IRAM so the CPU can execute these bytes.
    // MALLOC_CAP_EXEC + MALLOC_CAP_8BIT is the right combination on
    // ESP32-S3; on other Xtensa variants the equivalent is the same
    // pair of caps.
    void *exec = heap_caps_malloc(text_size,
                                  MALLOC_CAP_EXEC | MALLOC_CAP_8BIT);
    if (!exec) {
        err = "heap_caps_malloc(EXEC) returned NULL";
        return false;
    }
    memcpy(exec, buf + text_off, text_size);

    // Clear caches so the i-cache picks up the freshly written bytes.
    // The GCC builtin handles both d-cache flush and i-cache invalidate
    // for the address range — on Xtensa it expands to the appropriate
    // dhwbi.l/ihi.l sequence.
    __builtin___clear_cache((char *)exec, (char *)exec + text_size);

    out.exec = exec;
    out.exec_bytes = text_size;
    err = nullptr;
    return true;
}


static void free_loaded_elf(LoadedElf &le) {
    if (le.exec) {
        heap_caps_free(le.exec);
        le.exec = nullptr;
        le.exec_bytes = 0;
        le.entry = 0;
    }
}


// POST /load-elf with the ELF as the raw request body. We accumulate
// chunks in a heap buffer (capped at MAX_ELF_BYTES) and then commit
// to LittleFS in one go so a half-written file can never run.
static void handle_load_elf() {
    if (!server.hasArg("plain")) {
        server.send(400, "text/plain",
                    "POST raw ELF as request body\n");
        return;
    }
    const String &body = server.arg("plain");
    size_t n = body.length();
    if (n < 52) {
        server.send(400, "text/plain", "body too small to be an ELF\n");
        return;
    }
    if (n > MAX_ELF_BYTES) {
        server.send(413, "text/plain", "ELF exceeds MAX_ELF_BYTES\n");
        return;
    }
    const uint8_t *buf = (const uint8_t *)body.c_str();

    uint16_t e_machine = 0;
    uint8_t  e_class = 0;
    uint32_t entry = 0;
    if (!parse_elf_head(buf, n, e_machine, e_class, entry)) {
        server.send(400, "text/plain",
                    "not a valid ELF32/Xtensa (magic, class, or e_machine)\n");
        return;
    }

    File f = LittleFS.open(LOADED_ELF_PATH, "w");
    if (!f) {
        server.send(500, "text/plain",
                    "could not open " LOADED_ELF_PATH " for write\n");
        return;
    }
    size_t wrote = f.write(buf, n);
    f.close();
    if (wrote != n) {
        server.send(500, "text/plain", "short write\n");
        return;
    }

    last_elf.present    = true;
    last_elf.bytes      = (uint32_t)n;
    last_elf.e_machine  = e_machine;
    last_elf.e_class    = e_class;
    last_elf.entry      = entry;
    last_elf.recv_at_ms = millis();

    String out;
    out.reserve(160);
    out += "OK ";
    out += String(n);
    out += " B  e_machine=0x"; out += String(e_machine, HEX);
    out += "  entry=0x";       out += String(entry, HEX);
    out += "  saved as ";      out += LOADED_ELF_PATH;
    out += "\n";
    server.send(200, "text/plain", out);

    Serial.printf("[load-elf] %u B  entry=0x%08x  e_machine=0x%04x\n",
                  (unsigned)n, (unsigned)entry, (unsigned)e_machine);
}


// We hold one LoadedElf per slot so we can free the previous IRAM
// region when a new ELF replaces it (or /reset-slots is called).
static LoadedElf loaded_step    = {nullptr, 0, 0};
static LoadedElf loaded_render  = {nullptr, 0, 0};
static LoadedElf loaded_gpio    = {nullptr, 0, 0};


static void revert_slot(const String &name) {
    if (name == "step")   { HOT.step   = step_grid;              HOT.step_default   = true; free_loaded_elf(loaded_step); }
    if (name == "render") { HOT.render = render_pixels_default;  HOT.render_default = true; free_loaded_elf(loaded_render); }
    if (name == "gpio")   { HOT.gpio   = gpio_levels_default;    HOT.gpio_default   = true; free_loaded_elf(loaded_gpio); }
}


static void revert_all_slots() {
    revert_slot("step");
    revert_slot("render");
    revert_slot("gpio");
}


// POST /run-elf?slot=NAME — Phase 3C.
//
// 1. Read the ELF saved by /load-elf.
// 2. Extract .text into IRAM via load_elf_text().
// 3. Cast the entry pointer to the slot's signature.
// 4. Patch HOT.<slot>.
//
// Successive /run-elf calls on the same slot free the previous
// allocation. /reset-slots reverts every slot to its baked-in default.
//
// CAVEAT (Phase 3 honest limits): the loaded code must be self-
// contained — no external symbols, no globals, no .data/.rodata.
// xcc700 outputs that are pure functions over their args + stack
// locals satisfy this; anything that needs a syscall / printf /
// digitalWrite will not link and may crash. The hardware will reset
// on a true crash; on next boot all slots are defaults.
static void handle_run_elf() {
    if (!last_elf.present || !LittleFS.exists(LOADED_ELF_PATH)) {
        server.send(404, "text/plain",
                    "no ELF loaded; POST /load-elf first\n");
        return;
    }
    String slot = server.arg("slot");
    if (slot.length() == 0) slot = "step";
    if (slot != "step" && slot != "render" && slot != "gpio") {
        server.send(400, "text/plain",
                    "slot must be one of: step, render, gpio\n");
        return;
    }

    File f = LittleFS.open(LOADED_ELF_PATH, "r");
    if (!f) {
        server.send(500, "text/plain", "open failed\n");
        return;
    }
    size_t n = f.size();
    if (n > MAX_ELF_BYTES) n = MAX_ELF_BYTES;
    uint8_t *buf = (uint8_t *)malloc(n);
    if (!buf) {
        f.close();
        server.send(500, "text/plain", "malloc failed\n");
        return;
    }
    f.read(buf, n);
    f.close();

    LoadedElf le = {nullptr, 0, 0};
    const char *err = nullptr;
    bool ok = load_elf_text(buf, n, le, err);
    free(buf);
    if (!ok) {
        String out = String("LOAD FAIL: ") + (err ? err : "(unknown)") + "\n";
        Serial.print("[run-elf] "); Serial.print(out);
        server.send(400, "text/plain", out);
        return;
    }

    // Patch the slot. The cast assumes the loaded function matches
    // the slot's typedef — it's the user's contract (see /s3lab/compile/
    // examples for the right signatures).
    if (slot == "step") {
        free_loaded_elf(loaded_step);
        loaded_step = le;
        HOT.step = (step_fn_t)le.exec;
        HOT.step_default = false;
    } else if (slot == "render") {
        free_loaded_elf(loaded_render);
        loaded_render = le;
        HOT.render = (render_fn_t)le.exec;
        HOT.render_default = false;
    } else if (slot == "gpio") {
        free_loaded_elf(loaded_gpio);
        loaded_gpio = le;
        HOT.gpio = (gpio_fn_t)le.exec;
        HOT.gpio_default = false;
    }

    String out;
    out.reserve(200);
    out += "OK slot=";       out += slot;
    out += " text_bytes=";   out += String((unsigned)le.exec_bytes);
    out += " exec=0x";       out += String((uintptr_t)le.exec, HEX);
    out += " entry=0x";      out += String(le.entry, HEX);
    out += "\nWill take effect on the next CA tick.\n";
    Serial.print("[run-elf] "); Serial.print(out);
    server.send(200, "text/plain", out);
}


// POST /reset-slots — revert every slot to its baked-in default and
// free any IRAM held by previously-loaded ELFs.
static void handle_reset_slots() {
    revert_all_slots();
    server.send(200, "text/plain", "all slots reverted to defaults\n");
    Serial.println("[reset-slots] all slots reverted to defaults");
}


static void handle_not_found() {
    server.send(404, "text/plain", "not found\n");
}


// Public entry — called from setup() once LittleFS is mounted.
static void comms_setup() {
    String ssid, pass;
    if (read_wifi_creds(ssid, pass)) {
        try_connect_sta(ssid, pass);
    } else {
        Serial.println("WiFi: no /wifi.txt; AP-mode setup");
        start_ap_fallback();
    }

    server.on("/",            HTTP_GET,  handle_root);
    server.on("/info",        HTTP_GET,  handle_info);
    server.on("/wifi",        HTTP_POST, handle_wifi);
    server.on("/load-elf",    HTTP_POST, handle_load_elf);
    server.on("/run-elf",     HTTP_POST, handle_run_elf);
    server.on("/reset-slots", HTTP_POST, handle_reset_slots);
    server.onNotFound(handle_not_found);
    server.begin();
    Serial.printf("HTTP: server up on :%d\n", HTTP_PORT);
}


// ── setup / loop ──────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    uint32_t t_start = millis();
    while (!Serial && (millis() - t_start) < 2000) delay(10);
    Serial.println();
    Serial.println("=== hex-CA on-board full pipeline (S3) ===");

    if (!LittleFS.begin(true)) {
        Serial.println("LittleFS mount failed");
    }

    if (!LittleFS.exists("/gpio_map.txt")) {
        write_default_gpio_map();
        Serial.println("wrote default /gpio_map.txt");
    }
    load_bindings_from_fs();
    Serial.printf("%d output bindings, %d input bindings loaded\n",
                  n_bindings, n_input_bindings);

    auto warn_pin = [](int pin) {
        if (pin == 19 || pin == 20)
            Serial.printf("  warn: GPIO %d is USB D+/D- — Serial will die\n",
                          pin);
        if (pin == PIN_SCK || pin == PIN_MOSI ||
            pin == PIN_DC  || pin == PIN_CS  ||
            pin == PIN_RST || pin == PIN_BL)
            Serial.printf("  warn: GPIO %d collides with the TFT pin map\n",
                          pin);
    };

    for (int i = 0; i < n_bindings; i++) {
        const GpioBinding &b = bindings[i];
        warn_pin(b.gpio_pin);
        pinMode(b.gpio_pin, OUTPUT);
        digitalWrite(b.gpio_pin, LOW);
        Serial.printf("  out: cell (%d,%d) -> GPIO %d  mask=0x%X\n",
                      b.cell_x, b.cell_y, b.gpio_pin, b.state_mask);
    }

    for (int i = 0; i < n_input_bindings; i++) {
        const InputBinding &b = input_bindings[i];
        warn_pin(b.gpio_pin);
        pinMode(b.gpio_pin, INPUT_PULLUP);
        Serial.printf("  in : GPIO %d (pull-up) -> cell (%d,%d) "
                      "low=%d high=%d\n",
                      b.gpio_pin, b.cell_x, b.cell_y,
                      b.low_state, b.high_state);
    }

    pinMode(PIN_BL, OUTPUT);
    digitalWrite(PIN_BL, HIGH);
    tft.initR(INITR_MINI160x80);
    tft.setSPISpeed(SPI_HZ);
    tft.setRotation(3);
    tft.invertDisplay(true);
    tft.fillScreen(ST77XX_BLACK);

    prng_state = esp_random() ^ (uint32_t)esp_timer_get_time();
    if (!prng_state) prng_state = 1;

    uint32_t grid_seed = prng();
    run_hunt(grid_seed);

    rebuild_palette_rgb();

    uint32_t run_seed = esp_random();
    seed_grid(grid_a, run_seed);
    Serial.printf("run grid seed = %u  tick = %d ms\n",
                  (unsigned)run_seed, TICK_MS);

    tft.fillScreen(ST77XX_BLACK);
    apply_input_bindings(grid_a);
    // Initial frame uses the same slot path as the run loop so a
    // hot-loaded render slot affects boot-time as well.
    HOT.render(nullptr, grid_a, hot_rgb_buf);  // prev=NULL → full render
    blit_pixels_to_tft(hot_rgb_buf);
    HOT.gpio(grid_a, hot_levels_buf);
    apply_levels_to_pins(hot_levels_buf);

    // Comms (WiFi + HTTP) come up after the hunt finishes so the WiFi
    // stack doesn't compete with the GA for cycles. The CA run loop
    // below shares the CPU with server.handleClient() at TICK_MS cadence.
    comms_setup();

    Serial.println("=== RUN phase: stepping CA + driving GPIO + rendering TFT ===");
}

void loop() {
    static u8      *cur  = grid_a;
    static u8      *nxt  = grid_b;
    static uint32_t tick = 0;

    delay(TICK_MS);
    server.handleClient();       // service HTTP between every CA tick
    apply_input_bindings(cur);   // pin reads clamp cells before stepping
    HOT.step(genome, cur, nxt);                     // step slot
    HOT.render(cur, nxt, hot_rgb_buf);              // render slot → buffer
    blit_pixels_to_tft(hot_rgb_buf);                // firmware does the I/O
    HOT.gpio(nxt, hot_levels_buf);                  // gpio slot → buffer
    apply_levels_to_pins(hot_levels_buf);           // firmware does the I/O

    u8 *t = cur; cur = nxt; nxt = t;
    tick++;

    if (tick % 30 == 0) {
        Serial.printf("tick %u  ", (unsigned)tick);
        for (int i = 0; i < n_input_bindings; i++) {
            const InputBinding &b = input_bindings[i];
            int v = cur[b.cell_y * GRID_W + b.cell_x];
            Serial.printf("in%d=c%d ", b.gpio_pin, v);
        }
        for (int i = 0; i < n_bindings; i++) {
            const GpioBinding &b = bindings[i];
            int v = cur[b.cell_y * GRID_W + b.cell_x];
            Serial.printf("GPIO%d=%d(c=%d) ",
                          b.gpio_pin, level_for(b, v), v);
        }
        Serial.println();
    }
}
