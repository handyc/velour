// cellular_esp.cpp — distilled from s3lab Cellular sublab.
//
// SOURCE   : static/s3lab/js/sublabs/cellular.mjs (438 LOC)
//            + static/s3lab/js/engine.mjs (276 LOC)
//            + isolation/artifacts/hex_ca_class4/esp32_s3_xcc/src/main.cpp
//              (WiFi/HTTP chassis pattern)
// TARGET   : ESP32-S3 SuperMini, Arduino-ESP32 framework, ST7735S 80×160
// PARITY   : algorithm + scoring identical to the JS reference at the same
//            seed. Render is ST7735S TFT instead of HTML5 canvas.
//
// CONDENSER : population BSS would be ~1155 KiB
//             (256 cells × 4620 B each). Does NOT fit in 320 KB
//             SRAM, so the population is allocated in PSRAM via
//             heap_caps_malloc(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT). The
//             ESP32-S3 SuperMini ships with 8 MiB PSRAM — comfortable.

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// ── compile-time constants ──────────────────────────────────────────

#define K           4
#define NSIT        16384     // K^7
#define GBYTES      4096   // NSIT*2/8
#define PAL_BYTES   4
#define CA_W        16
#define CA_H        16
#define HORIZON     25

#define GRID_COLS   16
#define GRID_ROWS   16
#define N_CELLS     (GRID_COLS * GRID_ROWS)

#define TICK_MS     200
#define ROUND_MS    500
#define MUT_RATE    0.005

#define TILE_PX     7

// Panel pixel dimensions baked at distill time. Different panels use
// different INITR_* tokens + setRotation values, so the post-rotation
// effective WxH is what render_pop_diff centres into.
#define PANEL_W_PX  128
#define PANEL_H_PX  128

// Live-mode sub-tile geometry. Each cell's 16×16 internal CA gets
// subsampled down to SUB_W × SUB_H pixels — every rendered pixel
// represents a (CA_W/SUB_W) × (CA_H/SUB_H) region of the actual grid.
// On the 128×128 panel that's 8×8 per cell (16 cells × 8 px = 128 px,
// exact fit). On the 80×160 panel it's 4×4 (population area = 64×64
// centred, leaving margin).
#define SUB_W       6
#define SUB_H       6
#define SUB_DX      (CA_W / SUB_W)        // grid stride per rendered px
#define SUB_DY      (CA_H / SUB_H)

// ST7735S pin map (matches esp32_s3_xcc and esp32_s3_full).
#define PIN_SCK   12
#define PIN_MOSI  11
#define PIN_DC     4
#define PIN_CS     5
#define PIN_RST    6
#define PIN_BL     7
#define SPI_HZ    27000000UL

#define WIFI_CRED_PATH    "/wifi.txt"
#define AP_FALLBACK_SSID  "hexca-cellular-setup"
#define AP_FALLBACK_PASS  "helloboard"
#define HTTP_PORT         80

typedef uint8_t  u8;
typedef uint32_t u32;

static const int DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6] = {  0,  1, -1,  1, -1,  0 };
static const int DXO[6] = { -1,  0, -1,  1,  0,  1 };

static const int NB_DC_EVEN[6] = { -1, +1, -1,  0, -1,  0 };
static const int NB_DC_ODD [6] = { -1, +1,  0, +1,  0, +1 };
static const int NB_DR     [6] = {  0,  0, -1, -1, +1, +1 };

// ── PRNG: xorshift32 (matches engine.mjs::prng) ─────────────────────

static u32 prng_state = 0x9E3779B9u;
static inline u32 prng() {
    u32 x = prng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    prng_state = x;
    return x;
}
static inline double prng_unit() { return (double)prng() / 4294967296.0; }
static void seed_prng(u32 s) { prng_state = s ? s : 1u; }

static u32 lcg_state = 0;
static void lcg_seed(u32 s) { lcg_state = s ? s : 1u; }
static u32 lcg_step() {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}

// ── packed-genome accessors ─────────────────────────────────────────

