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
        ta.check_feeds_comment()                 # exits if feeds.toml pins another commit
        self.assertEqual(ta.feed_commit("Adreno650"), (ta.ADRENO650_GIT, ta.ADRENO650_COMMIT))
        repo, rev, path = ta.catalog_pin("Sm8550Platform")
        self.assertTrue(repo.endswith("UniXNU-sm8550-common") and len(rev) == 40 and path == "kits/Sm8550Platform")
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


class KnownFailures(unittest.TestCase):
    TEXT = "int a;\nstatic int write64(void *c,size_t at,uint64_t v){CHECK(0);return 1;}\n" \
           "    CHECK(s.vm.map(&second,0,0x802000,3,0,2,&b)==kIOReturnBadArgument);\n"

    def test_listed_failure_at_its_line(self):
        r, why = ta.classify("pin", "test_vm", self.TEXT, "line 2: 0")
        self.assertEqual(r, "known-fail")
        self.assertIn("TLBIVAL", why)
        # Resolved by patches/adreno650/0003: the patched test_vm failing at the old line is no longer excused.
        r, _ = ta.classify("patched", "test_vm", self.TEXT, "line 3: s.vm.map(...)")
        self.assertEqual(r, "FAILED")
        self.assertNotIn(("patched", "test_vm"), ta.KNOWN_FAILURES)

    def test_unlisted_or_elsewhere_is_failed(self):
        self.assertEqual(ta.classify("pin", "test_vm", self.TEXT, "line 3: x")[0], "FAILED")      # wrong line
        self.assertEqual(ta.classify("patched", "test_gmumap", self.TEXT, "line 2: 0")[0], "FAILED")  # fixed by 0002
        self.assertEqual(ta.classify("pin", "test_ring", self.TEXT, "line 2: 0")[0], "FAILED")
        self.assertEqual(ta.classify("pin", "test_vm", self.TEXT, "Segmentation fault")[0], "FAILED")
        self.assertEqual(ta.classify("pin", "test_vm", self.TEXT, "line 99: 0")[0], "FAILED")

    def test_series_files(self):
        lines = [l for l in (ta.PATCHES / "series").read_text().splitlines() if l.strip() and not l.startswith("#")]
        self.assertEqual(lines, ["0001-vm-map-null-memory.patch", "0002-tests-smmu-peers-accept-tlbival.patch",
                                 "0003-tests-vm-owned-alias-is-exclusive.patch"])
        for name in lines:
            text = (ta.PATCHES / name).read_text()
            self.assertIn("SPDX-License-Identifier", text)
        self.assertIn("NativeAdrenoVm.cpp", (ta.PATCHES / lines[0]).read_text())
        self.assertNotIn("NativeAdrenoVm.cpp", (ta.PATCHES / lines[1]).read_text())   # 0002 touches tests only
        self.assertTrue(all(f.startswith("tests/") for f in __import__("re").findall(
            r"^\+\+\+ b/(\S+)", (ta.PATCHES / lines[1]).read_text(), __import__("re").M)))
        # 0003 touches tests/test_vm.cpp only, and replaces the refusal expectation with upstream's.
        third = (ta.PATCHES / lines[2]).read_text()
        self.assertEqual(__import__("re").findall(r"^\+\+\+ b/(\S+)", third, __import__("re").M), ["tests/test_vm.cpp"])
        self.assertIn("-            CHECK(s.vm.map(&second,0,0x802000,change==2?9:3", third)
        self.assertIn("+        CHECK(!s.vm.map(&second,0,0x802000,3,1,2,&b) && !s.vm.unmap(b));", third)


if __name__ == "__main__":
    unittest.main()
