// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the kernel side of the KTZ8866 backlight, read only. With boot argument pipa-backlight=1, pipa_backlight_attach()
//   1. maps the GCC, the TLMM pages of the five pins and the I2C11 serial engine (device memory, unmapped again after),
//   2. reads the wrap1 clock votes and branches, the s3 clock source's DFS level and the pins, and checks them
//      (GeniI2cBoard.h): a clock that is off or a pin that is not configured stops here; nothing is turned on,
//   3. probes the engine and its SCL timing and reads the KTZ8866's DEVICE_ID (Ktz8866Driver.h ktz_attach).
// allow_writes stays 0: no KTZ8866 register is written (a register read sends the chip only its register pointer), and
// no GCC, TLMM or engine configuration register is written (the engine's command and FIFO registers are, as any
// transfer needs; GeniI2cCore.h). The outcome is in pipa_backlight_stats and on the console.
// New in macOS-Pad-6. Host-tested against a simulated tablet (PipaBacklightTests.c); not built into the macOS kernel
// yet and never run on the tablet.
#include "PipaBacklightPlatform.h"
#include "GeniI2cBoard.h"
#include "Ktz8866Driver.h"

// [0] state: 0 not run, 1 running, 2 attached, -1 a map failed, -2 clocks or pins not ready, -3 engine or chip refused
// [1] GeniI2cBoard problems   [2] selected s3 rate in kHz   [3] first bad pin's GPIO, -1 none   [4] first branch off, 0
// [5] GeniI2cStatus of the attach   [6] DEVICE_ID   [7] engine FW_REVISION   [8] SCL counters   [9] M_CLK_CFG
volatile int32_t pipa_backlight_stats[16];

#define GCC_WINDOW 0x60000u   // up to the vote register 0x52008 and the RCG at 0x183a0

static volatile uint32_t *gcc, *se, *pins[GIB_PINS];

static uint32_t rd(volatile uint32_t *base, uint32_t off) { return pipa_rd(base, off); }
static uint32_t se_read(void *ctx, uint32_t off) { return pipa_rd((volatile uint32_t *)ctx, off); }
static void se_write(void *ctx, uint32_t off, uint32_t v) { pipa_wr((volatile uint32_t *)ctx, off, v); }
static void se_delay(void *ctx, unsigned us) { (void)ctx; pipa_delay_us(us); }

static void unmap_all(void) {
    pipa_unmap(gcc, GCC_WINDOW);
    pipa_unmap(se, 0x4000);
    for (unsigned i = 0; i < GIB_PINS; ++i)
        pipa_unmap(pins[i], GIB_GPIO_STRIDE);
    gcc = se = 0;
    for (unsigned i = 0; i < GIB_PINS; ++i)
        pins[i] = 0;
}

static int finish(int32_t state, int32_t code) {
    pipa_backlight_stats[0] = state;
    unmap_all();
    return code;
}

// 0 attached, 1 not asked (no pipa-backlight=1), < 0 the step that stopped it (= pipa_backlight_stats[0]).
int pipa_backlight_attach(void) {
    uint32_t on = 0;
    if (!pipa_boot_arg("pipa-backlight", &on) || on != 1)
        return 1;
    for (unsigned i = 0; i < 16; ++i)
        pipa_backlight_stats[i] = 0;
    pipa_backlight_stats[0] = 1;
    pipa_backlight_stats[3] = -1;

    gcc = pipa_map(GIB_GCC_BASE, GCC_WINDOW);
    se = pipa_map(BKL_I2C_SE_BASE, 0x4000);
    for (unsigned i = 0; i < GIB_PINS; ++i)
        pins[i] = pipa_map(GIB_TLMM_BASE + gib_ctl(&gib_pins[i]), GIB_GPIO_STRIDE);
    int mapped = gcc && se;
    for (unsigned i = 0; i < GIB_PINS; ++i)
        mapped = mapped && pins[i];
    if (!mapped) {
        pipa_log("pipa-backlight: cannot map the GCC, TLMM or I2C11 windows\n");
        return finish(-1, -1);
    }

    GibReads r = {0};
    r.vote = rd(gcc, GIB_GCC_VOTE);
    for (unsigned i = 0; i < GIB_HALTS; ++i)
        r.halt[i] = rd(gcc, gib_halts[i]);
    r.dfsr = rd(gcc, GIB_S3_RCG + GIB_RCG_DFSR);
    for (unsigned l = 0; l < GIB_DFS_LEVELS; ++l) {
        r.perf_cfg[l] = rd(gcc, GIB_S3_RCG + GIB_RCG_PERF_CFG(l));
        r.perf_m[l] = rd(gcc, GIB_S3_RCG + GIB_RCG_PERF_M(l));
        r.perf_n[l] = rd(gcc, GIB_S3_RCG + GIB_RCG_PERF_N(l));
    }
    r.clk_sel = rd(se, GIB_SE_CLK_SEL) & 0xf;
    for (unsigned i = 0; i < GIB_PINS; ++i) {
        r.ctl[i] = rd(pins[i], 0);                 // the page starts at the pin's control register
        r.io[i] = rd(pins[i], 4);
    }
    const GibReport rep = gib_check(&r);
    pipa_backlight_stats[1] = (int32_t)rep.problems;
    pipa_backlight_stats[2] = (int32_t)(rep.se_hz / 1000);
    pipa_backlight_stats[3] = rep.bad_pin < GIB_PINS ? (int32_t)gib_pins[rep.bad_pin].gpio : -1;
    pipa_backlight_stats[4] = (int32_t)rep.bad_halt;
    if (rep.problems) {
        for (uint32_t bit = 1; bit && bit <= GIB_ENABLE_LOW; bit <<= 1)
            if (rep.problems & bit)
                pipa_log("pipa-backlight: not ready: %s\n", gib_problem_name(bit));
        return finish(-2, -2);
    }

    GeniI2c bus = {se_read, se_write, se_delay, (void *)se, 10, 1000};
    Ktz8866 k = ktz_pipa(&bus);                    // allow_writes = 0
    const GeniI2cStatus s = ktz_attach(&k);
    pipa_backlight_stats[5] = (int32_t)s;
    pipa_backlight_stats[6] = k.device_id;
    pipa_backlight_stats[7] = (int32_t)k.se.fw_revision;
    pipa_backlight_stats[8] = (int32_t)k.se.scl_counters;
    pipa_backlight_stats[9] = (int32_t)k.se.m_clk_cfg;
    if (s != GENI_I2C_OK) {
        pipa_log("pipa-backlight: KTZ8866 attach refused: %s\n", geni_i2c_status_name(s));
        return finish(-3, -3);
    }
    pipa_log("pipa-backlight: KTZ8866 at I2C11 0x11 answers, DEVICE_ID 0x%02x (read only)\n", k.device_id);
    return finish(2, 0);
}