static inline int g_get(const u8 *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static inline void g_set(u8 *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (g[b] & ~(3 << o)) | ((v & 3) << o);
}
static inline int sit_idx(int self_c, const int *n) {
    int i = self_c;
    for (int k = 0; k < 6; k++) i = i * K + n[k];
    return i;
}

// ── grid stepping (mirror engine.mjs::step_grid) ────────────────────

static void seed_grid_at(u8 *g, u32 s) {
    lcg_seed(s);
    for (int i = 0; i < CA_W * CA_H; i++) g[i] = (u8)(lcg_step() & 3);
}

static void step_grid(const u8 *genome, const u8 *in, u8 *out) {
    int n[6];
    for (int y = 0; y < CA_H; y++) {
        const int *dx = (y & 1) ? DXO : DXE;
        for (int x = 0; x < CA_W; x++) {
            int self_c = in[y * CA_W + x];
            for (int k = 0; k < 6; k++) {
                int yy = y + DY[k], xx = x + dx[k];
                n[k] = (yy >= 0 && yy < CA_H && xx >= 0 && xx < CA_W)
                     ? in[yy * CA_W + xx] : 0;
            }
            out[y * CA_W + x] = (u8)g_get(genome, sit_idx(self_c, n));
        }
    }
}

// ── fitness (mirror engine.mjs::fitness) ────────────────────────────

static u8 fit_a[CA_W * CA_H];
static u8 fit_b[CA_W * CA_H];

static double fitness(const u8 *genome, u32 grid_seed) {
    seed_grid_at(fit_a, grid_seed);
    double act[HORIZON];
    int colour_counts[K] = {0};
    for (int t = 0; t < HORIZON; t++) {
        step_grid(genome, fit_a, fit_b);
        int changed = 0;
        for (int i = 0; i < CA_W * CA_H; i++)
            if (fit_a[i] != fit_b[i]) changed++;
        act[t] = (double)changed / (CA_W * CA_H);
        memcpy(fit_a, fit_b, CA_W * CA_H);
    }
    int uniform = 1;
    for (int i = 1; i < CA_W * CA_H; i++)
        if (fit_a[i] != fit_a[0]) { uniform = 0; break; }
    for (int i = 0; i < CA_W * CA_H; i++) colour_counts[fit_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < K; c++)
        if (colour_counts[c] * 100 >= CA_W * CA_H) diversity++;
    int tail_n = HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++) avg += act[i];
    avg /= tail_n;
    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HORIZON - tail_n; i < HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;
    double activity_reward = (avg <= 0.12) ? avg / 0.12 : (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < K ? diversity : K);
    return score;
}

// ── GA ops ───────────────────────────────────────────────────────────

static void random_genome_into(u8 *g) {
    for (int i = 0; i < GBYTES; i++) g[i] = (u8)(prng() & 0xFF);
}

static void invent_palette_into(u8 *pal) {
    int n = 0;
    while (n < K) {
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        bool dup = false;
        for (int j = 0; j < n; j++) if (pal[j] == c) { dup = true; break; }
        if (!dup) pal[n++] = (u8)c;
    }
}

static void mutate_into(u8 *dst, const u8 *src, double rate) {
    memcpy(dst, src, GBYTES);
    for (int i = 0; i < NSIT; i++)
        if (prng_unit() < rate) g_set(dst, i, (int)(prng() & 3));
}

static void palette_inherit_into(u8 *dst, const u8 *a, const u8 *b) {
    const u8 *src = (prng() & 1) ? a : b;
    memcpy(dst, src, PAL_BYTES);
    if ((prng() % 100) < 8) {
        int slot = prng() % K;
        u32 c = ((prng() % 10) < 9) ? (16  + (prng() % 216))
                                     : (232 + (prng() % 24));
        dst[slot] = (u8)c;
    }
}

// ── topology ─────────────────────────────────────────────────────────

static int neighbour_idx(int i, int dir) {
    int r = i / GRID_COLS, c = i - r * GRID_COLS;
    int dc = (r & 1) ? NB_DC_ODD[dir] : NB_DC_EVEN[dir];
    int dr = NB_DR[dir];
    int nr = (r + dr + GRID_ROWS) % GRID_ROWS;
    int nc = (c + dc + GRID_COLS) % GRID_COLS;
    return nr * GRID_COLS + nc;
}

// ── ANSI-256 → RGB565 (matches esp32_s3_xcc::ansi256_to_rgb565) ─────

static const u8 ANSI_LVL[6]  = { 0, 95, 135, 175, 215, 255 };
static const u8 ANSI_STD[16][3] = {
    {0,0,0},      {128,0,0},   {0,128,0},   {128,128,0},
    {0,0,128},    {128,0,128}, {0,128,128}, {192,192,192},
    {128,128,128},{255,0,0},   {0,255,0},   {255,255,0},
    {0,0,255},    {255,0,255}, {0,255,255}, {255,255,255},
};

static uint16_t ansi256_to_rgb565(u8 idx) {
    int r = 0, g = 0, b = 0;
    if (idx < 16) {
        r = ANSI_STD[idx][0]; g = ANSI_STD[idx][1]; b = ANSI_STD[idx][2];
    } else if (idx < 232) {
        int i = idx - 16;
        r = ANSI_LVL[(i / 36)];
        g = ANSI_LVL[((i % 36) / 6)];
        b = ANSI_LVL[i % 6];
    } else {
        int v = 8 + (idx - 232) * 10;
        if (v > 255) v = 255;
        r = g = b = v;
    }
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}

