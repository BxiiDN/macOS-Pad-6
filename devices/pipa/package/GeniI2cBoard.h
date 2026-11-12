// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa's backlight bus (I2C11 = QUP wrapper 1 serial engine 3): the clocks and pins it needs, and a check of them from
// register reads alone. Pure functions over values a caller read; PipaBacklight.cpp does the reads on the tablet,
// GeniI2cBoardTests.c on modelled values. Nothing here writes: a clock that is off or a pin that is not configured is
// reported, never fixed (the firmware sets them; this board code does not change device configuration).
// Sources, all public, checked by scripts/pipa_hw.py drivers:
//   GCC  Linux drivers/clk/qcom/gcc-sm8250.c: gcc_qupv3_wrap1_{core_2x,core,s3}_clk, gcc_qupv3_wrap_1_{m,s}_ahb_clk
//        (halt registers, votes in 0x52008), gcc_qupv3_wrap1_s3_clk_src (cmd_rcgr 0x183a0, DFS, gcc_parent_map_0).
//   PIN  Linux drivers/pinctrl/qcom/pinctrl-sm8250.c (tile and function slot of each pin) and sm8250.dtsi
//        qup_i2c11_default (gpio60/61, qup11, 2 mA, bias-disable); TLMM register layout as in TouchBoard.h.
//   ML   sm8250-xiaomi-pipa.dts: backlight enable TLMM 139, bias regulators TLMM 130/131 (BacklightBoard.h).
#ifndef PIPA_GENI_I2C_BOARD_H
#define PIPA_GENI_I2C_BOARD_H
#include <stdint.h>
#include "BacklightBoard.h"

// GCC
#define GIB_GCC_BASE 0x00100000ULL
#define GIB_GCC_SIZE 0x1f0000ULL
#define GIB_GCC_VOTE 0x52008u                // GCC_APCS_CLOCK_BRANCH_ENA_VOTE
#define GIB_VOTE_WRAP1_CORE_2X (1u << 18)
#define GIB_VOTE_WRAP1_CORE (1u << 19)
#define GIB_VOTE_WRAP1_M_AHB (1u << 20)
#define GIB_VOTE_WRAP1_S_AHB (1u << 21)
#define GIB_VOTE_WRAP1_S3 (1u << 25)
#define GIB_VOTES (GIB_VOTE_WRAP1_CORE_2X | GIB_VOTE_WRAP1_CORE | GIB_VOTE_WRAP1_M_AHB | GIB_VOTE_WRAP1_S_AHB | GIB_VOTE_WRAP1_S3)
#define GIB_HALT_CORE_2X 0x23140u
#define GIB_HALT_CORE 0x23138u
#define GIB_HALT_S3 0x1839cu
#define GIB_HALT_M_AHB 0x18004u
#define GIB_HALT_S_AHB 0x18008u              // hwcg bit 1: under hardware clock gating CLK_OFF may read 1 while idle
#define GIB_CBCR_CLK_OFF (1u << 31)
#define GIB_CBCR_HW_CTL (1u << 1)
#define GIB_S3_RCG 0x183a0u
#define GIB_RCG_DFSR 0x14u                   // bit 0 DFS enabled (the s3 source is registered for DFS)
#define GIB_RCG_PERF_CFG(l) (0x1cu + 4u * (l))
#define GIB_RCG_PERF_M(l) (0x5cu + 4u * (l))
#define GIB_RCG_PERF_N(l) (0x9cu + 4u * (l))
#define GIB_DFS_LEVELS 8u
#define GIB_SE_HZ 19200000u                  // the source the 400 kHz SCL table is for (GeniI2cCore.h)
#define GIB_SE_CLK_SEL 0x7cu                 // SE_GENI_CLK_SEL: the DFS level the engine runs at

// TLMM
#define GIB_TLMM_BASE 0x0f000000ULL
#define GIB_TLMM_SIZE 0x1000000ULL
#define GIB_TILE_WEST 0x100000u
#define GIB_TILE_SOUTH 0x500000u
#define GIB_GPIO_STRIDE 0x1000u
#define GIB_GPIO_SDA 60u
#define GIB_GPIO_SCL 61u
#define GIB_FUNC_QUP11 1u                    // PINGROUP(60/61, SOUTH, qup11, ...): slot 1
#define GIB_FUNC_GPIO 0u
#define GIB_DRIVE_2MA 0u                     // drive-strength = <2>: code mA / 2 - 1
#define GIB_PULL_NONE 0u                     // bias-disable

typedef struct {
    unsigned gpio;
    uint32_t tile;
    unsigned func;
    int output;                              // 1: the pin must be an output driven high (enable lines); 0: a bus pin
    const char *name;
} GibPin;

static const GibPin gib_pins[] = {
    {GIB_GPIO_SDA, GIB_TILE_SOUTH, GIB_FUNC_QUP11, 0, "i2c11 sda"},
    {GIB_GPIO_SCL, GIB_TILE_SOUTH, GIB_FUNC_QUP11, 0, "i2c11 scl"},
    {BKL_GPIO_ENABLE, GIB_TILE_WEST, GIB_FUNC_GPIO, 1, "ktz8866 hwen"},
    {BKL_GPIO_VDDPOS, GIB_TILE_SOUTH, GIB_FUNC_GPIO, 1, "bias +5.5 V enable"},
    {BKL_GPIO_VDDNEG, GIB_TILE_SOUTH, GIB_FUNC_GPIO, 1, "bias -5.5 V enable"},
};
#define GIB_PINS (sizeof(gib_pins) / sizeof(gib_pins[0]))

