"""tools/hw/fdt.py and the helpers of scripts/pipa_hw.py on device trees built in the test.

The trees are written as FDT bytes here (no dtc needed): nodes, properties, phandles, nested ranges, a GIC, an
SPMI arbiter whose child names no interrupt-parent, interrupts-extended and /__symbols__.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tools.hw.fdt import Tree  # noqa: E402
import pipa_hw  # noqa: E402


def u32(*v):
    return struct.pack(f">{len(v)}I", *v)


def s(*v):
    return b"".join(x.encode() + b"\0" for x in v)


def fdt(tree):
    """tree: (name, {prop: bytes}, [children]) -> FDT version 17 blob."""
    strings, offsets, body = bytearray(), {}, bytearray()

    def name_off(n):
        if n not in offsets:
            offsets[n] = len(strings)
            strings.extend(n.encode() + b"\0")
        return offsets[n]

    def emit(node):
        name, props, children = node
        body.extend(u32(1))
        raw = name.encode() + b"\0"
        body.extend(raw + b"\0" * (-len(raw) % 4))
        for key, value in props.items():
            body.extend(u32(3, len(value), name_off(key)))
            body.extend(value + b"\0" * (-len(value) % 4))
        for child in children:
            emit(child)
        body.extend(u32(2))

    emit(tree)
    body.extend(u32(9))
    header_size, rsv = 40, 16
    off_struct = header_size + rsv
    off_strings = off_struct + len(body)
    total = off_strings + len(strings)
    header = u32(0xd00dfeed, total, off_struct, off_strings, header_size, 17, 16, 0, len(strings), len(body))
    return header + b"\0" * rsv + bytes(body) + bytes(strings)


GIC, SPMI, GCC, SMMU = 1, 2, 3, 4
TREE = ("", {"#address-cells": u32(2), "#size-cells": u32(2), "interrupt-parent": u32(GIC),
             "model": s("test")}, [
    ("cpus", {"#address-cells": u32(2), "#size-cells": u32(0)}, [
        ("cpu@0", {"reg": u32(0, 0)}, []), ("cpu@100", {"reg": u32(0, 0x100)}, [])]),
    ("soc@0", {"#address-cells": u32(2), "#size-cells": u32(2), "ranges": u32(0, 0, 0, 0, 0x10, 0)}, [
        ("interrupt-controller@17a00000", {"compatible": s("arm,gic-v3"), "interrupt-controller": b"",
                                           "#interrupt-cells": u32(3), "phandle": u32(GIC),
                                           "reg": u32(0, 0x17a00000, 0, 0x10000, 0, 0x17a60000, 0, 0x100000)}, []),
        ("clock-controller@100000", {"compatible": s("qcom,gcc-sm8250"), "#clock-cells": u32(1),
                                     "#power-domain-cells": u32(1), "phandle": u32(GCC),
                                     "reg": u32(0, 0x100000, 0, 0x1f0000)}, []),
        ("iommu@15000000", {"#iommu-cells": u32(2), "phandle": u32(SMMU), "reg": u32(0, 0x15000000, 0, 0x100000)}, []),
        # A bus with its own ranges: child address 0x1000 is CPU 0x3d01000.
        ("bus@3d00000", {"#address-cells": u32(1), "#size-cells": u32(1), "ranges": u32(0, 0, 0x3d00000, 0x40000)}, [
            ("gpu@1000", {"compatible": s("qcom,adreno-650.2", "qcom,adreno"), "reg": u32(0x1000, 0x800, 0x2000, 0x100),
                          "reg-names": s("main", "aux"), "interrupts": u32(0, 300, 4),
                          "clocks": u32(GCC, 7, GCC, 9), "power-domains": u32(GCC, 2),
                          "iommus": u32(SMMU, 0, 0x401), "status": s("okay")}, [])]),
        ("spmi@c440000", {"compatible": s("qcom,spmi-pmic-arb"), "interrupt-controller": b"", "#interrupt-cells": u32(4),
                          "#address-cells": u32(2), "#size-cells": u32(0), "phandle": u32(SPMI),
                          "reg": u32(0, 0xc440000, 0, 0x1100), "interrupts": u32(1, 4, 4)}, [
            ("pmic@0", {"compatible": s("qcom,pm8150", "qcom,spmi-pmic"), "reg": u32(0, 0), "#address-cells": u32(1),
                        "#size-cells": u32(0)}, [
                ("pon@800", {"reg": u32(0x800), "interrupts": u32(0, 8, 1, 3)}, [])])]),
        ("disabled-bus", {"status": s("disabled")}, [("child", {}, [])]),
        ("dev@20000", {"reg": u32(0, 0x20000, 0, 0x100),
                       "interrupts-extended": u32(GIC, 0, 5, 4, SPMI, 0, 8, 0, 3)}, [])]),
    ("__symbols__", {"intc": s("/soc@0/interrupt-controller@17a00000"), "gcc": s("/soc@0/clock-controller@100000"),
                     "gpu": s("/soc@0/bus@3d00000/gpu@1000"), "spmi_bus": s("/soc@0/spmi@c440000"),
                     "pon": s("/soc@0/spmi@c440000/pmic@0/pon@800"), "apps_smmu": s("/soc@0/iommu@15000000")}, [])])


class FdtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = Tree.parse(fdt(TREE))

    def test_structure_and_labels(self):
        t = self.tree
        self.assertEqual(len(t.nodes), 17)
        self.assertEqual(t.label("gpu").path, "/soc@0/bus@3d00000/gpu@1000")
        self.assertEqual(t.name_of(t.label("gcc")), "gcc")
        self.assertEqual(t.label("gpu").strings("compatible"), ["qcom,adreno-650.2", "qcom,adreno"])
        self.assertIsNone(t.label("nothing"))

    def test_regs_translate_through_nested_ranges(self):
        t = self.tree
        self.assertEqual(t.regs(t.label("gpu")), [(0x3d01000, 0x800), (0x3d02000, 0x100)])
        self.assertEqual(t.reg_named(t.label("gpu"), "aux"), (0x3d02000, 0x100))
        self.assertEqual(t.regs(t.label("gpu"), translate=False), [(0x1000, 0x800), (0x2000, 0x100)])
        self.assertEqual(t.regs(t.label("intc")), [(0x17a00000, 0x10000), (0x17a60000, 0x100000)])

    def test_bus_without_ranges_is_not_cpu_visible(self):
        pon = self.tree.label("pon")
        self.assertEqual(self.tree.regs(pon), [(None, 0)])
        self.assertEqual(self.tree.regs(pon, translate=False), [(0x800, 0)])

    def test_interrupt_parent_is_the_nearest_controller(self):
        # The PMIC peripheral names no interrupt-parent; the root names the GIC. Its parent is the SPMI arbiter.
        rows = self.tree.interrupts(self.tree.label("pon"))
        self.assertEqual([(r["controller"], r["cells"]) for r in rows], [("spmi_bus", [0, 8, 1, 3])])
        self.assertNotIn("gic", rows[0])

    def test_gic_decoding(self):
        rows = self.tree.interrupts(self.tree.label("gpu"))
        self.assertEqual(rows[0]["gic"], ("SPI", 300, 332))

    def test_interrupts_extended(self):
        dev = self.tree.path("/soc@0/dev@20000")
        rows = self.tree.interrupts(dev)
        self.assertEqual([r["controller"] for r in rows], ["intc", "spmi_bus"])
        self.assertEqual(rows[0]["gic"], ("SPI", 5, 37))
        self.assertEqual(rows[1]["cells"], [0, 8, 0, 3])

    def test_phandle_lists(self):
        t = self.tree
        gpu = t.label("gpu")
        self.assertEqual([(t.name_of(p), a) for p, a in t.phandle_list(gpu, "clocks", "#clock-cells")], [("gcc", [7]), ("gcc", [9])])
        self.assertEqual([a for _, a in t.phandle_list(gpu, "iommus", "#iommu-cells")], [[0, 0x401]])

    def test_status(self):
        t = self.tree
        self.assertFalse(t.effectively_enabled(t.path("/soc@0/disabled-bus/child")))
        self.assertTrue(t.effectively_enabled(t.label("gpu")))

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            Tree.parse(b"\0" * 64)
        blob = bytearray(fdt(TREE))
        struct.pack_into(">I", blob, 20, 3)          # version 3
        with self.assertRaises(ValueError):
            Tree.parse(bytes(blob))


class HelperTest(unittest.TestCase):
    def test_smr_streams(self):
        self.assertEqual(pipa_hw.smr_streams(0, 0x401), [0, 1, 0x400, 0x401])
        self.assertEqual(pipa_hw.smr_streams(5, 0x400), [5, 0x405])
        self.assertEqual(pipa_hw.smr_streams(0x5a3, 0), [0x5a3])

    def test_ppid(self):
        self.assertEqual(pipa_hw.ppid(0, 0x800), 0x008)
        self.assertEqual(pipa_hw.ppid(0, 0xc000 + 5 * 0x100), 0x0c5)
        self.assertEqual(pipa_hw.ppid(2, 0x4000), 0x240)

    def test_macro_and_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "x.h"
            src.write_text("#define A 0x009c0000ULL\n#define  B   (0x5a3)   // stream\n#define C 9600000u /* hz */\n"
                           "#define D (0xffu << 4)\nstatic const u64 phys[3] = {0x1UL, 0x2UL, 3};\n"
                           "constexpr unsigned kSids[2] = {5, 0x405};\n")
            self.assertEqual(pipa_hw.macro(src, "A"), 0x9c0000)
            self.assertEqual(pipa_hw.macro(src, "B"), 0x5a3)
            self.assertEqual(pipa_hw.macro(src, "C"), 9600000)
            with self.assertRaises(KeyError):
                pipa_hw.macro(src, "D")                  # an expression is not taken as a value
            self.assertEqual(pipa_hw.array(src, "phys"), [1, 2, 3])
            self.assertEqual(pipa_hw.array(src, "kSids"), [5, 0x405])
            src.write_text("constexpr uint64_t kZapPhys = 0x8681a000, kZapBytes = 0x2000;  // no-map\n")
            self.assertEqual(pipa_hw.constant(src, "kZapPhys"), 0x8681a000)
            self.assertEqual(pipa_hw.constant(src, "kZapBytes"), 0x2000)
            with self.assertRaises(KeyError):
                pipa_hw.constant(src, "kMissing")

    def test_decode_binding_names(self):
        tree = Tree.parse(fdt(TREE))
        names = {"clock/qcom,gcc-sm8250.h": {7: ["GCC_GPU_CFG_AHB_CLK"], 2: ["GCC_X_GDSC", "GCC_X_CLK"],
                                             9: ["GCC_Y_BCR", "GCC_Y_CLK"]}}
        gcc = tree.label("gcc")
        self.assertEqual(pipa_hw.decode(names, gcc, [7], "clock"), "GCC_GPU_CFG_AHB_CLK")
        self.assertEqual(pipa_hw.decode(names, gcc, [9], "clock"), "GCC_Y_CLK")
        self.assertEqual(pipa_hw.decode(names, gcc, [2], "power"), "GCC_X_GDSC")
        self.assertIsNone(pipa_hw.decode(names, gcc, [42], "clock"))


if __name__ == "__main__":
    unittest.main()
