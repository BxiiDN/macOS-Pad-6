// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa (Xiaomi Pad 6) panel backlight: the Kinetic KTZ8866 board facts and the register writes that drive it, as pure
// functions (no I2C access here). New in macOS-Pad-6; host-tested by BacklightBoardTests.c.
// Sources, every one public:
//   ML  mainline Linux sm8250-xiaomi-pipa.dts (067c5c24cef2): &i2c11 { clock-frequency = <400000>; backlight@11 {
//       compatible = "kinetic,ktz8866"; enable-gpios = <&tlmm 139>; current-num-sinks = <5>;
//       kinetic,current-ramp-delay-ms = <128>; kinetic,led-enable-ramp-delay-ms = <1>; kinetic,enable-lcd-bias; } },
//       bl_vddpos_5p5 (TLMM 130) and bl_vddneg_5p5 (TLMM 131), 5.5 V, ramp 233 us; i2c11 = GENI SE3 of QUP wrapper 1.
//   KTZ the register map and field encodings of Linux's drivers/video/backlight/ktz8866.c (the same commit): 8-bit
//       registers, 11-bit brightness split LSB[2:0] / MSB[7:0], BL_EN bits 5:0 the current sinks and bit 6 the enable,
//       BL_CFG2 = 0x80 | ramp code << 3 | PWM hysteresis 5, BL_DIMMING = on << 4 | off, LCD_BIAS_CFG1 = 0x9F.
// scripts/pipa_hw.py checks the ML values below against the mainline device tree. Nothing here has run on the tablet.
#ifndef PIPA_BACKLIGHT_BOARD_H
#define PIPA_BACKLIGHT_BOARD_H
#include <stdint.h>

// Board (ML)
#define BKL_I2C_SE_BASE 0x00a8c000ULL          // i2c11: QUP wrapper 1 (0xac0000) serial engine 3, GENI I2C
#define BKL_I2C_HZ 400000u
#define BKL_I2C_ADDR 0x11u                     // 7-bit
#define BKL_GPIO_ENABLE 139                    // TLMM, active high (HWEN)
#define BKL_GPIO_VDDPOS 130                    // TLMM, the +5.5 V panel bias regulator enable
#define BKL_GPIO_VDDNEG 131                    // TLMM, the -5.5 V panel bias regulator enable
#define BKL_GPIO_PANELID 30                    // TLMM, ktz8866,panelid-gpio of the vendor tree (not in mainline)
#define BKL_SINKS 5u
#define BKL_CURRENT_RAMP_MS 128u
#define BKL_LED_RAMP_MS 1u
#define BKL_LCD_BIAS 1u

// KTZ8866 registers (KTZ)
#define BKL_REG_DEVICE_ID 0x01u
#define BKL_REG_CFG2 0x03u
#define BKL_REG_BRT_LSB 0x04u
#define BKL_REG_BRT_MSB 0x05u
#define BKL_REG_EN 0x08u
#define BKL_REG_LCD_BIAS_CFG1 0x09u
#define BKL_REG_DIMMING 0x14u
#define BKL_REG_MAX 0x15u
#define BKL_EN_BIT 0x40u                       // BL_EN bit 6: the backlight on
#define BKL_LCD_BIAS_EN 0x9Fu
#define BKL_PWM_HYST 0x5u
#define BKL_MAX_LEVEL 2047u
#define BKL_DEFAULT_LEVEL 1500u

typedef struct {
    uint8_t reg;
    uint8_t mask;     // 0xff: a plain write; otherwise only these bits change (read-modify-write)
    uint8_t value;
} BklWrite;

typedef struct {
    unsigned sinks;            // 1..6; 0 means all six
    unsigned current_ramp_ms;  // 0 leaves BL_CFG2 alone
    int led_ramp_ms;           // < 0 leaves BL_DIMMING alone; 0 turns the dimming ramp off
    int lcd_bias;
} BklConfig;

static inline unsigned bkl_log2(unsigned v) {
    unsigned r = 0;
    while (v > 1) {
        v >>= 1;
        r++;
    }
    return r;
}

