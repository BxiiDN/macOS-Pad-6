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


class KernelSide(unittest.TestCase):
    """kernel_table: arm_vm_excluded_init of window-memory-excluded-ranges.patch, in Python."""
    BASE, SIZE = 0xc0000000, 6 * GIB

    def test_empty_slots_clip_round_join(self):
        top = self.BASE + 192 * MIB
        far = self.BASE + 1 * GIB
        pairs = [(0, 0), (far + 0x1800, 0x1000), (far + 0x2000, 0x3000),     # touch after rounding: one range
                 (far + 0x100000, 0x1000), (0, 0),
                 (self.BASE + self.SIZE - 0x1000, 0x10000)]                 # runs past the span: clipped
        k = pm.kernel_table(pairs, self.BASE, self.SIZE, top)
        self.assertIsNone(k["panic"])
        self.assertEqual(k["table"], [(far + 0x1000, far + 0x5000), (far + 0x100000, far + 0x101000),
                                      (self.BASE + self.SIZE - 0x1000, self.BASE + self.SIZE)])
        self.assertEqual(k["bytes"], 0x4000 + 0x1000 + 0x1000)
        # The table takes the page(s) at the old avail_start.
        self.assertEqual(k["avail_start"], ((top + 0xfff) & ~0xfff) + 0x1000)

    def test_page_rounding_is_outward(self):
        # A 16 KiB kernel would exclude more than a 4 KiB loader listed: memsize would disagree.
        far = self.BASE + 1 * GIB
        k4 = pm.kernel_table([(far + 0x1000, 0x1000)], self.BASE, self.SIZE, self.BASE)
        k16 = pm.kernel_table([(far + 0x1000, 0x1000)], self.BASE, self.SIZE, self.BASE, page=0x4000)
        self.assertEqual((k4["bytes"], k16["bytes"]), (0x1000, 0x4000))

    def test_first_range_check(self):
        top = self.BASE + 192 * MIB
        reserve = pm.kernel_reserve(self.SIZE)
        self.assertEqual(reserve, 96 * MIB)                                   # 6 GiB / 64
        self.assertEqual(pm.kernel_reserve(1 * GIB), 32 * MIB)                # the floor
        inside = pm.kernel_table([(top + reserve - 0x1000, 0x1000)], self.BASE, self.SIZE, top)
        outside = pm.kernel_table([(top + reserve, 0x1000)], self.BASE, self.SIZE, top)
        self.assertIn("inside the kernel's boot allocations", inside["panic"])
        self.assertIsNone(outside["panic"])
        self.assertIsNone(pm.kernel_table([], self.BASE, self.SIZE, top)["panic"])

    def test_bootstrap_pool(self):
        # 4 KiB granule: one L2 page per 1 GiB region; 2 roots + 14 L2 pages in the 16-page pool.
        self.assertEqual(pm.l2_tables(0, 6 * GIB), 6)
        self.assertEqual(pm.l2_tables(2 * MIB, 6 * GIB), 7)                   # straddles one more region
        self.assertEqual(pm.bootstrap_worst(0xc0000000, 6 * GIB), (15, 511))  # aligned V=P, any slide
        self.assertEqual(pm.bootstrap_worst(0xc0200000, 6 * GIB)[0], 16)      # both straddle: exactly full
        self.assertEqual(pm.bootstrap_worst(0xc0200000, 6 * GIB + 256 * MIB)[0], 17)
        self.assertEqual(pm.max_bootstrap_window(), 6 * GIB)
        self.assertEqual(pm.max_bootstrap_window(pm.L2_REGION), 6 * GIB)

    def test_bank_gaps(self):
        self.assertEqual(pm.bank_gaps(0xc0000000, 6 * GIB), [])                # inside bank 1
        gaps = pm.bank_gaps(0x80000000, 9 * GIB)
        self.assertEqual(gaps, [(0xb7700000, 0xc0000000 - 0xb7700000), (0x280000000, 1 * GIB)])

    def test_source_limits(self):
        if not pm.DEVICETREE.is_file():
            self.skipTest("third_party/UniXNU not checked out")
        limits, errors = pm.source_limits()
        self.assertEqual(errors, [])
        self.assertEqual((limits["slots_min"], limits["slots_max"]), (1, 4096))
        self.assertEqual((limits["window_min"], limits["window_max"], limits["window_step"]),
                         (256 * MIB, 8 * GIB, 2 * MIB))
        self.assertEqual(limits["kernel_reserve"], limits["loader_reserve"])
        self.assertEqual(limits["bootstrap_pages"], pm.BOOTSTRAP_PAGES)
        self.assertTrue(limits["first_range_check"])


