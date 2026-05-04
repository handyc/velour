// esp32_s3_forge — Forge wireworld CA running on a hardware timer.
//
// PIPELINE per timer fire (20 kHz):
//   1. Read ADC1 (GPIO1, 12 bit). Map [0, 4095] → rate ∈ [0, 1].
//      period = clamp(round(3 / rate), 3, 65535) ticks (rate ≤ 0
//      means "never pulse"). Wireworld can't sustain pulses faster
//      than every 3 ticks (head→tail→wire), so 3 is the floor.
//   2. If `tick % period == 0`, force INPUT_X/INPUT_Y cell to head.
//   3. Step the hex K=4 wireworld CA once.
//   4. Read OUTPUT_X/OUTPUT_Y; if it's a head (value 2), drive
//      OUTPUT_PIN HIGH for one tick; otherwise drive LOW.
//
// Default circuit is a single horizontal wire from (2, 8) to (13, 8)
// — a passthrough — so a 1 kHz tone on the ADC pin produces a
// 1 kHz pulse train on the output pin (rate-faithful within the
// wireworld 1/3-tick limit).
//
// Serial commands (115200 baud):
//   STATS   - prints step rate, input rate, head count, etc.
//   GRID    - dumps the current 16×16 grid as 256 hex digits
//   GRID <256-hex>  - replaces the grid (each pair = one cell, 0-3)
//   PORTS <ix> <iy> <ox> <oy>  - moves input + output ports
//   STOP    - pauses the timer
//   RUN     - resumes the timer
//
// Pin assignments:
//   GPIO1  = ADC input  (audio / voltage in)
//   GPIO2  = digital output  (head events out → headphone via RC)
//   GPIO15 = onboard LED (heartbeat at ~1 Hz)

#include <Arduino.h>
#include <esp_timer.h>
#include <driver/adc.h>

// ── compile-time constants ──────────────────────────────────────
#define K              4
#define WIDTH          16
#define HEIGHT         16
#define NCELLS         (WIDTH * HEIGHT)
#define LUT_SIZE       (K * K * K * K * K * K * K)   // 16384 = 4^7

#define STEP_HZ        20000               // timer fires this often
#define STEP_US        (1000000 / STEP_HZ) // 50 µs per tick

#define ADC_PIN        1                   // ADC1_CH0
#define OUTPUT_PIN     2
#define LED_PIN        15

// Default ports (passthrough centred on the grid).
static int input_x  = 2,  input_y  = 8;
static int output_x = 13, output_y = 8;

// ── state ───────────────────────────────────────────────────────
static uint8_t grid[NCELLS];
static uint8_t scratch[NCELLS];
static uint8_t lut[LUT_SIZE];
static volatile uint64_t tick_count = 0;
static volatile uint32_t input_period = 0;     // 0 = no input pulses
static volatile uint32_t head_count = 0;        // ticks output had a head
static volatile bool running = true;
static esp_timer_handle_t step_timer = nullptr;


// ── wireworld lookup-table builder ──────────────────────────────
// idx = self * K^6 + n0*K^5 + n1*K^4 + n2*K^3 + n3*K^2 + n4*K + n5
// (matches forge/sim.py exactly)
static void build_lut() {
    for (int s = 0; s < K; s++) {
        for (int n = 0; n < 4096; n++) {            // K^6 = 4096
            int n0 = (n >> 10) & 3;
            int n1 = (n >>  8) & 3;
            int n2 = (n >>  6) & 3;
            int n3 = (n >>  4) & 3;
            int n4 = (n >>  2) & 3;
            int n5 = (n      ) & 3;
            int heads = (n0 == 2) + (n1 == 2) + (n2 == 2)
                      + (n3 == 2) + (n4 == 2) + (n5 == 2);
            uint8_t out;
            if (s == 0) out = 0;                    // empty stays empty
            else if (s == 2) out = 3;               // head → tail
            else if (s == 3) out = 1;               // tail → wire
            else out = (heads == 1 || heads == 2) ? 2 : 1;
            lut[s * 4096 + n] = out;
        }
    }
}


// ── default grid: a passthrough wire ────────────────────────────
static void install_passthrough() {
    memset(grid, 0, NCELLS);
    for (int x = 2; x <= 13; x++) grid[8 * WIDTH + x] = 1;
}


// ── one CA tick ─────────────────────────────────────────────────
// Hex offset-column convention (matches forge/sim.py / taxon.engine).
static IRAM_ATTR void step_ca() {
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            int even = !(x & 1);
            uint8_t s = grid[y * WIDTH + x];
            uint8_t n0 = (y > 0)            ? grid[(y - 1) * WIDTH + x] : 0;
            int ner   = even ? y - 1 : y;
            uint8_t n1 = (ner >= 0 && x + 1 < WIDTH)
                ? grid[ner * WIDTH + (x + 1)] : 0;
            int ser   = even ? y : y + 1;
            uint8_t n2 = (ser < HEIGHT && x + 1 < WIDTH)
                ? grid[ser * WIDTH + (x + 1)] : 0;
            uint8_t n3 = (y + 1 < HEIGHT)   ? grid[(y + 1) * WIDTH + x] : 0;
            int swr   = even ? y : y + 1;
            uint8_t n4 = (swr < HEIGHT && x - 1 >= 0)
                ? grid[swr * WIDTH + (x - 1)] : 0;
            int nwr   = even ? y - 1 : y;
            uint8_t n5 = (nwr >= 0 && x - 1 >= 0)
                ? grid[nwr * WIDTH + (x - 1)] : 0;
            uint32_t idx = (uint32_t)((s << 12) | (n0 << 10) | (n1 << 8)
                          | (n2 << 6) | (n3 << 4) | (n4 << 2) | n5);
            scratch[y * WIDTH + x] = lut[idx];
        }
    }
    memcpy(grid, scratch, NCELLS);
}


