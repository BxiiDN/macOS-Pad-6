// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for GeniI2cCore.h and Ktz8866Driver.h against a register simulator of a GENI serial engine in I2C FIFO
// mode with I2C targets behind it. The simulator follows the register behaviour the Linux driver relies on (M_CMD0
// starts a command, TX words on the TX watermark, RX words with RX_LAST, GP IRQ 1/3/4 errors, M_GP_LENGTH, cancel and
// abort through M_CMD_CTRL); it is a model, not the chip. Nothing here has run on the tablet.
// cc -std=gnu11 -Wall -Wextra -Werror package/GeniI2cTests.c && ./a.out
#include "Ktz8866Driver.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

typedef struct {
    int present;
    uint8_t addr, ptr;
    uint8_t regs[256];
    unsigned nack_at;          // NACK the n-th byte after the address (1 = the register pointer); 0: never
    unsigned data_writes, data_reads;
} Target;

typedef enum { F_NONE, F_BUS, F_ARB, F_HANG, F_HANG_HARD } Fault;

typedef struct {
    unsigned op, addr, stretch, len, restart;
} Cmd;

typedef struct {
    uint32_t fw_rev, status, if_disable, m_clk_cfg, clk_sel, scl, hw_param0, dma_mode;
    uint32_t irq;
    int active;
    unsigned op, addr, stretch, len, moved, tx_len, rx_len;
    uint32_t tx_wm;
    uint32_t rx[256];
    unsigned rx_head, rx_tail;
    int rx_last;
    Target t[2];
    Target *cur;
    Fault fault;
    unsigned rx_per_poll;
    Cmd cmd[64];
    unsigned ncmd;
    int bus_held;
    unsigned stops, forbidden, cancels, aborts, delays, overruns;
} Sim;

static void sim_end(Sim *s, uint32_t bits, int error) {
    s->irq |= bits | GENI_M_CMD_DONE;
    s->active = 0;
    if (error || !s->stretch) {
        s->bus_held = 0;
        s->stops++;
    } else {
        s->bus_held = 1;
    }
}

static void sim_step(Sim *s) {
    if (!s->active)
        return;
    switch (s->fault) {
    case F_HANG:
    case F_HANG_HARD:
        return;
    case F_BUS:
        s->irq |= GENI_M_GP_IRQ_3 | GENI_M_CMD_FAILURE;     // no CMD_DONE: the driver must cancel
        return;
    case F_ARB:
        sim_end(s, GENI_M_GP_IRQ_4 | GENI_M_CMD_FAILURE, 1);
        return;
    case F_NONE:
        break;
    }
    if (s->op == GENI_I2C_READ && s->rx_head == s->rx_tail && s->moved < s->len) {
        for (unsigned w = 0; w < s->rx_per_poll && s->moved < s->len; w++) {
            uint32_t v = 0;
            for (unsigned b = 0; b < 4 && s->moved < s->len; b++, s->moved++) {
                v |= (uint32_t)s->cur->regs[s->cur->ptr++] << (8 * b);
                s->cur->data_reads++;
            }
            s->rx[s->rx_tail++ % 256] = v;
        }
        s->irq |= GENI_M_RX_FIFO_WATERMARK;
        if (s->moved == s->len) {
            s->rx_last = 1;
            s->irq |= GENI_M_RX_FIFO_LAST;
            sim_end(s, 0, 0);
        }
    }
}

