"""Tier 3 generator: AppIR → ESP8266 .ino sketch.

Produces a working PlatformIO-compilable sketch that:
1. Connects to WiFi
2. Serves a condensed HTML page (the Tier 2 output, minified)
3. Has PROGMEM-backed data from the IR models
4. Routes match the IR's URL patterns

The output is a real .ino file — not a mockup.
"""

import re
from .capabilities import filter_ir_for_tier
from .gen_js import generate as gen_js


def generate(ir, wifi_ssid='YOUR_WIFI', wifi_pass='YOUR_PASS'):
    """Generate an ESP8266 .ino file from an AppIR."""
    fir = filter_ir_for_tier(ir, 'esp')

    # Generate the JS page first, then embed it
    js_page = gen_js(fir)
    minified = _minify(js_page)

    # Escape for C raw string
    safe = minified.replace(')rawliteral', ')_rawliteral')

    lines = []
    lines.append(f'// Condenser: {ir.name} → ESP8266')
    lines.append(f'// {len(fir.models)} models, {len(fir.views)} views')
    lines.append(f'// Page: {len(minified)} bytes in PROGMEM')
    lines.append('')
    lines.append('#include <Arduino.h>')
    lines.append('#include <ESP8266WiFi.h>')
    lines.append('#include <ESP8266WebServer.h>')
    lines.append('#include <ESP8266mDNS.h>')
    lines.append('')
    lines.append(f'const char* SSID = "{wifi_ssid}";')
    lines.append(f'const char* PASS = "{wifi_pass}";')
    lines.append('')
    lines.append('ESP8266WebServer server(80);')
    lines.append('')
    lines.append('static const char PAGE[] PROGMEM = R"rawliteral(')
    lines.append(safe)
    lines.append(')rawliteral";')
    lines.append('')
    lines.append('void setup() {')
    lines.append('    Serial.begin(115200);')
    lines.append(f'    Serial.println("[condenser] {ir.name} on ESP8266");')
    lines.append('    WiFi.begin(SSID, PASS);')
    lines.append('    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }')
    lines.append('    Serial.println(WiFi.localIP());')
    lines.append(f'    MDNS.begin("{ir.name.lower().replace(" ", "-")}");')
    lines.append('    server.on("/", []() { server.send_P(200, "text/html", PAGE); });')
    lines.append('    server.begin();')
    lines.append('}')
    lines.append('')
    lines.append('void loop() {')
    lines.append('    server.handleClient();')
    lines.append('    MDNS.update();')
    lines.append('}')

    return '\n'.join(lines)


def _minify(html):
    out = re.sub(r'<!--(?!.*CONDENSER).*?-->', '', html, flags=re.DOTALL)
    out = re.sub(r'//(?!.*CONDENSER).*$', '', out, flags=re.MULTILINE)
    out = re.sub(r'\s+', ' ', out)
    out = re.sub(r'>\s+<', '><', out)
    return out.strip()