class AddressAudit(unittest.TestCase):
    def test_board_window(self):
        self.assertEqual(pm.dts_memory(), (0x80000000, 0x980000000))
        checks = pm.address_audit(0xc0000000, 6 * GIB, [])
        self.assertTrue(all(ok for _, ok, _ in checks), [c for c in checks if not c[1]])
        self.assertGreaterEqual(pm.IMAGE_ESTIMATE, pm.KC_BYTES)

    def test_failures_are_named(self):
        bad = {name for name, ok, _ in pm.address_audit(0x80000000, 9 * GIB, [])}
        failed = {name for name, ok, _ in pm.address_audit(0x80000000, 9 * GIB, []) if not ok}
        self.assertIn("window inside one DRAM bank", failed)                     # spans the bank 0 / bank 1 gap
        self.assertLessEqual(failed, bad)
        head = pm.IMAGE_ESTIMATE + pm.kernel_reserve(6 * GIB)
        inside_head = [(0xc0000000 + head - 0x1000, 0x1000)]
        failed = {name for name, ok, _ in pm.address_audit(0xc0000000, 6 * GIB, inside_head) if not ok}
        self.assertEqual(failed, {"excluded ranges page aligned, sorted, inside the window, past the head"})
        unaligned = [(0xc0000000 + 1 * GIB + 0x800, 0x1000)]
        failed = {name for name, ok, _ in pm.address_audit(0xc0000000, 6 * GIB, unaligned) if not ok}
        self.assertEqual(failed, {"excluded ranges page aligned, sorted, inside the window, past the head"})
        many = [(0xc0000000 + 1 * GIB + i * 0x2000, 0x1000) for i in range(257)]
        failed = {name for name, ok, _ in pm.address_audit(0xc0000000, 6 * GIB, many) if not ok}
        self.assertEqual(failed, {"kernel table fits one page"})


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

    def test_kernel_accepts_loader_tables(self):
        """Every table MemoryWindow.h writes, at the smallest and the largest capacity UniXNU allows and at the
        board's, is one the kernel takes without a panic and counts to the same bytes (hw.memsize)."""
        rng = random.Random(9)
        d0 = pm.model_map()
        for capacity in (1, 64, 4096):
            for _ in range(15):
                d = pm.perturbed(d0, rng.randint(1, 40), rng)
                row = pm.evaluate(self.win, d, 6 * GIB, capacity)
                self.assertTrue(row["base"])
                k = row["kernel"]
                self.assertIsNone(k["panic"], (capacity, k))
                self.assertTrue(k["memsize_agrees"], (capacity, k))
                self.assertLessEqual(k["ranges"], capacity)
                self.assertEqual(row["bank_gaps"], [])
                if capacity == 1:
                    self.assertLessEqual(len(row["exclusions"]), 1)
                if capacity == 4096:
                    self.assertFalse(row["merged"])

    def test_loader_tables_pass_the_address_audit(self):
        rng = random.Random(4)
        for _ in range(20):
            d = pm.perturbed(pm.model_map(), rng.randint(1, 30), rng)
            row = pm.evaluate(self.win, d, 6 * GIB, 64)
            checks = pm.address_audit(row["base"], 6 * GIB, row["exclusions"])
            self.assertTrue(all(ok for _, ok, _ in checks), [c for c in checks if not c[1]])

    def test_loader_and_kernel_reserve_agree(self):
        for size in range(256 * MIB, 8 * GIB + 1, 128 * MIB):
            self.assertEqual(self.win.reserve(size), pm.kernel_reserve(size), size)

    def test_head_never_holds_an_exclusion(self):
        """A firmware hole right behind the image: the loader moves the window rather than hand the kernel a table
        that would panic."""
        d0 = pm.model_map()
        d = pm.perturbed(d0, 0, random.Random(0))
        hole = 0xc0000000 + 100 * MIB
        d = sorted([x for x in d if not (x[0] == pm.FREE and x[1] <= hole < x[1] + x[2])] +
                   [(pm.FREE, 0xc0000000, hole - 0xc0000000), (4, hole, 2 * MIB),
                    (pm.FREE, hole + 2 * MIB, 0xc0000000 + 0x1c0000000 - hole - 2 * MIB)], key=lambda x: x[1])
        row = pm.evaluate(self.win, d, 6 * GIB, 64)
        self.assertTrue(row["base"])
        self.assertNotEqual(row["base"], 0xc0000000)
        self.assertIsNone(row["kernel"]["panic"])

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