static void sim_start(Sim *s, uint32_t v) {
    if (s->active) {
        s->irq |= GENI_M_ILLEGAL_CMD;
        return;
    }
    s->op = v >> 27;
    s->addr = (v >> 9) & 0x7f;
    s->stretch = (v >> 2) & 1;
    s->len = s->op == GENI_I2C_READ ? s->rx_len : s->tx_len;
    s->moved = 0;
    s->rx_head = s->rx_tail = 0;
    s->rx_last = 0;
    CHECK(s->ncmd < 64);
    s->cmd[s->ncmd++] = (Cmd){s->op, s->addr, s->stretch, s->len, (unsigned)s->bus_held};
    s->active = 1;
    s->cur = NULL;
    for (int i = 0; i < 2; i++)
        if (s->t[i].present && s->t[i].addr == s->addr)
            s->cur = &s->t[i];
    if (!s->cur)
        sim_end(s, GENI_M_GP_IRQ_1 | GENI_M_CMD_FAILURE, 1);   // address NACK, M_GP_LENGTH 0
    else if (s->len == 0 && s->fault == F_NONE)
        sim_end(s, 0, 0);
}

static void sim_tx(Sim *s, uint32_t v) {
    if (!s->active || s->op != GENI_I2C_WRITE || s->fault != F_NONE) {
        if (!s->active || s->op != GENI_I2C_WRITE)
            s->overruns++;
        return;
    }
    for (unsigned b = 0; b < 4 && s->moved < s->len; b++, v >>= 8) {
        if (s->cur->nack_at == s->moved + 1) {
            sim_end(s, GENI_M_GP_IRQ_1 | GENI_M_CMD_FAILURE, 1);
            return;
        }
        if (s->moved == 0)
            s->cur->ptr = (uint8_t)v;
        else {
            s->cur->regs[s->cur->ptr++] = (uint8_t)v;
            s->cur->data_writes++;
        }
        s->moved++;
    }
    if (s->moved == s->len)
        sim_end(s, 0, 0);
}

static uint32_t sim_read(void *ctx, uint32_t off) {
    Sim *s = ctx;
    switch (off) {
    case GENI_FW_REVISION_RO: return s->fw_rev;
    case GENI_STATUS: return s->status | (s->active ? GENI_M_CMD_ACTIVE : 0);
    case GENI_IF_DISABLE_RO: return s->if_disable;
    case GENI_SER_M_CLK_CFG: return s->m_clk_cfg;
    case GENI_CLK_SEL: return s->clk_sel;
    case GENI_I2C_SCL_COUNTERS: return s->scl;
    case GENI_HW_PARAM_0: return s->hw_param0;
    case GENI_DMA_MODE_EN: return s->dma_mode;
    case GENI_M_GP_LENGTH: return s->moved;
    case GENI_M_IRQ_STATUS:
        sim_step(s);
        return s->irq | (s->active && s->op == GENI_I2C_WRITE && s->tx_wm && s->moved < s->len && s->fault == F_NONE
                             ? GENI_M_TX_FIFO_WATERMARK : 0);
    case GENI_RX_FIFO_STATUS: return (s->rx_tail - s->rx_head) | (s->rx_last ? GENI_RX_LAST : 0);
    case GENI_RX_FIFO: return s->rx_head < s->rx_tail ? s->rx[s->rx_head++ % 256] : 0;
    default: return 0;
    }
}

static void sim_write(void *ctx, uint32_t off, uint32_t v) {
    Sim *s = ctx;
    switch (off) {
    case GENI_M_IRQ_CLEAR: s->irq &= ~v; break;
    case GENI_DMA_MODE_EN: s->dma_mode = v; break;
    case GENI_I2C_TX_TRANS_LEN: s->tx_len = v; break;
    case GENI_I2C_RX_TRANS_LEN: s->rx_len = v; break;
    case GENI_M_CMD0: sim_start(s, v); break;
    case GENI_TX_WATERMARK: s->tx_wm = v; break;
    case GENI_TX_FIFO: sim_tx(s, v); break;
    case GENI_M_CMD_CTRL:
        if (v & GENI_M_CMD_CANCEL) {
            s->cancels++;
            if (s->fault != F_HANG_HARD) {
                s->active = 0;
                s->irq |= GENI_M_CMD_CANCEL_IRQ;
                s->bus_held = 0;
                s->stops++;
            }
        }
        if (v & GENI_M_CMD_ABORT) {
            s->aborts++;
            s->active = 0;
            s->irq |= GENI_M_CMD_ABORT_IRQ;
            s->bus_held = 0;
        }
        break;
    default: s->forbidden++; break;        // clocks, SCL counters, packing, pins: the firmware's, never written
    }
}

