// Hex-CA on-board full pipeline — ESP32-S3 SuperMini.
//
// Combines, in a single binary, all three S3 artifacts:
//   - oneclick_class4/esp32_s3/   (GA hunt for class-4 rulesets)
//   - hex_ca_class4/esp_st7735s/  (CA visualisation on ST7735S)
//   - hex_ca_class4/esp32_s3_gpio (cell -> GPIO output bindings)
//
// Boot sequence:
//   1. Mount LittleFS, init TFT, configure GPIO outputs.
//   2. Run hunt (POP=30 GENS=40, ~10-30 s on S3). Show generation
//      counter + fitness + bottom progress bar on the TFT.
//   3. Persist top winner as /winner.bin (4104-byte hunter-tail format).
//   4. Loop forever: step CA, diff-render TFT, drive GPIOs at TICK_MS.
//
// Press the reset button to run another hunt.
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

// ── CA constants ──────────────────────────────────────────────────────
#define K            4
#define NSIT         16384
#define GBYTES       4096
#define PAL_BYTES    4
#define MAGIC_BYTES  4
#define TAIL_MAGIC   "HXC4"
#define TAIL_BYTES   (MAGIC_BYTES + PAL_BYTES + GBYTES)

#define GRID_W       14
#define GRID_H       14
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

#define CELL          5         // 14*5 = 70 px square grid
#define XPAD         44         // (160-72)/2 ≈ centred on landscape
#define YPAD          5         // (80-70)/2

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
    render_full(grid_a);
    apply_bindings(grid_a);

    Serial.println("=== RUN phase: stepping CA + driving GPIO + rendering TFT ===");
}

void loop() {
    static u8      *cur  = grid_a;
    static u8      *nxt  = grid_b;
    static uint32_t tick = 0;

    delay(TICK_MS);
    apply_input_bindings(cur);   // pin reads clamp cells before stepping
    step_grid(genome, cur, nxt);
    render_diff(cur, nxt);
    apply_bindings(nxt);

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