// ── population state — allocated in PSRAM ───────────────────────────

struct Cell {
    u8     genome[GBYTES];
    u8     palette[PAL_BYTES];
    u8     grid_a[CA_W * CA_H];
    u8     grid_b[CA_W * CA_H];
    double score;
    u32    refined_at_round;
};

static Cell *pop = nullptr;     // PSRAM

// Cached "dominant palette index" per cell so render() doesn't have
// to recount every frame. Updated when the cell's grid_a changes.
static u8 dom_cache[N_CELLS];
static uint16_t dom_rgb_cache[N_CELLS];

static void update_dom_cache(int idx) {
    Cell &c = pop[idx];
    int counts[K] = {0};
    for (int i = 0; i < CA_W * CA_H; i++) counts[c.grid_a[i]]++;
    int best = 0, best_n = counts[0];
    for (int i = 1; i < K; i++) if (counts[i] > best_n) {
        best_n = counts[i]; best = i;
    }
    u8 ansi = c.palette[best];
    if (dom_cache[idx] != ansi) {
        dom_cache[idx] = ansi;
        dom_rgb_cache[idx] = ansi256_to_rgb565(ansi);
    }
}

// ── TFT ─────────────────────────────────────────────────────────────

static Adafruit_ST7735 tft(PIN_CS, PIN_DC, PIN_MOSI, PIN_SCK, PIN_RST);

// Render the population grid as small hex-offset tiles. Only redraw
// tiles whose dominant color changed since last frame — keeps SPI
// traffic bounded.
static u8 last_drawn[N_CELLS];

// Render mode — flipped at runtime via POST /render-mode.
//   false: dominant-colour-per-cell (cheap, the original render)
//   true : live sub-CA per cell (every rendered pixel = a sample of
//          the actual grid). Costs ~16k pixel writes per tick (~10
//          ms SPI at 27 MHz on a 128×128 panel) but shows real CA
//          motion within every population tile.
static volatile bool g_render_live = false;

static void render_pop_full() {
    tft.fillScreen(ST77XX_BLACK);
    memset(last_drawn, 0xFF, N_CELLS);
}

// Live render — paint every cell's grid_a as a SUB_W × SUB_H subsample
// of its 16×16 internal CA, with hex stagger at TWO scales:
//   1. Inside each tile, every odd inner sub-row is x-shifted +1 px.
//   2. Across the population, every odd outer row is x-shifted by
//      tile_w/2.
//
// PUZZLE-PIECE INTERLOCK: tiles abut at stride SUB_W (no gutter
// between them). The drawn buffer is (SUB_W+1) wide so the
// shifted half of odd rows can land 1 px past the nominal tile
// edge. Adjacent tiles share that overlap column — we pre-fill it
// with the neighbour's cell colour so both tiles write the same
// value and the order of drawing doesn't matter:
//
//   buf[even sy][SUB_W] = right neighbour's cell sx=0  (read-ahead)
//   buf[odd  sy][0    ] = left  neighbour's cell sx=SUB_W-1 (read-back)
//
// Population edges (c=0 leftmost, c=GRID_COLS-1 rightmost) get
// their corresponding overflow set to BLACK — the natural jagged
// edge of a hex tessellation.

#define TILE_W      (SUB_W + 1)             /* +1 holds the 1-px shift */
#define TILE_H      SUB_H
#define OUTER_X_OFFSET  (SUB_W / 2)