static void sim_delay(void *ctx, unsigned us) {
    Sim *s = ctx;
    (void)us;
    s->delays++;
}

static const GeniI2cScl *scl400(void) { return geni_i2c_scl_lookup(19200000u, 400000u); }

static void sim_reset(Sim *s) {
    memset(s, 0, sizeof(*s));
    s->fw_rev = GENI_PROTOCOL_I2C << 8 | 0x0f;
    s->hw_param0 = 16u << 16;
    s->m_clk_cfg = geni_i2c_m_clk_cfg(scl400());
    s->scl = geni_i2c_scl_counters(scl400());
    s->rx_per_poll = 4;
    s->t[0].present = 1;
    s->t[0].addr = BKL_I2C_ADDR;
    s->t[0].regs[BKL_REG_DEVICE_ID] = 0x5a;      // a simulated ID: the public sources give no expected value
}

static GeniI2c bus_of(Sim *s) {
    GeniI2c g = {sim_read, sim_write, sim_delay, s, 10, 1000};
    return g;
}

static void test_tables(void) {
    const GeniI2cScl *s = scl400();
    CHECK(s && s->clk_div == 2 && s->t_high == 5 && s->t_low == 11 && s->t_cycle == 22);
    CHECK(geni_i2c_scl_counters(s) == (5u << 20 | 11u << 10 | 22u));
    CHECK(geni_i2c_m_clk_cfg(s) == 0x21);
    const GeniI2cScl *f = geni_i2c_scl_lookup(19200000u, 1000000u);
    CHECK(f && geni_i2c_m_clk_cfg(f) == 0x11 && geni_i2c_scl_counters(f) == (2u << 20 | 8u << 10 | 18u));
    const GeniI2cScl *t = geni_i2c_scl_lookup(32000000u, 100000u);
    CHECK(t && t->clk_div == 12 && t->t_cycle == 26);
    CHECK(!geni_i2c_scl_lookup(19200000u, 3400000u) && !geni_i2c_scl_lookup(50000000u, 400000u));
    CHECK(GENI_M_CMD(GENI_I2C_READ, GENI_I2C_ADDR(0x11) | GENI_I2C_STOP_STRETCH) == (2u << 27 | 0x11u << 9 | 4u));
    CHECK(GENI_FW_PROTOCOL(0x0000030f) == 3 && GENI_TX_FIFO_DEPTH(0x00100000) == 16);
    CHECK(strcmp(geni_i2c_status_name(GENI_I2C_ADDR_NACK), "addr-nack") == 0);
    CHECK(strcmp(geni_i2c_status_name(GENI_I2C_READ_ONLY), "read-only") == 0);
    CHECK(strcmp(geni_i2c_status_name((GeniI2cStatus)99), "?") == 0);
}

static void test_probe(void) {
    Sim s;
    GeniI2cInfo info;
    sim_reset(&s);
    GeniI2c g = bus_of(&s);
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_OK);
    CHECK(info.protocol == GENI_PROTOCOL_I2C && info.tx_fifo_depth == 16);
    CHECK(geni_i2c_check_clock(&info, 19200000u, 400000u) == GENI_I2C_OK);
    CHECK(geni_i2c_check_clock(&info, 19200000u, 100000u) == GENI_I2C_CLOCK);
    CHECK(geni_i2c_check_clock(&info, 32000000u, 400000u) == GENI_I2C_CLOCK);
    CHECK(geni_i2c_check_clock(&info, 19200000u, 123456u) == GENI_I2C_INVALID);
    CHECK(s.forbidden == 0 && s.ncmd == 0);                // probe is read only

    s.fw_rev = 2u << 8;                                    // UART firmware
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_NOT_I2C);
    s.fw_rev = 0;
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_NOT_I2C);
    sim_reset(&s);
    s.if_disable = GENI_FIFO_IF_DISABLE;                   // GPI DMA owns the engine
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_FIFO_DISABLED);
    sim_reset(&s);
    s.status = GENI_M_CMD_ACTIVE;
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_BUSY);
    sim_reset(&s);
    s.m_clk_cfg = 0x20;                                    // divider right, serial clock off
    CHECK(geni_i2c_probe(&g, &info) == GENI_I2C_OK);
    CHECK(geni_i2c_check_clock(&info, 19200000u, 400000u) == GENI_I2C_CLOCK);
}

