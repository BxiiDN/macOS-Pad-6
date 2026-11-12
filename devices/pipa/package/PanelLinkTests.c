// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for PanelLink.h: the DSC 1.1 configuration of each encoder (values worked out by hand below from the DSC
// formulas, independently of the code), the two DSI hosts at every porch-mode rate, the panel variant selection (and
// the touch firmware it leads to, none for an unknown panel), and the read-only reset-line check. Arithmetic on the
// device tree's numbers, not the hardware.
// cc -std=gnu11 -Wall -Wextra -Werror package/PanelLinkTests.c && ./a.out
#include "PanelLink.h"
#include "TouchVendor.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

int main(void) {
    // DSC, by hand: 450-pixel slices -> 150 groups a line; chunk 450 * 128 / 128 = 450 bytes; extra mux bits
    // 3 * (48 + 36 - 2) = 246, lowered to 240 so that 72000 - x divides by 48; initial scale 8 * 8192 / 2048 = 32;
    // decrement interval 150 / 24 = 6; final offset 8192 - (512 * 128 + 8) / 16 + 240 = 4336; final scale
    // 65536 / 3856 = 16; nfl ceil(12 * 2048 / 19) = 1294; slice ceil(2288 * 2048 / 3000) = 1562; increment
    // 4336 * 2048 / (2856 * 7) = 444; rbs 2048 + 4096 + 1800 = 7944, hrd 993, rc_bits 7944, dec delay 481.
    PnlDsc d;
    CHECK(pnl_dsc_config(&d) == 0);
    CHECK(d.pic_width == 900 && d.pic_height == 2880 && d.slice_width == 450 && d.slice_height == 20);
    CHECK(d.bits_per_pixel == 128 && d.bits_per_component == 8 && d.convert_rgb == 1 && d.line_buf_depth == 9);
    CHECK(d.slice_chunk_size == 450 && d.slice_chunk_size == pnl_dsc_chunk_bytes());
    CHECK(d.initial_xmit_delay == 512 && d.initial_offset == 6144 && d.first_line_bpg_offset == 12);
    CHECK(d.initial_scale_value == 32 && d.scale_decrement_interval == 6);
    CHECK(d.final_offset == 4336);
    CHECK(d.nfl_bpg_offset == 1294 && d.slice_bpg_offset == 1562);
    CHECK(d.scale_increment_interval == 444);
    CHECK(d.rc_bits == 7944 && d.initial_dec_delay == 481);
    CHECK(d.flatness_det_thresh == 2 && d.flatness_min_qp == 3 && d.flatness_max_qp == 12);
    CHECK(d.rc_model_size == 8192 && d.mux_word_size == 48 && d.rc_edge_factor == 6);
    CHECK(d.rc_buf_thresh[0] == 14 && d.rc_buf_thresh[13] == 126);              // 896 >> 6, 8064 >> 6
    CHECK(d.range_bpg_offset[0] == 2 && d.range_bpg_offset[3] == 0x3e && d.range_bpg_offset[14] == 0x34);   // -2, -12
    CHECK(d.range_min_qp[14] == 13 && d.range_max_qp[14] == 15);
    // The decoder's delay covers the encoder's: initial_xmit_delay + initial_dec_delay = hrd_delay.
    CHECK(d.initial_xmit_delay + d.initial_dec_delay == 993);

    // The two DSI hosts, at the base rate and each rate porch mode reaches; 144 Hz cannot be reached this way.
    PnlDsiHost h[PNL_DSI_COUNT];
    CHECK(pnl_dsi_hosts(PNL_FPS, h) == PNL_LINK_OK);
    CHECK(h[0].index == 0 && h[1].index == 1 && h[0].clock_source == 0 && h[1].clock_source == 0);
    CHECK(h[0].first_column == 0 && h[1].first_column == 900);
    CHECK(h[0].lane_hz == PNL_BITCLK_HZ && h[0].byte_hz == 125879040ull && h[0].pixel_hz == 167838720ull);
    CHECK(h[0].h_active_pclk == 300 && h[0].h_total_pclk == 448 && h[0].v_total == 3122);
    CHECK(h[1].bytes_per_line == 900 && h[1].packets_per_line == 1 && h[1].slices_per_line == 2);
    for (unsigned i = 0; i < sizeof(pnl_dfps); i++) {
        const uint32_t p = pnl_dsi_hosts(pnl_dfps[i], h);
        if (pnl_dfps[i] > PNL_FPS)
            CHECK(p == PNL_LINK_RATE);
        else
            CHECK(p == PNL_LINK_OK && h[0].lane_hz == PNL_BITCLK_HZ && h[0].v_total >= 3122);
    }
    CHECK(pnl_dsi_hosts(60, h) == PNL_LINK_OK && h[0].v_total == 2880 + 2 + 214 + 3148);

    // Panel variants: by node (as the bootloader names it, with or without its ":..." tail), by panel name, by maker.
    CHECK(pnl_variant_from_name("dsi_m82_36_02_0a_dual_dphy_video") == PNL_TM);
    CHECK(pnl_variant_from_name("dsi_m82_42_02_0b_dual_dphy_video:config0") == PNL_CSOT);
    CHECK(pnl_variant_from_name("xiaomi m82 36 02 0a video mode dual dsi dphy panel") == PNL_TM);
    CHECK(pnl_variant_from_name("dsi_m82_42_02_0b_dual_dphy_videoX") == PNL_UNKNOWN);
    CHECK(pnl_variant_from_name("dsi_k81_42_02_0a_dual_cphy_video") == PNL_UNKNOWN);   // pipa-sm8250's default panel, not pipa's
    CHECK(pnl_variant_from_name(NULL) == PNL_UNKNOWN);
    CHECK(pnl_variant_select("dsi_m82_36_02_0a_dual_dphy_video", 0, 0) == PNL_TM);
    CHECK(pnl_variant_select(NULL, 1, PNL_MAKER_CSOT) == PNL_CSOT);
    CHECK(pnl_variant_select("dsi_m82_36_02_0a_dual_dphy_video", 1, PNL_MAKER_TM) == PNL_TM);
    CHECK(pnl_variant_select("dsi_m82_36_02_0a_dual_dphy_video", 1, PNL_MAKER_CSOT) == PNL_UNKNOWN);   // disagree
    CHECK(pnl_variant_select(NULL, 1, 0x38) == PNL_UNKNOWN);                                         // unknown maker
    CHECK(pnl_variant_select("some panel", 1, PNL_MAKER_TM) == PNL_UNKNOWN);                         // unknown name
    CHECK(pnl_variant_select(NULL, 0, 0) == PNL_UNKNOWN);
    // The node table names the same panels as PanelBoard.h's identities.
    CHECK(pnl_variants[0].variant == pnl_variant(PNL_ID_MODEL, PNL_ID_TM));
    CHECK(pnl_variants[1].variant == pnl_variant(PNL_ID_MODEL, PNL_ID_CSOT));

    // Touch firmware follows the variant; an unknown panel gets none.
    CHECK(tv_config_for_variant(PNL_TM) && tv_config_for_variant(PNL_TM)->maker == PNL_MAKER_TM);
    CHECK(tv_config_for_variant(PNL_CSOT) && tv_config_for_variant(PNL_CSOT)->maker == PNL_MAKER_CSOT);
    CHECK(tv_config_for_variant(PNL_UNKNOWN) == NULL);
    CHECK(tv_config_for_variant(pnl_variant_select(NULL, 0, 0)) == NULL);
    CHECK(tv_config_for_variant(pnl_variant_select("dsi_m82_42_02_0b_dual_dphy_video", 1, PNL_MAKER_TM)) == NULL);
    CHECK(tv_config_for_variant(PNL_TM) == tv_config_for_panel(PNL_ID_MODEL, PNL_ID_TM));
    CHECK(tv_config_for_variant(PNL_CSOT) == tv_config_for_panel(PNL_ID_MODEL, PNL_ID_CSOT));

    // Reset line TLMM 75, read only: as the firmware should leave a running panel (gpio, output, 8 mA, no pull, high).
    const uint32_t running = pnl_reset_cfg(PNL_RESET_ACTIVE_MA, PNL_TLMM_PULL_NONE) | (1u << 9);
    CHECK(pnl_reset_check(running, 1u << 1) == PNL_RESET_OK);
    CHECK(pnl_reset_check(running, 0) == PNL_RESET_LOW);                                 // panel held in reset
    CHECK(pnl_reset_check(running & ~(1u << 9), 1u << 1) == PNL_RESET_NOT_OUTPUT);
    CHECK(pnl_reset_check(running | (1u << 2), 1u << 1) == PNL_RESET_FUNC);
    CHECK(pnl_reset_check(pnl_reset_cfg(PNL_RESET_SUSPEND_MA, PNL_TLMM_PULL_DOWN) | (1u << 9), 1u << 1) == PNL_RESET_DRIVE);
    CHECK(pnl_reset_check(0, 0) == (PNL_RESET_NOT_OUTPUT | PNL_RESET_LOW | PNL_RESET_DRIVE));

    puts("PASS: pipa panel link (DSC 1.1 rate control, both DSI hosts at every porch rate, TM/CSOT selection and its touch "
         "firmware, reset-line check)");
    return 0;
}
