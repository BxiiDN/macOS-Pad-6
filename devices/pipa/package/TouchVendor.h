// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa touchscreen: what a driver needs from the Android device tree, beyond the bus facts of TouchBoard.h. The
// controller is a Novatek NT36532 in TDDI mode (touch and display driver in one chip, the panel's mi,is-tddi-flag)
// on QUP0 SE4 SPI. Pure facts and helpers; host-tested by TouchVendorTests.c; scripts/pipa_hw.py vendor checks every
// value against MiCode/kernel_devicetree pipa-t-oss (qcom/pipa-sm8250.dtsi novatek@0). New in macOS-Pad-6.
//
// What it says a driver must do, as the vendor configures it:
//   - SPI mode 0 (TouchBoard.h) at 9.6 MHz (the tree lists 4.8, 9.6, 15 and 19.2 MHz as choices in a comment);
//   - interrupt on TLMM 39, rising edge, one shot (flags 0x2001 = IRQF_TRIGGER_RISING | IRQF_ONESHOT);
//   - no reset GPIO: novatek,reset-gpio is commented out; in TDDI mode the panel's reset line (PanelBoard.h
//     PNL_GPIO_RESET, TLMM 75) resets the touch half too, and the touch bootloader is otherwise reset over SPI;
//   - firmware chosen by the panel maker byte of mi,panel-id (PanelBoard.h): 0x42 CSOT, 0x36 TM; the images are the
//     tablet's (vendor partition), never in this repository. UniXNU-pipa's build-gop-legacy-display.py builds in the TM
//     image only, so a CSOT tablet would get the other maker's firmware: tv_config_for_panel is the selection a driver
//     should make from the panel identity instead (not wired yet);
//   - a 38 x 60 sensor matrix (X_Channel, Y_Channel of both makers' MP criteria), active pen, doubled stylus
//     resolution.
#ifndef PIPA_TOUCH_VENDOR_H
#define PIPA_TOUCH_VENDOR_H
#include <stddef.h>
#include <stdint.h>
#include "PanelBoard.h"

#define TV_COMPATIBLE "novatek,NVT-ts-spi"
#define TV_SPI_HZ 9600000u
#define TV_IRQ_GPIO 39u
#define TV_IRQ_FLAGS 0x2001u
#define TV_IRQF_TRIGGER_RISING 0x0001u     // include/linux/interrupt.h
#define TV_IRQF_ONESHOT 0x2000u
#define TV_X_CHANNELS 38u
#define TV_Y_CHANNELS 60u
#define TV_PEN 1
#define TV_STYLUS_DOUBLE 1

typedef struct {
    unsigned maker;
    const char *firmware, *mp;
} TvConfig;

// novatek,cfg_N in the tree's order.
static const TvConfig tv_configs[] = {
    {PNL_MAKER_CSOT, "novatek_nt36532_m82_fw_csot.bin", "novatek_nt36532_m82_mp_csot.bin"},
    {PNL_MAKER_TM, "novatek_nt36532_m82_fw_tm.bin", "novatek_nt36532_m82_mp_tm.bin"},
};
#define TV_CONFIGS (sizeof(tv_configs) / sizeof(tv_configs[0]))

// The SPI rates the tree's comment offers.
static const uint32_t tv_spi_choices[] = {4800000u, 9600000u, 15000000u, 19200000u};

// The configuration for a panel identity (mi,panel-id words), or NULL for a panel the tree does not know.
static inline const TvConfig *tv_config_for_panel(uint32_t id0, uint32_t id1) {
    if (pnl_variant(id0, id1) == PNL_UNKNOWN)
        return NULL;
    for (size_t i = 0; i < TV_CONFIGS; ++i)
        if (tv_configs[i].maker == pnl_maker(id1))
            return &tv_configs[i];
    return NULL;
}

// The sensor nodes a full-frame report covers.
static inline unsigned tv_nodes(void) { return TV_X_CHANNELS * TV_Y_CHANNELS; }

#endif