// ── timer ISR — runs at STEP_HZ ──────────────────────────────────
static IRAM_ATTR void on_step(void* /*arg*/) {
    if (!running) return;

    tick_count++;
    // 1. Sample ADC and rate-encode → period.
    int raw = adc1_get_raw(ADC1_CHANNEL_0);          // 0..4095
    if (raw <= 0) {
        input_period = 0;
    } else {
        // rate = raw / 4095, period = round(3 / rate) ≈ 3*4095/raw
        uint32_t per = (uint32_t)((3 * 4095) / raw);
        if (per < 3) per = 3;
        input_period = per;
    }
    // 2. Inject input pulse?
    if (input_period > 0 && (tick_count % input_period) == 0) {
        grid[input_y * WIDTH + input_x] = 2;          // force head
    }
    // 3. Step the rule.
    step_ca();
    // 4. Drive output pin from the head bit at the output cell.
    uint8_t out_v = grid[output_y * WIDTH + output_x];
    if (out_v == 2) {
        head_count++;
        gpio_set_level((gpio_num_t)OUTPUT_PIN, 1);
    } else {
        gpio_set_level((gpio_num_t)OUTPUT_PIN, 0);
    }
}


// ── serial command parser ──────────────────────────────────────
static String cmd_buf;

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static void handle_cmd(const String& cmd) {
    if (cmd == "STATS") {
        Serial.printf("ticks=%llu  input_period=%u  head_count=%u  "
                      "running=%d  ports=in(%d,%d) out(%d,%d)\n",
                      (unsigned long long)tick_count,
                      (unsigned)input_period,
                      (unsigned)head_count,
                      (int)running,
                      input_x, input_y, output_x, output_y);
        head_count = 0;
        return;
    }
    if (cmd == "STOP")  { running = false; Serial.println("stopped"); return; }
    if (cmd == "RUN")   { running = true;  Serial.println("running"); return; }
    if (cmd == "GRID") {
        Serial.print("GRID ");
        for (int i = 0; i < NCELLS; i++) Serial.printf("%01x", grid[i] & 0xf);
        Serial.println();
        return;
    }
    if (cmd.startsWith("GRID ")) {
        String hex = cmd.substring(5);
        hex.trim();
        if (hex.length() != NCELLS) {
            Serial.printf("err: GRID needs %d hex digits, got %d\n",
                          NCELLS, hex.length());
            return;
        }
        bool was = running; running = false;
        for (int i = 0; i < NCELLS; i++) {
            int v = hex_nibble(hex[i]);
            if (v < 0 || v > 3) {
                Serial.printf("err: bad hex at %d\n", i);
                running = was;
                return;
            }
            grid[i] = (uint8_t)v;
        }
        running = was;
        Serial.println("grid loaded");
        return;
    }
    if (cmd.startsWith("PORTS ")) {
        int ix, iy, ox, oy;
        if (sscanf(cmd.c_str() + 6, "%d %d %d %d",
                   &ix, &iy, &ox, &oy) == 4
            && 0 <= ix && ix < WIDTH && 0 <= iy && iy < HEIGHT
            && 0 <= ox && ox < WIDTH && 0 <= oy && oy < HEIGHT) {
            input_x = ix; input_y = iy; output_x = ox; output_y = oy;
            Serial.printf("ports: in(%d,%d) out(%d,%d)\n",
                          input_x, input_y, output_x, output_y);
        } else {
            Serial.println("err: PORTS needs 4 ints in [0, 16)");
        }
        return;
    }
    if (cmd == "RESET") { install_passthrough(); Serial.println("reset"); return; }
    Serial.printf("unknown command: %s\n", cmd.c_str());
}

static void poll_serial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmd_buf.length()) {
                handle_cmd(cmd_buf);
                cmd_buf = "";
            }
        } else if (cmd_buf.length() < 600) {
            cmd_buf += c;
        }
    }
}


// ── boot ───────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("esp32_s3_forge — wireworld 16x16 hex CA");
    Serial.printf("step rate %d Hz, max pulse %d Hz, ADC=GPIO%d, OUT=GPIO%d\n",
                  STEP_HZ, STEP_HZ / 3, ADC_PIN, OUTPUT_PIN);

    pinMode(LED_PIN, OUTPUT);
    pinMode(OUTPUT_PIN, OUTPUT);
    digitalWrite(OUTPUT_PIN, 0);

    // ADC1 channel 0 = GPIO1. 12-bit, 0..4095. Atten 11dB so the
    // full range is ~0..3.1 V (covers a 0-3.3V signal safely).
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(ADC1_CHANNEL_0, ADC_ATTEN_DB_11);

    build_lut();
    install_passthrough();

    const esp_timer_create_args_t args = {
        .callback = on_step, .arg = nullptr,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "ww-step",
        .skip_unhandled_events = true,
    };
    esp_timer_create(&args, &step_timer);
    esp_timer_start_periodic(step_timer, STEP_US);

    Serial.println("ready. send STATS / GRID / PORTS / STOP / RUN / RESET");
}

void loop() {
    poll_serial();
    static uint32_t led_t = 0;
    if (millis() - led_t > 500) {
        led_t = millis();
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
}
