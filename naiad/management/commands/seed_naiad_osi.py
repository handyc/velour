"""Seed Naiad with OSI 7-layer stage types + network input/target profiles.

This is the data-domain seed.  It does NOT touch the existing water
catalogue — `seed_naiad_defaults` still owns that.  Re-runnable;
upserts by slug.

Phase 1 ships the catalogue only — the simulator/fitness for the
data domain is Phase 2.  Each stage type's `removal` JSON encodes a
*proposed* metric transformation that the Phase-2 simulator will
consume; nothing reads it yet.  Conventions:

  removal = {
    "<metric_key>": <multiplier or absolute>,
    ...
  }

For now use a simple convention:
  - latency_ms / jitter_ms: STAGE ADDS this many ms (positive number)
  - throughput_kbps: STAGE CAPS at this max kbps (min(input, this))
  - reliability_pct: STAGE MULTIPLIES (e.g. 0.99 = drops 1%)
  - cost_eur_month / energy_watts: STAGE ADDS this many units
  - range_m / payload_bytes / duty_cycle_pct: STAGE CAPS at this max

The exact semantics will firm up as Phase 2 lands.  The values below
are reasonable orders-of-magnitude only — the GA can refine.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from naiad.models import StageType, WaterProfile


# (slug, name, kind, description, removal-as-transformation)
# Layered top-down, OSI 1 → OSI 7.
OSI_STAGES = [
    # ─── L1 PHY ─────────────────────────────────────────────
    ('phy-copper-twisted', 'Copper twisted-pair (Cat5e)', 'osi_phy',
     'Reliable indoor cabling, 100m range, ~1Gbps cap, low latency.',
     {'latency_ms': 0.1, 'throughput_kbps': 1_000_000, 'reliability_pct': 0.999,
      'range_m': 100, 'cost_eur_month': 0, 'energy_watts': 0.5}),
    ('phy-fiber-sm', 'Single-mode fiber', 'osi_phy',
     'Long-haul optical link; tens of km, 10Gbps+ cap, very low latency.',
     {'latency_ms': 0.05, 'throughput_kbps': 10_000_000, 'reliability_pct': 0.9999,
      'range_m': 40_000, 'cost_eur_month': 5, 'energy_watts': 1.5}),
    ('phy-rf-wifi', 'RF / 802.11 (consumer)', 'osi_phy',
     'Indoor wireless; 30m range, ~100Mbps real-world cap.',
     {'latency_ms': 2.0, 'throughput_kbps': 100_000, 'reliability_pct': 0.98,
      'range_m': 30, 'cost_eur_month': 0, 'energy_watts': 1.0}),
    ('phy-rf-cellular', 'Cellular (LTE/4G)', 'osi_phy',
     'Mobile uplink; km range, variable throughput, monthly cost.',
     {'latency_ms': 30, 'throughput_kbps': 20_000, 'reliability_pct': 0.97,
      'range_m': 5_000, 'cost_eur_month': 12, 'energy_watts': 1.5}),
    ('phy-satellite-leo', 'Satellite (LEO, e.g. Starlink)', 'osi_phy',
     'Sub-orbital constellation; global coverage, high cost, ~30ms latency.',
     {'latency_ms': 30, 'throughput_kbps': 100_000, 'reliability_pct': 0.99,
      'range_m': 1_000_000, 'cost_eur_month': 50, 'energy_watts': 50}),
    ('phy-satellite-geo', 'Satellite (GEO)', 'osi_phy',
     'Geostationary; ~600ms RTT, expensive, very long range.',
     {'latency_ms': 300, 'throughput_kbps': 5_000, 'reliability_pct': 0.98,
      'range_m': 36_000_000, 'cost_eur_month': 80, 'energy_watts': 60}),
    ('phy-lora', 'LoRa (sub-GHz ISM)', 'osi_phy',
     'Long-range low-bandwidth; km range, kbps cap, ~1% duty cycle.',
     {'latency_ms': 200, 'throughput_kbps': 5, 'reliability_pct': 0.95,
      'range_m': 5_000, 'cost_eur_month': 0, 'energy_watts': 0.05,
      'duty_cycle_pct': 1}),
    ('phy-wet-shoestring', 'Wet shoestring (degraded copper)', 'osi_phy',
     'The "rural worst case" — corroded twisted pair, intermittent. '
     'Heroic-baseline benchmark for the GA to beat.',
     {'latency_ms': 50, 'throughput_kbps': 56, 'reliability_pct': 0.85,
      'range_m': 2_000, 'cost_eur_month': 0, 'energy_watts': 1.0}),
    ('phy-acoustic-modem', 'Acoustic modem (water)', 'osi_phy',
     'Underwater comms; very slow, very limited bandwidth.',
     {'latency_ms': 700, 'throughput_kbps': 5, 'reliability_pct': 0.90,
      'range_m': 10_000, 'cost_eur_month': 0, 'energy_watts': 30}),

    # ─── L2 DLL ─────────────────────────────────────────────
    ('dll-ethernet', 'Ethernet (802.3)', 'osi_dll',
     'CSMA/CD wired LAN framing; near-zero overhead.',
     {'latency_ms': 0.05, 'reliability_pct': 0.9999,
      'payload_bytes': 1500, 'energy_watts': 0.2}),
    ('dll-wifi-mac', '802.11 MAC', 'osi_dll',
     'Wireless LAN MAC layer; CSMA/CA with collision retransmits.',
     {'latency_ms': 0.5, 'reliability_pct': 0.98,
      'payload_bytes': 2304, 'energy_watts': 0.3}),
    ('dll-ppp', 'PPP', 'osi_dll',
     'Point-to-point protocol; classic dial-up + serial framing.',
     {'latency_ms': 5, 'reliability_pct': 0.97, 'payload_bytes': 1500}),
    ('dll-lorawan', 'LoRaWAN', 'osi_dll',
     'Low-power-WAN MAC; ADR + duty-cycle + ABP/OTAA framing.',
     {'latency_ms': 50, 'reliability_pct': 0.93, 'payload_bytes': 222,
      'duty_cycle_pct': 1}),
    ('dll-bluetooth', 'Bluetooth Low Energy', 'osi_dll',
     'BLE link layer; tens of bytes per packet, very low power.',
     {'latency_ms': 7.5, 'reliability_pct': 0.96, 'payload_bytes': 244,
      'energy_watts': 0.01}),
    ('dll-can', 'CAN (Controller Area Network)', 'osi_dll',
     'Vehicular bus; deterministic, max 8 B per frame.',
     {'latency_ms': 0.5, 'reliability_pct': 0.9999, 'payload_bytes': 8}),

    # ─── L3 NET ─────────────────────────────────────────────
    ('net-ipv4', 'IPv4', 'osi_net',
     'Universal addressing; small header overhead.',
     {'latency_ms': 0.1, 'payload_bytes': 65535}),
    ('net-ipv6', 'IPv6', 'osi_net',
     'Larger headers; native end-to-end addressability.',
     {'latency_ms': 0.1, 'payload_bytes': 65535}),
    ('net-mesh-batman', 'B.A.T.M.A.N. mesh', 'osi_net',
     'Self-healing mesh routing; +overhead, +reliability via redundancy.',
     {'latency_ms': 5, 'reliability_pct': 1.005}),
    ('net-mesh-yggdrasil', 'Yggdrasil overlay mesh', 'osi_net',
     'IPv6 overlay; encrypted, self-organising spanning tree.',
     {'latency_ms': 8, 'reliability_pct': 1.005}),

    # ─── L4 TRANSPORT ───────────────────────────────────────
    ('trans-tcp', 'TCP', 'osi_trans',
     'Reliable, ordered, congestion-controlled.  +50% latency vs UDP '
     'on lossy links; turns reliability into latency.',
     {'latency_ms': 50, 'reliability_pct': 1.05}),     # > 1 = boost
    ('trans-udp', 'UDP', 'osi_trans',
     'Best-effort.  No retransmit, no ordering, lowest overhead.',
     {'latency_ms': 0.1}),
    ('trans-quic', 'QUIC', 'osi_trans',
     'TLS-bundled UDP transport.  Faster handshake, stream multiplex.',
     {'latency_ms': 5, 'reliability_pct': 1.04}),
    ('trans-kcp', 'KCP (custom UDP-on-RTT)', 'osi_trans',
     'Aggressive ARQ on UDP — lower latency + reliability than TCP for '
     'realtime apps.  Cost: extra retransmits.',
     {'latency_ms': 8, 'reliability_pct': 1.03,
      'throughput_kbps': 0.85}),                       # < 1 = scaled
    ('trans-raw', 'Raw socket / no transport', 'osi_trans',
     'Bypass.  Cheapest but useless on lossy links.',
     {'latency_ms': 0}),

    # ─── L5 SESSION ─────────────────────────────────────────
    ('session-tls', 'TLS 1.3', 'osi_session',
     'Encrypts + authenticates.  +handshake latency, +cpu, +cost.',
     {'latency_ms': 10, 'energy_watts': 0.3, 'reliability_pct': 1.0}),
    ('session-plain', 'No session encryption', 'osi_session',
     'Cleartext.  Free.', {}),
    ('session-noise', 'Noise Protocol', 'osi_session',
     'Modern handshake; smaller than TLS, lower overhead.',
     {'latency_ms': 4, 'energy_watts': 0.15}),

    # ─── L6 PRESENTATION ────────────────────────────────────
    ('pres-json', 'JSON', 'osi_pres',
     'Verbose but universal; ~3× the bytes of binary formats.',
     {'payload_bytes': 0.33, 'energy_watts': 0.1}),    # caps payload to 1/3
    ('pres-protobuf', 'Protocol Buffers', 'osi_pres',
     'Compact binary; schema-driven, ~10× more efficient than JSON.',
     {'energy_watts': 0.05}),
    ('pres-cbor', 'CBOR', 'osi_pres',
     'Concise binary object representation; JSON-compatible model.',
     {'energy_watts': 0.05}),
    ('pres-msgpack', 'MessagePack', 'osi_pres',
     'Like CBOR; widely supported.',
     {'energy_watts': 0.05}),
    ('pres-raw-bytes', 'Raw bytes / no encoding', 'osi_pres',
     'Just hand bytes through.  No structure, but minimal overhead.', {}),

    # ─── L7 APPLICATION ─────────────────────────────────────
    ('app-http', 'HTTP/1.1', 'osi_app',
     'Request/response over TCP.  Universal but verbose headers.',
     {'latency_ms': 5}),
    ('app-http3', 'HTTP/3', 'osi_app',
     'HTTP over QUIC.  Same semantics, lower latency on lossy links.',
     {'latency_ms': 1}),
    ('app-mqtt', 'MQTT', 'osi_app',
     'Pub/sub for IoT.  Tiny headers, retained messages.',
     {'latency_ms': 2, 'energy_watts': 0.05}),
    ('app-coap', 'CoAP', 'osi_app',
     'Constrained Application Protocol; UDP-friendly REST for IoT.',
     {'latency_ms': 1, 'energy_watts': 0.03}),
    ('app-grpc', 'gRPC', 'osi_app',
     'Protobuf-over-HTTP/2; RPC with streaming.',
     {'latency_ms': 3, 'energy_watts': 0.1}),
    ('app-smtp', 'SMTP', 'osi_app',
     'Store-and-forward email.  High latency tolerated by design.',
     {'latency_ms': 1000}),
    ('app-raw-socket', 'Raw socket', 'osi_app',
     'No application protocol; the app speaks bytes directly.', {}),
]


# Network input profiles (real-world starting conditions).
NETWORK_SOURCES = [
    {'slug': 'net-rural-poor-copper',
     'name': 'Rural site with degraded copper',
     'values': {'latency_ms': 50, 'throughput_kbps': 56,
                'reliability_pct': 85, 'jitter_ms': 30, 'range_m': 2000},
     'notes': 'Sketchy phone-line baseline; the kind of link the GA '
              'should learn to wring decent throughput out of.'},
    {'slug': 'net-urban-fiber',
     'name': 'Urban fiber-to-the-premises',
     'values': {'latency_ms': 2, 'throughput_kbps': 1_000_000,
                'reliability_pct': 99.9, 'jitter_ms': 1, 'range_m': 40_000},
     'notes': 'Best-case starting point.  Pipelines designed against '
              'this should optimise for cost + complexity, not throughput.'},
    {'slug': 'net-cellular-lte',
     'name': 'Cellular LTE (mobile)',
     'values': {'latency_ms': 50, 'throughput_kbps': 20_000,
                'reliability_pct': 97, 'jitter_ms': 20, 'range_m': 5_000},
     'notes': 'Typical 4G uplink.  Variable, monthly cost.'},
    {'slug': 'net-satellite-leo',
     'name': 'Satellite (LEO)',
     'values': {'latency_ms': 30, 'throughput_kbps': 100_000,
                'reliability_pct': 99, 'jitter_ms': 10, 'range_m': 1_000_000},
     'notes': 'LEO constellation; global coverage, $$$ recurring.'},
    {'slug': 'net-lora-rural',
     'name': 'LoRa-only rural sensor',
     'values': {'latency_ms': 200, 'throughput_kbps': 5,
                'reliability_pct': 95, 'jitter_ms': 50, 'range_m': 5_000,
                'duty_cycle_pct': 1},
     'notes': 'Cheap long-range low-bandwidth.  Targets must reflect '
              'sub-1% duty cycle and tens-of-bytes payloads.'},
]


# Network target profiles (application-level requirements).
NETWORK_TARGETS = [
    {'slug': 'net-target-streaming-video',
     'name': 'HD video streaming',
     'values': {'latency_ms': 100, 'throughput_kbps': 5_000,
                'reliability_pct': 99, 'jitter_ms': 20},
     'notes': '5 Mbps sustained, < 100 ms latency, < 1% loss.'},
    {'slug': 'net-target-traffic-light',
     'name': 'Traffic-light status (low-bandwidth, low-latency)',
     'values': {'latency_ms': 100, 'throughput_kbps': 1,
                'reliability_pct': 99.9, 'jitter_ms': 50,
                'payload_bytes': 64},
     'notes': 'Small periodic state messages, hard 100ms ceiling, '
              'must not drop.  The "low bandwidth high reporting time" '
              'case from the design conversation.'},
    {'slug': 'net-target-iot-periodic',
     'name': 'IoT sensor periodic report (1/min)',
     'values': {'latency_ms': 5_000, 'throughput_kbps': 0.5,
                'reliability_pct': 95, 'payload_bytes': 32,
                'duty_cycle_pct': 1, 'energy_watts': 0.05},
     'notes': 'Battery-powered sensor; latency tolerant, energy-bounded.'},
    {'slug': 'net-target-realtime-control',
     'name': 'Realtime motor control',
     'values': {'latency_ms': 10, 'throughput_kbps': 100,
                'reliability_pct': 99.99, 'jitter_ms': 2},
     'notes': 'Industrial command channel; deterministic, low jitter.'},
    {'slug': 'net-target-fiber-streaming',
     'name': 'High-bandwidth low-latency (gaming / streaming)',
     'values': {'latency_ms': 30, 'throughput_kbps': 50_000,
                'reliability_pct': 99.5, 'jitter_ms': 5},
     'notes': 'The "high bandwidth low reporting time" case.'},
]


class Command(BaseCommand):
    help = 'Seed Naiad with OSI 7-layer data-domain stage types + network profiles.'

    def handle(self, *args, **opts):
        n_stages = 0
        for slug, name, kind, desc, removal in OSI_STAGES:
            obj, created = StageType.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':        name,
                    'kind':        kind,
                    'domain':      'data',
                    'description': desc,
                    'removal':     removal,
                    'flow_lpm':    0,
                    'energy_watts': float(removal.get('energy_watts', 0)),
                    'cost_eur':    float(removal.get('cost_eur_month', 0)),
                },
            )
            n_stages += 1
            self.stdout.write(
                f'  stage   {"+" if created else "·"} {slug}')
        n_profiles = 0
        for p in NETWORK_SOURCES:
            obj, created = WaterProfile.objects.update_or_create(
                slug=p['slug'],
                defaults={'name': p['name'], 'scope': 'source',
                          'domain': 'data',
                          'values': p['values'], 'notes': p['notes']},
            )
            n_profiles += 1
            self.stdout.write(
                f'  source  {"+" if created else "·"} {obj.slug}')
        for p in NETWORK_TARGETS:
            obj, created = WaterProfile.objects.update_or_create(
                slug=p['slug'],
                defaults={'name': p['name'], 'scope': 'target',
                          'domain': 'data',
                          'values': p['values'], 'notes': p['notes']},
            )
            n_profiles += 1
            self.stdout.write(
                f'  target  {"+" if created else "·"} {obj.slug}')
        self.stdout.write(self.style.SUCCESS(
            f'seeded {n_stages} OSI stages + {n_profiles} network profiles '
            f'({len(NETWORK_SOURCES)} source + {len(NETWORK_TARGETS)} target)'))
