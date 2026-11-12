# SPDX-License-Identifier: BSD-2-Clause-Patent
"""The board package split by kernel (scripts/pipa_os_abi.py): what the macOS 26.5 kernel compiles names no iPadOS-only
interface, the iPadOS display/touch/GPU bring-up stays out of it, and the display, touch and backlight models stay host
models until a macOS driver uses them."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_os_abi as oa  # noqa: E402


class Split(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (oa.UNIXNU / "scripts/build-sheng-source-storage.py").is_file():
            raise unittest.SkipTest("needs the UniXNU submodule")
        cls.rows = {r["file"]: r for r in oa.classify()}

    def test_macos_kernel_sources(self):
        macos = {f for f, r in self.rows.items() if "macos" in r["kernels"] and f.endswith((".c", ".cpp"))}
        # The storage recipe's five, the A650 cold start of Adreno650, the export of libPipaGpu.a.
        self.assertEqual(macos, {"SourceStorage.cpp", "SourceRootPolicies.cpp", "SourceRootBinding.cpp", "BootLog.c",
                                 "BootReset.c", "A650Gmu.c", "BootLogExport.c"})

    def test_macos_kernel_names_no_ipados_interface(self):
        for f, r in self.rows.items():
            if "macos" in r["kernels"]:
                self.assertEqual(r["ipados_only_interfaces"], [], f)

    def test_ipados_bring_up_stays_out(self):
        for f in ("LegacyDisplayProbe.cpp", "MdssProbe.cpp", "FlipProbe.cpp", "TouchProbe.cpp", "TouchState.cpp",
                  "HidInputProbe.cpp", "GpuProbe.cpp", "KeyStoreProbe.cpp", "NativeBattery.cpp", "BootRamoops.c",
                  "LinkStubs.c"):
            self.assertEqual(self.rows[f]["kernels"], ["ipados"], f)
        self.assertIn("IOMobileFramebuffer", self.rows["LegacyDisplayProbe.cpp"]["ipados_only_interfaces"])

    def test_models_are_host_only(self):
        for f in ("PanelLink.h", "PanelBoard.h", "TouchVendor.h", "BacklightBoard.h", "GeniI2cCore.h", "GeniI2cBoard.h",
                  "Ktz8866Driver.h", "PipaBacklight.c", "PowerSupplyBoard.h"):
            self.assertEqual(self.rows[f]["kernels"], [], f)

    def test_comments_do_not_count(self):
        # BootLogExport.c mentions backboardd in a comment only (the fork's caller admits that process).
        self.assertIn("backboardd", (oa.PACKAGE / "BootLogExport.c").read_text())
        self.assertEqual(self.rows["BootLogExport.c"]["ipados_only_interfaces"], [])


if __name__ == "__main__":
    unittest.main()
