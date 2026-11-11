// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa's battery, gauge and charger as the Android device tree configures them: addresses, interrupts, supplies and
// the limits the vendor drivers charge with. Pure facts and lookups; NativeBatteryBoard.h keeps the register decoding
// NativeBattery.cpp reads with. Host-tested by PowerSupplyBoardTests.c; scripts/pipa_hw.py vendor checks every value
// against MiCode/kernel_devicetree pipa-t-oss 623dd5bf (qcom/pm8150b.dtsi, kona-pmic-overlay.dtsi, pipa-sm8250.dtsi,
// pipa-pinctrl.dtsi, kona-qupv3.dtsi, fg-gen4-batterydata-pipa-sunwoda-8840mah.dtsi). New in macOS-Pad-6.
//
// What the tree says, in short:
//   - the gauge Android uses is the PM8150B's FG gen4 (pm8150b_fg "ok", SPMI USID 2, peripherals 0x40..0x43); the two
//     TI bq27z561 gauges (master on QUP SE13 0x55, slave on SE0 0x55) are described but both buses are "disabled";
//   - the charger is the PM8150B's SMB5 (0x10..0x16), with a TI bq2597x charge pump on QUP SE16 (0x888000) at 0x66
//     for fast charging (mi,use-bq-pump), its interrupt on TLMM 68 (falling edge, one shot);
//   - the pack is "M82_sunwoda_8840mah": 8840 mAh nominal, 4.47 V maximum, 5.9 A fast charge, JEITA tables below.
// Nothing here writes a PMIC or charger register; macOS on pipa has no charger driver, and NativeBattery.cpp only reads.
#ifndef PIPA_POWER_SUPPLY_BOARD_H
#define PIPA_POWER_SUPPLY_BOARD_H
#include <stddef.h>
#include <stdint.h>

// PM8150B on SPMI (qcom,pm8150b@2: reg = <0x2 SPMI_USID>). PPID = USID << 8 | peripheral base >> 8.
#define PS_PMIC_USID 2u
#define PS_FG_SOC 0x4000u
#define PS_FG_INFO 0x4100u
#define PS_FG_RRADC 0x4200u
#define PS_FG_MEMIF 0x4300u
#define PS_SMB_CHGR 0x1000u
#define PS_SMB_DCDC 0x1100u
#define PS_SMB_BATIF 0x1200u
#define PS_SMB_USB 0x1300u
#define PS_SMB_DC 0x1400u
#define PS_SMB_TYPEC 0x1500u
#define PS_SMB_MISC 0x1600u
#define PS_PERIPH_SIZE 0x100u

static inline uint32_t ps_ppid(uint32_t usid, uint32_t base) { return usid << 8 | base >> 8; }

// The charger's limits (&pm8150b_charger in pipa-sm8250.dtsi).
#define PS_USB_ICL_UA 3000000u
#define PS_FCC_MAX_UA 5900000u
#define PS_FV_MAX_UV 4470000u
#define PS_NON_FFC_FV_MAX_UV 4440000u
#define PS_DC_ICL_UA 1000000u
#define PS_AUTO_RECHARGE_SOC 99u
#define PS_CHG_TERM_MA (-400)
#define PS_CHG_WARM_DECIC 480
#define PS_CHG_COOL_DECIC 150
#define PS_GPIO_VBUS_DISABLE 74u        // vbus-disable-gpio, active high

// The gauge's thresholds (&pm8150b_fg).
#define PS_FG_CUTOFF_MV 3400u
#define PS_FG_EMPTY_MV 3100u
#define PS_FG_CUTOFF_MA 200u
#define PS_FG_SYS_TERM_MA (-500)
#define PS_FG_FFC_SYS_TERM_MA (-1700)

// The battery profile (fg-gen4-batterydata-pipa-sunwoda-8840mah.dtsi).
#define PS_BATT_TYPE "M82_sunwoda_8840mah"
#define PS_BATT_MAH 8840u
#define PS_BATT_MAX_UV 4470000u
#define PS_BATT_FASTCHG_MA 5900u
#define PS_BATT_ID_KOHM 100u
#define PS_BATT_BETA 4250u
#define PS_JEITA_TOO_HOT_DECIC 590
#define PS_JEITA_TOO_COLD_DECIC (-100)

typedef struct {
    int16_t low, high;      // deci-degrees C, inclusive
    uint32_t value;         // uA (fcc) or uV (fv)
} PsRange;

static const PsRange ps_jeita_fcc[] = {
    {-100, 0, 868000u}, {1, 50, 1736000u}, {51, 100, 4340000u}, {101, 150, 5900000u}, {151, 480, 5900000u}, {480, 600, 4340000u},
};
static const PsRange ps_jeita_fv[] = {
    {-100, 0, 4440000u}, {1, 50, 4440000u}, {51, 100, 4440000u}, {101, 150, 4440000u}, {151, 480, 4470000u}, {481, 600, 4100000u},
};
#define PS_JEITA_FCC (sizeof(ps_jeita_fcc) / sizeof(ps_jeita_fcc[0]))
#define PS_JEITA_FV (sizeof(ps_jeita_fv) / sizeof(ps_jeita_fv[0]))

// The value of the first range holding temp, and how many ranges hold it (the fcc table lists 480 twice: which one
// the vendor driver applies there is its lookup order, not checked here). 0 outside every range: no charging.
static inline uint32_t ps_range_value(const PsRange *r, size_t n, int temp, unsigned *matches) {
    uint32_t v = 0;
    unsigned m = 0;
    for (size_t i = 0; i < n; i++) {
        if (temp >= r[i].low && temp <= r[i].high) {
            if (!m) v = r[i].value;
            m++;
        }
    }
    if (matches) *matches = m;
    return v;
}

// The bq2597x charge pump (&qupv3_se16_i2c bq2597x-standalone@66) and its interrupt pin (bq2597x_master_int_default).
#define PS_CP_SE_BASE 0x888000u
#define PS_CP_ADDR 0x66u
#define PS_CP_IRQ_GPIO 68u
#define PS_CP_IRQ_FLAGS 0x2002u         // IRQF_TRIGGER_FALLING | IRQF_ONESHOT
#define PS_CP_PIN_MA 2u                 // pull-up, input
#define PS_CP_BAT_OVP_MV 4550u
#define PS_CP_BAT_OVP_ALARM_MV 4525u
#define PS_CP_BUS_OVP_MV 12000u
#define PS_CP_BUS_OVP_ALARM_MV 11000u
#define PS_CP_BUS_OCP_MA 3800u
#define PS_CP_BUS_OCP_ALARM_MA 3500u

// The external gauges the tree describes and disables.
#define PS_EXT_FG_ADDR 0x55u
#define PS_EXT_FG_MASTER_SE 0xa94000u   // qupv3_se13_i2c, status "disabled"
#define PS_EXT_FG_SLAVE_SE 0x980000u    // qupv3_se0_i2c, status "disabled"

#endif
