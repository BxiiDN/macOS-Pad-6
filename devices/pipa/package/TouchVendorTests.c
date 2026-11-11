// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for TouchVendor.h: the interrupt flags decode to rising edge + one shot, the SPI rate is one the tree
// offers and within TouchBoard.h's limits, firmware selection follows the panel maker and refuses unknown panels, the
// sensor matrix. Arithmetic on the device tree's numbers, not the controller.
// cc -std=gnu11 -Wall -Wextra -Werror package/TouchVendorTests.c && ./a.out
#include "TouchVendor.h"
#include "TouchBoard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

int main(void) {
    // Interrupt: TLMM 39 (the same pin TouchBoard.h polls), flags = rising | oneshot and nothing else.
    CHECK(TV_IRQ_GPIO == TB_GPIO_IRQ);
    CHECK(TV_IRQ_FLAGS == (TV_IRQF_TRIGGER_RISING | TV_IRQF_ONESHOT));
    CHECK((TV_IRQ_FLAGS & 0x000eu) == 0);                     // not falling, not level

    // SPI: the configured rate is the default TouchBoard.h uses and one of the tree's four choices.
    CHECK(TV_SPI_HZ == TB_SPI_DEFAULT_HZ);
    unsigned listed = 0;
    for (unsigned i = 0; i < sizeof(tv_spi_choices) / sizeof(tv_spi_choices[0]); i++)
        listed += tv_spi_choices[i] == TV_SPI_HZ;
    CHECK(listed == 1);

    // Firmware by panel maker: CSOT first (cfg_0), TM second (cfg_1), names that say which.
    CHECK(TV_CONFIGS == 2);
    const TvConfig *tm = tv_config_for_panel(PNL_ID_MODEL, PNL_ID_TM), *csot = tv_config_for_panel(PNL_ID_MODEL, PNL_ID_CSOT);
    CHECK(tm && csot && tm != csot);
    CHECK(tm->maker == PNL_MAKER_TM && strstr(tm->firmware, "_tm.bin") && strstr(tm->mp, "_mp_tm"));
    CHECK(csot->maker == PNL_MAKER_CSOT && strstr(csot->firmware, "_csot.bin") && strstr(csot->mp, "_mp_csot"));
    CHECK(strstr(tm->firmware, "nt36532_m82") && strstr(csot->firmware, "nt36532_m82"));
    // An unknown panel (other maker byte, other model) gets no firmware rather than a guess.
    CHECK(tv_config_for_panel(PNL_ID_MODEL, 0x00380200u) == NULL);
    CHECK(tv_config_for_panel(0x4B383141u, PNL_ID_TM) == NULL);

    // Sensor matrix: 38 x 60 nodes, the long side along the panel's 2880 rows.
    CHECK(tv_nodes() == 2280);
    CHECK(TV_Y_CHANNELS > TV_X_CHANNELS && PNL_V_ACTIVE > pnl_width());
    CHECK(TV_PEN == 1 && TV_STYLUS_DOUBLE == 1);
    CHECK(strcmp(TV_COMPATIBLE, "novatek,NVT-ts-spi") == 0);

    puts("PASS: pipa touch vendor facts (irq flags, SPI rate, firmware by panel maker, sensor matrix)");
    return 0;
}
