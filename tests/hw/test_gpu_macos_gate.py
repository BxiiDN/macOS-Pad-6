# SPDX-License-Identifier: BSD-2-Clause-Patent
"""The macOS start path of the board (zzzzd-pipa-board-start.patch, PipaBoardStart.c, PipaGop.cpp, GpuProbe.cpp's macOS
build), read from the code: nothing runs without its boot argument, GPU modes that write registers need a second one,
mode 12 (the iPadOS Metal accelerator) does not exist on macOS, the presenter writes no register, and only the GPU
defconfigs compile the call."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "devices/pipa/package"
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_os_abi as oa  # noqa: E402


def macos(name):
    return oa.macos_code((PKG / name).read_text())


class Gate(unittest.TestCase):
    def test_gpu_probe_macos_entry(self):
        code = macos("GpuProbe.cpp")
        entry = code[code.index('extern "C" void native_gpu_probe(void)'):]
        entry = entry[:entry.index("thread_t thread")]
        self.assertIn('PE_parse_boot_argn("pipa-gpu", &mode, sizeof mode) || !mode) return;', entry)
        self.assertIn('PE_parse_boot_argn("pipa-gpu-writes", &writes, sizeof writes);', entry)
        self.assertIn("if (mode > 11) mode = 11;", entry)
        self.assertIn("if (mode > 1 && writes != 1) mode = 1;", entry)
        self.assertNotIn("mode > 12 ? 12", entry)          # the iPadOS clamp is not the macOS one

    def test_no_metal_accelerator_on_macos(self):
        code = macos("GpuProbe.cpp")
        for name in ("metal()", "native_adreno_accelerator_allocate", "OSKextLoadKextWithIdentifier", "backboardd",
                     "IOAcceleratorES"):
            self.assertNotIn(name, code, name)

    def test_mode_one_writes_nothing(self):
        # gpb's write filter: no register write is allowed below mode 2 (GCC AHB), 3 (GPUCC) or 6 (the rest).
        code = macos("GpuProbe.cpp")
        self.assertIn("return gMode >= 2;", code)
        self.assertIn("return gMode >= 3;", code)
        self.assertIn("if (gMode < 6) return false;", code)

    def test_presenter_attach_reads_only(self):
        code = macos("PipaGop.cpp")
        self.assertIn('PE_parse_boot_argn("pipa-gop", &on, sizeof on) || on != 1', code)
        # No register access of its own: no MMIO mapping, no volatile store.
        for name in ("ml_io_map", "mapDeviceMemory", "volatile uint32_t *", "IOMemoryMap"):
            self.assertNotIn(name, code, name)
        self.assertIn("native_gop_presenter_create()", code)

    def test_board_start_order(self):
        code = macos("PipaBoardStart.c")
        body = code[code.index("void pipa_board_start(void)\n{"):]
        self.assertLess(body.index("pipa_gop_start();"), body.index("native_gpu_probe();"))

    def test_only_gpu_defconfigs_compile_the_call(self):
        configs = ROOT / "devices/pipa/configs"
        for name in ("pipa_macos26_gpu_defconfig", "pipa_macos26_ufs_gpu_defconfig"):
            self.assertIn("-DXNU_PIPA_BOARD_START=1", (configs / name).read_text(), name)
            self.assertIn("libPipaGpu.a", (configs / name).read_text(), name)
        for name in ("pipa_macos26_defconfig", "pipa_macos26_ufs_defconfig"):
            self.assertNotIn("XNU_PIPA_BOARD_START", (configs / name).read_text(), name)
        patch = (ROOT / "devices/pipa/patches/xnu-12377/zzzzd-pipa-board-start.patch").read_text()
        self.assertIn("+#if defined(XNU_PIPA_BOARD_START) && XNU_PIPA_BOARD_START", patch)
        self.assertIn("+\tpipa_board_start();", patch)

    def test_ufs_stays_probe_only_in_the_combined_kernel(self):
        both = (ROOT / "devices/pipa/configs/pipa_macos26_ufs_gpu_defconfig").read_text()
        self.assertIn("libShengSourceStorage.a", both)
        self.assertNotRegex(both, re.compile(r"^CONFIG_XNU_(NATIVE_UFS|SOURCE_STORAGE|OWNER_)", re.M))
        guard = (PKG / "PipaStorageGuard.h").read_text()
        self.assertIn("return probe == 2 || probe == 6 || probe == 7 || probe == 8;", guard)
        board = (ROOT / "devices/pipa/board.toml").read_text()
        self.assertIn('[storage]\nroot = "none"', board)


if __name__ == "__main__":
    unittest.main()
