// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa KTZ8866 backlight driver core: the board writes of BacklightBoard.h carried out over GeniI2cCore.h. Portable C,
// no kernel dependency; host-tested against the register simulator of GeniI2cTests.c. New in macOS-Pad-6; nothing
// here has run on the tablet.
//
// Order of use, as Linux's drivers/video/backlight/ktz8866.c probe does it: the board raises the bias regulators
// (TLMM 130, 131) and HWEN (TLMM 139) - pins are not this file's - then
//   ktz_attach  read only: checks the serial engine (I2C firmware, FIFO interface, idle, 400 kHz counters) and reads
//               DEVICE_ID (0x01), which proves the chip acknowledges at 0x11. The value is recorded, not judged: the
//               public sources give no expected ID.
//   ktz_init    BacklightBoard.h's configuration writes (sinks, current ramp, dimming ramp, LCD bias).
//   ktz_set     a brightness level (0..2047); BL_EN bit 6 follows the level.
// Writes are refused (GENI_I2C_READ_ONLY) until the caller sets allow_writes: the first run on hardware is meant to be
// ktz_attach alone.
#ifndef PIPA_KTZ8866_DRIVER_H
#define PIPA_KTZ8866_DRIVER_H
#include "BacklightBoard.h"
#include "GeniI2cCore.h"

#define KTZ_SE_SOURCE_HZ 19200000u   // Linux keeps 19.2 MHz unless the firmware already selected 32 MHz

typedef struct {
    const GeniI2c *bus;
    uint8_t addr;
    int allow_writes;
    int on;                          // BL_EN bit 6 as last written
    unsigned level;
    uint8_t device_id;
    GeniI2cInfo se;
    uint32_t se_source_hz;
} Ktz8866;

static inline Ktz8866 ktz_pipa(const GeniI2c *bus) {
    Ktz8866 k = {0};
    k.bus = bus;
    k.addr = BKL_I2C_ADDR;
    k.se_source_hz = KTZ_SE_SOURCE_HZ;
    return k;
}

static inline GeniI2cStatus ktz_attach(Ktz8866 *k) {
    GeniI2cStatus s = geni_i2c_probe(k->bus, &k->se);
    if (s == GENI_I2C_OK)
        s = geni_i2c_check_clock(&k->se, k->se_source_hz, BKL_I2C_HZ);
    if (s == GENI_I2C_OK)
        s = geni_i2c_read_reg(k->bus, k->addr, BKL_REG_DEVICE_ID, &k->device_id);
    return s;
}

static inline GeniI2cStatus ktz_write(Ktz8866 *k, const BklWrite *w) {
    if (!k->allow_writes)
        return GENI_I2C_READ_ONLY;
    if (w->reg > BKL_REG_MAX)
        return GENI_I2C_INVALID;
    uint8_t v = w->value;
    if (w->mask != 0xff) {                       // regmap_update_bits: read, modify, write
        uint8_t cur;
        GeniI2cStatus s = geni_i2c_read_reg(k->bus, k->addr, w->reg, &cur);
        if (s != GENI_I2C_OK)
            return s;
        v = (uint8_t)((cur & ~w->mask) | (w->value & w->mask));
    }
    return geni_i2c_write_reg(k->bus, k->addr, w->reg, v);
}

static inline GeniI2cStatus ktz_write_all(Ktz8866 *k, const BklWrite *w, unsigned n) {
    for (unsigned i = 0; i < n; i++) {
        GeniI2cStatus s = ktz_write(k, &w[i]);
        if (s != GENI_I2C_OK)
            return s;
    }
    return GENI_I2C_OK;
}

static inline GeniI2cStatus ktz_init(Ktz8866 *k, const BklConfig *c) {
    BklWrite w[4];
    unsigned n = bkl_init_writes(c, w);
    GeniI2cStatus s = ktz_write_all(k, w, n);
    if (s == GENI_I2C_OK)
        k->on = 0;                               // BL_EN was written whole: bit 6 is clear
    return s;
}

static inline GeniI2cStatus ktz_set(Ktz8866 *k, unsigned level) {
    BklWrite w[3];
    int on = k->on;
    unsigned n = bkl_brightness_writes(level, &on, w);
    GeniI2cStatus s = ktz_write_all(k, w, n);
    if (s == GENI_I2C_OK) {
        k->on = on;
        k->level = level > BKL_MAX_LEVEL ? BKL_MAX_LEVEL : level;
    }
    return s;
}

#endif
