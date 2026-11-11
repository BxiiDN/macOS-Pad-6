// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa (Xiaomi Pad 6) DSI panel: the board facts of the Android device tree and the timing arithmetic around them, as
// pure functions. New in macOS-Pad-6; host-tested by PanelBoardTests.c. Nothing here drives MDSS or DSI, and nothing
// here has run on the tablet: macOS on pipa uses the firmware frame buffer (LegacyDisplayProbe.cpp, 1800x2880).
// Mainline Linux has no pipa panel node, so the source is the vendor tree, every value public:
//   VND MiCode/kernel_devicetree pipa-t-oss 623dd5bf821e: qcom/dsi-panel-m82-36-02-0a-video.dtsi and
//       qcom/dsi-panel-m82-42-02-0b-video.dtsi (the two panel makers, identical timing), the &dsi_m82_* blocks of
//       qcom/kona-sde-display.dtsi (dual DSI 0+1, PHY timings, topology), qcom/pipa-sm8250.dtsi (supplies, GPIOs) and
//       sde_dsi in qcom/kona-sde-display.dtsi (TE GPIO). scripts/pipa_hw.py vendor checks every VND value below.
#ifndef PIPA_PANEL_BOARD_H
#define PIPA_PANEL_BOARD_H
#include <stdint.h>

// Link (VND): dual DSI, D-PHY, 4 lanes each, video mode, non-burst with sync events, RGB888, DSC 1.1.
#define PNL_DSI_COUNT 2u
#define PNL_LANES 4u
#define PNL_BPP 24u
#define PNL_FPS 120u
#define PNL_BITCLK_HZ 1007032320u     // qcom,mdss-dsi-panel-clockrate: per lane
#define PNL_DSC_VERSION 0x11u
#define PNL_DSC_SLICE_WIDTH 450u
#define PNL_DSC_SLICE_HEIGHT 20u
#define PNL_DSC_SLICE_PER_PKT 2u
#define PNL_DSC_BPC 8u
#define PNL_DSC_BPP 8u                 // compressed bits per pixel
#define PNL_TOPOLOGY_LM 2u             // qcom,display-topology = <2 2 2>: mixers, DSC encoders, interfaces
#define PNL_TOPOLOGY_DSC 2u
#define PNL_TOPOLOGY_INTF 2u
// Timing per DSI (VND timing@0); the panel is two 900-pixel halves side by side.
#define PNL_H_ACTIVE 900u
#define PNL_V_ACTIVE 2880u
#define PNL_HPW 2u
#define PNL_HBP 46u
#define PNL_HFP 100u
#define PNL_VPW 2u
#define PNL_VBP 214u
#define PNL_VFP 26u
// Physical size in tenths of a millimetre (qcom,mdss-pan-physical-*-dimension).
#define PNL_WIDTH_DMM 1480u
#define PNL_HEIGHT_DMM 2367u
// Identity (VND mi,panel-id): "M82A", then the maker in bits 23:16 (0x36 TM, 0x42 CSOT); the same byte selects the
// touch firmware (novatek,display-maker in pipa-sm8250.dtsi).
#define PNL_ID_MODEL 0x4D383241u
#define PNL_ID_TM 0x00360200u
#define PNL_ID_CSOT 0x00420200u
#define PNL_MAKER_TM 0x36u
#define PNL_MAKER_CSOT 0x42u
// Status check: DCS read of 0x0A (get power mode), one byte, expected 0x9D (VND panel-status-*).
#define PNL_STATUS_DCS 0x0Au
#define PNL_STATUS_VALUE 0x9Du
// Board (VND): ESD error interrupts, tearing effect, supplies.
#define PNL_GPIO_ESD 51
#define PNL_GPIO_ESD_SEC 55
#define PNL_GPIO_TE 66
#define PNL_GPIO_DVDD_BUCK 36          // display_panel_dvdd_buck, 1.3 V
#define PNL_GPIO_DVDD_LDO 13           // display_panel_dvdd_ldo, 1.3 V
#define PNL_GPIO_ENP 130               // display_panel_enp, +5.5 V (= BacklightBoard.h BKL_GPIO_VDDPOS)
#define PNL_GPIO_ENN 131               // display_panel_enn, -5.5 V (= BKL_GPIO_VDDNEG)
#define PNL_DVDD_UV 1300000u
#define PNL_BIAS_UV 5500000u
#define PNL_BIAS_RAMP_US 233u

typedef struct {
    uint8_t level, ms;
} PnlResetStep;

