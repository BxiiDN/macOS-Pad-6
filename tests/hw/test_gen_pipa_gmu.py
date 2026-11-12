"""scripts/gen_pipa_gmu.py: the a6xx expression evaluator, the xml variant rule, the a650 path through a synthetic
a6xx_gmu_rpmh_init (and its refusal when the source's structure changes), and the A650Gmu.c cross-check, which must
report a changed constant as a mismatch.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_pipa_gmu as gg  # noqa: E402

XML_GMU = """<?xml version="1.0"?>
<database xmlns="http://nouveau.freedesktop.org/">
<domain name="A6XX" width="32">
  <reg32 offset="0x0004" name="GPU_RSCC_RSC_STATUS0_DRV0"/>
  <reg32 offset="0x000b" name="RSCC_PDC_SLAVE_ID_DRV0"/>
  <reg32 offset="0x0154" name="RSCC_SEQ_MEM_0_DRV0_A740" variants="A7XX"/>
  <reg32 offset="0x0180" name="RSCC_SEQ_MEM_0_DRV0"/>
  <reg32 offset="0x1f8f0" name="GPU_GMU_CX_GMU_CX_FAL_INTF" variants="A6XX"/>
  <reg32 offset="0x1f7ec" name="GPU_GMU_CX_GMU_CX_FAL_INTF" variants="A8XX-"/>
</domain>
</database>"""
XML_A6XX = """<?xml version="1.0"?>
<database xmlns="http://nouveau.freedesktop.org/">
<domain name="A6XX_PDC" width="32">
  <reg32 offset="0x1140" name="GPU_ENABLE_PDC"/>
  <reg32 offset="0x1148" name="GPU_SEQ_START_ADDR"/>
