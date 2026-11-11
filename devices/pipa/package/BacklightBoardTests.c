// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for BacklightBoard.h: the KTZ8866 register writes of pipa's configuration, the brightness split and
// the BL_EN bit across calls, against a modelled register file. This tests the encoding, not the tablet.
// cc -std=gnu11 -Wall -Wextra -Werror package/BacklightBoardTests.c && ./a.out
#include "BacklightBoard.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

int main(void) {
    BklWrite w[8];
    uint8_t regs[BKL_REG_MAX + 1];

    // pipa (ML): five sinks, 128 ms current ramp, 1 ms LED ramp, LCD bias on.
    BklConfig c = bkl_pipa_config();
    unsigned n = bkl_init_writes(&c, w);
    CHECK(n == 4);
    CHECK(w[0].reg == BKL_REG_EN && w[0].mask == 0xff && w[0].value == 0x1f);           // sinks 0..4
    CHECK(w[1].reg == BKL_REG_CFG2 && w[1].value == (0x80 | 7 << 3 | 5));              // log2(128) = 7 -> 0xbd
    CHECK(w[1].value == 0xbd);
    CHECK(w[2].reg == BKL_REG_DIMMING && w[2].value == 0x11);                           // log2(1) + 1 = 1, on and off
    CHECK(w[3].reg == BKL_REG_LCD_BIAS_CFG1 && w[3].value == 0x9f);

    // Field encodings.
    CHECK(bkl_cfg2(64) == (0x80 | 6 << 3 | 5));
    CHECK(bkl_cfg2(100) == (0x80 | 6 << 3 | 5));        // floor(log2(100)) = 6
    CHECK(bkl_cfg2(256) == (0x80 | 9 << 3 | 5));        // 5 + 256 / 64
    CHECK(bkl_cfg2(0) == (0x80 | 5));
    CHECK(bkl_dimming(0) == 0 && bkl_dimming(2) == 0x22 && bkl_dimming(16) == 0x55);

    // Options left out write nothing; zero or more than six sinks means all six.
    BklConfig bare = {0, 0, -1, 0};
    n = bkl_init_writes(&bare, w);
    CHECK(n == 1 && w[0].value == 0x3f);
    BklConfig many = {9, 0, -1, 0};
    CHECK(bkl_init_writes(&many, w) == 1 && w[0].value == 0x3f);

    // Power-up sequence then the default brightness, on the modelled registers.
    memset(regs, 0, sizeof(regs));
    n = bkl_init_writes(&c, w);
    bkl_apply(regs, w, n);
    int on = 0;
    n = bkl_brightness_writes(BKL_DEFAULT_LEVEL, &on, w);
    CHECK(n == 3 && on == 1);
    CHECK(w[0].reg == BKL_REG_EN && w[0].mask == BKL_EN_BIT && w[0].value == BKL_EN_BIT);
    bkl_apply(regs, w, n);
    CHECK(regs[BKL_REG_EN] == (0x1f | BKL_EN_BIT));         // the sinks kept, the enable added
    CHECK(regs[BKL_REG_BRT_LSB] == (1500 & 7) && regs[BKL_REG_BRT_MSB] == (1500 >> 3));
    CHECK((regs[BKL_REG_BRT_MSB] << 3 | regs[BKL_REG_BRT_LSB]) == 1500);

    // A second nonzero level only rewrites the brightness.
    n = bkl_brightness_writes(1, &on, w);
    CHECK(n == 2 && w[0].reg == BKL_REG_BRT_LSB);
    bkl_apply(regs, w, n);
    CHECK(regs[BKL_REG_BRT_LSB] == 1 && regs[BKL_REG_BRT_MSB] == 0 && (regs[BKL_REG_EN] & BKL_EN_BIT));

    // Zero turns the backlight off and leaves the sinks configured.
    n = bkl_brightness_writes(0, &on, w);
    CHECK(n == 3 && on == 0);
    bkl_apply(regs, w, n);
    CHECK(regs[BKL_REG_EN] == 0x1f && regs[BKL_REG_BRT_LSB] == 0 && regs[BKL_REG_BRT_MSB] == 0);

    // Clamping and every level round-trips through the two registers.
    n = bkl_brightness_writes(5000, &on, w);
    bkl_apply(regs, w, n);
    CHECK((regs[BKL_REG_BRT_MSB] << 3 | regs[BKL_REG_BRT_LSB]) == BKL_MAX_LEVEL);
    for (unsigned level = 0; level <= BKL_MAX_LEVEL; level++) {
        int state = 1;
        n = bkl_brightness_writes(level, &state, w);
        memset(regs, 0, sizeof(regs));
        bkl_apply(regs, w, n);
        CHECK((unsigned)(regs[BKL_REG_BRT_MSB] << 3 | regs[BKL_REG_BRT_LSB]) == level);
    }

    // Fractions.
    CHECK(bkl_level_from_fraction(0, 100) == 0);
    CHECK(bkl_level_from_fraction(100, 100) == BKL_MAX_LEVEL && bkl_level_from_fraction(200, 100) == BKL_MAX_LEVEL);
    CHECK(bkl_level_from_fraction(1, 2) == 1024);              // 1023.5 rounds up
    CHECK(bkl_level_from_fraction(1, 0) == 0);
    CHECK(bkl_level_from_fraction(0xffffffffu - 1, 0xffffffffu) == BKL_MAX_LEVEL);

    // Writes beyond the register file are ignored by the model.
    BklWrite bad = {0x40, 0xff, 1};
    memset(regs, 0, sizeof(regs));
    bkl_apply(regs, &bad, 1);
    for (unsigned i = 0; i <= BKL_REG_MAX; i++)
        CHECK(regs[i] == 0);

    puts("PASS: pipa backlight (KTZ8866 init writes, brightness split, BL_EN across calls)");
    return 0;
}
