// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa's display link as a driver would set it up, from PanelBoard.h: the two DSI hosts (DSI0 clock master, DSI1 its
// slave, each a 900-pixel half), the DSC 1.1 configuration of each encoder with its rate-control parameters, the panel
// variant (TM or CSOT) from the identity the boot hands over, and a read-only check of the reset line's pin state.
// Pure functions; host-tested by PanelLinkTests.c. Nothing here touches MDSS, DSI, the PHY, TLMM or the panel: reading
// MDSS from XNU without its GDSC and clocks voted ended in an SError panic (MdssProbe.cpp), and no driver here votes them.
// New in macOS-Pad-6.
//
// DSC: the rate-control derivation is Linux's drm_dsc_compute_rc_parameters() (drivers/gpu/drm/display/drm_dsc_helper.c)
// as msm's dsi_populate_dsc_params() calls it (convert_rgb, the DSC 1.1 pre-SCR table, line_buf_depth = bpc + 1), in the
// same integer arithmetic; the table row for 8 bpp / 8 bpc and the constants are checked against that source by
// scripts/pipa_hw.py drivers. Whether pipa's panels were tuned with exactly these values is not known: the vendor tree
// gives only the slice geometry and the bit depths.
#ifndef PIPA_PANEL_LINK_H
#define PIPA_PANEL_LINK_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "PanelBoard.h"

// --- DSC 1.1 (include/drm/display/drm_dsc.h constants) ---------------------------------------------------------------
#define DSC_NUM_BUF_RANGES 15
#define DSC_RC_PIXELS_PER_GROUP 3
#define DSC_SCALE_DECREMENT_INTERVAL_MAX 4095
#define DSC_RC_MODEL_SIZE_CONST 8192
#define DSC_RC_EDGE_FACTOR_CONST 6
#define DSC_RC_TGT_OFFSET_HI_CONST 3
#define DSC_RC_TGT_OFFSET_LO_CONST 3
#define DSC_MUX_WORD_SIZE_8_10_BPC 48
#define DSC_RANGE_BPG_OFFSET_MASK 0x3f

typedef struct {
    uint8_t min_qp, max_qp;
    int8_t bpg_offset;
} DscRange;

// drm_dsc_helper.c rc_parameters_pre_scr[], the { DSC_BPP(8), 8 } row.
typedef struct {
    uint16_t initial_xmit_delay;
    uint8_t first_line_bpg_offset;
    uint16_t initial_offset;
    uint8_t flatness_min_qp, flatness_max_qp, rc_quant_incr_limit0, rc_quant_incr_limit1;
    DscRange range[DSC_NUM_BUF_RANGES];
} DscRcParams;

static const DscRcParams dsc_pre_scr_8bpp_8bpc = {
    512, 12, 6144, 3, 12, 11, 11,
    {{0, 4, 2}, {0, 4, 0}, {1, 5, 0}, {1, 6, -2}, {3, 7, -4}, {3, 7, -6}, {3, 7, -8}, {3, 8, -8},
     {3, 9, -8}, {3, 10, -10}, {5, 11, -10}, {5, 12, -12}, {5, 13, -12}, {7, 13, -12}, {13, 15, -12}},
};

// drm_dsc_rc_buf_thresh[] (DSC 1.11), stored >> 6.
static const uint16_t dsc_rc_buf_thresh[DSC_NUM_BUF_RANGES - 1] = {
    896, 1792, 2688, 3584, 4480, 5376, 6272, 6720, 7168, 7616, 7744, 7872, 8000, 8064,
};

typedef struct {
    // inputs (the panel's)
    uint16_t pic_width, pic_height, slice_width, slice_height;
    uint16_t bits_per_pixel;          // in 1/16 bit
    uint8_t bits_per_component, convert_rgb, line_buf_depth;
    // constants and table
    uint16_t rc_model_size;
    uint8_t rc_edge_factor, rc_tgt_offset_high, rc_tgt_offset_low, mux_word_size;
    uint8_t rc_buf_thresh[DSC_NUM_BUF_RANGES - 1];
    uint16_t initial_xmit_delay, initial_offset;
    uint8_t first_line_bpg_offset, flatness_min_qp, flatness_max_qp, rc_quant_incr_limit0, rc_quant_incr_limit1;
    uint8_t range_min_qp[DSC_NUM_BUF_RANGES], range_max_qp[DSC_NUM_BUF_RANGES];
    uint8_t range_bpg_offset[DSC_NUM_BUF_RANGES];   // 6-bit two's complement, as the PPS carries it
    // derived (drm_dsc_compute_rc_parameters)
    uint8_t initial_scale_value;
    uint16_t slice_chunk_size, scale_decrement_interval, scale_increment_interval, final_offset;
    uint16_t nfl_bpg_offset, slice_bpg_offset, initial_dec_delay, rc_bits;
    uint32_t flatness_det_thresh;
} PnlDsc;

