// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for PanelBoard.h: the vendor panel timing is self-consistent (the DSC line time, totals and lane count give
// exactly the tree's bit clock), DSC slices tile the frame, dynamic-fps porches, physical size, identity. This checks
// arithmetic on the device tree's numbers, not the panel.
// cc -std=gnu11 -Wall -Wextra -Werror package/PanelBoardTests.c && ./a.out
#include "PanelBoard.h"
#include "BacklightBoard.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

static unsigned isqrt(uint64_t v) {
    uint64_t r = 0;
    while ((r + 1) * (r + 1) <= v)
        r++;
    return (unsigned)r;
}

int main(void) {
    // The frame buffer the firmware leaves (LegacyDisplayProbe.cpp, uefi-pipa GOP) is the whole panel.
    CHECK(pnl_width() == 1800 && PNL_V_ACTIVE == 2880);
    CHECK(pnl_fb_stride(4) == 7200);

    // Timing and link.
    CHECK(pnl_htotal() == 1048 && pnl_vtotal() == 3122);
    CHECK(pnl_pixel_clock(PNL_FPS) == 392622720ull);
    CHECK(pnl_dsc_h_active() == 300);
    CHECK(pnl_bitclk(PNL_FPS) == PNL_BITCLK_HZ);          // (300 + 148) * 3122 * 120 * 24 / 4
    CHECK(pnl_bitclk(PNL_FPS) < 2500000000ull);           // under the D-PHY 2.5 Gb/s per lane ceiling
    // Without DSC the same timing would need 2.36 Gb/s per lane: the tree's rate is only reachable compressed.
    CHECK(pnl_pixel_clock(PNL_FPS) * PNL_BPP / PNL_LANES > PNL_BITCLK_HZ);

    // DSC: two 450-pixel slices per line on each interface, 144 slice rows, one encoder per interface.
    CHECK(pnl_slices_per_line() == 2 && pnl_slice_rows() == 144);
    CHECK(PNL_DSC_SLICE_PER_PKT <= pnl_slices_per_line());
    CHECK(PNL_TOPOLOGY_DSC == PNL_DSI_COUNT && PNL_TOPOLOGY_INTF == PNL_DSI_COUNT && PNL_TOPOLOGY_LM == PNL_DSI_COUNT);
    CHECK(PNL_DSC_BPC == 8 && PNL_DSC_BPP == 8 && PNL_DSC_VERSION == 0x11);

    // Dynamic fps by front porch: the base rate is the tree's porch; lower rates stretch it; higher cannot.
    CHECK(pnl_vfp_for_fps(PNL_FPS) == (int)PNL_VFP);
    CHECK(pnl_vfp_for_fps(60) == 3148 && pnl_vfp_for_fps(30) == 9392 && pnl_vfp_for_fps(48) == 4709);
    CHECK(pnl_vfp_for_fps(144) == -1 && pnl_vfp_for_fps(0) == -1);
    unsigned listed = 0, reachable = 0;
    for (unsigned i = 0; i < sizeof(pnl_dfps); i++) {
        listed++;
        int vfp = pnl_vfp_for_fps(pnl_dfps[i]);
        if (vfp < 0)
            continue;
        reachable++;
        // The rate the stretched frame gives is within 0.05% of the one asked for.
        uint64_t vt = PNL_V_ACTIVE + PNL_VPW + PNL_VBP + (unsigned)vfp;
        uint64_t achieved_mhz = (uint64_t)pnl_vtotal() * PNL_FPS * 1000000ull / vt;
        uint64_t want_mhz = pnl_dfps[i] * 1000000ull;
        CHECK((achieved_mhz > want_mhz ? achieved_mhz - want_mhz : want_mhz - achieved_mhz) * 2000 < want_mhz);
    }
    CHECK(listed == 7 && reachable == 6);                // 144 Hz is listed but needs another clock

    // Physical size: a 10.99-inch diagonal (the touch tables say "CSOT10.99" / "TM 10.99"), square pixels.
    unsigned diag_dmm = isqrt((uint64_t)PNL_WIDTH_DMM * PNL_WIDTH_DMM + (uint64_t)PNL_HEIGHT_DMM * PNL_HEIGHT_DMM);
    CHECK(diag_dmm == 2791);
    CHECK(diag_dmm * 100 / 254 == 1098);                  // 10.98 in, truncated: 10.99 rounded
    unsigned ppi_x = pnl_width() * 254 / PNL_WIDTH_DMM, ppi_y = PNL_V_ACTIVE * 254 / PNL_HEIGHT_DMM;
    CHECK(ppi_x == 308 && ppi_y == 309);

    // Identity: both makers are "M82A"; the maker byte is the touch firmware selector.
    CHECK(pnl_variant(PNL_ID_MODEL, PNL_ID_TM) == PNL_TM && pnl_variant(PNL_ID_MODEL, PNL_ID_CSOT) == PNL_CSOT);
    CHECK(pnl_variant(PNL_ID_MODEL, 0x00380200) == PNL_UNKNOWN && pnl_variant(0x4B383141, PNL_ID_TM) == PNL_UNKNOWN);
    CHECK(pnl_maker(PNL_ID_TM) == PNL_MAKER_TM && pnl_maker(PNL_ID_CSOT) == PNL_MAKER_CSOT);
    CHECK((PNL_ID_MODEL >> 24) == 'M' && ((PNL_ID_MODEL >> 16) & 0xff) == '8' && (PNL_ID_MODEL & 0xff) == 'A');

    // Reset: low 10 ms, high 3, low 3, high 15; ends released.
    CHECK(pnl_reset_ms() == 31);
    CHECK(pnl_reset_sequence[0].level == 0 && pnl_reset_sequence[3].level == 1);

    // The panel bias rails are the backlight chip's bias outputs' enables (one board fact in two headers).
    CHECK(PNL_GPIO_ENP == BKL_GPIO_VDDPOS && PNL_GPIO_ENN == BKL_GPIO_VDDNEG);
    CHECK(sizeof(pnl_phy_timings) == 14);

    // DSI link with DSC, per interface: the pixel clock is the compressed line rate, and pixel clock * bpp / lanes and
    // byte clock * 8 both give the tree's lane rate.
    CHECK(pnl_dsc_pixel_clock(PNL_FPS) == 167838720ull);
    CHECK(pnl_dsc_pixel_clock(PNL_FPS) * PNL_BPP / PNL_LANES == PNL_BITCLK_HZ);
    CHECK(pnl_byte_clock(PNL_FPS) == 125879040ull && pnl_byte_clock(PNL_FPS) * 8 == PNL_BITCLK_HZ);
    CHECK(pnl_dsc_pixel_clock(PNL_FPS) < pnl_pixel_clock(PNL_FPS));      // compressed: fewer pixel clocks a line
    // DSC packing: 450-byte chunks, 900 bytes a line, one packet a line, 225 byte-clock cycles on 4 lanes; the same
    // 225 as the DSC active width (300 pixel clocks) at 24 bpp over 4 lanes.
    CHECK(pnl_dsc_chunk_bytes() == 450 && pnl_dsc_line_bytes() == 900 && pnl_dsc_packets_per_line() == 1);
    CHECK(pnl_dsc_line_byte_cycles() == 225);
    CHECK(pnl_dsc_line_byte_cycles() == pnl_dsc_h_active() * PNL_BPP / 8 / PNL_LANES);
    CHECK(pnl_dsc_ratio() == 3 && PNL_H_ACTIVE / pnl_dsc_ratio() == pnl_dsc_h_active());
    // Both halves: the whole panel's compressed payload per frame, 2 interfaces * 900 bytes * 2880 lines.
    CHECK((uint64_t)PNL_DSI_COUNT * pnl_dsc_line_bytes() * PNL_V_ACTIVE == 5184000ull);
    CHECK(PNL_CLOCK_MASTER == 0);

    // Reset pin: TLMM 75 (SOUTH), gpio function; the active and suspend pin states as GPIO_CFG values.
    CHECK(PNL_GPIO_RESET == 75 && pnl_reset_ctl_offset() == 0x54b000u);
    CHECK(pnl_reset_cfg(PNL_RESET_ACTIVE_MA, PNL_TLMM_PULL_NONE) == 0xc0u);     // drive code 3, no pull
    CHECK(pnl_reset_cfg(PNL_RESET_SUSPEND_MA, PNL_TLMM_PULL_DOWN) == 0x01u);    // drive code 0, pull-down
    // It is none of the other panel or backlight lines.
    CHECK(PNL_GPIO_RESET != PNL_GPIO_TE && PNL_GPIO_RESET != PNL_GPIO_ESD && PNL_GPIO_RESET != PNL_GPIO_ESD_SEC &&
          PNL_GPIO_RESET != PNL_GPIO_ENP && PNL_GPIO_RESET != PNL_GPIO_ENN && PNL_GPIO_RESET != BKL_GPIO_ENABLE);

    // Supplies: vddio first, the bias pair last, each at the tree's voltage; 6 ms of settling, then 31 ms of reset.
    CHECK(PNL_SUPPLIES == 5 && pnl_supply_ms() == 6);
    CHECK(pnl_supplies[0].uv == 1800000u && pnl_supplies[1].uv == PNL_DVDD_UV && pnl_supplies[2].uv == PNL_DVDD_UV);
    CHECK(pnl_supplies[3].uv == PNL_BIAS_UV && pnl_supplies[4].uv == PNL_BIAS_UV);
    CHECK(pnl_supply_ms() + pnl_reset_ms() == 37);

    puts("PASS: pipa panel (timing gives the tree's bit clock, DSC tiling and packing, link clocks, dfps porches, size, "
         "identity, reset pin and sequence, supplies)");
    return 0;
}
