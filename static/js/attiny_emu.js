// attiny_emu.js — ATtiny13a emulator in pure JS.
//
// Covers the AVR instruction subset avr-gcc -Os emits for the
// bodymap ATtiny workshop templates, plus enough of the t13a
// peripherals (PORTB / DDRB / PINB, ADC, Timer0 in fast-PWM mode,
// MCUSR) to run them against a live UI panel.
//
// Not cycle-accurate. Good enough to watch pot → LED, A&B → C,
// reset-button greeters, chase patterns, VCO square waves as pulse
// trains, etc.  exports: loadHex(), ATtiny13aEmu class.

(function (root) {
'use strict';

// --- Intel HEX -----------------------------------------------------------

function parseIntelHex(text) {
    const bytes = new Uint8Array(2048);  // bigger than t13a flash, we truncate
    let maxAddr = 0;
    for (const raw of text.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || line[0] !== ':') continue;
        const count = parseInt(line.substr(1, 2), 16);
        const addr  = parseInt(line.substr(3, 4), 16);
        const type  = parseInt(line.substr(7, 2), 16);
        if (type === 0x01) break;           // EOF
        if (type !== 0x00) continue;        // skip extended segment/linear
        for (let i = 0; i < count; i++) {
            const b = parseInt(line.substr(9 + i * 2, 2), 16);
            bytes[addr + i] = b;
            if (addr + i + 1 > maxAddr) maxAddr = addr + i + 1;
        }
    }
    return bytes.subarray(0, maxAddr);
}

// --- Register / IO constants --------------------------------------------

const SREG_C = 0, SREG_Z = 1, SREG_N = 2, SREG_V = 3,
      SREG_S = 4, SREG_H = 5, SREG_T = 6, SREG_I = 7;

// Low I/O addresses (0x00..0x3F). Data memory = ioAddr + 0x20.
const IO = {
    ADCSRB: 0x03, ADCL: 0x04, ADCH: 0x05, ADCSRA: 0x06, ADMUX: 0x07,
    PINB:   0x16, DDRB:  0x17, PORTB:  0x18,
    OCR0B:  0x29, TCCR0A: 0x2F, TCNT0: 0x32, TCCR0B: 0x33,
    MCUSR:  0x34, OCR0A: 0x36, TIFR0: 0x38, TIMSK0: 0x39,
    SPL:    0x3D, SREG:  0x3F,
};

const RAMEND = 0x9F;    // t13a has 64 B SRAM, ends at 0x9F

// --- Core ---------------------------------------------------------------

class ATtiny13aEmu {
    constructor() {
        // Flash stored as 16-bit words (512 words = 1 KB on t13a).
        this.flash = new Uint16Array(512);
        // Unified data memory: 0x00-0x1F regs, 0x20-0x5F IO, 0x60-0x9F SRAM.
        this.mem = new Uint8Array(RAMEND + 1);
        this.pc = 0;        // word-addressed program counter
        this.sreg = 0;
        this.sp = RAMEND;
        this.cycles = 0;
        this.halted = false;

        // Peripheral state fed by the UI:
        //   pinInput[i] = 0 or 1 — what the user wants pin i to read
        //                 when it's configured as input. For outputs,
        //                 we ignore this and show the driven value.
        //   adc[c]       = 10-bit value 0..1023 for ADC channel c (0..3).
        this.pinInput = [1, 1, 1, 1, 1, 1];   // idle high (pull-ups)
        this.adc      = [0, 0, 0, 0];

        // Output mirrors (populated each write so UI can read quickly).
        this.portb = 0;
        this.ddrb  = 0;
        // PWM output levels 0..255 for OC0A (PB0) and OC0B (PB1), or
        // -1 when the timer is not driving that pin.
        this.pwmA = -1;
        this.pwmB = -1;

        // Used by LDS/STS-triggered ADC start: we fake a 1-tick conversion.
        this._adcBusy = 0;
    }

    // ---- Memory access ------------------------------------------------

    _readIO(ioAddr) {
        switch (ioAddr) {
        case IO.PINB: {
            // For output pins, PINB reads back PORTB value; for input pins,
            // it reads the external state set by the UI.
            let v = 0;
            for (let i = 0; i < 6; i++) {
                const outBit = (this.ddrb >> i) & 1;
                const bit    = outBit ? ((this.portb >> i) & 1) : this.pinInput[i];
                v |= bit << i;
            }
            return v;
        }
        case IO.SREG: return this.sreg;
        case IO.SPL:  return this.sp & 0xFF;
        default:      return this.mem[0x20 + ioAddr];
        }
    }

    _writeIO(ioAddr, val) {
        val &= 0xFF;
        this.mem[0x20 + ioAddr] = val;
        switch (ioAddr) {
        case IO.PORTB:  this.portb = val; this._recomputePwm(); break;
        case IO.DDRB:   this.ddrb  = val; this._recomputePwm(); break;
        case IO.TCCR0A: this._recomputePwm(); break;
        case IO.OCR0A:  this._recomputePwm(); break;
        case IO.OCR0B:  this._recomputePwm(); break;
        case IO.ADCSRA: {
            // If software sets ADSC (bit 6), kick a fake conversion.
            if (val & 0x40) this._startAdc();
            break;
        }
        case IO.SREG:  this.sreg = val; break;
        case IO.SPL:   this.sp = 0x0000 | val; break;
        case IO.MCUSR: this.mem[0x20 + IO.MCUSR] = val; break;  // software clears flags
        }
    }

    _readMem(addr) {
        if (addr < 0x20)            return this.mem[addr];    // regs
        if (addr < 0x60)            return this._readIO(addr - 0x20);
        if (addr <= RAMEND)         return this.mem[addr];
        return 0;
    }
    _writeMem(addr, val) {
        val &= 0xFF;
        if (addr < 0x20)            { this.mem[addr] = val; return; }
        if (addr < 0x60)            { this._writeIO(addr - 0x20, val); return; }
        if (addr <= RAMEND)         { this.mem[addr] = val; return; }
    }

    // ---- PWM recomputation -------------------------------------------

    _recomputePwm() {
        const tccr0a = this.mem[0x20 + IO.TCCR0A];
        // COM0A1 (bit 7) set + WGM Fast-PWM + DDRB PB0 as output → PB0 is PWM
        const wgm    = ((this.mem[0x20 + IO.TCCR0B] >> 3) & 0x04) |
                       ((tccr0a >> 0) & 0x03);
        const fastPwm = (wgm === 0x03 || wgm === 0x07);
        const com0a1 = (tccr0a & 0x80) !== 0;
        const com0b1 = (tccr0a & 0x20) !== 0;

        this.pwmA = (fastPwm && com0a1 && (this.ddrb & 0x01))
                    ? this.mem[0x20 + IO.OCR0A] : -1;
        this.pwmB = (fastPwm && com0b1 && (this.ddrb & 0x02))
                    ? this.mem[0x20 + IO.OCR0B] : -1;
    }

    // ---- ADC ----------------------------------------------------------

    _startAdc() {
        const admux = this.mem[0x20 + IO.ADMUX];
        const ch    = admux & 0x0F;
        // Only channels 0..3 map to physical pot inputs on t13a.
        const raw   = (ch < 4) ? (this.adc[ch] | 0) : 0;
        const v     = Math.max(0, Math.min(1023, raw));
        this.mem[0x20 + IO.ADCL] = v & 0xFF;
        this.mem[0x20 + IO.ADCH] = (v >> 8) & 0x03;
        // Clear ADSC to signal conversion done. (Instant in this model.)
        this.mem[0x20 + IO.ADCSRA] &= ~0x40;
    }

    // ---- Reset + program load ----------------------------------------

    loadProgram(progBytes) {
        this.flash.fill(0);
        for (let i = 0; i + 1 < progBytes.length; i += 2) {
            this.flash[i >> 1] = progBytes[i] | (progBytes[i + 1] << 8);
        }
    }

    reset(externalReset) {
        this.mem.fill(0);
        this.pc = 0;
        this.sreg = 0;
        this.sp = RAMEND;
        this.cycles = 0;
        this.halted = false;
        this.portb = 0;
        this.ddrb  = 0;
        this.pwmA = -1;
        this.pwmB = -1;
        this.mem[0x20 + IO.SPL] = RAMEND & 0xFF;
        // MCUSR latches reset source. Bit 0 = PORF, 1 = EXTRF.
        this.mem[0x20 + IO.MCUSR] = externalReset ? 0x02 : 0x01;
    }

    // ---- Status register helpers -------------------------------------

    _setBit(mask, on) {
        if (on) this.sreg |= mask; else this.sreg &= ~mask;
    }
    _getBit(b) { return (this.sreg >> b) & 1; }

    _flagsLogical(r) {
        // After AND/OR/EOR/COM.  V=0, N=r.7, Z=r==0, S=N^V.
        const n = (r >> 7) & 1;
        this._setBit(1 << SREG_V, false);
        this._setBit(1 << SREG_N, n);
        this._setBit(1 << SREG_Z, (r & 0xFF) === 0);
        this._setBit(1 << SREG_S, n);
    }
    _flagsAddSub(a, b, r, isSub, withCarry) {
        // r already masked to 8 bits by caller.
        const a7 = (a >> 7) & 1, b7 = (b >> 7) & 1, r7 = (r >> 7) & 1;
        const a3 = (a >> 3) & 1, b3 = (b >> 3) & 1, r3 = (r >> 3) & 1;
        let h, c, v;
        if (isSub) {
            h = (~a3 & b3) | (b3 & r3) | (r3 & ~a3);
            c = (~a7 & b7) | (b7 & r7) | (r7 & ~a7);
            v = (a7 & ~b7 & ~r7) | (~a7 & b7 & r7);
        } else {
            h = (a3 & b3) | (b3 & ~r3) | (~r3 & a3);
            c = (a7 & b7) | (b7 & ~r7) | (~r7 & a7);
            v = (a7 & b7 & ~r7) | (~a7 & ~b7 & r7);
        }
        const n = r7;
        const s = n ^ v;
        this._setBit(1 << SREG_H, h);
        this._setBit(1 << SREG_C, c);
        this._setBit(1 << SREG_V, v);
        this._setBit(1 << SREG_N, n);
        this._setBit(1 << SREG_S, s);
        // CPC/SBC treat Z as sticky — the caller passes withCarry in that case.
        if (withCarry) {
            this._setBit(1 << SREG_Z, ((r & 0xFF) === 0) && this._getBit(SREG_Z));
        } else {
            this._setBit(1 << SREG_Z, (r & 0xFF) === 0);
        }
    }

    // ---- Stack ---------------------------------------------------------

    _push(v) { this._writeMem(this.sp, v & 0xFF); this.sp--; }
    _pop()   { this.sp++; return this._readMem(this.sp); }

    // ---- Main decode / execute ----------------------------------------

    step() {
        if (this.halted) return 0;
        const op = this.flash[this.pc] | 0;
        this.pc = (this.pc + 1) & 0x1FF;
        return this._execute(op);
    }

    _execute(op) {
        // --- Class decoding by top nibbles + masks -------------------

        // NOP — 0x0000
        if (op === 0x0000) return 1;

        // MOVW Rd, Rr — 0000 0001 dddd rrrr   (d,r = 4-bit pair index * 2)
        if ((op & 0xFF00) === 0x0100) {
            const d = ((op >> 4) & 0x0F) * 2;
            const r = (op & 0x0F) * 2;
            this.mem[d]     = this.mem[r];
            this.mem[d + 1] = this.mem[r + 1];
            return 1;
        }
        // MULS / MULSU / FMUL / FMULSU / MUL — t13a has no multiplier; skip.

        // CPC — 0000 01rd dddd rrrr
        if ((op & 0xFC00) === 0x0400) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r], c = this._getBit(SREG_C);
            const res = (a - b - c) & 0xFF;
            this._flagsAddSub(a, b + c, res, true, true);
            return 1;
        }
        // SBC — 0000 10rd dddd rrrr
        if ((op & 0xFC00) === 0x0800) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r], c = this._getBit(SREG_C);
            const res = (a - b - c) & 0xFF;
            this._flagsAddSub(a, b + c, res, true, true);
            this.mem[d] = res;
            return 1;
        }
        // ADD — 0000 11rd dddd rrrr
        if ((op & 0xFC00) === 0x0C00) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r];
            const res = (a + b) & 0xFF;
            this._flagsAddSub(a, b, res, false, false);
            this.mem[d] = res;
            return 1;
        }
        // CPSE — 0001 00rd dddd rrrr
        if ((op & 0xFC00) === 0x1000) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            if (this.mem[d] === this.mem[r]) this._skipNext();
            return 1;
        }
        // CP — 0001 01rd dddd rrrr
        if ((op & 0xFC00) === 0x1400) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r];
            const res = (a - b) & 0xFF;
            this._flagsAddSub(a, b, res, true, false);
            return 1;
        }
        // SUB — 0001 10rd dddd rrrr
        if ((op & 0xFC00) === 0x1800) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r];
            const res = (a - b) & 0xFF;
            this._flagsAddSub(a, b, res, true, false);
            this.mem[d] = res;
            return 1;
        }
        // ADC — 0001 11rd dddd rrrr
        if ((op & 0xFC00) === 0x1C00) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const a = this.mem[d], b = this.mem[r], c = this._getBit(SREG_C);
            const res = (a + b + c) & 0xFF;
            this._flagsAddSub(a, b + c, res, false, false);
            this.mem[d] = res;
            return 1;
        }
        // AND — 0010 00rd dddd rrrr
        if ((op & 0xFC00) === 0x2000) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const res = (this.mem[d] & this.mem[r]) & 0xFF;
            this.mem[d] = res;
            this._flagsLogical(res);
            return 1;
        }
        // EOR — 0010 01rd dddd rrrr
        if ((op & 0xFC00) === 0x2400) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const res = (this.mem[d] ^ this.mem[r]) & 0xFF;
            this.mem[d] = res;
            this._flagsLogical(res);
            return 1;
        }
        // OR — 0010 10rd dddd rrrr
        if ((op & 0xFC00) === 0x2800) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            const res = (this.mem[d] | this.mem[r]) & 0xFF;
            this.mem[d] = res;
            this._flagsLogical(res);
            return 1;
        }
        // MOV — 0010 11rd dddd rrrr
        if ((op & 0xFC00) === 0x2C00) {
            const d = (op >> 4) & 0x1F;
            const r = ((op >> 5) & 0x10) | (op & 0x0F);
            this.mem[d] = this.mem[r];
            return 1;
        }

        // CPI Rd, K — 0011 KKKK dddd KKKK  (d = 16..31)
        if ((op & 0xF000) === 0x3000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            const a = this.mem[d];
            const res = (a - k) & 0xFF;
            this._flagsAddSub(a, k, res, true, false);
            return 1;
        }
        // SBCI — 0100 KKKK dddd KKKK
        if ((op & 0xF000) === 0x4000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            const a = this.mem[d], c = this._getBit(SREG_C);
            const res = (a - k - c) & 0xFF;
            this._flagsAddSub(a, k + c, res, true, true);
            this.mem[d] = res;
            return 1;
        }
        // SUBI — 0101 KKKK dddd KKKK
        if ((op & 0xF000) === 0x5000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            const a = this.mem[d];
            const res = (a - k) & 0xFF;
            this._flagsAddSub(a, k, res, true, false);
            this.mem[d] = res;
            return 1;
        }
        // ORI — 0110 KKKK dddd KKKK
        if ((op & 0xF000) === 0x6000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            const res = (this.mem[d] | k) & 0xFF;
            this.mem[d] = res;
            this._flagsLogical(res);
            return 1;
        }
        // ANDI — 0111 KKKK dddd KKKK
        if ((op & 0xF000) === 0x7000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            const res = (this.mem[d] & k) & 0xFF;
            this.mem[d] = res;
            this._flagsLogical(res);
            return 1;
        }

        // LDS Rd, k — 1001 000d dddd 0000  kkkkkkkk kkkkkkkk  (32-bit)
        if ((op & 0xFE0F) === 0x9000) {
            const d = (op >> 4) & 0x1F;
            const k = this.flash[this.pc];
            this.pc = (this.pc + 1) & 0x1FF;
            this.mem[d] = this._readMem(k & 0xFFFF);
            return 2;
        }
        // STS k, Rr — 1001 001r rrrr 0000  kkkkkkkk kkkkkkkk
        if ((op & 0xFE0F) === 0x9200) {
            const r = (op >> 4) & 0x1F;
            const k = this.flash[this.pc];
            this.pc = (this.pc + 1) & 0x1FF;
            this._writeMem(k & 0xFFFF, this.mem[r]);
            return 2;
        }

        // LD Rd, X / X+ / -X  — 1001 000d dddd 1100/1101/1110
        // LD Rd, Y+/-Y/Y+q  — 1000 000d dddd 1000 / 1001 000d dddd 1001/1010 / 10q0 qq0d dddd 1qqq
        // LD Rd, Z+/-Z/Z+q  — similar
        // ST with analogous encodings.
        // We implement the common forms the compiler emits: LD/ST with X/Y/Z
        // post-inc / pre-dec, plus displacement LDD/STD.

        // LDD Rd, Z+q / Y+q / LDS without displacement handled below
        if ((op & 0xD208) === 0x8000) {
            // LDD/LD Rd, Z+q or Y+q
            return this._handleLdStDisp(op, false);
        }
        if ((op & 0xD208) === 0x8008) {
            return this._handleLdStDisp(op, false);  // LDD Rd, Y+q
        }
        if ((op & 0xD208) === 0x8200) {
            return this._handleLdStDisp(op, true);   // STD Z+q, Rr
        }
        if ((op & 0xD208) === 0x8208) {
            return this._handleLdStDisp(op, true);   // STD Y+q, Rr
        }

        // Single-register / misc ops — 1001 010d dddd xxxx + 1001 0101 xxxx xxxx
        // (COM, NEG, SWAP, INC, DEC, ASR, LSR, ROR, BSET, BCLR, RET, RETI,
        //  SLEEP, WDR, LPM R0,Z — all live here). Must be checked BEFORE
        // the 0xFC00==0x9000 LD/ST branch, which would otherwise swallow
        // these opcodes' low nibbles and mis-dispatch them as memory ops.
        if ((op & 0xFE00) === 0x9400) {
            return this._handle9400(op);
        }

        // LD/ST with X/Y/Z post-inc / pre-dec variants — 1001 00?d dddd xxxx
        if ((op & 0xFC00) === 0x9000) {
            const low = op & 0x0F;
            const d   = (op >> 4) & 0x1F;
            const isStore = (op & 0x0200) !== 0;
            let regPair, addrReg;
            switch (low) {
            case 0x0C: regPair = 26; break;   // X
            case 0x0D: regPair = 26; break;   // X+
            case 0x0E: regPair = 26; break;   // -X
            case 0x09: regPair = 28; break;   // Y+
            case 0x0A: regPair = 28; break;   // -Y
            case 0x01: regPair = 30; break;   // Z+
            case 0x02: regPair = 30; break;   // -Z
            case 0x00: regPair = 30; break;   // LPM Rd, Z (handled below too)
            case 0x04: /* LPM Rd, Z */ break;
            case 0x05: /* LPM Rd, Z+ */ break;
            case 0x0F: {
                // PUSH Rr / POP Rd depending on isStore bit.
                if (isStore) { this._push(this.mem[d]); return 2; }
                else         { this.mem[d] = this._pop(); return 2; }
            }
            default: regPair = -1; break;
            }
            // LPM variants:
            if (low === 0x04 || low === 0x05) {
                const z = this.mem[30] | (this.mem[31] << 8);
                const byte = (this.flash[z >> 1] >> ((z & 1) * 8)) & 0xFF;
                this.mem[d] = byte;
                if (low === 0x05) {
                    const nz = (z + 1) & 0xFFFF;
                    this.mem[30] = nz & 0xFF;
                    this.mem[31] = (nz >> 8) & 0xFF;
                }
                return 3;
            }
            if (regPair >= 0) {
                let addr = this.mem[regPair] | (this.mem[regPair + 1] << 8);
                const preDec  = (low === 0x0E || low === 0x0A || low === 0x02);
                const postInc = (low === 0x0D || low === 0x09 || low === 0x01);
                if (preDec) addr = (addr - 1) & 0xFFFF;
                if (isStore) this._writeMem(addr, this.mem[d]);
                else         this.mem[d] = this._readMem(addr);
                if (postInc) addr = (addr + 1) & 0xFFFF;
                if (preDec || postInc) {
                    this.mem[regPair]     = addr & 0xFF;
                    this.mem[regPair + 1] = (addr >> 8) & 0xFF;
                }
                return 2;
            }
        }

        // ADIW / SBIW — 1001 0110/0111 KKdd KKKK
        if ((op & 0xFE00) === 0x9600) {
            const d = 24 + ((op >> 4) & 0x03) * 2;
            const k = ((op >> 2) & 0x30) | (op & 0x0F);
            const lo = this.mem[d], hi = this.mem[d + 1];
            const val = lo | (hi << 8);
            const res = (val + k) & 0xFFFF;
            this.mem[d]     = res & 0xFF;
            this.mem[d + 1] = (res >> 8) & 0xFF;
            const r15 = (res >> 15) & 1, rdh7 = (hi >> 7) & 1;
            this._setBit(1 << SREG_V, (~rdh7 & r15) & 1);
            this._setBit(1 << SREG_N, r15);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_C, ((~r15 & rdh7)) & 1);
            this._setBit(1 << SREG_S, ((r15 ^ (~rdh7 & r15)) & 1));
            return 2;
        }
        if ((op & 0xFE00) === 0x9700) {
            const d = 24 + ((op >> 4) & 0x03) * 2;
            const k = ((op >> 2) & 0x30) | (op & 0x0F);
            const lo = this.mem[d], hi = this.mem[d + 1];
            const val = lo | (hi << 8);
            const res = (val - k) & 0xFFFF;
            this.mem[d]     = res & 0xFF;
            this.mem[d + 1] = (res >> 8) & 0xFF;
            // Atmel SBIW flags: V = Rdh7_old & !R15, C = R15 & !Rdh7_old.
            const r15 = (res >> 15) & 1, rdh7 = (hi >> 7) & 1;
            const v = (rdh7 & (1 ^ r15)) & 1;
            const c = (r15 & (1 ^ rdh7)) & 1;
            this._setBit(1 << SREG_V, v);
            this._setBit(1 << SREG_N, r15);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_C, c);
            this._setBit(1 << SREG_S, (r15 ^ v) & 1);
            return 2;
        }

        // CBI / SBIC / SBI / SBIS — 1001 10?? AAAA Abbb
        if ((op & 0xFF00) === 0x9800) {    // CBI A, b
            const a = (op >> 3) & 0x1F;
            const b = op & 0x07;
            const v = this._readIO(a);
            this._writeIO(a, v & ~(1 << b));
            return 2;
        }
        if ((op & 0xFF00) === 0x9900) {    // SBIC A, b
            const a = (op >> 3) & 0x1F;
            const b = op & 0x07;
            if ((this._readIO(a) & (1 << b)) === 0) this._skipNext();
            return 1;
        }
        if ((op & 0xFF00) === 0x9A00) {    // SBI A, b
            const a = (op >> 3) & 0x1F;
            const b = op & 0x07;
            const v = this._readIO(a);
            this._writeIO(a, v | (1 << b));
            return 2;
        }
        if ((op & 0xFF00) === 0x9B00) {    // SBIS A, b
            const a = (op >> 3) & 0x1F;
            const b = op & 0x07;
            if ((this._readIO(a) & (1 << b)) !== 0) this._skipNext();
            return 1;
        }

        // IN / OUT — 1011 xAAd dddd AAAA  (x=0 IN, x=1 OUT)
        if ((op & 0xF800) === 0xB000) {
            const a = ((op >> 5) & 0x30) | (op & 0x0F);
            const d = (op >> 4) & 0x1F;
            this.mem[d] = this._readIO(a);
            return 1;
        }
        if ((op & 0xF800) === 0xB800) {
            const a = ((op >> 5) & 0x30) | (op & 0x0F);
            const d = (op >> 4) & 0x1F;
            this._writeIO(a, this.mem[d]);
            return 1;
        }

        // RJMP — 1100 kkkk kkkk kkkk
        if ((op & 0xF000) === 0xC000) {
            let k = op & 0x0FFF;
            if (k & 0x0800) k -= 0x1000;
            this.pc = (this.pc + k) & 0x1FF;
            return 2;
        }
        // RCALL — 1101 kkkk kkkk kkkk
        if ((op & 0xF000) === 0xD000) {
            let k = op & 0x0FFF;
            if (k & 0x0800) k -= 0x1000;
            const ret = this.pc;
            this._push((ret >> 8) & 0xFF);
            this._push(ret & 0xFF);
            this.pc = (this.pc + k) & 0x1FF;
            return 3;
        }
        // LDI Rd, K — 1110 KKKK dddd KKKK   (d = 16..31)
        if ((op & 0xF000) === 0xE000) {
            const d = 16 + ((op >> 4) & 0x0F);
            const k = ((op >> 4) & 0xF0) | (op & 0x0F);
            this.mem[d] = k;
            return 1;
        }

        // Conditional branches — 1111 0xxx kkkk kkks  (BRBS if bit5=0) / 1111 1xxx (BRBC)
        if ((op & 0xFC00) === 0xF000) {     // BRBS s, k
            const s = op & 0x07;
            let k = (op >> 3) & 0x7F;
            if (k & 0x40) k -= 0x80;
            if (this._getBit(s)) this.pc = (this.pc + k) & 0x1FF;
            return this._getBit(s) ? 2 : 1;
        }
        if ((op & 0xFC00) === 0xF400) {     // BRBC s, k
            const s = op & 0x07;
            let k = (op >> 3) & 0x7F;
            if (k & 0x40) k -= 0x80;
            if (!this._getBit(s)) this.pc = (this.pc + k) & 0x1FF;
            return this._getBit(s) ? 1 : 2;
        }

        // BLD Rd, b — 1111 100d dddd 0bbb
        if ((op & 0xFE08) === 0xF800) {
            const d = (op >> 4) & 0x1F;
            const b = op & 0x07;
            const t = this._getBit(SREG_T);
            const v = this.mem[d];
            this.mem[d] = t ? (v | (1 << b)) : (v & ~(1 << b));
            return 1;
        }
        // BST Rd, b — 1111 101d dddd 0bbb
        if ((op & 0xFE08) === 0xFA00) {
            const d = (op >> 4) & 0x1F;
            const b = op & 0x07;
            this._setBit(1 << SREG_T, (this.mem[d] >> b) & 1);
            return 1;
        }
        // SBRC Rr, b — 1111 110r rrrr 0bbb
        if ((op & 0xFE08) === 0xFC00) {
            const r = (op >> 4) & 0x1F;
            const b = op & 0x07;
            if (((this.mem[r] >> b) & 1) === 0) this._skipNext();
            return 1;
        }
        // SBRS — 1111 111r rrrr 0bbb
        if ((op & 0xFE08) === 0xFE00) {
            const r = (op >> 4) & 0x1F;
            const b = op & 0x07;
            if (((this.mem[r] >> b) & 1) !== 0) this._skipNext();
            return 1;
        }

        // Unknown opcode — log once and halt so the UI can show it.
        console.warn('attiny_emu: unknown opcode 0x' + op.toString(16).padStart(4,'0')
                     + ' at pc=0x' + ((this.pc - 1) & 0x1FF).toString(16));
        this.halted = true;
        return 1;
    }

    _skipNext() {
        // Next word may itself be 32-bit (LDS / STS / CALL / JMP). Detect.
        const nxt = this.flash[this.pc];
        const is32 =
            ((nxt & 0xFE0F) === 0x9000) ||
            ((nxt & 0xFE0F) === 0x9200) ||
            ((nxt & 0xFE0E) === 0x940C) ||
            ((nxt & 0xFE0E) === 0x940E);
        this.pc = (this.pc + (is32 ? 2 : 1)) & 0x1FF;
    }

    _handleLdStDisp(op, isStore) {
        // LDD/STD with displacement — 10q0 qq0d dddd 1qqq  (Y or Z)
        const d  = (op >> 4) & 0x1F;
        const q  = ((op >> 8) & 0x20) | ((op >> 7) & 0x18) | (op & 0x07);
        const useY = (op & 0x08) !== 0;
        const base = useY ? 28 : 30;
        const addr = ((this.mem[base] | (this.mem[base + 1] << 8)) + q) & 0xFFFF;
        if (isStore) this._writeMem(addr, this.mem[d]);
        else         this.mem[d] = this._readMem(addr);
        return 2;
    }

    _handle9400(op) {
        // 1001 010d dddd xxxx — single-register ops + misc 94xx forms.
        const low = op & 0x0F;
        const d   = (op >> 4) & 0x1F;

        // RET / RETI / SLEEP / WDR — 1001 0101 xxxx 1000
        if (op === 0x9508) {            // RET
            const lo = this._pop();
            const hi = this._pop();
            this.pc = ((hi << 8) | lo) & 0x1FF;
            return 4;
        }
        if (op === 0x9518) {            // RETI
            const lo = this._pop();
            const hi = this._pop();
            this.pc = ((hi << 8) | lo) & 0x1FF;
            this._setBit(1 << SREG_I, 1);
            return 4;
        }
        if (op === 0x9588) { /* SLEEP */ return 1; }
        if (op === 0x95A8) { /* WDR   */ return 1; }
        if (op === 0x95C8) { /* LPM R0,Z */
            const z = this.mem[30] | (this.mem[31] << 8);
            this.mem[0] = (this.flash[z >> 1] >> ((z & 1) * 8)) & 0xFF;
            return 3;
        }

        // BSET s — 1001 0100 0sss 1000
        if ((op & 0xFF8F) === 0x9408) {
            this._setBit(1 << ((op >> 4) & 0x07), 1);
            return 1;
        }
        // BCLR s — 1001 0100 1sss 1000
        if ((op & 0xFF8F) === 0x9488) {
            this._setBit(1 << ((op >> 4) & 0x07), 0);
            return 1;
        }

        const v = this.mem[d];
        switch (low) {
        case 0x0: {        // COM Rd
            const res = (~v) & 0xFF;
            this.mem[d] = res;
            this._setBit(1 << SREG_C, 1);
            this._flagsLogical(res);
            return 1;
        }
        case 0x1: {        // NEG Rd
            const res = (-v) & 0xFF;
            this.mem[d] = res;
            this._flagsAddSub(0, v, res, true, false);
            return 1;
        }
        case 0x2: {        // SWAP Rd
            this.mem[d] = ((v >> 4) & 0x0F) | ((v << 4) & 0xF0);
            return 1;
        }
        case 0x3: {        // INC Rd
            const res = (v + 1) & 0xFF;
            this.mem[d] = res;
            const n = (res >> 7) & 1;
            this._setBit(1 << SREG_V, v === 0x7F);
            this._setBit(1 << SREG_N, n);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_S, n ^ (v === 0x7F ? 1 : 0));
            return 1;
        }
        case 0x5: {        // ASR Rd
            const c = v & 1;
            const res = ((v >> 1) | (v & 0x80)) & 0xFF;
            this.mem[d] = res;
            const n = (res >> 7) & 1;
            this._setBit(1 << SREG_C, c);
            this._setBit(1 << SREG_N, n);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_V, n ^ c);
            this._setBit(1 << SREG_S, n);
            return 1;
        }
        case 0x6: {        // LSR Rd
            const c = v & 1;
            const res = (v >> 1) & 0xFF;
            this.mem[d] = res;
            this._setBit(1 << SREG_C, c);
            this._setBit(1 << SREG_N, 0);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_V, c);
            this._setBit(1 << SREG_S, c);
            return 1;
        }
        case 0x7: {        // ROR Rd
            const c = v & 1;
            const cIn = this._getBit(SREG_C);
            const res = ((v >> 1) | (cIn << 7)) & 0xFF;
            this.mem[d] = res;
            const n = (res >> 7) & 1;
            this._setBit(1 << SREG_C, c);
            this._setBit(1 << SREG_N, n);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_V, n ^ c);
            this._setBit(1 << SREG_S, n ^ (n ^ c));
            return 1;
        }
        case 0xA: {        // DEC Rd
            const res = (v - 1) & 0xFF;
            this.mem[d] = res;
            const n = (res >> 7) & 1;
            this._setBit(1 << SREG_V, v === 0x80);
            this._setBit(1 << SREG_N, n);
            this._setBit(1 << SREG_Z, res === 0);
            this._setBit(1 << SREG_S, n ^ (v === 0x80 ? 1 : 0));
            return 1;
        }
        }
        console.warn('attiny_emu: unhandled 94xx op 0x' + op.toString(16));
        this.halted = true;
        return 1;
    }

    // ---- Bulk step helper --------------------------------------------

    runFor(cycleBudget) {
        let used = 0;
        while (used < cycleBudget && !this.halted) {
            used += this.step();
        }
        this.cycles += used;
        return used;
    }
}

// --- Export -------------------------------------------------------------

root.AttinyEmu = {
    parseIntelHex,
    ATtiny13aEmu,
    IO,
};

})(typeof window !== 'undefined' ? window : globalThis);