static inline unsigned long pnl_div_round_up(unsigned long n, unsigned long d) { return (n + d - 1) / d; }

// One encoder's configuration for one 900-pixel half. 0 on success, -1 when the parameters cannot be derived
// (drm_dsc_compute_rc_parameters' -ERANGE, an unsupported depth, or a fractional bpp, which msm's DSI refuses).
static inline int pnl_dsc_config(PnlDsc *d) {
    memset(d, 0, sizeof(*d));
    d->pic_width = PNL_H_ACTIVE;
    d->pic_height = PNL_V_ACTIVE;
    d->slice_width = PNL_DSC_SLICE_WIDTH;
    d->slice_height = PNL_DSC_SLICE_HEIGHT;
    d->bits_per_pixel = PNL_DSC_BPP << 4;
    d->bits_per_component = PNL_DSC_BPC;
    if ((d->bits_per_pixel & 0xf) || d->bits_per_component != 8 || d->bits_per_pixel != (8u << 4))
        return -1;                                     // only the row this board needs is carried
    d->convert_rgb = 1;                                // dsi_populate_dsc_params
    // drm_dsc_set_const_params
    d->rc_model_size = DSC_RC_MODEL_SIZE_CONST;
    d->rc_edge_factor = DSC_RC_EDGE_FACTOR_CONST;
    d->rc_tgt_offset_high = DSC_RC_TGT_OFFSET_HI_CONST;
    d->rc_tgt_offset_low = DSC_RC_TGT_OFFSET_LO_CONST;
    d->mux_word_size = DSC_MUX_WORD_SIZE_8_10_BPC;
    // drm_dsc_set_rc_buf_thresh (not the 6 bpp exception)
    for (unsigned i = 0; i < DSC_NUM_BUF_RANGES - 1; i++)
        d->rc_buf_thresh[i] = (uint8_t)(dsc_rc_buf_thresh[i] >> 6);
    // drm_dsc_setup_rc_params(DRM_DSC_1_1_PRE_SCR)
    const DscRcParams *p = &dsc_pre_scr_8bpp_8bpc;
    d->first_line_bpg_offset = p->first_line_bpg_offset;
    d->initial_xmit_delay = p->initial_xmit_delay;
    d->initial_offset = p->initial_offset;
    d->flatness_min_qp = p->flatness_min_qp;
    d->flatness_max_qp = p->flatness_max_qp;
    d->rc_quant_incr_limit0 = p->rc_quant_incr_limit0;
    d->rc_quant_incr_limit1 = p->rc_quant_incr_limit1;
    for (unsigned i = 0; i < DSC_NUM_BUF_RANGES; i++) {
        d->range_min_qp[i] = p->range[i].min_qp;
        d->range_max_qp[i] = p->range[i].max_qp;
        d->range_bpg_offset[i] = (uint8_t)(p->range[i].bpg_offset & DSC_RANGE_BPG_OFFSET_MASK);
    }
    // drm_dsc_initial_scale_value, line_buf_depth
    d->initial_scale_value = (uint8_t)(8 * d->rc_model_size / (d->rc_model_size - d->initial_offset));
    d->line_buf_depth = d->bits_per_component + 1;
    d->flatness_det_thresh = 2u << (d->bits_per_component - 8);

    // drm_dsc_compute_rc_parameters (4:4:4 path)
    unsigned long groups_per_line = pnl_div_round_up(d->slice_width, DSC_RC_PIXELS_PER_GROUP);
    d->slice_chunk_size = (uint16_t)pnl_div_round_up((unsigned long)d->slice_width * d->bits_per_pixel, 8 * 16);
    unsigned long num_extra_mux_bits = 3 * (d->mux_word_size + (4 * d->bits_per_component + 4) - 2);   // convert_rgb
    unsigned long slice_bits = 8ul * d->slice_chunk_size * d->slice_height;
    while (num_extra_mux_bits > 0 && (slice_bits - num_extra_mux_bits) % d->mux_word_size)
        num_extra_mux_bits--;
    if (groups_per_line < (unsigned long)d->initial_scale_value - 8)
        d->initial_scale_value = (uint8_t)(groups_per_line + 8);
    d->scale_decrement_interval = d->initial_scale_value > 8
        ? (uint16_t)(groups_per_line / (d->initial_scale_value - 8)) : DSC_SCALE_DECREMENT_INTERVAL_MAX;
    unsigned long final_offset = d->rc_model_size - ((unsigned long)d->initial_xmit_delay * d->bits_per_pixel + 8) / 16 +
                                 num_extra_mux_bits;
    if (final_offset >= d->rc_model_size)
        return -1;
    d->final_offset = (uint16_t)final_offset;
    unsigned long final_scale = ((unsigned long)d->rc_model_size * 8) / (d->rc_model_size - d->final_offset);
    d->nfl_bpg_offset = d->slice_height > 1
        ? (uint16_t)pnl_div_round_up((unsigned long)d->first_line_bpg_offset << 11, d->slice_height - 1u) : 0;
    unsigned long groups_total = groups_per_line * d->slice_height;
    d->slice_bpg_offset = (uint16_t)pnl_div_round_up(
        ((unsigned long)d->rc_model_size - d->initial_offset + num_extra_mux_bits) << 11, groups_total);
    d->scale_increment_interval = final_scale > 9
        ? (uint16_t)(((unsigned long)d->final_offset * (1ul << 11)) /
                     (((unsigned long)d->nfl_bpg_offset + d->slice_bpg_offset) * (final_scale - 9)))
        : 0;
    unsigned long rbs_min = d->rc_model_size - d->initial_offset +
                            pnl_div_round_up((unsigned long)d->initial_xmit_delay * d->bits_per_pixel, 16) +
                            groups_per_line * d->first_line_bpg_offset;
    unsigned long hrd_delay = pnl_div_round_up(rbs_min * 16, d->bits_per_pixel);
    d->rc_bits = (uint16_t)((hrd_delay * d->bits_per_pixel) / 16);
    d->initial_dec_delay = (uint16_t)(hrd_delay - d->initial_xmit_delay);
    return 0;
}