</domain>
</database>"""
RPMH = """
static void a6xx_gmu_rpmh_init(struct a6xx_gmu *gmu)
{
	u32 seqmem0_drv0_reg = REG_A6XX_RSCC_SEQ_MEM_0_DRV0;
	if (adreno_is_a650_family(adreno_gpu) ||
	    adreno_is_a7xx(adreno_gpu))
		pdc_in_aop = true;
	/* Disable SDE clock gating */
	gmu_write_rscc(gmu, REG_A6XX_GPU_RSCC_RSC_STATUS0_DRV0, BIT(24));
	gmu_write_rscc(gmu, REG_A6XX_RSCC_PDC_SLAVE_ID_DRV0,
		       (adreno_is_a740_family(adreno_gpu) ||
			adreno_is_a722(adreno_gpu)) ? 0x80000021 : 0x80000000);
	/* The second spin of A7xx GPUs messed with some register offsets.. */
	if (adreno_is_a740_family(adreno_gpu) || adreno_is_a722(adreno_gpu))
		seqmem0_drv0_reg = REG_A7XX_RSCC_SEQ_MEM_0_DRV0_A740;
	/* Load RSC sequencer uCode for sleep and wakeup */
	if (adreno_is_a650_family(adreno_gpu) ||
	    adreno_is_a7xx(adreno_gpu)) {
		gmu_write_rscc(gmu, seqmem0_drv0_reg, 0xeaaae5a0);
		gmu_write_rscc(gmu, seqmem0_drv0_reg + 1, 0xe1a1ebab);
	} else {
		gmu_write_rscc(gmu, REG_A6XX_RSCC_SEQ_MEM_0_DRV0, 0xa7a506a0);
	}
	if (pdc_in_aop)
		goto setup_pdc;
	pdc_write(seqptr, REG_A6XX_PDC_GPU_SEQ_MEM_0, 0xfebea1e1);
setup_pdc:
	pdc_write(pdcptr, REG_A6XX_PDC_GPU_SEQ_START_ADDR, 0);
	pdc_write(pdcptr, REG_A6XX_PDC_GPU_ENABLE_PDC, 0x80000001);
	wmb();
}
"""


def tree(d, rpmh=RPMH):
    root = Path(d)
    for name, rel in gg.SOURCES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / gg.SOURCES["a6xx_gmu.xml"]).write_text(XML_GMU)
    (root / gg.SOURCES["a6xx.xml"]).write_text(XML_A6XX)
    (root / gg.SOURCES["a6xx_gmu.c"]).write_text(rpmh)
    return root


class Evaluator(unittest.TestCase):
    def test_values(self):
        sym = {"REG_A6XX_X": 0x10, "seqmem0_drv0_reg": 0x180}
        self.assertEqual(gg.c_value("REG_A6XX_X + 4", sym), 0x14)
        self.assertEqual(gg.c_value("BIT(24)", sym), 1 << 24)
        self.assertEqual(gg.c_value("seqmem0_drv0_reg + 3", sym), 0x183)
        self.assertEqual(gg.c_value("(adreno_is_a740_family(adreno_gpu) ||\n adreno_is_a722(adreno_gpu)) ? 0x80000021 : 0x80000000", sym),
                         0x80000000)
        self.assertEqual(gg.c_value("adreno_is_a650_family(adreno_gpu) ? 7 : 8", sym), 7)
        with self.assertRaises(SystemExit):
            gg.c_value("unknown_name + 1", sym)
        with self.assertRaises(SystemExit):
            gg.c_value("adreno_is_a999(adreno_gpu) ? 1 : 2", sym)

    def test_variants(self):
        self.assertTrue(gg.applies(None) and gg.applies("A6XX") and gg.applies("A6XX-") and gg.applies("A5XX-A6XX"))
        self.assertFalse(gg.applies("A7XX") or gg.applies("A8XX-") or gg.applies("A7XX-"))


class Sequence(unittest.TestCase):
    def test_a650_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = tree(d)
            regs = gg.load_registers(root)
            writes = gg.rpmh_sequence(root, regs, expected=6)
            self.assertEqual(writes, [
                (gg.RSCC, 0x004, 1 << 24), (gg.RSCC, 0x00b, 0x80000000),       # the non-a740 ternary branch
                (gg.RSCC, 0x180, 0xeaaae5a0), (gg.RSCC, 0x181, 0xe1a1ebab),    # the a650 sequencer, not A740's 0x154
                (gg.PDC, 0x1148, 0), (gg.PDC, 0x1140, 0x80000001)])            # pdc_in_aop: no PDC sequencer
            with self.assertRaises(SystemExit) as e:
                gg.rpmh_sequence(root, regs)                                    # the real sequence has 19
            self.assertIn("6 writes", str(e.exception))
            self.assertEqual(gg.register(regs, "A6XX", "GPU_GMU_CX_GMU_CX_FAL_INTF")[0], 0x1f8f0)   # the a6xx one

    def test_changed_structure_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = tree(d, RPMH.replace("goto setup_pdc;", "do_something();"))
            with self.assertRaises(SystemExit) as e:
                gg.rpmh_sequence(root, gg.load_registers(root))
            self.assertIn("pdc_in_aop", str(e.exception))


class CrossCheck(unittest.TestCase):
    def test_a650gmu_constants_parse(self):
        enums, defines, rsc = gg.a650gmu_constants()
        self.assertEqual(enums["GMU_RPMH_CTRL"], 0x50e8)
        self.assertEqual(defines["A650_GMU_CHIP_ID"], 0x06050002)
        self.assertEqual(len(rsc), 19)
        self.assertEqual(rsc[0], (gg.RSCC, 0x004, 1 << 24))
        self.assertEqual(rsc[-1], (gg.PDC, 0x1140, 0x80000001))

    def test_mismatch_is_reported(self):
        enums, defines, rsc = gg.a650gmu_constants()
        g = {"registers": {n: enums[n] for n in list(gg.GMU_NAMES) + list(gg.RSCC_NAMES) + list(gg.PDC_NAMES)},
             "ao_fatal": defines["AO_FATAL"], "cm3_fatal": defines["CM3_FATAL"], "chip_id": defines["A650_GMU_CHIP_ID"],
             "windows": {"gmu": (0, defines["A650_GMU_CORE_BYTES"]), "rscc": (0, defines["A650_GMU_RSCC_BYTES"]),
                         "gmu_pdc": (0, defines["A650_GMU_PDC_BYTES"])}, "rsc_setup": rsc}
        self.assertTrue(all(r["result"] == "match" for r in gg.check(g)))
        bad = copy.deepcopy(g)
        bad["registers"]["GMU_HFI_CTRL_INIT"] += 1
        bad["rsc_setup"] = rsc[:-1] + [(gg.PDC, 0x1140, 0x80000003)]
        wrong = sorted(r["fact"] for r in gg.check(bad) if r["result"] != "match")
        self.assertEqual(wrong, ["GMU_HFI_CTRL_INIT", "rsc[] (window, dword, value)"])


if __name__ == "__main__":
    unittest.main()
