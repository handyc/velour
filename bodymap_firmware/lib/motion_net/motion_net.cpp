#include "motion_net.h"

#include <WiFi.h>
#include <esp_now.h>
#include <string.h>

// ESP-NOW's receive callback signature changed between arduino-esp32 core
// 2.x (raw mac pointer) and 3.x (esp_now_recv_info_t struct). Gate on the
// version macro so the same file compiles against both.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  #define BODYMAP_RECV_CB_SIG(name) \
      void name(const esp_now_recv_info_t* info, const uint8_t* data, int len)
  #define BODYMAP_RECV_CB_MAC(info_or_mac) info_or_mac->src_addr
#else
  #define BODYMAP_RECV_CB_SIG(name) \
      void name(const uint8_t* mac, const uint8_t* data, int len)
  #define BODYMAP_RECV_CB_MAC(info_or_mac) info_or_mac
#endif

static MotionNet* _self = nullptr;

static BODYMAP_RECV_CB_SIG(_recvTrampoline) {
    if (!_self) return;
    _self->_onReceive(BODYMAP_RECV_CB_MAC(info), data, len);
}

bool MotionNet::begin() {
    _self = this;

    // ESP-NOW runs over the station interface. Caller is expected to
    // have WiFi.begin()'d already, so WiFi.mode() is STA by the time we
    // get here. If WiFi isn't up the peer add below will still succeed,
    // but packets won't actually fly until the radio is configured.
    if (esp_now_init() != ESP_OK) {
        return false;
    }
    if (esp_now_register_recv_cb(_recvTrampoline) != ESP_OK) {
        return false;
    }

    esp_now_peer_info_t peer = {};
    memset(peer.peer_addr, 0xFF, 6);  // broadcast
    peer.channel = 0;                 // 0 = follow current WiFi channel
    peer.ifidx   = WIFI_IF_STA;
    peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        return false;
    }
    return true;
}

bool MotionNet::broadcast(const MotionBuffer& src) {
    // We need BODYMAP_NET_PACKET_SAMPLES samples at a stride of
    // BODYMAP_NET_SAMPLE_STRIDE — i.e. a contiguous run of
    // packet_samples * stride raw samples.
    const size_t needed = BODYMAP_NET_PACKET_SAMPLES * BODYMAP_NET_SAMPLE_STRIDE;
    if (src.size() < needed) {
        // Buffer hasn't warmed up — skip. Once the IMU is live this will
        // hold the first ~3 seconds after boot, then broadcast normally.
        return false;
    }

    // Grab the newest `needed` samples oldest-to-newest, then stride-pick.
    GyroSample raw[BODYMAP_NET_PACKET_SAMPLES * BODYMAP_NET_SAMPLE_STRIDE];
    const size_t got = src.snapshot(raw, needed);
    if (got < needed) return false;

    MotionPacket pkt = {};
    pkt.magic0      = BODYMAP_NET_MAGIC0;
    pkt.magic1      = BODYMAP_NET_MAGIC1;
    pkt.version     = BODYMAP_NET_VERSION;
    pkt.sampleCount = BODYMAP_NET_PACKET_SAMPLES;
    pkt.t0Ms        = raw[0].tMs;
    // Two picks are BODYMAP_NET_SAMPLE_STRIDE apart in the raw buffer —
    // dt between them is (tMs[stride] - tMs[0]). Cast to ms.
    pkt.dtMs        = (uint16_t)(raw[BODYMAP_NET_SAMPLE_STRIDE].tMs - raw[0].tMs);
    pkt.seq         = _seq++;

    const float invScale = 1.0f / BODYMAP_NET_GYRO_SCALE;
    for (size_t i = 0; i < BODYMAP_NET_PACKET_SAMPLES; i++) {
        const GyroSample& s = raw[i * BODYMAP_NET_SAMPLE_STRIDE];
        // Clamp to int16 range before cast. At 0.001 rad/s/LSB the clip
        // point is ±32.7 rad/s; anything past that would saturate a real
        // MEMS gyro too, so clamping loses no meaningful information.
        float fx = s.gx * invScale;
        float fy = s.gy * invScale;
        float fz = s.gz * invScale;
        if (fx >  32767.f) fx =  32767.f;
        if (fx < -32768.f) fx = -32768.f;
        if (fy >  32767.f) fy =  32767.f;
        if (fy < -32768.f) fy = -32768.f;
        if (fz >  32767.f) fz =  32767.f;
        if (fz < -32768.f) fz = -32768.f;
        pkt.gyro[i][0] = (int16_t)fx;
        pkt.gyro[i][1] = (int16_t)fy;
        pkt.gyro[i][2] = (int16_t)fz;
    }

    uint8_t bcast[6];
    memset(bcast, 0xFF, 6);
    esp_err_t err = esp_now_send(bcast, (const uint8_t*)&pkt, sizeof(pkt));
    if (err != ESP_OK) {
        _sendErrors++;
        return false;
    }
    _pktsTx++;
    return true;
}

void MotionNet::_onReceive(const uint8_t* mac, const uint8_t* data, int len) {
    if (len != (int)sizeof(MotionPacket)) return;
    const MotionPacket* in = (const MotionPacket*)data;
    if (in->magic0 != BODYMAP_NET_MAGIC0 || in->magic1 != BODYMAP_NET_MAGIC1) return;
    if (in->version != BODYMAP_NET_VERSION) return;

    // Find existing peer entry by MAC.
    int idx = -1;
    for (size_t i = 0; i < _peerCount; i++) {
        if (memcmp(_peers[i].mac, mac, 6) == 0) { idx = (int)i; break; }
    }
    if (idx < 0) {
        if (_peerCount >= BODYMAP_MAX_PEERS) return;  // table full, drop
        idx = (int)_peerCount++;
        memcpy(_peers[idx].mac, mac, 6);
        _peers[idx].packetsReceived = 0;
    }

    _peers[idx].latest          = *in;
    _peers[idx].lastReceivedMs  = millis();
    _peers[idx].packetsReceived++;
    _pktsRx++;
}

size_t MotionNet::peerSnapshot(PeerObservation* out, size_t maxOut) const {
    const size_t n = (_peerCount < maxOut) ? _peerCount : maxOut;
    for (size_t i = 0; i < n; i++) {
        out[i] = _peers[i];
    }
    return n;
}
