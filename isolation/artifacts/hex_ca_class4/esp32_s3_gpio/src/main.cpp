// Hex-CA GPIO actuator — ESP32-S3 SuperMini.
//
// Runs an evolved hex-CA ruleset in memory and drives configured GPIO
// pins from individual cell states. Sibling of esp_st7735s/ which
// drives a TFT — same engine, different output device.
//
// Inputs (LittleFS):
//   /genome.bin    — 4104-byte tail [HXC4 magic + 4 palette + 4096 genome]
//                    same format the hunter's winner_<N>.bin uses.
//   /gpio_map.txt  — one binding per line: cell_x,cell_y,gpio_pin,state_mask
//                    state_mask is 4-bit (K=4 states); bit N set means
//                    pin HIGH when cell value == N.
//
// On first boot a default /gpio_map.txt is written and a random
// fallback genome is used. Upload a real /genome.bin from a hunt to
// get class-4 dynamics.
//
// Build & flash:
//   pio run -t upload && pio device monitor
//
// Memory: ~5 KB BSS for grids + bindings + genome. Trivial on the S3.

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_system.h>

#define K           4
#define NSIT        16384
#define GBYTES      4096
#define PAL_BYTES   4
#define MAGIC_BYTES 4
#define TAIL_MAGIC  "HXC4"
#define TAIL_BYTES  (MAGIC_BYTES + PAL_BYTES + GBYTES)

#define GRID_W       14
#define GRID_H       14
#define TICK_MS      1000      // 1 Hz default; lower for faster
#define MAX_BINDINGS       64
#define MAX_INPUT_BINDINGS 32

typedef uint8_t u8;

struct GpioBinding {
    int  cell_x;
    int  cell_y;
    int  gpio_pin;
    u8   state_mask;   // bit N set ⇒ pin HIGH when cell value == N
};

// Input binding — pin drives cell. Pin uses INPUT_PULLUP, so a button
// shorting to GND reads LOW. When pin is LOW, cell is forced to
// low_state; HIGH ⇒ high_state. This makes the CA a logic processor:
// external signals dictate a few cells, the rule propagates, output
// cells respond to whatever the dynamics produce.
struct InputBinding {
    int gpio_pin;
    int cell_x;
    int cell_y;
    u8  low_state;
    u8  high_state;
};

// ── BSS arenas ────────────────────────────────────────────────────────

static u8 genome[GBYTES];
static u8 palette[PAL_BYTES];
static int genome_loaded = 0;

static u8 grid_a[GRID_W * GRID_H];
static u8 grid_b[GRID_W * GRID_H];

static GpioBinding  bindings[MAX_BINDINGS];
static int          n_bindings = 0;
static InputBinding input_bindings[MAX_INPUT_BINDINGS];
static int          n_input_bindings = 0;

// Hex offset deltas — match hunter.c.
static const int DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int DXE[6] = {  0,  1, -1,  1, -1,  0 };
static const int DXO[6] = { -1,  0, -1,  1,  0,  1 };

// ── Engine: same as hunter.c ──────────────────────────────────────────

static uint32_t lcg_state;
static inline uint32_t lcg() {
    lcg_state = lcg_state * 1103515245u + 12345u;
    return lcg_state >> 16;
}

