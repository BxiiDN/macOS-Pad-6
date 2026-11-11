// SPDX-License-Identifier: BSD-2-Clause-Patent
// Qualcomm GENI serial engine as an I2C controller, FIFO mode, polled: the part of a driver that does not depend on
// the kernel. Every register access goes through GeniI2c.read32/write32 (and every wait through delay_us), so the same
// code can run behind a kernel MMIO mapping of the serial engine and runs today against the register simulator of
// GeniI2cTests.c. New in macOS-Pad-6. It has not run on the tablet.
//
// Register map, bit fields, command encoding and the 19.2/32 MHz SCL tables are the public ones of Linux's
// include/linux/soc/qcom/geni-se.h, drivers/soc/qcom/qcom-geni-se.c and drivers/i2c/busses/i2c-qcom-geni.c (mainline
// 067c5c24cef2); the code is written here. What it does:
//   probe    read only: the protocol the serial engine's firmware runs (must be I2C), whether its FIFO interface is
//            enabled, whether a command is active, and the clock and SCL configuration the firmware left.
//   transfer a list of messages (write, read, or write then read with a repeated start), each one M_CMD0 with the
//            target address; TX words written on the TX watermark, RX words read on the RX watermark or last word;
//            address NACK, data NACK (told apart by M_GP_LENGTH, as Linux does), bus and arbitration errors from the
//            GP IRQs; a command that does not finish is cancelled, then aborted.
// It does not touch clocks, pins, GPI DMA or the packing configuration: those are the firmware's (geni_se_init and
// geni_se_config_packing in Linux). geni_i2c_check_clock() refuses a bus whose SCL counters are not the expected
// ones, so a transfer never runs at an unknown speed.
#ifndef PIPA_GENI_I2C_CORE_H
#define PIPA_GENI_I2C_CORE_H
#include <stdint.h>
#include <stddef.h>

// Registers (geni-se.h, qcom-geni-se.c, i2c-qcom-geni.c)
#define GENI_STATUS 0x040u
#define GENI_SER_M_CLK_CFG 0x048u
#define GENI_IF_DISABLE_RO 0x064u
#define GENI_FW_REVISION_RO 0x068u
#define GENI_CLK_SEL 0x07cu
#define GENI_BYTE_GRAN 0x254u
#define GENI_DMA_MODE_EN 0x258u
#define GENI_TX_PACKING_CFG0 0x260u
#define GENI_TX_PACKING_CFG1 0x264u
#define GENI_I2C_TX_TRANS_LEN 0x26cu
#define GENI_I2C_RX_TRANS_LEN 0x270u
#define GENI_I2C_SCL_COUNTERS 0x278u
#define GENI_RX_PACKING_CFG0 0x284u
#define GENI_RX_PACKING_CFG1 0x288u
#define GENI_M_CMD0 0x600u
#define GENI_M_CMD_CTRL 0x604u
#define GENI_M_IRQ_STATUS 0x610u
#define GENI_M_IRQ_EN 0x614u
#define GENI_M_IRQ_CLEAR 0x618u
#define GENI_TX_FIFO 0x700u
#define GENI_RX_FIFO 0x780u
#define GENI_TX_FIFO_STATUS 0x800u
#define GENI_RX_FIFO_STATUS 0x804u
#define GENI_TX_WATERMARK 0x80cu
#define GENI_M_GP_LENGTH 0x910u
#define GENI_HW_PARAM_0 0xe24u