static void render_pop_live() {
    /* Total width = 16 tiles abutting at stride SUB_W, plus the
     * outer x-shift on odd rows, plus the rightmost overflow column. */
    const int total_w = GRID_COLS * SUB_W + OUTER_X_OFFSET + 1;
    const int total_h = GRID_ROWS * SUB_H;
    const int x0 = (PANEL_W_PX - total_w) / 2;
    const int y0 = (PANEL_H_PX - total_h) / 2;
    uint16_t tile_buf[TILE_W * TILE_H];
    for (int r = 0; r < GRID_ROWS; r++) {
        const int outer_x_shift = (r & 1) ? OUTER_X_OFFSET : 0;
        const int ty = y0 + r * SUB_H;
        for (int c = 0; c < GRID_COLS; c++) {
            const Cell &cell = pop[r * GRID_COLS + c];
            const Cell *left  = (c > 0)              ? &pop[r * GRID_COLS + c - 1] : nullptr;
            const Cell *right = (c < GRID_COLS - 1)  ? &pop[r * GRID_COLS + c + 1] : nullptr;
            for (int sy = 0; sy < SUB_H; sy++) {
                int gy = sy * SUB_DY;
                if (gy >= CA_H) gy = CA_H - 1;
                const int inner_shift = sy & 1;

                /* Pre-fill the overlap column on the side that
                 * doesn't carry our own cells (the other side is a
                 * normal cell and overwrites this on the same loop). */
                if (inner_shift) {
                    /* buf_x=0 belongs to the LEFT neighbour's odd-row
                     * rightmost cell. */
                    if (left) {
                        int gx = (SUB_W - 1) * SUB_DX;
                        if (gx >= CA_W) gx = CA_W - 1;
                        uint8_t v = left->grid_a[gy * CA_W + gx] % K;
                        tile_buf[sy * TILE_W + 0] = ansi256_to_rgb565(left->palette[v]);
                    } else {
                        tile_buf[sy * TILE_W + 0] = 0;   /* jagged edge */
                    }
                } else {
                    /* buf_x=SUB_W belongs to the RIGHT neighbour's
                     * even-row leftmost cell. */
                    if (right) {
                        uint8_t v = right->grid_a[gy * CA_W + 0] % K;
                        tile_buf[sy * TILE_W + SUB_W] = ansi256_to_rgb565(right->palette[v]);
                    } else {
                        tile_buf[sy * TILE_W + SUB_W] = 0; /* jagged edge */
                    }
                }

                /* Our own cells, with internal stagger. */
                for (int sx = 0; sx < SUB_W; sx++) {
                    int gx = sx * SUB_DX;
                    if (gx >= CA_W) gx = CA_W - 1;
                    uint8_t v = cell.grid_a[gy * CA_W + gx] % K;
                    tile_buf[sy * TILE_W + sx + inner_shift] =
                        ansi256_to_rgb565(cell.palette[v]);
                }
            }
            /* Tiles abut at stride SUB_W (NOT TILE_W) so adjacent
             * tiles' overlap columns coincide on the shared pixel. */
            tft.drawRGBBitmap(x0 + c * SUB_W + outer_x_shift, ty,
                              tile_buf, TILE_W, TILE_H);
        }
    }
}

static void render_pop_diff() {
    int total_w = GRID_COLS * TILE_PX + TILE_PX / 2;
    int total_h = (GRID_ROWS * TILE_PX * 866) / 1000;     // hex pack
    int x0 = (PANEL_W_PX - total_w) / 2;
    int y0 = (PANEL_H_PX - total_h) / 2;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    for (int r = 0; r < GRID_ROWS; r++) {
        for (int c = 0; c < GRID_COLS; c++) {
            int idx = r * GRID_COLS + c;
            if (last_drawn[idx] == dom_cache[idx]) continue;
            int x = x0 + c * TILE_PX + ((r & 1) ? (TILE_PX / 2) : 0);
            int y = y0 + (r * TILE_PX * 866) / 1000;
            tft.fillRect(x, y, TILE_PX - 1, TILE_PX - 1, dom_rgb_cache[idx]);
            last_drawn[idx] = dom_cache[idx];
        }
    }
}

// ── tick + round ────────────────────────────────────────────────────

static void tick_all() {
    for (int i = 0; i < N_CELLS; i++) {
        Cell &c = pop[i];
        step_grid(c.genome, c.grid_a, c.grid_b);
        // swap A/B
        u8 tmp[CA_W * CA_H];
        memcpy(tmp, c.grid_a, CA_W * CA_H);
        memcpy(c.grid_a, c.grid_b, CA_W * CA_H);
        memcpy(c.grid_b, tmp, CA_W * CA_H);
        update_dom_cache(i);
    }
}

static u32 g_rounds = 0;
static int last_winner = -1, last_loser = -1;

static void run_round() {
    int ci  = (int)(prng() % N_CELLS);
    int dir = (int)(prng() % 6);
    int ni  = neighbour_idx(ci, dir);
    if (ci == ni) return;
    u32 shared_seed = prng();
    double fc = fitness(pop[ci].genome, shared_seed);
    double fn = fitness(pop[ni].genome, shared_seed);
    pop[ci].score = fc; pop[ni].score = fn;
    int winner = (fc >= fn) ? ci : ni;
    int loser  = (winner == ci) ? ni : ci;
    Cell &W = pop[winner], &L = pop[loser];
    mutate_into(L.genome, W.genome, MUT_RATE);
    palette_inherit_into(L.palette, W.palette, W.palette);
    L.score = W.score;
    L.refined_at_round = g_rounds;
    seed_grid_at(L.grid_a, prng());
    last_winner = winner; last_loser = loser;
    g_rounds++;
    update_dom_cache(loser);
}

// ── bootstrap ───────────────────────────────────────────────────────

