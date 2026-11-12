// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for PowerSupplyBoard.h against NativeBatteryBoard.h: the PPIDs NativeBattery.cpp reads are the vendor
// tree's peripherals on USID 2, the pack's capacity is the design capacity it reports, the charger and gauge limits
// are consistent with each other and with the pack, the JEITA tables cover the charging range without gaps.
// Arithmetic on the device tree's numbers, not the PMIC.
// cc -std=gnu11 -Wall -Wextra -Werror package/PowerSupplyBoardTests.c && ./a.out
#include "PowerSupplyBoard.h"
#include "NativeBatteryBoard.h"
#include "GeniI2cBoard.h"
#include "TouchBoard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

static void table_ok(const PsRange *r, size_t n) {
    CHECK(r[0].low == PS_JEITA_TOO_COLD_DECIC);
    for (size_t i = 0; i < n; i++) {
        CHECK(r[i].low <= r[i].high && r[i].value > 0);
        if (i) CHECK(r[i].low <= r[i - 1].high + 1);      // no gap between neighbours
    }
    CHECK(r[n - 1].high >= PS_JEITA_TOO_HOT_DECIC);         // up to the too-hot cut-off and beyond
}

int main(void) {
    // The registers NativeBattery.cpp reads are the vendor tree's PM8150B peripherals.
    CHECK(ps_ppid(PS_PMIC_USID, PS_FG_SOC) == BAT_PPID_FG_SOC);
    CHECK(ps_ppid(PS_PMIC_USID, PS_FG_INFO) == BAT_PPID_FG_INFO);
    CHECK(ps_ppid(PS_PMIC_USID, PS_FG_RRADC) == BAT_PPID_FG_RRADC);
    CHECK(ps_ppid(PS_PMIC_USID, PS_FG_MEMIF) == BAT_PPID_FG_MEMIF);
    CHECK(ps_ppid(PS_PMIC_USID, PS_SMB_CHGR) == BAT_PPID_SMB_CHGR);
    CHECK(ps_ppid(PS_PMIC_USID, PS_SMB_DCDC) == BAT_PPID_SMB_DCDC);
    CHECK(ps_ppid(PS_PMIC_USID, PS_SMB_BATIF) == BAT_PPID_SMB_BATIF);
    CHECK(ps_ppid(PS_PMIC_USID, PS_SMB_USB) == BAT_PPID_SMB_USBIN);
    CHECK(ps_ppid(PS_PMIC_USID, PS_SMB_MISC) == BAT_PPID_SMB_MISC);
    // Peripherals do not overlap.
    const uint32_t p[] = {PS_SMB_CHGR, PS_SMB_DCDC, PS_SMB_BATIF, PS_SMB_USB, PS_SMB_DC, PS_SMB_TYPEC, PS_SMB_MISC,
                          PS_FG_SOC, PS_FG_INFO, PS_FG_RRADC, PS_FG_MEMIF};
    for (size_t i = 1; i < sizeof(p) / sizeof(p[0]); i++)
        CHECK(p[i] >= p[i - 1] + PS_PERIPH_SIZE);

    // The pack: the design capacity NativeBattery reports, the charger's ceiling = the pack's maximum voltage.
    CHECK(PS_BATT_MAH == BAT_DESIGN_MAH);
    CHECK(strcmp(PS_BATT_TYPE, "M82_sunwoda_8840mah") == 0);
    CHECK(PS_FV_MAX_UV == PS_BATT_MAX_UV && PS_NON_FFC_FV_MAX_UV < PS_FV_MAX_UV);
    CHECK(PS_FCC_MAX_UA == PS_BATT_FASTCHG_MA * 1000u);
    CHECK(PS_FCC_MAX_UA * 10u / (PS_BATT_MAH * 1000u) == 6u);      // about 0.67 C: fast charge through the pump

    // JEITA: both tables span too-cold .. too-hot without gaps; no current above the pack's fast charge; no voltage
    // above the charger ceiling; full current only in the room-temperature band.
    table_ok(ps_jeita_fcc, PS_JEITA_FCC);
    table_ok(ps_jeita_fv, PS_JEITA_FV);
    for (size_t i = 0; i < PS_JEITA_FCC; i++) CHECK(ps_jeita_fcc[i].value <= PS_FCC_MAX_UA);
    for (size_t i = 0; i < PS_JEITA_FV; i++) CHECK(ps_jeita_fv[i].value <= PS_FV_MAX_UV);
    unsigned m = 0;
    CHECK(ps_range_value(ps_jeita_fcc, PS_JEITA_FCC, 250, &m) == 5900000u && m == 1);
    CHECK(ps_range_value(ps_jeita_fv, PS_JEITA_FV, 250, &m) == 4470000u && m == 1);
    CHECK(ps_range_value(ps_jeita_fcc, PS_JEITA_FCC, -50, &m) == 868000u && m == 1);   // cold: about 0.1 C
    CHECK(ps_range_value(ps_jeita_fv, PS_JEITA_FV, 550, &m) == 4100000u && m == 1);    // hot: lower float
    CHECK(ps_range_value(ps_jeita_fcc, PS_JEITA_FCC, 480, &m) == 5900000u && m == 2);  // listed twice in the tree
    CHECK(ps_range_value(ps_jeita_fcc, PS_JEITA_FCC, 601, &m) == 0 && m == 0);
    CHECK(ps_range_value(ps_jeita_fcc, PS_JEITA_FCC, -101, &m) == 0 && m == 0);
    // The charger's warm and cool thresholds are the profile's band edges.
    CHECK(PS_CHG_WARM_DECIC == 480 && PS_CHG_COOL_DECIC == 150);

    // Gauge thresholds: empty below cut-off, cut-off below the lowest float, termination currents are discharge-signed.
    uint32_t fv_min = UINT32_MAX;
    for (size_t i = 0; i < PS_JEITA_FV; i++) fv_min = ps_jeita_fv[i].value < fv_min ? ps_jeita_fv[i].value : fv_min;
    CHECK(PS_FG_EMPTY_MV < PS_FG_CUTOFF_MV && PS_FG_CUTOFF_MV * 1000u < fv_min);
    CHECK(PS_FG_SYS_TERM_MA < 0 && PS_FG_FFC_SYS_TERM_MA < PS_FG_SYS_TERM_MA && PS_CHG_TERM_MA < 0);

    // The charge pump: its bus OVP above the 12 V PD maximum's alarm, bat OVP above the pack's maximum.
    CHECK(PS_CP_BAT_OVP_MV * 1000u > PS_BATT_MAX_UV && PS_CP_BAT_OVP_ALARM_MV < PS_CP_BAT_OVP_MV);
    CHECK(PS_CP_BUS_OVP_ALARM_MV < PS_CP_BUS_OVP_MV && PS_CP_BUS_OCP_ALARM_MA < PS_CP_BUS_OCP_MA);
    CHECK(PS_CP_IRQ_FLAGS == (0x0002u | 0x2000u));
    // It, the backlight's and the touch's buses are different serial engines.
    CHECK(PS_CP_SE_BASE != BKL_I2C_SE_BASE && PS_CP_SE_BASE != TB_SE_BASE);
    CHECK(PS_CP_IRQ_GPIO != PS_GPIO_VBUS_DISABLE && PS_CP_IRQ_GPIO != TB_GPIO_IRQ);
    CHECK(PS_EXT_FG_MASTER_SE != PS_EXT_FG_SLAVE_SE && PS_EXT_FG_ADDR == 0x55);

    puts("PASS: pipa power supply (PPIDs = vendor PM8150B, pack and charger limits, JEITA tables, charge pump)");
    return 0;
}