// Fields
#define GENI_M_CMD_ACTIVE (1u << 0)
#define GENI_FIFO_IF_DISABLE (1u << 0)
#define GENI_FW_PROTOCOL_MASK 0x0000ff00u
#define GENI_FW_PROTOCOL_SHIFT 8
#define GENI_FW_PROTOCOL(v) (((v) & GENI_FW_PROTOCOL_MASK) >> GENI_FW_PROTOCOL_SHIFT)
#define GENI_PROTOCOL_I2C 3u                    // enum geni_se_protocol_type: NONE, SPI, UART, I2C
#define GENI_SER_CLK_EN (1u << 0)
#define GENI_CLK_DIV_MASK 0x0000fff0u
#define GENI_CLK_DIV_SHIFT 4
#define GENI_SCL_HIGH_MASK 0x3ff00000u
#define GENI_SCL_HIGH_SHIFT 20
#define GENI_SCL_LOW_MASK 0x000ffc00u
#define GENI_SCL_LOW_SHIFT 10
#define GENI_SCL_CYCLE_MASK 0x000003ffu
#define GENI_TX_FIFO_DEPTH_MASK 0x003f0000u
#define GENI_TX_FIFO_DEPTH_SHIFT 16
#define GENI_TX_FIFO_DEPTH(v) (((v) & GENI_TX_FIFO_DEPTH_MASK) >> GENI_TX_FIFO_DEPTH_SHIFT)
#define GENI_RX_FIFO_WC_MASK 0x01ffffffu
#define GENI_RX_FIFO_WC(v) ((v) & GENI_RX_FIFO_WC_MASK)
#define GENI_RX_LAST (1u << 31)
#define GENI_M_CMD_ABORT (1u << 1)
#define GENI_M_CMD_CANCEL (1u << 2)

// M_IRQ bits
#define GENI_M_CMD_DONE (1u << 0)
#define GENI_M_CMD_OVERRUN (1u << 1)
#define GENI_M_ILLEGAL_CMD (1u << 2)
#define GENI_M_CMD_FAILURE (1u << 3)
#define GENI_M_CMD_CANCEL_IRQ (1u << 4)
#define GENI_M_CMD_ABORT_IRQ (1u << 5)
#define GENI_M_GP_IRQ_0 (1u << 9)
#define GENI_M_GP_IRQ_1 (1u << 10)      // address NACK (or data NACK on a write)
#define GENI_M_GP_IRQ_3 (1u << 12)      // bus protocol error
#define GENI_M_GP_IRQ_4 (1u << 13)      // arbitration lost
#define GENI_M_RX_FIFO_WATERMARK (1u << 26)
#define GENI_M_RX_FIFO_LAST (1u << 27)
#define GENI_M_TX_FIFO_WATERMARK (1u << 30)
#define GENI_I2C_ERR_BITS (GENI_M_CMD_OVERRUN | GENI_M_ILLEGAL_CMD | GENI_M_CMD_FAILURE | GENI_M_GP_IRQ_1 | \
                           GENI_M_GP_IRQ_3 | GENI_M_GP_IRQ_4)

// I2C commands and parameters (i2c-qcom-geni.c)
#define GENI_I2C_WRITE 0x1u
#define GENI_I2C_READ 0x2u
#define GENI_I2C_STOP_STRETCH (1u << 2)
#define GENI_I2C_ADDR_MASK 0x0000fe00u
#define GENI_I2C_ADDR_SHIFT 9
#define GENI_I2C_ADDR(a) (((uint32_t)(a) << GENI_I2C_ADDR_SHIFT) & GENI_I2C_ADDR_MASK)
#define GENI_M_OPCODE_SHIFT 27
#define GENI_M_PARAMS_MASK 0x07ffffffu
#define GENI_M_CMD(op, params) (((uint32_t)(op) << GENI_M_OPCODE_SHIFT) | ((params) & GENI_M_PARAMS_MASK))