static void bootstrap_pop(u32 seed) {
    seed_prng(seed);
    for (int i = 0; i < N_CELLS; i++) {
        seed_prng((seed ^ (u32)i * 2654435761u) ? : 1u);
        random_genome_into(pop[i].genome);
        invent_palette_into(pop[i].palette);
        seed_grid_at(pop[i].grid_a, prng());
        memset(pop[i].grid_b, 0, CA_W * CA_H);
        pop[i].score = 0;
        pop[i].refined_at_round = 0;
        update_dom_cache(i);
    }
    seed_prng(seed ^ 0xDEADBEEFu);
}

// ── WiFi + HTTP (chassis pattern from esp32_s3_xcc) ─────────────────

static WebServer server(HTTP_PORT);
static String wifi_ip_str = "", wifi_ssid_str = "";
static bool wifi_sta_connected = false;
static volatile bool g_paused = false;

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
    Serial.printf("WiFi AP '%s' at %s\n", AP_FALLBACK_SSID, wifi_ip_str.c_str());
}

static void try_connect_sta(const String &ssid, const String &pass) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());
    Serial.printf("WiFi joining '%s' ", ssid.c_str());
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 12000) {
        delay(200); Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
        wifi_sta_connected = true;
        wifi_ip_str = WiFi.localIP().toString();
        wifi_ssid_str = ssid;
        Serial.printf("WiFi joined IP %s\n", wifi_ip_str.c_str());
        if (MDNS.begin("hexca-cellular")) {
            MDNS.addService("http", "tcp", HTTP_PORT);
            Serial.println("mDNS: http://hexca-cellular.local/");
        }
    } else {
        Serial.println("STA failed; falling back to AP");
        start_ap_fallback();
    }
}

static void handle_root() {
    String html;
    html.reserve(1500);
    html += F("<!doctype html><html><head><title>cellular</title>"
              "<style>body{font-family:ui-monospace,Menlo,monospace;"
              "max-width:640px;margin:1rem auto;padding:0 1rem;"
              "background:#0d1117;color:#c9d1d9;line-height:1.4}"
              "table{border-collapse:collapse;width:100%}"
              "td{padding:4px 8px;border-bottom:1px solid #30363d}"
              "td:first-child{color:#8b949e}"
              "code{background:#161b22;padding:1px 4px;border-radius:3px}</style>"
              "</head><body>");
    html += F("<h1>cellular</h1><p>ESP32-S3 supermini · 16×16 hex CA population GA</p>");
    html += F("<table>");
    html += "<tr><td>uptime</td><td>" + String(millis() / 1000) + " s</td></tr>";
    html += "<tr><td>free heap</td><td>" + String(ESP.getFreeHeap()) + " B</td></tr>";
    html += "<tr><td>free PSRAM</td><td>" + String(ESP.getFreePsram()) + " B</td></tr>";
    html += "<tr><td>WiFi</td><td>" + String(wifi_sta_connected ? "STA" : "AP") +
            " · " + wifi_ssid_str + " · " + wifi_ip_str + "</td></tr>";
    html += "<tr><td>rounds</td><td>" + String(g_rounds) + "</td></tr>";
    html += "<tr><td>state</td><td>" + String(g_paused ? "PAUSED" : "running") + "</td></tr>";
    html += "<tr><td>render mode</td><td>" + String(g_render_live ? "live (sub-CA)" : "dominant") + "</td></tr>";
    html += "<tr><td>auto refine</td><td>" + String(g_auto_refine ? "ON" : "off") +
            String(g_auto_refine ? (" (every " + String(g_auto_delay_ms / 1000) + " s)") : "") + "</td></tr>";
    html += "<tr><td>last winner</td><td>" + String(last_winner) + "</td></tr>";
    html += "<tr><td>last loser</td><td>" + String(last_loser) + "</td></tr>";
    html += F("</table>");
    html += F("<h2>endpoints</h2><ul>"
              "<li><code>GET /info</code> — JSON status</li>"
              "<li><code>POST /wifi</code> — body <code>ssid=…&amp;password=…</code></li>"
              "<li><code>POST /reset</code> — bootstrap a fresh population</li>"
              "<li><code>POST /pause</code>, <code>POST /resume</code></li>"
              "<li><code>POST /render-mode</code> — body <code>mode=dominant|live</code></li>"
              "<li><code>POST /hunt</code> — score, sort, refresh bottom 128 cells</li>"
              "<li><code>POST /refine</code> — clone elite into 255 mutants</li>"
              "<li><code>POST /auto</code> — body <code>mode=on|off&amp;delay=N</code> "
                  "(N seconds, 1..60; on triggers Hunt then loops Refine)</li>"
              "<li><code>POST /palette-reroll</code> — invent_palette() per cell</li>"
              "<li><code>POST /palettes</code> — raw 1024-byte ANSI body, one 4-byte "
                  "palette per cell in row-major order (image-derived from browser)</li>"
              "<li><code>GET /agent?r=R&amp;c=C</code> — download an agent's HXC4 "
                  "genome.bin (4104 B), round-trips into s3lab/automaton/taxon</li>"
              "</ul></body></html>");
    server.send(200, "text/html", html);
}

