"""scripts/pipa_memory.py: the pipa memory map model, DarwinBoot's MemoryWindow.h (compiled from the UniXNU submodule)
against the script's independent reference, the single-run rule, and the board's configured windows.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_memory as pm  # noqa: E402

MIB, GIB = pm.MIB, pm.GIB
HAVE = pm.HEADER.is_file() and (shutil.which("cc") or shutil.which("clang") or shutil.which("gcc"))


class Model(unittest.TestCase):
    def test_map_covers_banks(self):
        d = pm.model_map()
        self.assertEqual(sum(s for _, _, s in d), sum(s for _, s in pm.BANKS))
        self.assertEqual(sum(s for k, _, s in d if k == pm.RESERVED_TYPE), sum(s for _, s in pm.RESERVED))
        starts = [a for _, a, _ in d]
        self.assertEqual(starts, sorted(starts))
        for (k1, a1, s1), (k2, a2, s2) in zip(d, d[1:]):
            self.assertLessEqual(a1 + s1, a2)

    def test_reference_exclusions(self):
        d = [(pm.FREE, 0x100000, 0x100000), (pm.RESERVED_TYPE, 0x200000, 0x100000), (pm.FREE, 0x300000, 0x100000)]
        self.assertEqual(pm.reference_exclusions(d, 0x100000, 0x400000),
                         [(0x200000, 0x100000), (0x400000, 0x100000)])

    def test_single_run_rule(self):
        d = [(pm.FREE, 0x80000000, 0x10000000), (pm.RESERVED_TYPE, 0x90000000, 0x200000), (pm.FREE, 0x90200000, 0x40000000)]
        self.assertEqual(pm.window_without_table(d, 0x20000000), 0x90200000)
        self.assertEqual(pm.window_without_table(d, 0x08000000), 0x80000000)
        self.assertEqual(pm.window_without_table(d, 0x80000000), 0)

    def test_board_windows(self):
        rows = {w["profile"]: w for w in pm.board_windows()}
        mac, ipad = rows["macos-26.5-25F71"], rows["ipados-17.7.11-21H461"]
        self.assertEqual((mac["size"], mac["table"]), (6 * GIB, 64))
        self.assertEqual((ipad["size"], ipad["table"]), (0x170000000, 0))   # iPadOS 17 reads no table

    def test_board_windows_override_semantics(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "board.toml"
            p.write_text('[board]\nos_profile = "a"\n[payload.adt]\nowned_memory_size = "0x100000000"\n'
                         'owned_memory_excluded_ranges = 8\n[os_overrides.b]\nremove = []\n'
                         '[os_overrides.c]\nremove = ["payload.adt.owned_memory_excluded_ranges"]\n')
            rows = {w["profile"]: w for w in pm.board_windows(p)}
            self.assertEqual(rows["b"]["table"], 8)
            self.assertEqual(rows["c"]["table"], 0)


@unittest.skipUnless(HAVE, "needs a C compiler and third_party/UniXNU (git submodule update --init third_party/UniXNU)")
class LoaderCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = pm.Window()

    def test_configured_windows(self):
        d = pm.model_map()
        for row in pm.scenarios(self.win, d):
            if row["configured"]:
                self.assertTrue(row["base"], row)
                self.assertFalse(row.get("merged"), row)
        mac = pm.evaluate(self.win, d, 6 * GIB, 64)
        self.assertEqual((mac["base"], mac["usable"], mac["exclusions"]), (0xc0000000, 6 * GIB, []))

    def test_window_over_the_low_bank(self):
        """Only the low bank and bank 1: an 8 GiB span from 0x80000000 must cover the bank gap and the no-map
        regions, and MemoryWindow.h must list exactly what the reference lists."""
        d = pm.model_map(pm.BANKS[:2])
        blob = pm.pack(d)
        start = 0x80000000
        ref = pm.reference_exclusions(d, start, 8 * GIB)
        count, excluded, pairs = self.win.exclusions(blob, start, 8 * GIB, 64)
        self.assertEqual(pairs, ref)
        self.assertEqual(count, len(ref))
        self.assertEqual(excluded, sum(s for _, s in ref))
        self.assertIn((0xb7700000, 0xc0000000 - 0xb7700000), ref)      # the gap between bank 0 and bank 1
        self.assertIn((0x80000000, 0x600000 + 0x260000 + 0x20000), ref)  # hyp_mem, xbl_aop_mem, cmd_db: adjacent, one range
        self.assertEqual(self.win.usable(blob, start, 8 * GIB), 8 * GIB - excluded)

    def test_small_table_merges_without_losing_exclusions(self):
        d = pm.model_map(pm.BANKS[:2])
        blob = pm.pack(d)
        ref = pm.reference_exclusions(d, 0x80000000, 8 * GIB)
        self.assertGreater(len(ref), 4)
        count, excluded, pairs = self.win.exclusions(blob, 0x80000000, 8 * GIB, 4)
        self.assertEqual(len(pairs), 4)
        self.assertGreaterEqual(excluded, sum(s for _, s in ref))      # merging gives memory up, never leaves out
        for a, s in ref:                                               # every excluded byte is still covered
            self.assertTrue(any(pa <= a and a + s <= pa + ps for pa, ps in pairs), hex(a))

    def test_perturbed_maps(self):
        stats = pm.robustness(self.win, pm.model_map(), 6 * GIB, 64, trials=40, seed=5)
        self.assertEqual(stats["table_placed"], 40)
        self.assertEqual(stats["disagreements"], 0)
        self.assertEqual(stats["table_merged"], 0)
        self.assertLess(stats["single_run_placed"], 40)

    def test_random_maps_against_reference(self):
        rng = random.Random(1)
        for _ in range(50):
            d, cursor = [], 0x80000000
            for _ in range(rng.randint(1, 12)):
                kind = rng.choice([pm.FREE, pm.FREE, pm.RESERVED_TYPE, 4, pm.LOADER_DATA])
                size = rng.randint(1, 512) * 0x200000
                d.append((kind, cursor, size))
                cursor += size + rng.choice([0, 0, 0x200000])
            blob = pm.pack(d)
            size = rng.randint(1, 64) * 0x2000000
            base, usable = self.win.start(blob, 0x2000000, size)
            if not base:
                continue
            ref = pm.reference_exclusions(d, base, size)
            count, excluded, pairs = self.win.exclusions(blob, base, size, 64)
            if len(ref) <= 64:
                self.assertEqual(pairs, ref)
            self.assertEqual(usable, size - sum(s for _, s in ref))


if __name__ == "__main__":
    unittest.main()