static void test_transfers(void) {
    Sim s;
    sim_reset(&s);
    GeniI2c g = bus_of(&s);
    uint8_t v = 0;

    // Register write: one WRITE command, pointer then data, then STOP.
    CHECK(geni_i2c_write_reg(&g, 0x11, 0x05, 0xbb) == GENI_I2C_OK);
    CHECK(s.t[0].regs[0x05] == 0xbb && s.t[0].data_writes == 1);
    CHECK(s.ncmd == 1 && s.cmd[0].op == GENI_I2C_WRITE && s.cmd[0].addr == 0x11 && s.cmd[0].len == 2);
    CHECK(s.cmd[0].stretch == 0 && s.stops == 1 && !s.bus_held && !s.active);
    CHECK(s.dma_mode == 0 && s.tx_wm == 0 && s.overruns == 0);

    // Register read: WRITE (pointer) with STOP_STRETCH, then READ with a repeated start, then STOP.
    s.ncmd = s.stops = 0;
    CHECK(geni_i2c_read_reg(&g, 0x11, BKL_REG_DEVICE_ID, &v) == GENI_I2C_OK && v == 0x5a);
    CHECK(s.ncmd == 2 && s.cmd[0].op == GENI_I2C_WRITE && s.cmd[0].stretch == 1 && s.cmd[0].len == 1);
    CHECK(s.cmd[1].op == GENI_I2C_READ && s.cmd[1].restart == 1 && s.cmd[1].stretch == 0 && s.cmd[1].len == 1);
    CHECK(s.stops == 1 && s.t[0].data_writes == 1);

    // Multi-word write (9 bytes: three TX words) and read (7 bytes, one RX word per poll).
    uint8_t out[9] = {0x20, 1, 2, 3, 4, 5, 6, 7, 8}, in[7];
    GeniI2cMsg w = {0x11, 0, 9, out};
    CHECK(geni_i2c_transfer(&g, &w, 1) == GENI_I2C_OK);
    for (int i = 0; i < 8; i++)
        CHECK(s.t[0].regs[0x20 + i] == i + 1);
    s.rx_per_poll = 1;
    uint8_t ptr = 0x21;
    GeniI2cMsg wr[2] = {{0x11, 0, 1, &ptr}, {0x11, 1, 7, in}};
    unsigned polls = s.delays;
    CHECK(geni_i2c_transfer(&g, wr, 2) == GENI_I2C_OK);
    for (int i = 0; i < 7; i++)
        CHECK(in[i] == i + 2);
    CHECK(s.delays > polls);                              // more than one poll for two RX words
    CHECK(s.forbidden == 0 && s.overruns == 0);

    // Two targets on one bus; the second is addressed separately.
    s.t[1].present = 1;
    s.t[1].addr = 0x2c;
    s.t[1].regs[0] = 0x77;
    CHECK(geni_i2c_read_reg(&g, 0x2c, 0, &v) == GENI_I2C_OK && v == 0x77);
}

