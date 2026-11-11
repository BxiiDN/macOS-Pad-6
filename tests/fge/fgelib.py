"""ctypes binding of kernel/fge for host tests, plus an llvm-mc helper.

The encodings used by the tests come from LLVM's assembler at test time, so a
wrong mask in fge.c cannot be hidden by a wrong hand-typed constant here.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import ctypes
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FGE_DIR = ROOT / "kernel" / "fge"
BUILD = ROOT / "build" / "host"

CLASSES = ["none", "pac-dp1", "pacga", "pac-branch", "pac-load", "pac-keyreg",
           "jscvt", "flagm", "flagm2", "sb", "rcpc2", "pstate", "sha3", "sha512"]

NOT_HANDLED, HANDLED, MEM_FAULT = 0, 1, 2
N, Z, C, V = 1 << 31, 1 << 30, 1 << 29, 1 << 28

LLVM_MATTR = "+v8.5a,+pauth,+jsconv,+flagm,+altnzcv,+sb,+rcpc-immo,+ssbs,+rcpc,+sha3"


def find_tool(name):
    """Find llvm-mc / llvm-objdump, also as versioned names (llvm-mc-18)."""
    env = os.environ.get(name.upper().replace("-", "_"))
    if env:
        return env
    path = shutil.which(name)
    if path:
        return path
    for ver in range(30, 13, -1):
        path = shutil.which(f"{name}-{ver}")
        if path:
            return path
    raise FileNotFoundError(f"{name} not found (set {name.upper().replace('-', '_')})")


_ENC = re.compile(r"encoding: \[(0x[0-9a-f]{2}),(0x[0-9a-f]{2}),(0x[0-9a-f]{2}),(0x[0-9a-f]{2})\]")


def assemble(lines):
    """Return the 32-bit encodings of AArch64 assembly lines, in order."""
    src = "\n".join(lines) + "\n"
    out = subprocess.run(
        [find_tool("llvm-mc"), "-triple=aarch64", f"-mattr={LLVM_MATTR}", "-show-encoding"],
        input=src, capture_output=True, text=True, check=True).stdout
    words = []
    for m in _ENC.finditer(out):
        b = [int(x, 16) for x in m.groups()]
        words.append(b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24)
    if len(words) != len(lines):
        raise ValueError(f"assembled {len(words)} of {len(lines)} lines:\n{out}")
    return words


def build_lib():
    BUILD.mkdir(parents=True, exist_ok=True)
    so = BUILD / "libfge.so"
    src = FGE_DIR / "fge.c"
    if not so.exists() or so.stat().st_mtime < max(src.stat().st_mtime,
                                                    (FGE_DIR / "fge.h").stat().st_mtime):
        cc = os.environ.get("CC", "cc")
        subprocess.run([cc, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra",
                        "-Werror", "-o", str(so), str(src)], check=True)
    return so


class VReg(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint64), ("hi", ctypes.c_uint64)]


READ_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p,
                           ctypes.c_uint)
WRITE_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p,
                            ctypes.c_uint)
BARRIER_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class Ctx(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint64 * 31),
        ("sp", ctypes.c_uint64),
        ("pc", ctypes.c_uint64),
        ("nzcv", ctypes.c_uint32),
        ("el", ctypes.c_int),
        ("v", ctypes.POINTER(VReg)),
        ("fpsr", ctypes.POINTER(ctypes.c_uint32)),
        ("fpcr", ctypes.c_uint32),
        ("read_mem", READ_FN),
        ("write_mem", WRITE_FN),
        ("barrier", BARRIER_FN),
        ("cookie", ctypes.c_void_p),
        ("pacga_key", ctypes.c_uint64),
    ]


class Machine:
    """A context with a sparse byte memory, for one test."""

    def __init__(self, lib, el=0):
        self.lib = lib
        self.mem = {}
        self.faulting = set()          # page numbers (4 KiB) that fault
        self.barriers = 0
        self.vregs = (VReg * 32)()
        self.fpsr = ctypes.c_uint32(0)
        self.ctx = Ctx()
        self.ctx.el = el
        self.ctx.pc = 0x100000
        self.ctx.v = ctypes.cast(self.vregs, ctypes.POINTER(VReg))
        self.ctx.fpsr = ctypes.pointer(self.fpsr)
        self._r = READ_FN(self._read)
        self._w = WRITE_FN(self._write)
        self._b = BARRIER_FN(self._barrier)
        self.ctx.read_mem = self._r
        self.ctx.write_mem = self._w
        self.ctx.barrier = self._b
        self.ctx.pacga_key = 0x1234_5678_9ABC_DEF0

    def _read(self, _cookie, addr, dst, size):
        if any(((addr + k) >> 12) in self.faulting for k in range(size)):
            return 1
        data = bytes(self.mem.get(addr + k, 0) for k in range(size))
        ctypes.memmove(dst, data, size)
        return 0

    def _write(self, _cookie, addr, src, size):
        if any(((addr + k) >> 12) in self.faulting for k in range(size)):
            return 1
        data = ctypes.string_at(src, size)
        for k, b in enumerate(data):
            self.mem[addr + k] = b
        return 0

    def _barrier(self, _cookie):
        self.barriers += 1

    def poke(self, addr, value, size=8):
        for k in range(size):
            self.mem[addr + k] = (value >> (8 * k)) & 0xFF

    def peek(self, addr, size=8):
        return sum(self.mem.get(addr + k, 0) << (8 * k) for k in range(size))

    def snapshot(self):
        return (list(self.ctx.x), self.ctx.sp, self.ctx.pc, self.ctx.nzcv,
                dict(self.mem), self.fpsr.value)

    def run(self, insn):
        cls = ctypes.c_int(0)
        res = self.lib.fge_emulate(ctypes.byref(self.ctx), ctypes.c_uint32(insn),
                                   ctypes.byref(cls))
        return res, CLASSES[cls.value]


def load():
    lib = ctypes.CDLL(str(build_lib()))
    lib.fge_emulate.restype = ctypes.c_int
    lib.fge_emulate.argtypes = [ctypes.POINTER(Ctx), ctypes.c_uint32, ctypes.POINTER(ctypes.c_int)]
    lib.fge_classify.restype = ctypes.c_int
    lib.fge_classify.argtypes = [ctypes.c_uint32, ctypes.c_int]
    lib.fge_fjcvtzs.restype = ctypes.c_uint32
    lib.fge_fjcvtzs.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_uint32)]
    return lib