// --- the two DSI hosts ------------------------------------------------------------------------------------------------
typedef struct {
    unsigned index;                  // DSI0, DSI1
    unsigned clock_source;           // the DSI whose PLL drives it (PNL_CLOCK_MASTER for both)
    unsigned first_column;           // where its half starts in the 1800-pixel frame buffer
    unsigned lanes;
    uint64_t lane_hz, byte_hz, pixel_hz;
    unsigned h_active_pclk, h_total_pclk, v_total;     // in DSC pixel clocks per line, lines per frame
    unsigned bytes_per_line, packets_per_line, slices_per_line;
} PnlDsiHost;

enum {
    PNL_LINK_OK = 0,
    PNL_LINK_DSC = 1u << 0,          // DSC parameters could not be derived
    PNL_LINK_TILING = 1u << 1,       // slices do not tile a half
    PNL_LINK_RATE = 1u << 2,         // the lane rate the timing implies is not the tree's clockrate, or over 2.5 Gb/s
    PNL_LINK_CHUNK = 1u << 3,        // the DSC chunk is not what the link packs per slice
    PNL_LINK_HALVES = 1u << 4,       // the halves do not cover the frame buffer exactly
};

// Both hosts at a refresh rate of the porch-mode list (PanelBoard.h pnl_vfp_for_fps), and the problems found.
static inline uint32_t pnl_dsi_hosts(unsigned fps, PnlDsiHost host[PNL_DSI_COUNT]) {
    uint32_t problems = 0;
    PnlDsc dsc;
    if (pnl_dsc_config(&dsc)) problems |= PNL_LINK_DSC;
    const int vfp = pnl_vfp_for_fps(fps);
    const unsigned v_total = vfp < 0 ? 0 : PNL_V_ACTIVE + PNL_VPW + PNL_VBP + (unsigned)vfp;
    for (unsigned i = 0; i < PNL_DSI_COUNT; i++) {
        PnlDsiHost *h = &host[i];
        h->index = i;
        h->clock_source = PNL_CLOCK_MASTER;
        h->first_column = i * PNL_H_ACTIVE;
        h->lanes = PNL_LANES;
        h->h_active_pclk = pnl_dsc_h_active();
        h->h_total_pclk = h->h_active_pclk + PNL_HPW + PNL_HBP + PNL_HFP;
        h->v_total = v_total;
        // porch-mode dfps keeps the link clock: the base rate's
        h->pixel_hz = pnl_dsc_pixel_clock(PNL_FPS);
        h->lane_hz = h->pixel_hz * PNL_BPP / PNL_LANES;
        h->byte_hz = h->lane_hz / 8;
        h->bytes_per_line = pnl_dsc_line_bytes();
        h->packets_per_line = pnl_dsc_packets_per_line();
        h->slices_per_line = pnl_slices_per_line();
    }
    if (!pnl_slices_per_line() || !pnl_slice_rows() || !pnl_dsc_packets_per_line()) problems |= PNL_LINK_TILING;
    if (host[0].lane_hz != PNL_BITCLK_HZ || host[0].lane_hz > 2500000000ull || !v_total) problems |= PNL_LINK_RATE;
    if (!(problems & PNL_LINK_DSC) && dsc.slice_chunk_size != pnl_dsc_chunk_bytes()) problems |= PNL_LINK_CHUNK;
    if (host[PNL_DSI_COUNT - 1].first_column + PNL_H_ACTIVE != pnl_width()) problems |= PNL_LINK_HALVES;
    return problems;
}