// qcom,mdss-dsi-reset-sequence = <0 10>, <1 3>, <0 3>, <1 15>: level, then hold in ms.
static const PnlResetStep pnl_reset_sequence[] = {{0, 10}, {1, 3}, {0, 3}, {1, 15}};
// qcom,dsi-supported-dfps-list, in the tree's order; switched by stretching the vertical front porch.
static const uint8_t pnl_dfps[] = {120, 144, 90, 60, 50, 48, 30};
// qcom,mdss-dsi-panel-phy-timings of &dsi_m82_* (kona-sde-display.dtsi).
static const uint8_t pnl_phy_timings[14] = {0x00, 0x22, 0x08, 0x09, 0x19, 0x17, 0x09,
                                            0x09, 0x09, 0x02, 0x04, 0x00, 0x1C, 0x0E};

typedef enum { PNL_UNKNOWN = 0, PNL_TM, PNL_CSOT } PnlVariant;

static inline PnlVariant pnl_variant(uint32_t id0, uint32_t id1) {
    if (id0 != PNL_ID_MODEL)
        return PNL_UNKNOWN;
    return id1 == PNL_ID_TM ? PNL_TM : id1 == PNL_ID_CSOT ? PNL_CSOT : PNL_UNKNOWN;
}

static inline unsigned pnl_maker(uint32_t id1) { return (id1 >> 16) & 0xffu; }

static inline unsigned pnl_width(void) { return PNL_H_ACTIVE * PNL_DSI_COUNT; }      // 1800
static inline unsigned pnl_htotal(void) { return PNL_H_ACTIVE + PNL_HPW + PNL_HBP + PNL_HFP; }
static inline unsigned pnl_vtotal(void) { return PNL_V_ACTIVE + PNL_VPW + PNL_VBP + PNL_VFP; }

// Pixel clock of one DSI interface, uncompressed timing.
static inline uint64_t pnl_pixel_clock(unsigned fps) { return (uint64_t)pnl_htotal() * pnl_vtotal() * fps; }

// With DSC the link carries active pixels at the compressed rate: an active line is H_ACTIVE * DSC_BPP / BPP pixel
// times of the uncompressed format (900 * 8 / 24 = 300), the porches unchanged. Returns 0 if that is not exact.
static inline unsigned pnl_dsc_h_active(void) {
    return (PNL_H_ACTIVE * PNL_DSC_BPP) % PNL_BPP ? 0 : PNL_H_ACTIVE * PNL_DSC_BPP / PNL_BPP;
}

// The lane bit rate the timing implies: DSC line time * vtotal * fps * bpp / lanes. For 120 Hz this is the tree's
// qcom,mdss-dsi-panel-clockrate exactly (PanelBoardTests.c checks it), which ties the timing values to each other.
static inline uint64_t pnl_bitclk(unsigned fps) {
    uint64_t line = (uint64_t)pnl_dsc_h_active() + PNL_HPW + PNL_HBP + PNL_HFP;
    return line * pnl_vtotal() * fps * PNL_BPP / PNL_LANES;
}

// DSC slices: per line per interface, and per column. 0 when they do not tile the frame.
static inline unsigned pnl_slices_per_line(void) {
    return PNL_H_ACTIVE % PNL_DSC_SLICE_WIDTH ? 0 : PNL_H_ACTIVE / PNL_DSC_SLICE_WIDTH;
}
static inline unsigned pnl_slice_rows(void) {
    return PNL_V_ACTIVE % PNL_DSC_SLICE_HEIGHT ? 0 : PNL_V_ACTIVE / PNL_DSC_SLICE_HEIGHT;
}

// Vertical front porch for a refresh rate under porch-mode dynamic fps (dfps_immediate_porch_mode_vfp): the link
// clock and the horizontal timing stay, vtotal grows to vtotal * PNL_FPS / fps (rounded). Rates above the base cannot
// be reached this way (vtotal would have to shrink below the active area plus porches): returns -1.
static inline int pnl_vfp_for_fps(unsigned fps) {
    if (fps == 0 || fps > PNL_FPS)
        return -1;
    unsigned vt = (pnl_vtotal() * PNL_FPS + fps / 2) / fps;
    return (int)(vt - PNL_V_ACTIVE - PNL_VPW - PNL_VBP);
}

// Total reset sequence time in ms.
static inline unsigned pnl_reset_ms(void) {
    unsigned ms = 0;
    for (unsigned i = 0; i < sizeof(pnl_reset_sequence) / sizeof(pnl_reset_sequence[0]); i++)
        ms += pnl_reset_sequence[i].ms;
    return ms;
}

// Frame buffer row pitch for a 32-bit format over the whole panel.
static inline unsigned pnl_fb_stride(unsigned bytes_per_pixel) { return pnl_width() * bytes_per_pixel; }

#endif