static void handle_info() {
    String j;
    j.reserve(360);
    j += "{\"uptime_s\":" + String(millis() / 1000);
    j += ",\"free_heap\":" + String(ESP.getFreeHeap());
    j += ",\"free_psram\":" + String(ESP.getFreePsram());
    j += ",\"wifi_mode\":\"" + String(wifi_sta_connected ? "STA" : "AP") + "\"";
    j += ",\"ssid\":\"" + wifi_ssid_str + "\"";
    j += ",\"ip\":\"" + wifi_ip_str + "\"";
    j += ",\"rounds\":" + String(g_rounds);
    j += ",\"paused\":" + String(g_paused ? "true" : "false");
    j += ",\"last_winner\":" + String(last_winner);
    j += ",\"last_loser\":" + String(last_loser);
    j += ",\"grid_cols\":" + String(GRID_COLS);
    j += ",\"grid_rows\":" + String(GRID_ROWS);
    j += ",\"render_mode\":\"" + String(g_render_live ? "live" : "dominant") + "\"";
    j += ",\"auto_refine\":" + String(g_auto_refine ? "true" : "false");
    j += ",\"auto_delay_ms\":" + String(g_auto_delay_ms) + "}";
    server.send(200, "application/json", j);
}

static void handle_wifi() {
    String ssid = server.arg("ssid"), pass = server.arg("password");
    if (ssid.length() == 0) {
        server.send(400, "text/plain", "missing ssid"); return;
    }
    if (!write_wifi_creds(ssid, pass)) {
        server.send(500, "text/plain", "write failed"); return;
    }
    server.send(200, "text/plain", "saved; rebooting in 2 s\n");
    delay(2000); ESP.restart();
}

static void handle_reset() {
    bootstrap_pop((u32)esp_random());
    g_rounds = 0; last_winner = -1; last_loser = -1;
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    server.send(200, "text/plain", "fresh population\n");
    Serial.println("[reset] fresh population");
}

static void handle_pause()  { g_paused = true;  server.send(200, "text/plain", "paused\n"); }
static void handle_resume() { g_paused = false; server.send(200, "text/plain", "resumed\n"); }

// ── Hunt / Refine / auto-loop / palettes / agent download ──────────
//
// Browser-side parity: every operation /s3lab/cellular/tft/ exposes
// is also reachable via HTTP on the device. Memory cost is bounded
// (the score arrays sit in BSS, ~2.3 KB; the auto loop is just a
// timestamp comparison in loop()). A Hunt or Refine call blocks the
// HTTP server for ~1 s on the supermini (256 × fitness() at K=4 +
// HORIZON=25); curl --max-time 5 covers that with margin.

static double g_scores[N_CELLS];
static uint8_t g_score_order[N_CELLS];

static void score_population(uint32_t seed) {
    for (int i = 0; i < N_CELLS; i++)
        g_scores[i] = fitness(pop[i].genome, seed);
}

// Selection sort indices by score descending. POP=256 → 65k
// comparisons, ~5 ms — fine for occasional Hunt/Refine.
static void sort_indices_by_score_desc() {
    for (int i = 0; i < N_CELLS; i++) g_score_order[i] = (uint8_t)i;
    for (int i = 0; i < N_CELLS - 1; i++) {
        for (int j = i + 1; j < N_CELLS; j++) {
            if (g_scores[g_score_order[j]] > g_scores[g_score_order[i]]) {
                uint8_t t = g_score_order[i];
                g_score_order[i] = g_score_order[j];
                g_score_order[j] = t;
            }
        }
    }
}

static void do_hunt() {
    score_population(esp_random());
    sort_indices_by_score_desc();
    int boundary = N_CELLS / 2;
    for (int k = boundary; k < N_CELLS; k++) {
        int i = g_score_order[k];
        Cell &c = pop[i];
        random_genome_into(c.genome);
        invent_palette_into(c.palette);
        seed_grid_at(c.grid_a, prng());
        c.score = 0;
        c.refined_at_round = g_rounds;
        update_dom_cache(i);
    }
}

static int do_refine() {
    score_population(esp_random());
    int elite = 0;
    for (int i = 1; i < N_CELLS; i++)
        if (g_scores[i] > g_scores[elite]) elite = i;
    Cell &E = pop[elite];
    const float REFINE_RATE = 0.002f;
    for (int i = 0; i < N_CELLS; i++) {
        if (i == elite) continue;
        Cell &c = pop[i];
        mutate_into(c.genome, E.genome, REFINE_RATE);
        palette_inherit_into(c.palette, E.palette, E.palette);
        seed_grid_at(c.grid_a, prng());
        c.score = g_scores[elite];
        c.refined_at_round = g_rounds;
        update_dom_cache(i);
    }
    return elite;
}