static const uint32_t gib_halts[] = {GIB_HALT_CORE_2X, GIB_HALT_CORE, GIB_HALT_S3, GIB_HALT_M_AHB, GIB_HALT_S_AHB};
#define GIB_HALTS (sizeof(gib_halts) / sizeof(gib_halts[0]))

// The TLMM control and in/out register of a pin, relative to GIB_TLMM_BASE.
static inline uint32_t gib_ctl(const GibPin *p) { return p->tile + p->gpio * GIB_GPIO_STRIDE; }
static inline uint32_t gib_io(const GibPin *p) { return gib_ctl(p) + 4u; }

// What the caller read: GCC (vote, halts, the s3 RCG's DFS registers), the engine's CLK_SEL, each pin's ctl and io.
typedef struct {
    uint32_t vote;
    uint32_t halt[GIB_HALTS];
    uint32_t dfsr, perf_cfg[GIB_DFS_LEVELS], perf_m[GIB_DFS_LEVELS], perf_n[GIB_DFS_LEVELS];
    uint32_t clk_sel;
    uint32_t ctl[GIB_PINS], io[GIB_PINS];
} GibReads;

enum {
    GIB_OK = 0,
    GIB_VOTE_MISSING = 1u << 0,      // a wrap1 branch is not voted on
    GIB_BRANCH_OFF = 1u << 1,        // a branch reports CLK_OFF (and is not under hardware gating)
    GIB_NO_DFS = 1u << 2,            // the s3 RCG is not in DFS mode
    GIB_WRONG_RATE = 1u << 3,        // the level the engine selected is not 19.2 MHz
    GIB_PIN_MUX = 1u << 4,           // a bus pin is not on qup11, or an enable pin not on gpio
    GIB_PIN_CONFIG = 1u << 5,        // drive or bias of a bus pin is not the DT's
    GIB_ENABLE_LOW = 1u << 6,        // HWEN or a bias enable is not an output driven high: the chip is not powered
};

typedef struct {
    uint32_t problems;
    uint64_t se_hz;                  // the rate of the selected DFS level, 0 if not decodable
    unsigned bad_pin;                // the first pin with a problem (index into gib_pins), GIB_PINS if none
    uint32_t bad_halt;               // the first branch reported off, 0 if none
} GibReport;

// RCG rate from a DFS level's CFG (src 10:8, mode 13:12, hid 4:0) and M/N (N stored inverted, 16-bit), gcc_parent_map_0.
static inline uint64_t gib_level_hz(uint32_t cfg, uint32_t mreg, uint32_t nreg) {
    unsigned src = (cfg >> 8) & 7, mode = (cfg >> 12) & 3, hid = cfg & 0x1f;
    uint64_t hz = src == 0 ? 19200000ULL : src == 1 ? 600000000ULL : src == 6 ? 300000000ULL : 0;
    if (hid) hz = hz * 2 / (hid + 1);
    if (mode) {
        uint32_t m = mreg & 0xffff, n = ((~nreg) & 0xffff) + m;
        hz = n ? hz * m / n : 0;
    }
    return hz;
}

static inline GibReport gib_check(const GibReads *r) {
    GibReport out = {0, 0, GIB_PINS, 0};
    if ((r->vote & GIB_VOTES) != GIB_VOTES) out.problems |= GIB_VOTE_MISSING;
    for (unsigned i = 0; i < GIB_HALTS; ++i) {
        if ((r->halt[i] & GIB_CBCR_CLK_OFF) && !(r->halt[i] & GIB_CBCR_HW_CTL)) {
            out.problems |= GIB_BRANCH_OFF;
            if (!out.bad_halt) out.bad_halt = gib_halts[i];
        }
    }
    if (!(r->dfsr & 1)) {
        out.problems |= GIB_NO_DFS;
    } else if (r->clk_sel < GIB_DFS_LEVELS) {
        out.se_hz = gib_level_hz(r->perf_cfg[r->clk_sel], r->perf_m[r->clk_sel], r->perf_n[r->clk_sel]);
    }
    if (out.se_hz != GIB_SE_HZ && !(out.problems & GIB_NO_DFS)) out.problems |= GIB_WRONG_RATE;
    for (unsigned i = 0; i < GIB_PINS; ++i) {
        const GibPin *p = &gib_pins[i];
        uint32_t ctl = r->ctl[i], io = r->io[i], pr = 0;
        if (((ctl >> 2) & 0xf) != p->func) pr |= GIB_PIN_MUX;
        if (!p->output && (((ctl >> 6) & 7) != GIB_DRIVE_2MA || (ctl & 3) != GIB_PULL_NONE)) pr |= GIB_PIN_CONFIG;
        if (p->output && (!(ctl & (1u << 9)) || !(io & (1u << 1)))) pr |= GIB_ENABLE_LOW;
        if (pr && out.bad_pin == GIB_PINS) out.bad_pin = i;
        out.problems |= pr;
    }
    return out;
}

static inline const char *gib_problem_name(uint32_t bit) {
    switch (bit) {
    case GIB_VOTE_MISSING: return "wrap1 clock vote missing";
    case GIB_BRANCH_OFF: return "a wrap1 branch is off";
    case GIB_NO_DFS: return "s3 clock source not in DFS mode";
    case GIB_WRONG_RATE: return "selected s3 level is not 19.2 MHz";
    case GIB_PIN_MUX: return "pin function differs";
    case GIB_PIN_CONFIG: return "bus pin drive or bias differs";
    case GIB_ENABLE_LOW: return "enable or bias line not driven high";
    }
    return "?";
}

#endif
