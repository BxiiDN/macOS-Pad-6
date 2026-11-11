// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for PipaBacklight.c, the kernel shim of the KTZ8866 backlight, run against a simulated tablet: the GCC and
// TLMM as register files, the I2C11 serial engine as the GENI simulator (GeniI2cSim.h) with a KTZ8866 at 0x11. Checks
// that the shim maps what it needs, refuses on every clock or pin problem without writing a GCC or TLMM register, reads
// DEVICE_ID without writing a KTZ8866 register, never writes the engine's configuration, and unmaps everything.
// A model of the tablet, not the tablet.
// cc -std=gnu11 -Wall -Wextra -Werror package/PipaBacklightTests.c package/PipaBacklight.c && ./a.out
#include "Ktz8866Driver.h"
#include "GeniI2cBoard.h"
#include "PipaBacklightPlatform.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)
#include "GeniI2cSim.h"

extern volatile int32_t pipa_backlight_stats[16];
int pipa_backlight_attach(void);

// The simulated tablet.
static uint32_t gcc[0x60000 / 4];
static uint32_t tlmm[GIB_PINS][GIB_GPIO_STRIDE / 4];
static uint32_t se_page[0x4000 / 4];             // only its address is used: accesses go to the simulator
static Sim sim;
static int arg_set;
static uint32_t arg_value;
static unsigned maps, unmaps, gcc_writes, tlmm_writes, fail_map_after = 1000;

volatile uint32_t *pipa_map(uint64_t phys, uint64_t size) {
    if (maps++ >= fail_map_after) return NULL;
    if (phys == GIB_GCC_BASE && size == sizeof gcc) return gcc;
    if (phys == BKL_I2C_SE_BASE && size == sizeof se_page) return se_page;
    for (unsigned i = 0; i < GIB_PINS; ++i)
        if (phys == GIB_TLMM_BASE + gib_ctl(&gib_pins[i]) && size == GIB_GPIO_STRIDE) return tlmm[i];
    CHECK(!"mapped an unexpected window");
    return NULL;
}
void pipa_unmap(volatile uint32_t *va, uint64_t size) { (void)size; if (va) unmaps++; }
void pipa_delay_us(unsigned us) { (void)us; }
int pipa_boot_arg(const char *name, uint32_t *value) {
    CHECK(strcmp(name, "pipa-backlight") == 0);
    if (arg_set) *value = arg_value;
    return arg_set;
}
void pipa_barrier(void) {}
uint32_t pipa_rd(volatile uint32_t *base, uint32_t off) {
    if (base == se_page) return sim_read(&sim, off);
    return base[off / 4];
}
void pipa_wr(volatile uint32_t *base, uint32_t off, uint32_t v) {
    if (base == se_page) { sim_write(&sim, off, v); return; }
    if (base == gcc) gcc_writes++; else tlmm_writes++;
    base[off / 4] = v;
}
int pipa_log(const char *fmt, ...) { va_list a; va_start(a, fmt); int n = vprintf(fmt, a); va_end(a); return n; }

// A tablet as the firmware is expected to leave it: wrap1 voted and running, s3 at 19.2 MHz (DFS level 0 = TCXO),
// the bus pins on qup11 at 2 mA without bias, HWEN and both bias enables driven high, a KTZ8866 at 0x11.
static void good_tablet(void) {
    memset(gcc, 0, sizeof gcc);
    memset(tlmm, 0, sizeof tlmm);
    gcc[GIB_GCC_VOTE / 4] = GIB_VOTES | 0x3c0;               // other branches voted too
    gcc[GIB_HALT_S_AHB / 4] = GIB_CBCR_CLK_OFF | GIB_CBCR_HW_CTL;   // hardware-gated and idle: not an error
    gcc[(GIB_S3_RCG + GIB_RCG_DFSR) / 4] = 1;
    gcc[(GIB_S3_RCG + GIB_RCG_PERF_CFG(0)) / 4] = 0;          // TCXO, no divider: 19.2 MHz
    gcc[(GIB_S3_RCG + GIB_RCG_PERF_CFG(3)) / 4] = 1u << 8 | 11; // GPLL0 600 MHz / 6 = 100 MHz
    for (unsigned i = 0; i < GIB_PINS; ++i) {
        if (gib_pins[i].output) {
            tlmm[i][0] = 1u << 9;                             // gpio function, output enabled
            tlmm[i][1] = 1u << 1;                             // driven high
        } else {
            tlmm[i][0] = GIB_FUNC_QUP11 << 2;                 // qup11, 2 mA, no pull
        }
    }
    sim_reset(&sim);
    maps = unmaps = gcc_writes = tlmm_writes = 0;
    fail_map_after = 1000;
    arg_set = 1;
    arg_value = 1;
}