typedef enum {
    GENI_I2C_OK = 0,
    GENI_I2C_NOT_I2C,        // the serial engine's firmware runs another protocol (or none)
    GENI_I2C_FIFO_DISABLED,  // FIFO interface disabled: the engine is owned by GPI DMA or another execution environment
    GENI_I2C_BUSY,           // a command was active before ours
    GENI_I2C_CLOCK,          // SCL counters or divider are not the expected ones
    GENI_I2C_ADDR_NACK,
    GENI_I2C_DATA_NACK,
    GENI_I2C_BUS_ERROR,
    GENI_I2C_ARB_LOST,
    GENI_I2C_FAILURE,        // overrun, illegal command or command failure
    GENI_I2C_TIMEOUT,
    GENI_I2C_INVALID,        // bad arguments
    GENI_I2C_READ_ONLY,      // a write refused by the caller's policy (Ktz8866Driver.h)
} GeniI2cStatus;

typedef struct {
    uint32_t (*read32)(void *ctx, uint32_t offset);
    void (*write32)(void *ctx, uint32_t offset, uint32_t value);
    void (*delay_us)(void *ctx, unsigned us);
    void *ctx;
    unsigned poll_us;        // delay between status reads
    unsigned timeout_polls;  // per message
} GeniI2c;

typedef struct {
    uint32_t fw_revision, status, if_disable, m_clk_cfg, clk_sel, scl_counters, hw_param0;
    unsigned protocol, tx_fifo_depth;
} GeniI2cInfo;

typedef struct {
    uint8_t addr;            // 7-bit
    uint8_t read;            // 1: read len bytes into buf
    uint16_t len;
    uint8_t *buf;
} GeniI2cMsg;

typedef struct {
    uint32_t source_hz, bus_hz;
    uint16_t clk_div, t_high, t_low, t_cycle;
} GeniI2cScl;

// The SCL tables for a 19.2 MHz and a 32 MHz serial engine clock (i2c-qcom-geni.c geni_i2c_clk_map_*).
static const GeniI2cScl geni_i2c_scl_table[] = {
    {19200000u, 100000u, 7, 10, 12, 26}, {19200000u, 400000u, 2, 5, 11, 22}, {19200000u, 1000000u, 1, 2, 8, 18},
    {32000000u, 100000u, 12, 9, 10, 26}, {32000000u, 400000u, 4, 3, 9, 19}, {32000000u, 1000000u, 2, 3, 5, 15},
};

static inline const GeniI2cScl *geni_i2c_scl_lookup(uint32_t source_hz, uint32_t bus_hz) {
    for (size_t i = 0; i < sizeof(geni_i2c_scl_table) / sizeof(geni_i2c_scl_table[0]); i++)
        if (geni_i2c_scl_table[i].source_hz == source_hz && geni_i2c_scl_table[i].bus_hz == bus_hz)
            return &geni_i2c_scl_table[i];
    return NULL;
}

static inline uint32_t geni_i2c_scl_counters(const GeniI2cScl *s) {
    return ((uint32_t)s->t_high << GENI_SCL_HIGH_SHIFT & GENI_SCL_HIGH_MASK) |
           ((uint32_t)s->t_low << GENI_SCL_LOW_SHIFT & GENI_SCL_LOW_MASK) | (s->t_cycle & GENI_SCL_CYCLE_MASK);
}

static inline uint32_t geni_i2c_m_clk_cfg(const GeniI2cScl *s) {
    return ((uint32_t)s->clk_div << GENI_CLK_DIV_SHIFT & GENI_CLK_DIV_MASK) | GENI_SER_CLK_EN;
}

// Read only.
static inline GeniI2cStatus geni_i2c_probe(const GeniI2c *g, GeniI2cInfo *info) {
    info->fw_revision = g->read32(g->ctx, GENI_FW_REVISION_RO);
    info->status = g->read32(g->ctx, GENI_STATUS);
    info->if_disable = g->read32(g->ctx, GENI_IF_DISABLE_RO);
    info->m_clk_cfg = g->read32(g->ctx, GENI_SER_M_CLK_CFG);
    info->clk_sel = g->read32(g->ctx, GENI_CLK_SEL);
    info->scl_counters = g->read32(g->ctx, GENI_I2C_SCL_COUNTERS);
    info->hw_param0 = g->read32(g->ctx, GENI_HW_PARAM_0);
    info->protocol = GENI_FW_PROTOCOL(info->fw_revision);
    info->tx_fifo_depth = GENI_TX_FIFO_DEPTH(info->hw_param0);
    if (info->protocol != GENI_PROTOCOL_I2C)
        return GENI_I2C_NOT_I2C;
    if (info->if_disable & GENI_FIFO_IF_DISABLE)
        return GENI_I2C_FIFO_DISABLED;
    if (info->status & GENI_M_CMD_ACTIVE)
        return GENI_I2C_BUSY;
    return GENI_I2C_OK;
}

