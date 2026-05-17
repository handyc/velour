/*
 * keychain_quine — ESP32-S3 pocket-DB keychain firmware.
 *
 * Behaviour: the chip boots, prints a banner with the embedded seed's
 * sha256, then waits forever for host commands over USB-CDC.
 *
 * Wire protocol (matches spoeqi/keychain_device.py):
 *
 *   Boot banner (unprompted, on USB-CDC ready):
 *     "VELOUR-KEYCHAIN v1 sha=<hex64>\n"
 *
 *   Host  → Device:    Device → Host:
 *     "HELLO\n"        "OK sha=<hex64> size=16384\n" + 16,384 raw bytes
 *     "SHA\n"          "OK sha=<hex64>\n"
 *     "PING\n"         "PONG\n"
 *     "BYE\n"          "OK\n"
 *
 * The whole 16 KB seed is stored in flash, served from a pointer the
 * linker hands us via the platformio ``board_build.embed_files`` rule.
 * No RAM allocation; no PSRAM; no CA simulation on-device — the host
 * does the CA expansion. (See the comments in spoeqi/keychain.py for
 * why putting the chain walk in PSRAM would be slower than just
 * shipping the seed.)
 */

#include <Arduino.h>
#include "mbedtls/sha256.h"

// PlatformIO `embed_files` makes data/seed.bin available as a
// linker-generated symbol pair.  The names are
// "_binary_<path-with-_-instead-of-/>_start" / "_end" — easiest to
// declare them as extern char[] and let the linker fix them up.
extern const uint8_t seed_start[] asm("_binary_data_seed_bin_start");
extern const uint8_t seed_end[]   asm("_binary_data_seed_bin_end");

static const size_t SEED_BYTES = 16384;

// Computed once at boot; cached.  64 hex chars + NUL.
static char seed_sha_hex[65];

// ──────────────────────────────────────────────────────────────────────
// helpers
// ──────────────────────────────────────────────────────────────────────

static void hex_encode(const uint8_t *in, size_t n, char *out) {
    static const char H[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        out[2*i]     = H[in[i] >> 4];
        out[2*i + 1] = H[in[i] & 0xF];
    }
    out[2*n] = '\0';
}

static void compute_seed_sha(void) {
    uint8_t digest[32];
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    mbedtls_sha256_starts(&ctx, 0);          // 0 = SHA-256 (not 224)
    mbedtls_sha256_update(&ctx, seed_start, SEED_BYTES);
    mbedtls_sha256_finish(&ctx, digest);
    mbedtls_sha256_free(&ctx);
    hex_encode(digest, 32, seed_sha_hex);
}

// Drain the input until '\n' or `cap` chars, copy into `buf` (NUL-term).
// Returns the number of payload chars (not counting the '\n').  Blocks.
static size_t read_line(char *buf, size_t cap) {
    size_t n = 0;
    while (n + 1 < cap) {
        while (!Serial.available()) {
            delay(1);
        }
        int c = Serial.read();
        if (c < 0) continue;
        if (c == '\r') continue;
        if (c == '\n') break;
        buf[n++] = (char)c;
    }
    buf[n] = '\0';
    return n;
}

static bool ieq(const char *a, const char *b) {
    while (*a && *b) {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return false;
        a++; b++;
    }
    return *a == 0 && *b == 0;
}

// ──────────────────────────────────────────────────────────────────────
// command handlers
// ──────────────────────────────────────────────────────────────────────

static void cmd_hello(void) {
    Serial.print("OK sha=");
    Serial.print(seed_sha_hex);
    Serial.print(" size=");
    Serial.println(SEED_BYTES);
    // Stream the raw 16,384 bytes in one shot.  USB-CDC handles its
    // own framing; the host knows how many bytes to expect from the
    // size= field we just printed.
    Serial.write(seed_start, SEED_BYTES);
    Serial.flush();
}

static void cmd_sha(void) {
    Serial.print("OK sha=");
    Serial.println(seed_sha_hex);
}

static void cmd_ping(void) {
    Serial.println("PONG");
}

static void cmd_bye(void) {
    Serial.println("OK");
}

static void cmd_unknown(const char *line) {
    Serial.print("ERR unknown command: ");
    Serial.println(line);
}

// ──────────────────────────────────────────────────────────────────────
// setup / loop
// ──────────────────────────────────────────────────────────────────────

void setup(void) {
    Serial.begin(115200);
    // Wait up to 3 s for the host to attach its CDC endpoint — past
    // that we proceed anyway so the device works on every boot, even
    // unattached (the banner is then just lost into the void).
    uint32_t t0 = millis();
    while (!Serial && (millis() - t0) < 3000) {
        delay(10);
    }
    compute_seed_sha();
    Serial.print("VELOUR-KEYCHAIN v1 sha=");
    Serial.println(seed_sha_hex);
}

void loop(void) {
    char line[32];
    size_t n = read_line(line, sizeof(line));
    if (n == 0) return;
    if      (ieq(line, "HELLO")) cmd_hello();
    else if (ieq(line, "SHA"))   cmd_sha();
    else if (ieq(line, "PING"))  cmd_ping();
    else if (ieq(line, "BYE"))   cmd_bye();
    else                          cmd_unknown(line);
}