static void handle_hunt() {
    do_hunt();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    server.send(200, "text/plain", "hunt: bottom 128 cells refreshed\n");
    Serial.println("[hunt] bottom 128 cells refreshed");
}

static void handle_refine() {
    int elite = do_refine();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    String out = String("refine: cloned cell #") + elite +
                 " (score " + String(g_scores[elite], 3) + ") into 255 mutants\n";
    server.send(200, "text/plain", out);
    Serial.print("[refine] "); Serial.print(out);
}

// POST /palette-reroll: invent_palette() per cell, mirroring the
// browser's "🎨 Reroll palettes" button.
static void handle_palette_reroll() {
    for (int i = 0; i < N_CELLS; i++) {
        invent_palette_into(pop[i].palette);
        update_dom_cache(i);
    }
    if (g_render_live) render_pop_live();
    else                { render_pop_full(); render_pop_diff(); }
    server.send(200, "text/plain", "rerolled 256 palettes\n");
}

// POST /palettes: accept exactly N_CELLS * PAL_BYTES (= 1024 bytes)
// of ANSI indices. Each 4-byte chunk replaces the corresponding
// cell's palette in row-major order, so the browser can compute
// image-derived palettes and push them in one round trip.
static void handle_palettes() {
    if (!server.hasArg("plain")) {
        server.send(400, "text/plain", "POST raw 1024-byte palette body\n");
        return;
    }
    const String &body = server.arg("plain");
    if (body.length() != N_CELLS * PAL_BYTES) {
        server.send(400, "text/plain",
                    "expected 1024 bytes (256 cells × 4 ANSI indices)\n");
        return;
    }
    const uint8_t *buf = (const uint8_t *)body.c_str();
    for (int i = 0; i < N_CELLS; i++) {
        memcpy(pop[i].palette, buf + i * PAL_BYTES, PAL_BYTES);
        update_dom_cache(i);
    }
    if (g_render_live) render_pop_live();
    else                { render_pop_full(); render_pop_diff(); }
    server.send(200, "text/plain", "256 palettes applied\n");
    Serial.println("[palettes] 256 palettes applied");
}

// POST /auto body: mode=on|off, optional delay=N (seconds, 1..60).
// When on: device fires a Refine every `delay` seconds in loop().
// Initial Hunt happens once on transition off→on, mirroring the
// browser's "🔁 Full auto" semantics.
static volatile bool     g_auto_refine = false;
static volatile uint32_t g_auto_delay_ms = 3000;
static uint32_t g_next_auto_at = 0;

static void handle_auto() {
    String mode_s = server.arg("mode");
    String delay_s = server.arg("delay");
    if (delay_s.length() > 0) {
        long d = delay_s.toInt();
        if (d < 1) d = 1;
        if (d > 60) d = 60;
        g_auto_delay_ms = (uint32_t)(d * 1000);
    }
    if (mode_s == "on") {
        if (!g_auto_refine) {
            g_auto_refine = true;
            do_hunt();
            if (g_render_live) render_pop_live(); else render_pop_diff();
            g_next_auto_at = millis() + g_auto_delay_ms;
        }
    } else if (mode_s == "off") {
        g_auto_refine = false;
    } else if (mode_s.length() > 0) {
        server.send(400, "text/plain", "mode must be on or off\n");
        return;
    }
    String out = String("auto: ") + (g_auto_refine ? "on" : "off") +
                 ", delay = " + String(g_auto_delay_ms / 1000) + "s\n";
    server.send(200, "text/plain", out);
}

// GET /agent?r=R&c=C: download a single agent's genome.bin (HXC4
// 4104-byte format). Same wire format as /s3lab/, /automaton/,
// /taxon/, and the device's /winner.bin — round-trips into any of
// those.
static uint8_t g_agent_buf[TAIL_BYTES];

static void handle_agent() {
    int r = server.arg("r").toInt();
    int c = server.arg("c").toInt();
    if (r < 0 || r >= GRID_ROWS || c < 0 || c >= GRID_COLS) {
        server.send(400, "text/plain",
                    "out of bounds (r=0..15, c=0..15)\n");
        return;
    }
    const Cell &cell = pop[r * GRID_COLS + c];
    memcpy(g_agent_buf, TAIL_MAGIC, MAGIC_BYTES);
    memcpy(g_agent_buf + MAGIC_BYTES, cell.palette, PAL_BYTES);
    memcpy(g_agent_buf + MAGIC_BYTES + PAL_BYTES, cell.genome, GBYTES);
    String fname = String("agent-r") + (r < 10 ? "0" : "") + r +
                   "-c" + (c < 10 ? "0" : "") + c + ".genome.bin";
    server.sendHeader("Content-Disposition",
                      "attachment; filename=\"" + fname + "\"");
    server.setContentLength(TAIL_BYTES);
    server.send(200, "application/octet-stream", "");
    server.sendContent_P((const char *)g_agent_buf, TAIL_BYTES);
}

