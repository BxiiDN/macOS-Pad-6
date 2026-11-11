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

    puts("PASS: pipa panel (timing gives the tree's bit clock, DSC tiling, dfps porches, size, identity, reset)");
    return 0;
}