static void test_errors(void) {
    Sim s;
    uint8_t v = 0, b[4] = {0};
    sim_reset(&s);
    GeniI2c g = bus_of(&s);

    // Nothing at the address: address NACK (M_GP_LENGTH 0), the bus is released.
    CHECK(geni_i2c_read_reg(&g, 0x12, 0, &v) == GENI_I2C_ADDR_NACK);
    CHECK(s.ncmd == 1 && !s.bus_held && !s.active && s.cancels == 0);
    CHECK(geni_i2c_write_reg(&g, 0x12, 0, 1) == GENI_I2C_ADDR_NACK);

    // The target NACKs a data byte: data NACK, nothing after it is written.
    sim_reset(&s);
    s.t[0].nack_at = 2;
    CHECK(geni_i2c_write_reg(&g, 0x11, 0x05, 0xbb) == GENI_I2C_DATA_NACK);
    CHECK(s.t[0].regs[0x05] == 0 && s.t[0].data_writes == 0 && !s.active);

    // A NACK in the first message stops a write-then-read before the read. Nothing had moved (M_GP_LENGTH 0), so it
    // reads as an address NACK: the same rule as Linux's geni_i2c_check_addr_data_nack.
    sim_reset(&s);
    s.t[0].nack_at = 1;
    CHECK(geni_i2c_read_reg(&g, 0x11, 0x01, &v) == GENI_I2C_ADDR_NACK && s.ncmd == 1);

    // Bus protocol error without CMD_DONE: cancelled, not aborted.
    sim_reset(&s);
    s.fault = F_BUS;
    CHECK(geni_i2c_read_reg(&g, 0x11, 0x01, &v) == GENI_I2C_BUS_ERROR);
    CHECK(s.cancels == 1 && s.aborts == 0 && !s.active && s.irq == 0);

    // Arbitration lost (with CMD_DONE): no cancel needed.
    sim_reset(&s);
    s.fault = F_ARB;
    CHECK(geni_i2c_write_reg(&g, 0x11, 0x05, 1) == GENI_I2C_ARB_LOST && s.cancels == 0);

    // A command that never finishes: timeout, cancel; if cancel does not take, abort.
    sim_reset(&s);
    s.fault = F_HANG;
    CHECK(geni_i2c_write_reg(&g, 0x11, 0x05, 1) == GENI_I2C_TIMEOUT);
    CHECK(s.cancels == 1 && s.aborts == 0 && !s.active);
    sim_reset(&s);
    s.fault = F_HANG_HARD;
    CHECK(geni_i2c_read_reg(&g, 0x11, 0x01, &v) == GENI_I2C_TIMEOUT);
    CHECK(s.cancels == 1 && s.aborts == 1 && !s.active && s.irq == 0);

    // Bad arguments never reach the engine.
    sim_reset(&s);
    GeniI2cMsg m = {0x11, 0, 4, NULL};
    CHECK(geni_i2c_transfer(&g, &m, 1) == GENI_I2C_INVALID);
    m.buf = b;
    CHECK(geni_i2c_transfer(&g, &m, 0) == GENI_I2C_INVALID);
    CHECK(geni_i2c_transfer(NULL, &m, 1) == GENI_I2C_INVALID);
    CHECK(s.ncmd == 0 && s.forbidden == 0);
}

