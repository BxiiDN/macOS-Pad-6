"""scripts/pipa_storage_build.py: the board environment it gives UniXNU's storage recipe, and the recipe inputs it
links into a kernel step's tree that the macOS profile left without them (kernel-build run 43100577481 stopped at
"no such file ... tree/drivers/ShengUfs/NativeUfs.cpp").

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_storage_build as sb  # noqa: E402


def make(path, files):
    for rel in files:
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text("x")


class Env(unittest.TestCase):
    def test_board_env(self):
        env = sb.board_env()
        self.assertEqual(env["UNIXNU_SOURCE_STORAGE_ROOT"], "none")
        self.assertEqual(env["UNIXNU_KIT"], "pipa")
        self.assertEqual(env["UNIXNU_XNU_ARCH"], "arm64e")
        self.assertTrue(env["UNIXNU_SOC"])


class Errors(unittest.TestCase):
    def test_compile_errors(self):
        log = "a.cpp:1:2: warning: w\n  x\nb.cpp:3:4: error: no member named 'y'\n  3 | z.y\n    |   ^\nclang: error: no input files\n"
        out = sb.compile_errors(log, context=2)
        self.assertEqual(out[0], "ERROR b.cpp:3:4: error: no member named 'y'")
        self.assertEqual(out[1:3], ["  3 | z.y", "    |   ^"])
        self.assertIn("ERROR clang: error: no input files", out)
        self.assertNotIn("warning", " ".join(out))


class LinkMap(unittest.TestCase):
    def test_members(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "kernel-link.map"
            m.write_text("# Path: kernel\n# Arch: arm64e\n# Object files:\n[  0] linker synthesized\n"
                         "[  1] /t/build/xnu/osfmk/startup.o\n"
                         "[ 25] /t/build/sheng-source-storage/libShengSourceStorage.a(SourceStorage.o)\n"
                         "[ 26] /t/build/sheng-source-storage/libShengSourceStorage.a(NativeUfs.late.o)\n"
                         "# Sections:\n# Address Size Segment Section\n"
                         "0x0 0x10 __TEXT __text libShengSourceStorage.a(Other.o)\n")
            self.assertEqual(sb.map_members(m), ["SourceStorage.o", "NativeUfs.late.o"])
            m.write_text("# Object files:\n[  1] /t/startup.o\n# Sections:\n")
            self.assertEqual(sb.map_members(m), [])
            self.assertIsNone(sb.map_members(Path(d) / "absent.map"))


class Inputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.tree, self.unixnu, self.feed = base / "tree", base / "UniXNU", base / "feeds/ShengUfs-5c64c0125e0d"
        make(self.tree, ["scripts/build-sheng-source-storage.py", "drivers/ArmCpu/a.c"])
        make(self.unixnu, ["drivers/RamBlock/NativeRamBlock.cpp", "drivers/VirtioMmioBlock/VirtioBlock.h",
                           "kits/VerifiedRoot/src/verified_root.c", "drivers/ShengUfs/NativeUfs.cpp"])
        make(self.feed, ["NativeUfs.cpp", "GccUfs.h"])
        self.modules = base / "modules.json"
        self.modules.write_text(json.dumps({"modules": {"driver:ShengUfs": str(self.feed)}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_missing_inputs_from_the_pin_and_the_checkout(self):
        done = sb.ensure_inputs(self.tree, self.unixnu, self.modules)
        # ShengUfs from the feeds.toml pin (PipaUfs), not UniXNU's own SM8550 ShengUfs.
        self.assertEqual((self.tree / "drivers/ShengUfs").resolve(), self.feed.resolve())
        self.assertEqual(done["drivers/ShengUfs"], str(self.feed))
        for rel in ("drivers/RamBlock", "drivers/VirtioMmioBlock", "kits/VerifiedRoot"):
            self.assertEqual((self.tree / rel).resolve(), (self.unixnu / rel).resolve(), rel)
        # A second run finds them all.
        self.assertEqual(set(sb.ensure_inputs(self.tree, self.unixnu, self.modules).values()), {"present"})

    def test_present_inputs_are_left_alone(self):
        make(self.tree, ["drivers/ShengUfs/NativeUfs.cpp"])
        done = sb.ensure_inputs(self.tree, self.unixnu, self.modules)
        self.assertEqual(done["drivers/ShengUfs"], "present")
        self.assertFalse((self.tree / "drivers/ShengUfs").is_symlink())

    def test_missing_source_stops(self):
        self.modules.write_text(json.dumps({"modules": {}}))
        (self.unixnu / "drivers/ShengUfs/NativeUfs.cpp").unlink()
        with self.assertRaises(SystemExit):
            sb.ensure_inputs(self.tree, self.unixnu, self.modules)

    def test_foreign_directory_is_not_replaced(self):
        make(self.tree, ["kits/VerifiedRoot/README"])
        with self.assertRaises(SystemExit):
            sb.ensure_inputs(self.tree, self.unixnu, self.modules)


if __name__ == "__main__":
    unittest.main()