// Read only: the divider must have the serial clock on and the counters must be the table's for (source_hz, bus_hz).
static inline GeniI2cStatus geni_i2c_check_clock(const GeniI2cInfo *info, uint32_t source_hz, uint32_t bus_hz) {
    const GeniI2cScl *s = geni_i2c_scl_lookup(source_hz, bus_hz);
    if (!s)
        return GENI_I2C_INVALID;
    if (info->m_clk_cfg != geni_i2c_m_clk_cfg(s) || info->scl_counters != geni_i2c_scl_counters(s))
        return GENI_I2C_CLOCK;
    return GENI_I2C_OK;
}

// gp_length: M_GP_LENGTH at the error, the bytes the command moved; 0 means the address itself was not acknowledged.
static inline GeniI2cStatus geni_i2c_error(uint32_t m_irq, uint32_t gp_length) {
    if (m_irq & GENI_M_GP_IRQ_1)
        return gp_length ? GENI_I2C_DATA_NACK : GENI_I2C_ADDR_NACK;
    if (m_irq & GENI_M_GP_IRQ_3)
        return GENI_I2C_BUS_ERROR;
    if (m_irq & GENI_M_GP_IRQ_4)
        return GENI_I2C_ARB_LOST;
    return GENI_I2C_FAILURE;
}

// Cancel then abort a command that did not finish (Linux: geni_i2c_cancel_xfer, geni_i2c_abort_xfer).
static inline void geni_i2c_stop(const GeniI2c *g) {
    g->write32(g->ctx, GENI_TX_WATERMARK, 0);
    g->write32(g->ctx, GENI_M_CMD_CTRL, GENI_M_CMD_CANCEL);
    for (unsigned i = 0; i < g->timeout_polls; i++) {
        if (g->read32(g->ctx, GENI_M_IRQ_STATUS) & GENI_M_CMD_CANCEL_IRQ)
            break;
        g->delay_us(g->ctx, g->poll_us);
    }
    if (g->read32(g->ctx, GENI_STATUS) & GENI_M_CMD_ACTIVE)
        g->write32(g->ctx, GENI_M_CMD_CTRL, GENI_M_CMD_ABORT);
    g->write32(g->ctx, GENI_M_IRQ_CLEAR, 0xffffffffu);
}

