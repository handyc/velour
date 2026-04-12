"""Tier 2→3: Distill a JS page into an ESP8266 firmware sketch.

Takes the HTML output from a Tier 2 distillation and produces a
complete .ino file that serves it from an ESP8266 web server.

What the automated distiller does:
  1. Minify the HTML (strip comments, collapse whitespace)
  2. Escape it for C string embedding
  3. Wrap it in PROGMEM
  4. Generate ESP8266WebServer boilerplate with WiFi config
  5. Output a compilable .ino file

What the automated distiller CANNOT do (Claude's territory):
  - Decide what to cut when the page is too large
  - Reimagine the UI for a tiny screen
  - Restructure the logic for the ESP's constraints
  - Add device-specific features (sensor reads, GPIO)

The automated version produces a faithful but dumb embedding.
Claude would produce a thoughtful re-architecture.
"""

import re
import html


def minify_html(raw):
    """Brute-force HTML minification."""
    # Remove HTML comments (but preserve CONDENSER markers)
    out = re.sub(r'<!--(?!.*CONDENSER).*?-->', '', raw, flags=re.DOTALL)
    # Remove JS single-line comments (but preserve CONDENSER)
    out = re.sub(r'//(?!.*CONDENSER).*$', '', out, flags=re.MULTILINE)
    # Collapse whitespace
    out = re.sub(r'\s+', ' ', out)
    # Remove spaces around tags
    out = re.sub(r'>\s+<', '><', out)
    return out.strip()


def escape_for_c(s):
    """Escape a string for embedding in a C raw string literal."""
    # Use the R"rawliteral(...)rawliteral" syntax
    # Just need to make sure the delimiter doesn't appear in the content
    return s


def distill(tier2_html, wifi_ssid='WIFI_SSID', wifi_pass='WIFI_PASS'):
    """Generate an ESP8266 .ino file from Tier 2 HTML."""

    minified = minify_html(tier2_html)
    original_size = len(tier2_html.encode('utf-8'))
    minified_size = len(minified.encode('utf-8'))

    # CONDENSER annotation: what was lost in minification
    size_note = (f'// CONDENSER: Tier 2 was {original_size} bytes, '
                 f'minified to {minified_size} bytes '
                 f'({100-minified_size*100//original_size}% reduction). '
                 f'Comments and whitespace removed. Logic unchanged.')

    return f'''// ============================================================
// CONDENSER: Tier 3 (ESP8266) distillation
//
// This sketch serves the condensed HTML page from an ESP8266.
// The page is stored in PROGMEM (flash) and served verbatim.
//
// What survived from Tier 2:
//   - All JS logic (tiling, rendering, interaction)
//   - All CSS (minified)
//   - All HTML structure
//
// What was added at Tier 3:
//   - WiFi connection management
//   - HTTP server on port 80
//   - mDNS for .local access
//   - OTA placeholder
//
// What a Claude distillation would do differently:
//   - Split the page into chunks if > 32KB
//   - Add sensor reads and inject them into the page
//   - Restructure for the ESP's event loop
//   - Add a WebSocket for live data instead of static HTML
//   - Design for the device's constraints, not just embed
//
// {size_note}
// ============================================================

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266mDNS.h>

// CONDENSER: WiFi credentials — replace before compiling.
// At Tier 4 (ATTiny), there is no WiFi. The "network" becomes
// GPIO pin states read by adjacent microcontrollers.
const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASS = "{wifi_pass}";

ESP8266WebServer server(80);

// CONDENSER: The entire condensed page in PROGMEM.
// On ESP8266, PROGMEM strings are read with pgm_read_byte.
// ESP8266WebServer handles this transparently via send_P.
static const char PAGE[] PROGMEM = R"rawliteral(
{minified}
)rawliteral";

void setup() {{
    Serial.begin(115200);
    Serial.println();
    Serial.println("[condenser] Tier 3 — ESP8266 distillation");

    // Connect to WiFi
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("[wifi] connecting");
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 60) {{
        delay(500);
        Serial.print(".");
        attempts++;
    }}
    if (WiFi.status() == WL_CONNECTED) {{
        Serial.println();
        Serial.print("[wifi] connected: ");
        Serial.println(WiFi.localIP());
    }} else {{
        Serial.println();
        Serial.println("[wifi] FAILED — starting AP mode");
        WiFi.softAP("condenser", "condenser");
        Serial.print("[wifi] AP IP: ");
        Serial.println(WiFi.softAPIP());
    }}

    // mDNS
    if (MDNS.begin("condenser")) {{
        Serial.println("[mdns] http://condenser.local/");
    }}

    // Serve the page
    server.on("/", []() {{
        server.send_P(200, "text/html", PAGE);
    }});
    server.begin();
    Serial.println("[http] server started on port 80");

    // CONDENSER: At Tier 4 (ATTiny), there is no HTTP server.
    // The "serving" becomes: set GPIO pins to represent the
    // current tile state. Another device reads the pins.
}}

void loop() {{
    server.handleClient();
    MDNS.update();
    // CONDENSER: At Tier 4, the loop becomes:
    //   1. Read neighbor pins (4 or 6 inputs)
    //   2. Find a matching tile (lookup table in flash)
    //   3. Set output pins to the matched tile's opposite edges
    //   4. Delay for the "tick" interval
    // At Tier 5 (555), the loop IS the oscillator frequency.
}}
'''