static inline BklConfig bkl_pipa_config(void) {
    BklConfig c = {BKL_SINKS, BKL_CURRENT_RAMP_MS, (int)BKL_LED_RAMP_MS, BKL_LCD_BIAS};
    return c;
}

// BL_CFG2's current ramp field: floor(log2(ms)) up to 128 ms, 5 + ms / 64 above (KTZ). A ramp of 0 ms is encoded as 0.
static inline uint8_t bkl_cfg2(unsigned ramp_ms) {
    unsigned code = ramp_ms <= 128 ? (ramp_ms ? bkl_log2(ramp_ms) : 0) : 5 + ramp_ms / 64;
    return (uint8_t)(0x80u | (code & 0xfu) << 3 | BKL_PWM_HYST);
}

// BL_DIMMING: the same code for the on and off ramps, floor(log2(ms)) + 1; 0 turns the ramp off (KTZ).
static inline uint8_t bkl_dimming(unsigned ramp_ms) {
    if (ramp_ms == 0)
        return 0;
    unsigned off = (bkl_log2(ramp_ms) + 1) & 0xfu;
    return (uint8_t)(off << 4 | off);
}

// The configuration writes after power-up, in order. Returns the number written to out (at most 4).
static inline unsigned bkl_init_writes(const BklConfig *c, BklWrite *out) {
    unsigned n = 0, sinks = c->sinks == 0 || c->sinks > 6 ? 6 : c->sinks;
    out[n++] = (BklWrite){BKL_REG_EN, 0xff, (uint8_t)((1u << sinks) - 1)};
    if (c->current_ramp_ms)
        out[n++] = (BklWrite){BKL_REG_CFG2, 0xff, bkl_cfg2(c->current_ramp_ms)};
    if (c->led_ramp_ms >= 0)
        out[n++] = (BklWrite){BKL_REG_DIMMING, 0xff, bkl_dimming((unsigned)c->led_ramp_ms)};
    if (c->lcd_bias)
        out[n++] = (BklWrite){BKL_REG_LCD_BIAS_CFG1, 0xff, BKL_LCD_BIAS_EN};
    return n;
}

// The writes that set a brightness (0..2047; larger values are clamped). *on tracks BL_EN bit 6 across calls, as the
// driver keeps it: the bit is set on the first nonzero level and cleared at 0. Returns the number written (at most 3).
static inline unsigned bkl_brightness_writes(unsigned level, int *on, BklWrite *out) {
    unsigned n = 0;
    if (level > BKL_MAX_LEVEL)
        level = BKL_MAX_LEVEL;
    if (level > 0 && !*on) {
        out[n++] = (BklWrite){BKL_REG_EN, BKL_EN_BIT, BKL_EN_BIT};
        *on = 1;
    } else if (level == 0) {
        out[n++] = (BklWrite){BKL_REG_EN, BKL_EN_BIT, 0};
        *on = 0;
    }
    out[n++] = (BklWrite){BKL_REG_BRT_LSB, 0xff, (uint8_t)(level & 0x7u)};
    out[n++] = (BklWrite){BKL_REG_BRT_MSB, 0xff, (uint8_t)((level >> 3) & 0xffu)};
    return n;
}

// A brightness fraction num/den (as a display stack reports it) to the 11-bit level, rounded to nearest.
static inline unsigned bkl_level_from_fraction(uint32_t num, uint32_t den) {
    if (den == 0)
        return 0;
    if (num >= den)
        return BKL_MAX_LEVEL;
    return (unsigned)(((uint64_t)num * BKL_MAX_LEVEL + den / 2) / den);
}

// Applies writes to a modelled register file (for tests and for logging what a sequence leaves behind).
static inline void bkl_apply(uint8_t regs[BKL_REG_MAX + 1], const BklWrite *w, unsigned n) {
    for (unsigned i = 0; i < n; i++) {
        if (w[i].reg > BKL_REG_MAX)
            continue;
        regs[w[i].reg] = (uint8_t)((regs[w[i].reg] & ~w[i].mask) | (w[i].value & w[i].mask));
    }
}

#endif
