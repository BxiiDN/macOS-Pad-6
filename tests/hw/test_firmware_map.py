# SPDX-License-Identifier: BSD-2-Clause-Patent
"""uefi-pipa's boot image settings and static memory map against the board and the G6 model (scripts/pipa_firmware_map.py)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_firmware_map as fm  # noqa: E402


@unittest.skipUnless((fm.UEFI / fm.MEMORY_MAP).is_file() and (ROOT / "third_party/UniXNU/drivers").is_dir(),
                     "needs the uefi-pipa and UniXNU submodules")
class FirmwareMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = fm.analyse()

    def test_all_checks_hold(self):
        self.assertEqual([c["check"] for c in self.report["checks"] if not c["ok"]], [])

    def test_boot_route(self):
        self.assertEqual(self.report["boot_image"]["header_version"], 1)
        self.assertTrue(self.report["boot_image_kernel"]["append_dtb"])
        self.assertEqual(self.report["uefi_fd"], {"base": 0x9FC00000, "size": 0x300000})

    def test_blind_spots_are_listed(self):
        # The firmware reserves the bank 1 hole and ABL's load area; the mainline DT model has neither.
        found = {(r["base"], r["length"]) for r in self.report["firmware_only_reservations"]}
        self.assertIn(("0xffc00000", "0x20000"), found)
        self.assertIn(("0xa0000000", "0x10000000"), found)

    def test_parser(self):
        rows = fm.descriptors('gMemoryDescriptor[] = {\n {"A", 0x80000000, 0x1000, AddMem, MEM_RES, X, Reserv, Y},\n'
                              '// {"B", 0x1, 0x2, a, b, c, d, e},\n {"C", 0x90000000, 0x2000, AddMem, SYS_MEM, X, Conv, Y}\n};')
        self.assertEqual([r["name"] for r in rows], ["A", "C"])
        self.assertEqual(fm.ddr_reserved(rows), [(0x80000000, 0x1000)])


if __name__ == "__main__":
    unittest.main()