static void test_ktz8866(void) {
    Sim s;
    sim_reset(&s);
    GeniI2c g = bus_of(&s);
    Ktz8866 k = ktz_pipa(&g);
    uint8_t model[BKL_REG_MAX + 1] = {0};

    // Attach is read only: DEVICE_ID read, nothing written to the chip.
    CHECK(k.addr == 0x11 && !k.allow_writes);
    CHECK(ktz_attach(&k) == GENI_I2C_OK && k.device_id == 0x5a);
    CHECK(s.t[0].data_writes == 0 && s.forbidden == 0 && s.ncmd == 2);

    // Writes are refused until allowed, and then never reach the engine.
    BklConfig c = bkl_pipa_config();
    s.ncmd = 0;
    CHECK(ktz_init(&k, &c) == GENI_I2C_READ_ONLY && ktz_set(&k, 100) == GENI_I2C_READ_ONLY);
    CHECK(s.ncmd == 0 && s.t[0].data_writes == 0);

    // Allowed: the chip's registers end as BacklightBoard.h's model says.
    k.allow_writes = 1;
    BklWrite w[4];
    unsigned n = bkl_init_writes(&c, w);
    model[BKL_REG_DEVICE_ID] = 0x5a;
    bkl_apply(model, w, n);
    CHECK(ktz_init(&k, &c) == GENI_I2C_OK);
    CHECK(memcmp(s.t[0].regs, model, sizeof(model)) == 0);
    CHECK(s.t[0].regs[BKL_REG_EN] == 0x1f && s.t[0].regs[BKL_REG_CFG2] == 0xbd);
    CHECK(s.t[0].regs[BKL_REG_DIMMING] == 0x11 && s.t[0].regs[BKL_REG_LCD_BIAS_CFG1] == 0x9f);

    // 1500: BL_EN bit 6 by read-modify-write (sinks kept), LSB 1500 & 7, MSB 1500 >> 3.
    s.ncmd = 0;
    CHECK(ktz_set(&k, 1500) == GENI_I2C_OK && k.on && k.level == 1500);
    CHECK(s.t[0].regs[BKL_REG_EN] == 0x5f && s.t[0].regs[BKL_REG_BRT_LSB] == 4 && s.t[0].regs[BKL_REG_BRT_MSB] == 187);
    CHECK(s.ncmd == 2 + 1 + 1 + 1);                       // read (2 commands), EN write, LSB write, MSB write
    // A second nonzero level does not touch BL_EN.
    s.ncmd = 0;
    CHECK(ktz_set(&k, 2) == GENI_I2C_OK && s.ncmd == 2);
    CHECK(s.t[0].regs[BKL_REG_BRT_LSB] == 2 && s.t[0].regs[BKL_REG_BRT_MSB] == 0 && s.t[0].regs[BKL_REG_EN] == 0x5f);
    // Clamped, then off: bit 6 cleared, sinks kept.
    CHECK(ktz_set(&k, 5000) == GENI_I2C_OK && k.level == BKL_MAX_LEVEL);
    CHECK(s.t[0].regs[BKL_REG_BRT_LSB] == 7 && s.t[0].regs[BKL_REG_BRT_MSB] == 255);
    CHECK(ktz_set(&k, 0) == GENI_I2C_OK && !k.on && s.t[0].regs[BKL_REG_EN] == 0x1f);
    CHECK(s.forbidden == 0 && s.overruns == 0);

    // A failed write leaves the driver's state as it was.
    s.t[0].nack_at = 2;
    CHECK(ktz_set(&k, 900) == GENI_I2C_DATA_NACK && !k.on && k.level == 0);
    s.t[0].nack_at = 0;
    BklWrite far = {0x40, 0xff, 1};
    CHECK(ktz_write(&k, &far) == GENI_I2C_INVALID);

    // Attach refuses an engine at the wrong speed without any I2C traffic, and reports an absent chip.
    sim_reset(&s);
    k = ktz_pipa(&g);
    s.scl = geni_i2c_scl_counters(geni_i2c_scl_lookup(19200000u, 100000u));
    CHECK(ktz_attach(&k) == GENI_I2C_CLOCK && s.ncmd == 0);
    sim_reset(&s);
    s.t[0].present = 0;
    CHECK(ktz_attach(&k) == GENI_I2C_ADDR_NACK);
    sim_reset(&s);
    s.fw_rev = 1u << 8;                                    // SPI firmware
    CHECK(ktz_attach(&k) == GENI_I2C_NOT_I2C && s.ncmd == 0);
}

int main(void) {
    test_tables();
    test_probe();
    test_transfers();
    test_errors();
    test_ktz8866();
    puts("PASS: GENI I2C core (probe, clock check, FIFO write/read, repeated start, NACK/bus/arb/timeout, cancel/abort)"
         " and KTZ8866 driver (read-only attach, write gate, init, brightness) against a register simulator");
    return 0;
}
