// SPDX-License-Identifier: BSD-2-Clause-Patent
// The pipa GPU and GMU nodes of mainline Linux's device tree through the Adreno 650 fork's device-tree parser
// (NativeAdrenoBoard, xVanTuring/Adreno650): the windows and streams it extracts are the ones package/GpuPowerBoard.h
// and GpuProbe.cpp use. The property bytes come from pipa_gpu_props.h, which scripts/test_adreno650.py writes from
// the DTB. A host test of parsing; no device access.
#include "XnuMemoryFixture.h"
#include "NativeAdrenoBoard.h"
#include <cstdio>
#include <cstdlib>
extern "C" {
#include "GpuPowerBoard.h"
}
#include "pipa_gpu_props.h"
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(1);}}while(0)

int main() {
    NativeAdrenoWindow w[NativeAdrenoMaxWindows];
    size_t n = 0;
    uint16_t sids[8];

    // gpu@3d00000: one window, the whole register space.
    CHECK(NativeAdrenoBoard::parseReg(pipa_gpu_reg, sizeof(pipa_gpu_reg), pipa_address_cells, pipa_size_cells, w,
                                      NativeAdrenoMaxWindows, &n) == kIOReturnSuccess);
    CHECK(n == 1 && w[0].base == GPB_GPU_BASE && w[0].bytes == GPB_GPU_WINDOW);

    // gmu@3d6a000: gmu, rscc, gmu_pdc, gmu_pdc_seq; the first two are the board's.
    CHECK(NativeAdrenoBoard::parseReg(pipa_gmu_reg, sizeof(pipa_gmu_reg), pipa_address_cells, pipa_size_cells, w,
                                      NativeAdrenoMaxWindows, &n) == kIOReturnSuccess);
    CHECK(n == 4);
    CHECK(w[0].base == GPB_GMU_BASE && w[0].bytes == GPB_GMU_SIZE);
    CHECK(w[1].base == GPB_RSCC_BASE && w[1].bytes == GPB_RSCC_SIZE);

    // A window table too small is refused, not truncated.
    CHECK(NativeAdrenoBoard::parseReg(pipa_gmu_reg, sizeof(pipa_gmu_reg), pipa_address_cells, pipa_size_cells, w, 2,
                                      &n) != kIOReturnSuccess);

    // iommus: <&adreno_smmu SID mask>, #iommu-cells specifier cells after the phandle. The parser keeps the SID
    // (GpuProbe.cpp expands the mask: kGpuSids 0, 1, 0x400, 0x401 and kGmuSids 5, 0x405 start with these).
    CHECK(NativeAdrenoBoard::parseIommus(pipa_gpu_iommus, sizeof(pipa_gpu_iommus), pipa_iommu_cells, sids, 8, &n) ==
          kIOReturnSuccess);
    CHECK(n == 1 && sids[0] == 0);
    CHECK(NativeAdrenoBoard::parseIommus(pipa_gmu_iommus, sizeof(pipa_gmu_iommus), pipa_iommu_cells, sids, 8, &n) ==
          kIOReturnSuccess);
    CHECK(n == 1 && sids[0] == 5);

    std::printf("PASS: pipa gpu and gmu nodes (1 + 4 windows, 2 stream IDs) through NativeAdrenoBoard = GpuPowerBoard.h\n");
    return 0;
}