static inline int g_get(const u8 *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
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

// ── Genome loading ────────────────────────────────────────────────────

static int load_genome_from_fs() {
    File f = LittleFS.open("/genome.bin", "r");
    if (!f) return -1;
    if ((size_t)f.size() < TAIL_BYTES) { f.close(); return -1; }
    char magic[MAGIC_BYTES];
    int ok = (f.read((u8 *)magic, MAGIC_BYTES) == MAGIC_BYTES)
          && (memcmp(magic, TAIL_MAGIC, MAGIC_BYTES) == 0)
          && (f.read(palette, PAL_BYTES) == PAL_BYTES)
          && (f.read(genome,  GBYTES)    == GBYTES);
    f.close();
    return ok ? 0 : -1;
}

static void random_fallback_genome() {
    for (int i = 0; i < GBYTES; i++) genome[i]  = esp_random() & 0xFF;
    for (int i = 0; i < PAL_BYTES; i++) palette[i] = 16 + (esp_random() % 216);
}

// ── GPIO map parsing ──────────────────────────────────────────────────

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

// Parse one binding line: cell_x,cell_y,gpio_pin,state_mask.
// Returns 0 on success, -1 on malformed.
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
// (the caller has already verified the "input," prefix). Returns 0 on
// success, -1 on malformed.
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

        // Input binding (pin -> cell)?
        if (strncmp(t, "input,", 6) == 0) {
            if (n_input_bindings >= MAX_INPUT_BINDINGS) {
                Serial.printf("  warn: more than %d input bindings, "
                              "ignoring rest\n", MAX_INPUT_BINDINGS);
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

        // Output binding (cell -> pin)
        if (n_bindings >= MAX_BINDINGS) {
            Serial.printf("  warn: more than %d bindings, ignoring rest\n",
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
        "# CA cell <-> GPIO bindings.\n"
        "#\n"
        "# Output (cell drives pin):\n"
        "#   cell_x,cell_y,gpio_pin,state_mask\n"
        "# state_mask is 4-bit (K=4 states); bit N set => pin HIGH when\n"
        "# cell value == N. Examples:\n"
        "#   0x8 = HIGH only when cell == 3\n"
        "#   0x7 = LOW  only when cell == 3 (other states HIGH)\n"
        "#   0xA = HIGH on states 1 and 3 (alternating)\n"
        "#   0xF = always HIGH; 0x0 = always LOW\n"
        "#\n"
        "# Input (pin drives cell):\n"
        "#   input,gpio_pin,cell_x,cell_y,low_state,high_state\n"
        "# Pin uses INPUT_PULLUP (button to GND reads LOW). When pin is\n"
        "# LOW, cell forced to low_state; HIGH => high_state. Per-tick\n"
        "# order: read inputs -> step CA -> drive outputs.\n"
        "#\n"
        "# Demo outputs: four pins watching a horizontal strip of cells,\n"
        "# each firing on state 3.\n"
        "3,5,4,0x8\n"
        "4,5,5,0x8\n"
        "5,5,6,0x8\n"
        "6,5,7,0x8\n"
        "#\n"
        "# Demo inputs (commented out): two buttons clamping corner cells.\n"
        "# Uncomment + adjust pins to use.\n"
        "# input,9,0,0,0,3\n"
        "# input,10,13,13,0,3\n"
    );
    f.close();
}

// ── GPIO dispatch ─────────────────────────────────────────────────────

static inline int level_for(const GpioBinding &b, int cell_value) {
    return (b.state_mask >> cell_value) & 1;
}

static void apply_bindings(const u8 *grid) {
    for (int i = 0; i < n_bindings; i++) {
        const GpioBinding &b = bindings[i];
        int v = grid[b.cell_y * GRID_W + b.cell_x];
        digitalWrite(b.gpio_pin, level_for(b, v));
    }
}

// Read each input pin and clamp the bound cell. Pin uses INPUT_PULLUP,
// so digitalRead returns 0 when the pin is grounded (button pressed)
// and 1 when floating. low_state vs high_state are arbitrary CA states.
static void apply_input_bindings(u8 *grid) {
    for (int i = 0; i < n_input_bindings; i++) {
        const InputBinding &b = input_bindings[i];
        int high = digitalRead(b.gpio_pin);
        grid[b.cell_y * GRID_W + b.cell_x] = high ? b.high_state : b.low_state;
    }
}

// ── setup / loop ──────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    uint32_t t_start = millis();
    while (!Serial && (millis() - t_start) < 2000) delay(10);
    Serial.println();
    Serial.println("=== hex-CA GPIO actuator — ESP32-S3 ===");

    if (!LittleFS.begin(true)) {
        Serial.println("LittleFS mount failed");
    }

    if (load_genome_from_fs() == 0) {
        genome_loaded = 1;
        Serial.printf("genome loaded; palette=[%d %d %d %d]\n",
                      palette[0], palette[1], palette[2], palette[3]);
    } else {
        random_fallback_genome();
        genome_loaded = 0;
        Serial.println("WARN: no /genome.bin or invalid magic — using "
                       "random fallback (will likely be class-1 garbage). "
                       "Upload a winner_<N>.bin from the hunter for "
                       "class-4 dynamics.");
    }

    if (!LittleFS.exists("/gpio_map.txt")) {
        write_default_gpio_map();
        Serial.println("wrote default /gpio_map.txt — edit to taste");
    }
    load_bindings_from_fs();
    Serial.printf("%d output bindings, %d input bindings loaded\n",
                  n_bindings, n_input_bindings);

    for (int i = 0; i < n_bindings; i++) {
        const GpioBinding &b = bindings[i];
        if (b.gpio_pin == 19 || b.gpio_pin == 20) {
            Serial.printf("  warn: GPIO %d is the USB-OTG D+/D- line on "
                          "the SuperMini — driving it will likely kill "
                          "USB CDC (Serial)\n", b.gpio_pin);
        }
        pinMode(b.gpio_pin, OUTPUT);
        digitalWrite(b.gpio_pin, LOW);
        Serial.printf("  out: cell (%d,%d) -> GPIO %d  mask=0x%X\n",
                      b.cell_x, b.cell_y, b.gpio_pin, b.state_mask);
    }

    for (int i = 0; i < n_input_bindings; i++) {
        const InputBinding &b = input_bindings[i];
        if (b.gpio_pin == 19 || b.gpio_pin == 20) {
            Serial.printf("  warn: GPIO %d is the USB-OTG D+/D- line\n",
                          b.gpio_pin);
        }
        pinMode(b.gpio_pin, INPUT_PULLUP);
        Serial.printf("  in : GPIO %d (pull-up) -> cell (%d,%d) "
                      "low=%d high=%d\n",
                      b.gpio_pin, b.cell_x, b.cell_y,
                      b.low_state, b.high_state);
    }

    uint32_t grid_seed = esp_random();
    seed_grid(grid_a, grid_seed);
    Serial.printf("grid seed = %u   tick = %d ms\n",
                  (unsigned)grid_seed, TICK_MS);

    // Apply inputs first, then outputs, so t=0 state matches the wires.
    apply_input_bindings(grid_a);
    apply_bindings(grid_a);
}

void loop() {
    static u8      *cur = grid_a;
    static u8      *nxt = grid_b;
    static uint32_t tick = 0;

    delay(TICK_MS);
    apply_input_bindings(cur);   // pin reads clamp cells before stepping
    step_grid(genome, cur, nxt);
    apply_bindings(nxt);
    u8 *t = cur; cur = nxt; nxt = t;
    tick++;

    // Heartbeat every 10 ticks so monitor users see what's happening.
    if (tick % 10 == 0) {
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
