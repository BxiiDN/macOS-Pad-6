"""The C #define reader of scripts/pipa_hw.py drivers, on sources written in the test, and the repository's own
GENI and KTZ8866 headers through it (their values, not Linux's: the comparison with Linux runs in CI).

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_hw  # noqa: E402

SOURCE = r"""
#define PLAIN 0x600
#define SUFFIXED 0x00a8c000ULL   // trailing comment
#define BITS BIT(10)
#define MASK GENMASK(15, 9)
#define SHIFTED (1u << 27)
#define COMBINED (BITS | SHIFTED | \
                  BIT(0))
#define FUNCLIKE(v) ((v) << 2)
#define STRINGY "text"
enum proto {
	P_NONE,
	P_SPI, /* one */
	P_I2C,
	P_BIG = 0x40,
	P_NEXT,
};
static const struct { int a, b, c, d, e; } geni_i2c_clk_map_19p2mhz[] = {
	{ I2C_FAST, 2, 5, 11, 22 },
	{}
};
static const struct { int a, b, c, d, e; } geni_i2c_clk_map_32mhz[] = {
	{ I2C_FAST, 4, 3, 9, 19 },
	{}
};
"""


class DefineReader(unittest.TestCase):
    def setUp(self):
        self.defs = pipa_hw.c_defines(SOURCE)

    def test_values(self):
        ev = lambda n: pipa_hw.c_eval(self.defs[n], self.defs)
        self.assertEqual(ev("PLAIN"), 0x600)
        self.assertEqual(ev("SUFFIXED"), 0xa8c000)
        self.assertEqual(ev("BITS"), 1 << 10)
        self.assertEqual(ev("MASK"), 0xfe00)
        self.assertEqual(ev("SHIFTED"), 1 << 27)
        self.assertEqual(ev("COMBINED"), (1 << 10) | (1 << 27) | 1)

    def test_skips_function_like_and_rejects_non_integers(self):
        self.assertNotIn("FUNCLIKE", self.defs)
        with self.assertRaises(ValueError):
            pipa_hw.c_eval(self.defs["STRINGY"], self.defs)
        with self.assertRaises(ValueError):
            pipa_hw.c_eval("UNKNOWN_NAME | 1", self.defs)
        with self.assertRaises(ValueError):
            pipa_hw.c_eval("__import__('os')", {})
        with self.assertRaises(ValueError):
            pipa_hw.c_eval("abc | 1", {})            # a name made of hex letters is still a name

    def test_enum(self):
        self.assertEqual(pipa_hw.c_enum_index(SOURCE, "proto", "P_I2C"), 2)
        self.assertEqual(pipa_hw.c_enum_index(SOURCE, "proto", "P_NEXT"), 0x41)
        with self.assertRaises(KeyError):
            pipa_hw.c_enum_index(SOURCE, "proto", "P_MISSING")

    def test_scl_tables(self):
        texts = {"i2c-qcom-geni.c": SOURCE}
        rows = pipa_hw.linux_scl_tables(texts, {"I2C_FAST": "400000"})
        self.assertEqual(rows, [[19200000, 400000, 2, 5, 11, 22], [32000000, 400000, 4, 3, 9, 19]])


class RepositoryHeaders(unittest.TestCase):
    """The repository side of every pair the drivers check compares resolves to an integer."""

    def test_pairs_resolve(self):
        headers = {h: pipa_hw.c_defines((pipa_hw.PKG / h).read_text()) for h in ("GeniI2cCore.h", "BacklightBoard.h")}
        for header, ours, src, theirs in pipa_hw.GENI_PAIRS + pipa_hw.KTZ_PAIRS:
            self.assertIn(src, pipa_hw.LINUX_DRIVERS)
            self.assertIsInstance(pipa_hw.c_eval(headers[header][ours], headers[header]), int, ours)

    def test_scl_table(self):
        rows = pipa_hw.repo_scl_table(pipa_hw.PKG / "GeniI2cCore.h")
        self.assertIn([19200000, 400000, 2, 5, 11, 22], rows)
        self.assertEqual(len(rows), 6)

    def test_driver_facts_on_a_copy(self):
        """driver_facts against a fake Linux tree made of the repository's own values: all match, and a changed
        value is reported as a mismatch, not silently accepted."""
        with tempfile.TemporaryDirectory() as d:
            core = pipa_hw.c_defines((pipa_hw.PKG / "GeniI2cCore.h").read_text())
            bkl = pipa_hw.c_defines((pipa_hw.PKG / "BacklightBoard.h").read_text())
            files = {k: [] for k in pipa_hw.LINUX_DRIVERS}
            for header, ours, src, theirs in pipa_hw.GENI_PAIRS + pipa_hw.KTZ_PAIRS:
                defs = core if header == "GeniI2cCore.h" else bkl
                files[src].append(f"#define {theirs} {pipa_hw.c_eval(defs[ours], defs)}")
            files["geni-se.h"].append("enum geni_se_protocol_type { GENI_SE_NONE, GENI_SE_SPI, GENI_SE_UART, GENI_SE_I2C, };")
            rows = pipa_hw.repo_scl_table(pipa_hw.PKG / "GeniI2cCore.h")
            for hz, name in ((19200000, "19p2mhz"), (32000000, "32mhz")):
                body = "".join(f"\t{{ {r[1]}, {r[2]}, {r[3]}, {r[4]}, {r[5]} }},\n" for r in rows if r[0] == hz)
                files["i2c-qcom-geni.c"].append(f"static const struct x geni_i2c_clk_map_{name}[] = {{\n{body}\t{{}}\n}};")
            for k, rel in pipa_hw.LINUX_DRIVERS.items():
                p = Path(d) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(files[k]) + "\n")
            facts = pipa_hw.driver_facts(d)
            self.assertTrue(all(r["result"] == "match" for r in facts), [r for r in facts if r["result"] != "match"])
            p = Path(d) / pipa_hw.LINUX_DRIVERS["ktz8866.c"]
            p.write_text(p.read_text().replace("#define BL_EN 8", "#define BL_EN 9"))
            bad = [r["fact"] for r in pipa_hw.driver_facts(d) if r["result"] != "match"]
            self.assertEqual(bad, ["BKL_REG_EN"])


if __name__ == "__main__":
    unittest.main()
