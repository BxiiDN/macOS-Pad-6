"""scripts/test_adreno650.py helpers: the fork pin agrees with devices/pipa/feeds.toml, link failures are attributed to
the source that was not built (and only then skipped), and the ArmSmmu4K pin is read from feeds.toml.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import test_adreno650 as ta  # noqa: E402


class Helpers(unittest.TestCase):
    def test_pins(self):
        ta.check_feeds_comment()                 # exits if feeds.toml names another commit
        git, commit = ta.feed_commit("ArmSmmu4K")
        self.assertIn("ArmSmmu4K", git)
        self.assertEqual(len(commit), 40)
        with self.assertRaises(KeyError):
            ta.feed_commit("NoSuchSource")

    def test_owner(self):
        with tempfile.TemporaryDirectory() as d:
            fork = Path(d) / "Adreno650"
            fork.mkdir()
            (fork / "NativeAdrenoSubmit.cpp").write_text('extern "C" {volatile uint32_t native_adreno_wc_audit[6];}\n')
            (fork / "NativeAdrenoMemory.cpp").write_text('extern "C" {volatile uint32_t native_adreno_trace_stage;}\n'
                                                       'void helper(int x) {}\n')
            kit = Path(d) / "ArmSmmu4K"
            kit.mkdir()
            (kit / "ArmSmmu4KMmio.c").write_text("int ArmSmmu4KMmioRead(void) { return 0; }\n")
            missing = {"NativeAdrenoSubmit.cpp": "AArch64 only", "NativeAdrenoMemory.cpp": "AArch64 only",
                       "ArmSmmu4KMmio.c": "AArch64 only"}
            self.assertEqual(ta.owner("NativeAdrenoSubmit::submit", fork, missing), "NativeAdrenoSubmit.cpp")
            self.assertEqual(ta.owner("native_adreno_wc_audit", fork, missing), "NativeAdrenoSubmit.cpp")
            self.assertEqual(ta.owner("native_adreno_trace_stage", fork, missing), "NativeAdrenoMemory.cpp")
            self.assertEqual(ta.owner("helper", fork, missing), "NativeAdrenoMemory.cpp")
            self.assertEqual(ta.owner("ArmSmmu4KMmioRead", fork, missing), "ArmSmmu4KMmio.c")
            self.assertIsNone(ta.owner("NativeAdrenoRing::attach", fork, missing))      # built: a real failure
            self.assertIsNone(ta.owner("some_other_symbol", fork, missing))


if __name__ == "__main__":
    unittest.main()