// One message. stretch: hold the bus (no STOP) for the next message, giving a repeated start.
static inline GeniI2cStatus geni_i2c_one(const GeniI2c *g, const GeniI2cMsg *m, int stretch) {
    uint32_t params = GENI_I2C_ADDR(m->addr) | (stretch ? GENI_I2C_STOP_STRETCH : 0);
    unsigned done = 0;
    g->write32(g->ctx, GENI_M_IRQ_CLEAR, 0xffffffffu);
    g->write32(g->ctx, GENI_DMA_MODE_EN, 0);                         // FIFO mode
    if (m->read) {
        g->write32(g->ctx, GENI_I2C_RX_TRANS_LEN, m->len);
        g->write32(g->ctx, GENI_M_CMD0, GENI_M_CMD(GENI_I2C_READ, params));
    } else {
        g->write32(g->ctx, GENI_I2C_TX_TRANS_LEN, m->len);
        g->write32(g->ctx, GENI_M_CMD0, GENI_M_CMD(GENI_I2C_WRITE, params));
        g->write32(g->ctx, GENI_TX_WATERMARK, m->len ? 1 : 0);       // a TX watermark IRQ while the FIFO has room
    }
    for (unsigned polls = 0; polls < g->timeout_polls; polls++) {
        uint32_t irq = g->read32(g->ctx, GENI_M_IRQ_STATUS);
        if (irq & GENI_I2C_ERR_BITS) {
            g->write32(g->ctx, GENI_TX_WATERMARK, 0);
            g->write32(g->ctx, GENI_M_IRQ_CLEAR, irq);
            GeniI2cStatus err = geni_i2c_error(irq, g->read32(g->ctx, GENI_M_GP_LENGTH));
            if (!(irq & GENI_M_CMD_DONE))
                geni_i2c_stop(g);
            return err;
        }
        if (m->read && (irq & (GENI_M_RX_FIFO_WATERMARK | GENI_M_RX_FIFO_LAST))) {
            uint32_t words = GENI_RX_FIFO_WC(g->read32(g->ctx, GENI_RX_FIFO_STATUS));
            for (uint32_t w = 0; w < words; w++) {
                uint32_t v = g->read32(g->ctx, GENI_RX_FIFO);
                for (unsigned b = 0; b < 4 && done < m->len; b++, v >>= 8)
                    m->buf[done++] = (uint8_t)v;
            }
        }
        if (!m->read && (irq & GENI_M_TX_FIFO_WATERMARK) && done < m->len) {
            uint32_t v = 0;
            for (unsigned b = 0; b < 4 && done < m->len; b++)
                v |= (uint32_t)m->buf[done++] << (8 * b);
            g->write32(g->ctx, GENI_TX_FIFO, v);
            if (done == m->len)
                g->write32(g->ctx, GENI_TX_WATERMARK, 0);
        }
        if (irq)
            g->write32(g->ctx, GENI_M_IRQ_CLEAR, irq);
        if (irq & GENI_M_CMD_DONE)
            return done == m->len ? GENI_I2C_OK : GENI_I2C_FAILURE;
        g->delay_us(g->ctx, g->poll_us);
    }
    geni_i2c_stop(g);
    return GENI_I2C_TIMEOUT;
}

static inline GeniI2cStatus geni_i2c_transfer(const GeniI2c *g, const GeniI2cMsg *msgs, unsigned count) {
    if (!g || !msgs || count == 0)
        return GENI_I2C_INVALID;
    for (unsigned i = 0; i < count; i++) {
        if (msgs[i].len && !msgs[i].buf)
            return GENI_I2C_INVALID;
        GeniI2cStatus s = geni_i2c_one(g, &msgs[i], i + 1 < count);
        if (s != GENI_I2C_OK)
            return s;
    }
    return GENI_I2C_OK;
}

// 8-bit register helpers for devices with one address byte (the KTZ8866).
static inline GeniI2cStatus geni_i2c_read_reg(const GeniI2c *g, uint8_t addr, uint8_t reg, uint8_t *value) {
    GeniI2cMsg m[2] = {{addr, 0, 1, &reg}, {addr, 1, 1, value}};
    return geni_i2c_transfer(g, m, 2);
}

static inline GeniI2cStatus geni_i2c_write_reg(const GeniI2c *g, uint8_t addr, uint8_t reg, uint8_t value) {
    uint8_t b[2] = {reg, value};
    GeniI2cMsg m = {addr, 0, 2, b};
    return geni_i2c_transfer(g, &m, 1);
}

static inline const char *geni_i2c_status_name(GeniI2cStatus s) {
    static const char *const names[] = {"ok", "not-i2c", "fifo-disabled", "busy", "clock", "addr-nack", "data-nack",
                                        "bus-error", "arb-lost", "failure", "timeout", "invalid", "read-only"};
    return (unsigned)s < sizeof(names) / sizeof(names[0]) ? names[s] : "?";
}

#endif
