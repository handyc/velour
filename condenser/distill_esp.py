"""Tier 2→3: Distill a JS page into an ESP8266 firmware sketch.

Produces a complete .ino file that serves the condensed page.
"""

import re


def minify_html(raw):
    """Brute-force HTML minification."""
    out = re.sub(r'<!--(?!.*CONDENSER).*?-->', '', raw, flags=re.DOTALL)
    out = re.sub(r'//(?!.*CONDENSER).*$', '', out, flags=re.MULTILINE)
    out = re.sub(r'\s+', ' ', out)
    out = re.sub(r'>\s+<', '><', out)
    return out.strip()


def distill(tier2_html, wifi_ssid='YOUR_WIFI', wifi_pass='YOUR_PASS'):
    """Generate an ESP8266 .ino file from Tier 2 HTML."""

    minified = minify_html(tier2_html)
    orig_size = len(tier2_html.encode('utf-8'))
    mini_size = len(minified.encode('utf-8'))

    # Escape any rawliteral delimiters in the content
    safe = minified.replace(')rawliteral', ')_rawliteral')

    lines = []
    lines.append('// CONDENSER: Tier 3 (ESP8266) — serves condensed page from flash')
    lines.append('// Original: %d bytes, minified: %d bytes (%d%% reduction)' % (
        orig_size, mini_size, 100 - mini_size * 100 // orig_size))
    lines.append('//')
    lines.append('// What Claude would do differently:')
    lines.append('//   - Add WebSocket for live data injection')
    lines.append('//   - Split page if > 32KB for chunked transfer')
    lines.append('//   - Add sensor reads and inject into page')
    lines.append('//   - Design for the ESP event loop, not just embed')
    lines.append('')
    lines.append('#include <Arduino.h>')
    lines.append('#include <ESP8266WiFi.h>')
    lines.append('#include <ESP8266WebServer.h>')
    lines.append('#include <ESP8266mDNS.h>')
    lines.append('')
    lines.append('const char* WIFI_SSID = "%s";' % wifi_ssid)
    lines.append('const char* WIFI_PASS = "%s";' % wifi_pass)
    lines.append('')
    lines.append('ESP8266WebServer server(80);')
    lines.append('')
    lines.append('static const char PAGE[] PROGMEM = R"rawliteral(')
    lines.append(safe)
    lines.append(')rawliteral";')
    lines.append('')
    lines.append('void setup() {')
    lines.append('    Serial.begin(115200);')
    lines.append('    Serial.println();')
    lines.append('    Serial.println("[condenser] Tier 3 ESP8266");')
    lines.append('')
    lines.append('    WiFi.begin(WIFI_SSID, WIFI_PASS);')
    lines.append('    Serial.print("[wifi] connecting");')
    lines.append('    int tries = 0;')
    lines.append('    while (WiFi.status() != WL_CONNECTED && tries < 60) {')
    lines.append('        delay(500); Serial.print("."); tries++;')
    lines.append('    }')
    lines.append('    if (WiFi.status() == WL_CONNECTED) {')
    lines.append('        Serial.println();')
    lines.append('        Serial.print("[wifi] IP: ");')
    lines.append('        Serial.println(WiFi.localIP());')
    lines.append('    } else {')
    lines.append('        Serial.println("\\n[wifi] FAILED — starting AP");')
    lines.append('        WiFi.softAP("condenser", "condenser");')
    lines.append('    }')
    lines.append('')
    lines.append('    MDNS.begin("condenser");')
    lines.append('    server.on("/", []() { server.send_P(200, "text/html", PAGE); });')
    lines.append('    server.begin();')
    lines.append('    Serial.println("[http] ready on port 80");')
    lines.append('}')
    lines.append('')
    lines.append('void loop() {')
    lines.append('    server.handleClient();')
    lines.append('    MDNS.update();')
    lines.append('}')

    return '\n'.join(lines)
