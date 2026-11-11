// SPDX-License-Identifier: BSD-2-Clause-Patent
// Test-only: a register simulator of a GENI serial engine in I2C FIFO mode with I2C targets behind it (the register
// behaviour Linux's i2c-qcom-geni.c relies on). Used by GeniI2cTests.c and PipaBacklightTests.c; a model, not the chip.
// The includer defines CHECK(cond) and includes Ktz8866Driver.h first.
#ifndef PIPA_GENI_I2C_SIM_H
#define PIPA_GENI_I2C_SIM_H
#include <string.h>

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

static inline void sim_end(Sim *s, uint32_t bits, int error) {
    s->irq |= bits | GENI_M_CMD_DONE;
    s->active = 0;
    if (error || !s->stretch) {
        s->bus_held = 0;
        s->stops++;
    } else {
        s->bus_held = 1;
    }
}

static inline void sim_step(Sim *s) {
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

static inline void sim_start(Sim *s, uint32_t v) {
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

static inline void sim_tx(Sim *s, uint32_t v) {
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

static inline uint32_t sim_read(void *ctx, uint32_t off) {
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

static inline void sim_write(void *ctx, uint32_t off, uint32_t v) {
    Sim *s = ctx;
    switch (off) {
    case GENI_M_IRQ_CLEAR: s->irq &= ~v; break;
    case GENI_DMA_MODE_EN: s->dma_mode = v; s->forbidden++; break;   // the mode is the firmware's: never written
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

static inline void sim_delay(void *ctx, unsigned us) {
    Sim *s = ctx;
    (void)us;
    s->delays++;
}

static inline const GeniI2cScl *scl400(void) { return geni_i2c_scl_lookup(19200000u, 400000u); }

static inline void sim_reset(Sim *s) {
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

static inline GeniI2c bus_of(Sim *s) {
    GeniI2c g = {sim_read, sim_write, sim_delay, s, 10, 1000};
    return g;
}

#endif
