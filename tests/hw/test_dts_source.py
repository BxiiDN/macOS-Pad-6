"""tools/hw/dts_source.py on device tree source written in the test: labels, &label blocks before and after their
definition, /delete-*/, cells with references, macros and expressions, strings, byte strings, preprocessor lines and
unexpanded macro statements; and scripts/pipa_hw.py's struct_array.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tools.hw.dts_source import DtsError, Source  # noqa: E402
import pipa_hw  # noqa: E402

BASE = r"""
/dts-v1/;
#include <dt-bindings/interrupt-controller/arm-gic.h>
#define LOCAL 3
&soc {
	qupv3_se4_spi: spi@990000 {
		compatible = "qcom,spi-geni";
		reg = <0x990000 0x4000>;
		interrupts = <GIC_SPI 604 IRQ_TYPE_LEVEL_HIGH>;
		status = "disabled";
	};
	table: opp-table {
		BW_OPP_ENTRY(  150, 16); /* a macro statement */
	};
};
"""

BOARD = r"""
&early { early-prop = <1>; };          // a block before its label is defined
&qupv3_se4_spi {
	status = "ok";
	#address-cells = <1>;
	novatek@0 {
		compatible = "novatek,NVT-ts-spi";
		reg = <0>;
		novatek,irq-gpio = <&tlmm 39 0x2001>;
		novatek,cfg_0 { novatek,display-maker = <0x42>; };
		dropped = <1>;
		/delete-property/ dropped;
	};
	gone { x; };
	/delete-node/ gone;
};
/ {
	early: late-node { own = "here"; };
	panel {
		seq = <0 10>, <1 3>;
		expr = <(1 << 4) (-600) (MACRO + 1)>;
		cmd = [06 01 00 00
		       00 00 01 0A];   // a byte string across lines
		mixed = "a", <2>, [ff];
		flag;
		str = "esc\"aped // not a comment";
		bits = /bits/ 16 <0x145 0x4F>;
	};
};
"""


class DtsSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = Source()
        self.src.parse(BASE, "base.dtsi")
        self.src.parse(BOARD, "board.dtsi")

    def test_label_merge(self):
        spi = self.src.label("qupv3_se4_spi")
        self.assertEqual(spi.u32s("reg"), [0x990000, 0x4000])
        self.assertEqual(spi.strings("status"), ["ok"])           # the board block overrides the base
        self.assertTrue(spi.enabled())
        self.assertEqual(spi.cells("interrupts"), ["GIC_SPI", 604, "IRQ_TYPE_LEVEL_HIGH"])   # macros kept as names
        self.assertEqual(spi.path, "&soc/spi@990000")

    def test_children_and_deletes(self):
        nvt = self.src.label("qupv3_se4_spi").child("novatek")
        self.assertEqual(nvt.cells("novatek,irq-gpio"), ["&tlmm", 39, 0x2001])
        self.assertNotIn("dropped", nvt.props)
        self.assertNotIn("gone", self.src.label("qupv3_se4_spi").children)
        self.assertEqual(nvt.child("novatek,cfg_0").u32("novatek,display-maker"), 0x42)
        with self.assertRaises(LookupError):
            nvt.child("missing")

    def test_block_before_definition(self):
        node = self.src.label("early")
        self.assertEqual(node.string("own"), "here")
        self.assertEqual(node.u32("early-prop"), 1)
        self.assertEqual(node.path, "/late-node")

    def test_values(self):
        panel = self.src.root.child("panel")
        self.assertEqual(panel.groups("seq"), [[0, 10], [1, 3]])
        self.assertEqual(panel.cells("expr"), [16, -600, "(MACRO + 1)"])
        self.assertEqual(panel.bytes("cmd"), bytes.fromhex("060100000000010a"))
        self.assertEqual(panel.parts("mixed"), [("str", "a"), ("cells", [2]), ("bytes", b"\xff")])
        self.assertTrue(panel.flag("flag"))
        self.assertEqual(panel.string("str"), 'esc"aped // not a comment')
        self.assertEqual(panel.u32s("bits"), [0x145, 0x4F])
        with self.assertRaises(DtsError):
            panel.u32("seq")                                       # four cells, not one
        with self.assertRaises(DtsError):
            panel.u32s("expr")                                     # a macro cell is not an integer

    def test_macro_statement_and_missing_label(self):
        self.assertEqual(self.src.label("table").macros, ["BW_OPP_ENTRY(  150, 16)"])
        with self.assertRaises(LookupError):
            self.src.label("nowhere")

    def test_detached_label(self):
        src = Source()
        src.parse("&qupv3_se11_i2c { status = \"ok\"; ktz8866@11 { reg = <0x11>; }; };", "board.dtsi")
        node = src.label("qupv3_se11_i2c")
        self.assertEqual(node.child("ktz8866").u32("reg"), 0x11)

    def test_errors(self):
        for bad in ("/ { a = <1> }", "/ { a = <1 ; };", "/ { a = [0]; };", "/ { ? = ; };", "/ { a = <1>;"):
            with self.assertRaises(DtsError, msg=bad):
                Source().parse(bad, "bad.dts")


class StructArray(unittest.TestCase):
    def test_rows(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.h"
            p.write_text("static const T seq[] = {{0, 10}, {1, 0x3u}};\n")
            self.assertEqual(pipa_hw.struct_array(p, "seq"), [[0, 10], [1, 3]])
            with self.assertRaises(KeyError):
                pipa_hw.struct_array(p, "other")


if __name__ == "__main__":
    unittest.main()