static void no_side_effects(void) {
    CHECK(gcc_writes == 0 && tlmm_writes == 0);               // clocks and pins are only read
    CHECK(sim.t[0].data_writes == 0);                         // no KTZ8866 register written
    CHECK(sim.forbidden == 0);                                // no engine configuration register written
    CHECK(unmaps == maps);                                    // every window unmapped again
}

int main(void) {
    // Not asked for: nothing is mapped.
    good_tablet();
    arg_set = 0;
    CHECK(pipa_backlight_attach() == 1 && maps == 0 && pipa_backlight_stats[0] == 0);
    arg_set = 1; arg_value = 2;
    CHECK(pipa_backlight_attach() == 1 && maps == 0);

    // A ready tablet: attached, DEVICE_ID read, nothing written.
    good_tablet();
    CHECK(pipa_backlight_attach() == 0);
    CHECK(pipa_backlight_stats[0] == 2 && pipa_backlight_stats[1] == 0 && pipa_backlight_stats[2] == 19200);
    CHECK(pipa_backlight_stats[5] == GENI_I2C_OK && pipa_backlight_stats[6] == 0x5a && pipa_backlight_stats[3] == -1);
    CHECK(maps == 2 + GIB_PINS);
    CHECK(sim.ncmd == 2 && sim.cmd[0].op == GENI_I2C_WRITE && sim.cmd[0].len == 1 && sim.cmd[1].op == GENI_I2C_READ);
    no_side_effects();

    // Each clock or pin problem stops it before any I2C traffic, with the reason.
    good_tablet(); gcc[GIB_GCC_VOTE / 4] &= ~GIB_VOTE_WRAP1_S3;
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_VOTE_MISSING && sim.ncmd == 0);
    no_side_effects();
    good_tablet(); gcc[GIB_HALT_CORE / 4] = GIB_CBCR_CLK_OFF;
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_BRANCH_OFF &&
          pipa_backlight_stats[4] == (int32_t)GIB_HALT_CORE && sim.ncmd == 0);
    no_side_effects();
    good_tablet(); sim.clk_sel = 3;                            // the engine runs at the 100 MHz level
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_WRONG_RATE && pipa_backlight_stats[2] == 100000);
    no_side_effects();
    good_tablet(); gcc[(GIB_S3_RCG + GIB_RCG_DFSR) / 4] = 0;
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_NO_DFS);
    no_side_effects();
    good_tablet(); tlmm[2][1] = 0;                             // HWEN (TLMM 139) low: the chip is off
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_ENABLE_LOW && pipa_backlight_stats[3] == 139);
    no_side_effects();
    good_tablet(); tlmm[1][0] = 0;                             // SCL left as a GPIO
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_PIN_MUX && pipa_backlight_stats[3] == 61);
    no_side_effects();
    good_tablet(); tlmm[0][0] |= 3;                            // SDA with a pull-up
    CHECK(pipa_backlight_attach() == -2 && pipa_backlight_stats[1] == GIB_PIN_CONFIG && pipa_backlight_stats[3] == 60);
    no_side_effects();

    // The engine or the chip refuses: reported, nothing written.
    good_tablet(); sim.t[0].present = 0;
    CHECK(pipa_backlight_attach() == -3 && pipa_backlight_stats[5] == GENI_I2C_ADDR_NACK);
    no_side_effects();
    good_tablet(); sim.dma_mode = 1;
    CHECK(pipa_backlight_attach() == -3 && pipa_backlight_stats[5] == GENI_I2C_DMA_MODE && sim.ncmd == 0);
    no_side_effects();
    good_tablet(); sim.scl = geni_i2c_scl_counters(geni_i2c_scl_lookup(19200000u, 100000u));
    CHECK(pipa_backlight_attach() == -3 && pipa_backlight_stats[5] == GENI_I2C_CLOCK && sim.ncmd == 0);
    no_side_effects();
    good_tablet(); sim.fw_rev = 2u << 8;
    CHECK(pipa_backlight_attach() == -3 && pipa_backlight_stats[5] == GENI_I2C_NOT_I2C);
    no_side_effects();

    // A window that cannot be mapped: stopped, the others unmapped.
    good_tablet(); fail_map_after = 3;
    CHECK(pipa_backlight_attach() == -1 && pipa_backlight_stats[0] == -1 && unmaps == 3);

    puts("PASS: pipa backlight shim (map, clock/pin checks, read-only KTZ8866 attach, refusals, unmap) on a simulated tablet");
    return 0;
}