// --- panel variant --------------------------------------------------------------------------------------------------
// Which of the two panels a tablet has is not readable from any public table: Android's bootloader detects it and names
// the panel node to the kernel (msm_drm.dsi_display0=<node>:...); the panel node then gives mi,panel-id. A driver here
// gets the node name or the panel name from whatever hands over the boot (or a boot argument), and the maker byte if it
// has one; both must agree, and anything else is "unknown", for which no panel sequence and no touch firmware is chosen.
static const struct {
    PnlVariant variant;
    const char *node, *name;
} pnl_variants[] = {
    {PNL_TM, "dsi_m82_36_02_0a_dual_dphy_video", "xiaomi m82 36 02 0a video mode dual dsi dphy panel"},
    {PNL_CSOT, "dsi_m82_42_02_0b_dual_dphy_video", "xiaomi m82 42 02 0b video mode dual dsi dphy panel"},
};

// The variant a node or panel name names (the bootloader's form "<node>:..." is accepted), PNL_UNKNOWN otherwise.
static inline PnlVariant pnl_variant_from_name(const char *s) {
    if (!s) return PNL_UNKNOWN;
    for (size_t i = 0; i < sizeof(pnl_variants) / sizeof(pnl_variants[0]); i++) {
        const size_t n = strlen(pnl_variants[i].node);
        if (!strncmp(s, pnl_variants[i].node, n) && (s[n] == 0 || s[n] == ':')) return pnl_variants[i].variant;
        if (!strcmp(s, pnl_variants[i].name)) return pnl_variants[i].variant;
    }
    return PNL_UNKNOWN;
}

// The variant from a name and/or the maker byte (have_maker 0: none). Unknown when neither identifies one or they disagree.
static inline PnlVariant pnl_variant_select(const char *name, int have_maker, unsigned maker) {
    const PnlVariant by_name = pnl_variant_from_name(name);
    const PnlVariant by_maker = !have_maker ? PNL_UNKNOWN : maker == PNL_MAKER_TM ? PNL_TM : maker == PNL_MAKER_CSOT ? PNL_CSOT
                                                                                                        : PNL_UNKNOWN;
    if (have_maker && by_maker == PNL_UNKNOWN) return PNL_UNKNOWN;     // a maker this tree does not know
    if (name && by_name == PNL_UNKNOWN) return PNL_UNKNOWN;           // a name this tree does not know
    if (by_name != PNL_UNKNOWN && by_maker != PNL_UNKNOWN && by_name != by_maker) return PNL_UNKNOWN;
    return by_name != PNL_UNKNOWN ? by_name : by_maker;
}

// --- reset line, read only ----------------------------------------------------------------------------------------------
enum {
    PNL_RESET_OK = 0,
    PNL_RESET_FUNC = 1u << 0,        // not the gpio function
    PNL_RESET_NOT_OUTPUT = 1u << 1,  // output enable (bit 9) clear: nothing drives it
    PNL_RESET_LOW = 1u << 2,         // driven low: the panel (and the TDDI touch half) is held in reset
    PNL_RESET_DRIVE = 1u << 3,       // not sde_dsi_active's 8 mA, no pull
};

// What TLMM 75's GPIO_CFG and GPIO_IN_OUT say about a panel the firmware left running: the active pin state, an output,
// released (high) after the reset sequence. The caller reads the two registers; nothing is written.
static inline uint32_t pnl_reset_check(uint32_t ctl, uint32_t io) {
    uint32_t p = 0;
    if (((ctl >> 2) & 0xf) != 0) p |= PNL_RESET_FUNC;
    if (!(ctl & (1u << 9))) p |= PNL_RESET_NOT_OUTPUT;
    if (!(io & (1u << 1))) p |= PNL_RESET_LOW;
    if ((ctl & 0x1c3u) != pnl_reset_cfg(PNL_RESET_ACTIVE_MA, PNL_TLMM_PULL_NONE)) p |= PNL_RESET_DRIVE;
    return p;
}

#endif
