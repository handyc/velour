// display_emu.js — virtual displays for the ATtiny13a emulator.
//
// Two decoders:
//   ST7735SDecoder  — bit-banged SPI mode 0, 80×160 RGB565 IPS panel
//                     used by display_st7735s_13a. Pins: MOSI=PB0,
//                     SCK=PB2, RST=PB3, DC=PB4.
//   SSD1306Decoder  — bit-banged I2C (open-drain) 128×64 mono OLED
//                     used by display_gm009605_13a. Pins: SDA=PB0,
//                     SCL=PB2.
//
// Both decoders subscribe to ATtiny13aEmu.pinObserver, which fires on
// every PORTB / DDRB write. The ATtiny drives pins by toggling PORTB
// (for SPI, push-pull) or by toggling DDRB (for I2C, open-drain —
// DDR=1 ⇒ driven low, DDR=0 ⇒ released to pull-up HIGH).

(function (root) {
'use strict';

// ===========================================================================
// ST7735S — bit-banged SPI
// ===========================================================================
//
// Driver pattern:  set MOSI bit, pulse SCK high-then-low. MSB first.
// Data latched on SCK rising edge. DC selects command vs data.

class ST7735SDecoder {
    constructor() {
        // Landscape: 160 wide × 80 tall. Matches the driver's MADCTL=0x60
        // and the swapped COL_OFFSET / ROW_OFFSET baked into the '85/'13a
        // templates.
        this.W = 160;
        this.H = 80;
        this.COL_OFFSET = 0;
        this.ROW_OFFSET = 24;

        this.fb = new Uint16Array(this.W * this.H);  // RGB565 framebuffer
        this.dirty = true;

        // Bit-bang state
        this._prevSck  = 0;
        this._prevRst  = 1;
        this._byte     = 0;
        this._bitCount = 0;

        // Active window + write pointer (in panel coords, already offset-corrected)
        this._x0 = 0; this._x1 = this.W - 1;
        this._y0 = 0; this._y1 = this.H - 1;
        this._px = 0; this._py = 0;

        // Command parser state
        this._cmd       = 0;
        this._dataBytes = [];      // payload of current cmd's data phase
        this._pixHi     = -1;      // first byte of a 2-byte RGB565 pixel

        this._invOn = false;
    }

    reset() {
        this.fb.fill(0);
        this._prevSck = 0; this._prevRst = 1;
        this._byte = 0; this._bitCount = 0;
        this._pixHi = -1;
        this._cmd = 0; this._dataBytes = [];
        this.dirty = true;
    }

    onPins(portb, _ddrb) {
        // SPI lines are push-pull outputs; level = PORTB bit.
        const mosi = (portb >> 0) & 1;
        const sck  = (portb >> 2) & 1;
        const rst  = (portb >> 3) & 1;
        const dc   = (portb >> 4) & 1;

        // External reset: RST falling edge clears decoder state.
        if (this._prevRst === 1 && rst === 0) {
            this._byte = 0; this._bitCount = 0;
            this._pixHi = -1;
        }
        this._prevRst = rst;

        // SPI clock: rising edge of SCK samples MOSI (mode 0).
        if (this._prevSck === 0 && sck === 1) {
            this._byte = ((this._byte << 1) | mosi) & 0xFF;
            this._bitCount++;
            if (this._bitCount === 8) {
                this._byteIn(this._byte, dc);
                this._byte = 0; this._bitCount = 0;
            }
        }
        this._prevSck = sck;
    }

    // ---- Byte-level dispatch ------------------------------------------
    // DC low = command. DC high = data for the most recently issued cmd.
    _byteIn(b, dc) {
        if (dc === 0) {
            this._cmd = b;
            this._dataBytes.length = 0;
            this._pixHi = -1;
            // RAMWR (0x2C) opens a pixel-data stream; actual pixels arrive
            // with DC=HIGH afterwards.
            return;
        }

        // DC high — data byte for the current command.
        if (this._cmd === 0x2A) {         // CASET: XS_HI, XS_LO, XE_HI, XE_LO
            this._dataBytes.push(b);
            if (this._dataBytes.length === 4) {
                const xs = ((this._dataBytes[0] << 8) | this._dataBytes[1]);
                const xe = ((this._dataBytes[2] << 8) | this._dataBytes[3]);
                this._x0 = xs - this.COL_OFFSET;
                this._x1 = xe - this.COL_OFFSET;
                this._px = this._x0; this._py = this._y0;
                this._dataBytes.length = 0;
            }
        } else if (this._cmd === 0x2B) {  // RASET: YS_HI, YS_LO, YE_HI, YE_LO
            this._dataBytes.push(b);
            if (this._dataBytes.length === 4) {
                const ys = ((this._dataBytes[0] << 8) | this._dataBytes[1]);
                const ye = ((this._dataBytes[2] << 8) | this._dataBytes[3]);
                this._y0 = ys - this.ROW_OFFSET;
                this._y1 = ye - this.ROW_OFFSET;
                this._px = this._x0; this._py = this._y0;
                this._dataBytes.length = 0;
            }
        } else if (this._cmd === 0x2C || this._cmd === 0x3C) {
            // RAMWR / RAMWRC — pixel stream. Two data bytes per pixel
            // (RGB565 big-endian).
            if (this._pixHi < 0) { this._pixHi = b; return; }
            const pix = ((this._pixHi << 8) | b) & 0xFFFF;
            this._pixHi = -1;
            if (this._px >= 0 && this._px < this.W &&
                this._py >= 0 && this._py < this.H) {
                this.fb[this._py * this.W + this._px] =
                    this._invOn ? (pix ^ 0xFFFF) : pix;
                this.dirty = true;
            }
            this._px++;
            if (this._px > this._x1) { this._px = this._x0; this._py++; }
            if (this._py > this._y1) { this._py = this._y0; }  // wrap
        } else if (this._cmd === 0x36) {   // MADCTL — accept arg, but we
            this._dataBytes.push(b);       // render only default portrait.
        } else if (this._cmd === 0x21) {   // INVON (no data, but accept)
            this._invOn = true;
        } else if (this._cmd === 0x20) {
            this._invOn = false;
        } else {
            // Other commands (COLMOD, FRMCTR, PWCTR, gamma, etc.) — swallow
            // their args quietly. We don't use them for rendering.
            this._dataBytes.push(b);
        }
    }

    // ---- Render --------------------------------------------------------
    renderCanvas(canvas) {
        if (!canvas) return;
        // Scale to integer multiple of panel height that fits 360px left panel.
        const want = canvas.width || (this.W * 2);
        const scale = Math.max(1, Math.floor(want / this.W));
        const dstW = this.W * scale, dstH = this.H * scale;
        if (canvas.width !== dstW)  canvas.width  = dstW;
        if (canvas.height !== dstH) canvas.height = dstH;

        const ctx = canvas.getContext('2d');
        const img = ctx.createImageData(this.W, this.H);
        for (let i = 0; i < this.fb.length; i++) {
            const p = this.fb[i];
            // RGB565 → RGB888 (expand each channel linearly).
            const r = ((p >> 11) & 0x1F);
            const g = ((p >> 5)  & 0x3F);
            const b = (p & 0x1F);
            const o = i * 4;
            img.data[o]     = (r << 3) | (r >> 2);
            img.data[o + 1] = (g << 2) | (g >> 4);
            img.data[o + 2] = (b << 3) | (b >> 2);
            img.data[o + 3] = 255;
        }
        // Draw 1:1 then scale up.
        const tmp = document.createElement('canvas');
        tmp.width = this.W; tmp.height = this.H;
        tmp.getContext('2d').putImageData(img, 0, 0);
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, dstW, dstH);
        ctx.drawImage(tmp, 0, 0, dstW, dstH);
        this.dirty = false;
    }
}


// ===========================================================================
// SSD1306 (GM009605) — bit-banged I2C
// ===========================================================================
//
// Open-drain discipline:
//   DDR=1 ⇒ driven LOW (PORTB bit assumed to be 0 by the driver).
//   DDR=0 ⇒ released, pull-up HIGH.
// So the effective line level is (~DDR bit) OR (PORTB bit & DDR bit) —
// in practice just !DDR-bit because the driver always leaves PORTB low
// on SDA/SCL.

class SSD1306Decoder {
    constructor() {
        this.W = 128;
        this.H = 64;
        this.PAGES = this.H / 8;
        this.fb = new Uint8Array(this.W * this.PAGES);   // 1 byte per 8-pixel column
        this.dirty = true;

        // Bus state
        this._sda = 1;
        this._scl = 1;

        // Transaction state machine:
        //   'idle'    — waiting for start
        //   'byte'    — mid-byte, collecting 8 bits
        //   'ack'     — expecting ACK bit from us (we release SDA)
        this._state = 'idle';

        this._bit    = 0;       // next bit index in current byte
        this._byte   = 0;       // current byte being assembled
        this._txPos  = 0;       // byte index within transaction
        this._mode   = 'none';  // 'cmd' | 'data' | 'none'

        // Drawing pointer
        this._page = 0;
        this._col  = 0;

        this._displayOn = true;
        this._invert    = false;
    }

    reset() {
        this.fb.fill(0);
        this._sda = 1; this._scl = 1;
        this._state = 'idle';
        this._bit = 0; this._byte = 0; this._txPos = 0;
        this._mode = 'none';
        this._page = 0; this._col = 0;
        this._displayOn = true; this._invert = false;
        this.dirty = true;
    }

    onPins(portb, ddrb) {
        // Open-drain: DDR bit drives low, DDR released ⇒ pull-up HIGH.
        // (Driver keeps PORTB bit at 0 for PB0 and PB2, so PORTB bit is
        // irrelevant in practice; we still AND it in for correctness.)
        const sdaDdr = (ddrb >> 0) & 1;
        const sclDdr = (ddrb >> 2) & 1;
        const sdaPort = (portb >> 0) & 1;
        const sclPort = (portb >> 2) & 1;
        const sda = sdaDdr ? sdaPort : 1;
        const scl = sclDdr ? sclPort : 1;

        // Detect START / STOP while SCL is HIGH.
        if (scl === 1 && this._scl === 1) {
            if (this._sda === 1 && sda === 0) {
                // START: SDA falling while SCL high
                this._state = 'byte';
                this._bit = 0; this._byte = 0; this._txPos = 0;
                this._mode = 'none';
            } else if (this._sda === 0 && sda === 1) {
                // STOP: SDA rising while SCL high
                this._state = 'idle';
                this._mode = 'none';
            }
        }

        // Bit sampled on SCL rising edge (data is stable while SCL high).
        if (this._scl === 0 && scl === 1 && this._state !== 'idle') {
            if (this._state === 'byte') {
                this._byte = ((this._byte << 1) | sda) & 0xFF;
                this._bit++;
                if (this._bit === 8) {
                    this._state = 'ack';
                }
            } else if (this._state === 'ack') {
                // ACK bit — driver releases SDA, we don't care what it
                // reads. Move on to the next byte.
                this._onByte(this._byte);
                this._byte = 0; this._bit = 0; this._state = 'byte';
                this._txPos++;
            }
        }

        this._sda = sda;
        this._scl = scl;
    }

    // ---- Byte-level dispatch ------------------------------------------
    _onByte(b) {
        if (this._txPos === 0) {
            // Address byte — 0x78 = write to 0x3C. Ignore; anything else
            // we'd ignore anyway since only one slave.
            return;
        }
        if (this._txPos === 1) {
            // Control byte: bit 6 = D/C. 0x00 => commands, 0x40 => data.
            this._mode = (b & 0x40) ? 'data' : 'cmd';
            return;
        }
        if (this._mode === 'cmd') this._onCmd(b);
        else if (this._mode === 'data') this._onData(b);
    }

    _onCmd(c) {
        // Naive per-byte dispatch — each oled_cmd transaction ships exactly
        // one command byte, so we never see true multi-byte commands. The
        // init list sends argument bytes in *separate* transactions; those
        // mis-dispatch here (e.g. 0x00 as "column low=0" instead of as a
        // memory-mode arg) but land on benign settings we overwrite before
        // any real drawing, so it's fine.
        if (c <= 0x0F) {
            this._col = (this._col & 0xF0) | (c & 0x0F);
        } else if (c <= 0x1F) {
            this._col = (this._col & 0x0F) | ((c & 0x0F) << 4);
        } else if (c >= 0xB0 && c <= 0xB7) {
            this._page = c & 0x07;
        } else if (c === 0xAE) {
            this._displayOn = false;
        } else if (c === 0xAF) {
            this._displayOn = true;
        } else if (c === 0xA6) {
            this._invert = false;
        } else if (c === 0xA7) {
            this._invert = true;
        }
        // Everything else (segment remap, COM scan, contrast, multiplex,
        // clock divider, charge pump, precharge, VCOMH) is visually
        // invisible on our pixel-grid renderer — ignore.
    }

    _onData(b) {
        if (this._page < this.PAGES && this._col < this.W) {
            this.fb[this._page * this.W + this._col] = b;
            this.dirty = true;
        }
        this._col++;
        if (this._col >= this.W) {
            this._col = 0;
            this._page = (this._page + 1) & 0x07;   // horizontal addressing wrap
        }
    }

    // ---- Render --------------------------------------------------------
    renderCanvas(canvas) {
        if (!canvas) return;
        const want = canvas.width || (this.W * 2);
        const scale = Math.max(1, Math.floor(want / this.W));
        const dstW = this.W * scale, dstH = this.H * scale;
        if (canvas.width !== dstW)  canvas.width  = dstW;
        if (canvas.height !== dstH) canvas.height = dstH;

        const ctx = canvas.getContext('2d');
        const img = ctx.createImageData(this.W, this.H);

        // On-colour matches the GM009605's native yellow-ish white. The
        // SSD1306 data format is: one byte per 8-pixel vertical column,
        // LSB = top pixel.
        const onR = 0xE0, onG = 0xE8, onB = 0x7A;
        const offR = 0x06, offG = 0x0C, offB = 0x18;
        for (let p = 0; p < this.PAGES; p++) {
            for (let c = 0; c < this.W; c++) {
                const byte = this.fb[p * this.W + c];
                for (let bit = 0; bit < 8; bit++) {
                    const y = p * 8 + bit;
                    const on = (((byte >> bit) & 1) ^ (this._invert ? 1 : 0)) && this._displayOn;
                    const o = (y * this.W + c) * 4;
                    img.data[o]     = on ? onR : offR;
                    img.data[o + 1] = on ? onG : offG;
                    img.data[o + 2] = on ? onB : offB;
                    img.data[o + 3] = 255;
                }
            }
        }
        const tmp = document.createElement('canvas');
        tmp.width = this.W; tmp.height = this.H;
        tmp.getContext('2d').putImageData(img, 0, 0);
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, dstW, dstH);
        ctx.drawImage(tmp, 0, 0, dstW, dstH);
        this.dirty = false;
    }
}


// ===========================================================================
// Slug → decoder registry
// ===========================================================================

function decoderForSlug(slug) {
    if (!slug) return null;
    if (slug.indexOf('st7735s') >= 0)  return new ST7735SDecoder();
    if (slug.indexOf('gm009605') >= 0) return new SSD1306Decoder();
    if (slug.indexOf('ssd1306')  >= 0) return new SSD1306Decoder();
    return null;
}

root.DisplayEmu = {
    ST7735SDecoder,
    SSD1306Decoder,
    decoderForSlug,
};

})(typeof window !== 'undefined' ? window : globalThis);
