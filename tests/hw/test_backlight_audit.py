"""Static audit of the KTZ8866 backlight shim (devices/pipa/package/PipaBacklight.c and what it calls): every write it can
make, read from the source. Complements PipaBacklightTests.c, which runs the shim on a simulated tablet and counts writes;
this proves from the code that no path exists to write a GCC, TLMM or KTZ8866 register or the engine's configuration.

  - PipaBacklight.c writes only through se_write, the GENI callback; the GCC and TLMM windows are only read (pipa_rd);
  - GeniI2cCore.h writes only the engine's transfer registers (command, IRQ clear, transfer lengths, TX FIFO and its
    watermark), never its clock, SCL counters, packing, pins or DMA mode;
  - Ktz8866Driver.h: every KTZ8866 register write goes through ktz_write, which refuses while allow_writes is 0; ktz_pipa
    leaves it 0 and nothing in PipaBacklight.c sets it; ktz_attach only probes and reads DEVICE_ID.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import re
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "devices/pipa/package"
TRANSFER_REGISTERS = {"GENI_TX_WATERMARK", "GENI_M_CMD_CTRL", "GENI_M_IRQ_CLEAR", "GENI_I2C_RX_TRANS_LEN",
                      "GENI_I2C_TX_TRANS_LEN", "GENI_M_CMD0", "GENI_TX_FIFO"}


def strip_comments(text):
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def function_body(text, name):
    m = re.search(rf"\b{re.escape(name)}\s*\([^)]*\)\s*\{{", text)
    if not m:
        raise LookupError(name)
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


class Shim(unittest.TestCase):
    def setUp(self):
        self.shim = strip_comments((PKG / "PipaBacklight.c").read_text())

    def test_writes_only_through_the_engine_callback(self):
        calls = re.findall(r"\bpipa_wr\s*\(([^;]*)\);", self.shim)
        self.assertEqual(calls, ["(volatile uint32_t *)ctx, off, v"])          # se_write's, and nothing else
        self.assertIn("pipa_wr", function_body(self.shim, "se_write"))
        for window in ("gcc", "pins[i]", "pins"):
            self.assertNotRegex(self.shim, rf"pipa_wr\s*\(\s*{re.escape(window)}\b")
        # The GCC and pin windows go only to the read helper.
        self.assertRegex(self.shim, r"rd\(gcc, GIB_GCC_VOTE\)")
        self.assertRegex(self.shim, r"rd\(pins\[i\], 0\)")
        # The engine window handed to GeniI2c is se; the GCC and TLMM ones never reach a GeniI2c.
        self.assertRegex(self.shim, r"GeniI2c bus = \{se_read, se_write, se_delay, \(void \*\)se,")

    def test_no_direct_register_store(self):
        # No `base[...] =` or `*p =` store into a mapped window in the shim itself.
        self.assertNotRegex(self.shim, r"\b(gcc|se|pins\[[^\]]+\])\s*\[[^\]]*\]\s*=")
        self.assertNotRegex(self.shim, r"\*\s*\(?\s*(gcc|se)\b[^;=]*=[^=]")

    def test_writes_to_the_chip_stay_locked(self):
        self.assertNotIn("allow_writes", re.sub(r"ktz_pipa\(&bus\);", "", self.shim))
        self.assertIn("ktz_attach(&k)", self.shim)
        for forbidden in ("ktz_write", "ktz_init", "ktz_set"):
            self.assertNotIn(forbidden, self.shim)

    def test_kernel_store_is_the_platform_helper(self):
        platform = strip_comments((PKG / "PipaBacklightPlatform.h").read_text())
        kernel = platform[platform.index("#ifdef KERNEL"):platform.index("#else")]
        self.assertEqual(re.findall(r"base\[off / 4\] = v", kernel), ["base[off / 4] = v"])   # pipa_wr's, once


class Engine(unittest.TestCase):
    def test_transfer_registers_only(self):
        core = strip_comments((PKG / "GeniI2cCore.h").read_text())
        written = set(re.findall(r"write32\(g->ctx,\s*(GENI_[A-Z0-9_]+)", core))
        self.assertTrue(written)
        self.assertLessEqual(written, TRANSFER_REGISTERS, written - TRANSFER_REGISTERS)
        for config in ("GENI_DMA_MODE_EN", "GENI_SER_M_CLK_CFG", "GENI_CLK_SEL", "GENI_I2C_SCL_COUNTERS",
                       "GENI_TX_PACKING_CFG0", "GENI_TX_PACKING_CFG1", "GENI_RX_PACKING_CFG0", "GENI_RX_PACKING_CFG1"):
            self.assertIn(f"#define {config} ", core)                            # the register exists in the header ...
            self.assertNotIn(config, written)                                      # ... and is never written
        # Every write32 names its register directly (no computed offset that this audit could not see).
        self.assertEqual(len(re.findall(r"write32\(", core)), len(re.findall(r"write32\(g->ctx,\s*GENI_[A-Z0-9_]+", core)))


class Chip(unittest.TestCase):
    def test_every_register_write_is_gated(self):
        ktz = strip_comments((PKG / "Ktz8866Driver.h").read_text())
        writers = [m.start() for m in re.finditer(r"geni_i2c_write_reg\(", ktz)]
        self.assertEqual(len(writers), 1)                                         # in ktz_write only
        body = function_body(ktz, "ktz_write")
        self.assertIn("geni_i2c_write_reg(", body)
        self.assertLess(body.index("if (!k->allow_writes)"), body.index("geni_i2c_write_reg("))
        self.assertIn("return GENI_I2C_READ_ONLY;", body)
        self.assertNotIn("allow_writes", function_body(ktz, "ktz_pipa"))           # {0}: locked
        attach = function_body(ktz, "ktz_attach")
        self.assertNotIn("write", attach.replace("geni_i2c_read_reg", ""))


if __name__ == "__main__":
    unittest.main()