// POST /render-mode body: mode=dominant or mode=live. Flips the
// per-tick render path and forces an immediate full repaint so the
// switch is visible without waiting for the next tick.
static void handle_render_mode() {
    String m = server.arg("mode");
    if (m == "live") {
        g_render_live = true;
    } else if (m == "dominant") {
        g_render_live = false;
    } else {
        server.send(400, "text/plain",
                    "mode must be \"dominant\" or \"live\"\n");
        return;
    }
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    server.send(200, "text/plain",
                String("render mode: ") + (g_render_live ? "live" : "dominant") + "\n");
}

static void comms_setup() {
    String ssid, pass;
    if (read_wifi_creds(ssid, pass)) try_connect_sta(ssid, pass);
    else { Serial.println("no /wifi.txt; AP-mode setup"); start_ap_fallback(); }
    server.on("/",                HTTP_GET,  handle_root);
    server.on("/info",            HTTP_GET,  handle_info);
    server.on("/wifi",            HTTP_POST, handle_wifi);
    server.on("/reset",           HTTP_POST, handle_reset);
    server.on("/pause",           HTTP_POST, handle_pause);
    server.on("/resume",          HTTP_POST, handle_resume);
    server.on("/render-mode",     HTTP_POST, handle_render_mode);
    server.on("/hunt",            HTTP_POST, handle_hunt);
    server.on("/refine",          HTTP_POST, handle_refine);
    server.on("/auto",            HTTP_POST, handle_auto);
    server.on("/palette-reroll",  HTTP_POST, handle_palette_reroll);
    server.on("/palettes",        HTTP_POST, handle_palettes);
    server.on("/agent",           HTTP_GET,  handle_agent);
    server.begin();
    Serial.printf("HTTP on :%d\n", HTTP_PORT);
}

// ── setup / loop ────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    uint32_t t0 = millis();
    while (!Serial && (millis() - t0) < 2000) delay(10);
    Serial.println("\n=== cellular ESP32-S3 (PSRAM-backed population) ===");

    if (!LittleFS.begin(true)) Serial.println("LittleFS mount failed");
    if (!psramInit())          Serial.println("PSRAM init FAILED — population will not fit!");

    size_t need = (size_t)N_CELLS * sizeof(Cell);
    pop = (Cell *)heap_caps_malloc(need,
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!pop) {
        Serial.printf("PSRAM allocation of %u B FAILED\n", (unsigned)need);
        while (1) delay(1000);
    }
    Serial.printf("PSRAM: allocated %u B (%u KiB) for population\n",
                  (unsigned)need, (unsigned)(need / 1024));

    pinMode(PIN_BL, OUTPUT); digitalWrite(PIN_BL, HIGH);
    tft.initR(INITR_144GREENTAB);
    tft.setSPISpeed(SPI_HZ);
    tft.setRotation(0);
    tft.invertDisplay(true);
    tft.fillScreen(ST77XX_BLACK);

    u32 seed = esp_random() ^ (u32)esp_timer_get_time();
    bootstrap_pop(seed);
    render_pop_full();
    if (g_render_live) render_pop_live(); else render_pop_diff();
    Serial.printf("bootstrapped with seed %u (render mode: %s)\n",
                  seed, g_render_live ? "live" : "dominant");

    comms_setup();
    Serial.println("=== running tournament GA + TFT ===");
}

static uint32_t next_tick_ms  = 0;
static uint32_t next_round_ms = 0;

void loop() {
    server.handleClient();
    if (g_paused) { delay(20); return; }
    uint32_t now = millis();
    if (now >= next_tick_ms) {
        tick_all();
        if (g_render_live) render_pop_live();
        else                render_pop_diff();
        next_tick_ms = now + TICK_MS;
    }
    if (now >= next_round_ms) {
        run_round();
        next_round_ms = now + ROUND_MS;
        if (g_rounds % 30 == 0) {
            Serial.printf("round %u  free_heap=%u  free_psram=%u\n",
                          g_rounds, ESP.getFreeHeap(), ESP.getFreePsram());
        }
    }
    if (g_auto_refine && now >= g_next_auto_at) {
        do_refine();
        if (g_render_live) render_pop_live(); else render_pop_diff();
        g_next_auto_at = now + g_auto_delay_ms;
        Serial.printf("[auto] refine fired (next in %u ms)\n",
                      (unsigned)g_auto_delay_ms);
    }
    delay(5);
}
