"""FGE's SHA3/SHA512 emulation against two references:

1. A Python model written from the Arm pseudocode (always runs).
2. QEMU's own helpers (target/arm/tcg/crypto_helper.c), compiled at test time
   from a QEMU checkout named by QEMU_SRC; skipped without it. QEMU is GPL and
   is only used as a test oracle here: no QEMU code is committed.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import ctypes
import os
import random
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fge.fgelib import HANDLED, Machine, assemble, load

LIB = load()
RNG = random.Random(512)
M64 = (1 << 64) - 1
QEMU_COMMIT = "29760efaf96bbe5928f8111881eddbf5ac06439e"


def ror(x, n):
    n &= 63
    return ((x >> n) | (x << (64 - n))) & M64 if n else x


def S0(x): return ror(x, 28) ^ ror(x, 34) ^ ror(x, 39)
def S1(x): return ror(x, 14) ^ ror(x, 18) ^ ror(x, 41)
def s0(x): return ror(x, 1) ^ ror(x, 8) ^ (x >> 7)
def s1(x): return ror(x, 19) ^ ror(x, 61) ^ (x >> 6)
def ch(x, y, z): return (x & y) ^ (~x & M64 & z)
def maj(x, y, z): return (x & y) ^ (x & z) ^ (y & z)


def model(op, d, n, m, a=(0, 0), imm=0):
    """(lo, hi) result of one instruction; arguments are (lo, hi) pairs."""
    if op == "eor3":
        return n[0] ^ m[0] ^ a[0], n[1] ^ m[1] ^ a[1]
    if op == "bcax":
        return n[0] ^ (m[0] & ~a[0] & M64), n[1] ^ (m[1] & ~a[1] & M64)
    if op == "rax1":
        return n[0] ^ ror(m[0], 63), n[1] ^ ror(m[1], 63)
    if op == "xar":
        return ror(n[0] ^ m[0], imm), ror(n[1] ^ m[1], imm)
    if op == "sha512su0":
        return (d[0] + s0(d[1])) & M64, (d[1] + s0(n[0])) & M64
    if op == "sha512su1":
        return (d[0] + s1(n[0]) + m[0]) & M64, (d[1] + s1(n[1]) + m[1]) & M64
    if op == "sha512h":
        hi = (d[1] + S1(m[1]) + ch(m[1], n[0], n[1])) & M64
        t = (hi + m[0]) & M64
        return (d[0] + S1(t) + ch(t, m[1], n[0])) & M64, hi
    if op == "sha512h2":
        hi = (d[1] + S0(m[0]) + maj(n[0], m[1], m[0])) & M64
        return (d[0] + S0(hi) + maj(hi, m[0], m[1])) & M64, hi
    raise ValueError(op)


LINES = {
    "eor3": "eor3 v1.16b, v2.16b, v3.16b, v4.16b",
    "bcax": "bcax v1.16b, v2.16b, v3.16b, v4.16b",
    "rax1": "rax1 v1.2d, v2.2d, v3.2d",
    "sha512su0": "sha512su0 v1.2d, v2.2d",
    "sha512su1": "sha512su1 v1.2d, v2.2d, v3.2d",
    "sha512h": "sha512h q1, q2, v3.2d",
    "sha512h2": "sha512h2 q1, q2, v3.2d",
}


def run_fge(word, d, n, m, a):
    mach = Machine(LIB)
    for k, val in ((1, d), (2, n), (3, m), (4, a)):
        mach.vregs[k].lo, mach.vregs[k].hi = val
    res, cls = mach.run(word)
    return res, cls, (mach.vregs[1].lo, mach.vregs[1].hi)


def rand128():
    return RNG.getrandbits(64), RNG.getrandbits(64)


class AgainstModel(unittest.TestCase):
    def test_all_ops(self):
        words = dict(zip(LINES, assemble(list(LINES.values()))))
        for op, word in words.items():
            for _ in range(2000):
                d, n, m, a = rand128(), rand128(), rand128(), rand128()
                res, cls, got = run_fge(word, d, n, m, a)
                self.assertEqual(res, HANDLED, op)
                self.assertEqual(cls, "sha3" if op in ("eor3", "bcax", "rax1") else "sha512", op)
                self.assertEqual(got, model(op, d, n, m, a), op)

    def test_xar_every_rotation(self):
        words = assemble([f"xar v1.2d, v2.2d, v3.2d, #{k}" for k in range(64)])
        for k, word in enumerate(words):
            d, n, m = rand128(), rand128(), rand128()
            _res, cls, got = run_fge(word, d, n, m, (0, 0))
            self.assertEqual((cls, got), ("sha3", model("xar", d, n, m, imm=k)), k)


QEMU_HARNESS = r"""
#include <stdint.h>
static inline uint64_t ror64(uint64_t x, int n) { n &= 63; return n ? (x >> n) | (x << (64 - n)) : x; }
static inline uint64_t rol64(uint64_t x, int n) { return ror64(x, 64 - n); }
#define HELPER(name) oracle_##name
#define clear_tail_16(vd, desc) ((void)0)
#define clear_tail(vd, a, b) ((void)0)
#define simd_oprsz(desc) 16
#define simd_maxsz(desc) 16
"""


@unittest.skipUnless(os.environ.get("QEMU_SRC"), "set QEMU_SRC to a QEMU checkout to run the oracle")
class AgainstQemu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = Path(os.environ["QEMU_SRC"]) / "target/arm/tcg/crypto_helper.c"
        text = src.read_text()
        sha = text[text.index("static uint64_t cho512"):text.index("void HELPER(crypto_sm3partw1)")]
        rax = re.search(r"void HELPER\(crypto_rax1\).*?\n}\n", text, re.S).group(0)
        cls.tmp = tempfile.TemporaryDirectory()
        c = Path(cls.tmp.name) / "oracle.c"
        c.write_text(QEMU_HARNESS + sha + rax)
        so = Path(cls.tmp.name) / "oracle.so"
        subprocess.run([os.environ.get("CC", "cc"), "-O1", "-fPIC", "-shared", "-o", str(so), str(c)], check=True)
        cls.lib = ctypes.CDLL(str(so))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def oracle(self, op, d, n, m):
        arr = lambda v: (ctypes.c_uint64 * 2)(*v)  # noqa: E731
        vd, vn, vm = arr(d), arr(n), arr(m)
        fn = getattr(self.lib, f"oracle_crypto_{op}")
        if op == "sha512su0":
            fn(vd, vn, ctypes.c_uint32(0))
        else:
            fn(vd, vn, vm, ctypes.c_uint32(0))
        return vd[0], vd[1]

    def test_sha512_and_rax1(self):
        ops = ["sha512h", "sha512h2", "sha512su0", "sha512su1", "rax1"]
        words = dict(zip(ops, assemble([LINES[o] for o in ops])))
        for op in ops:
            for _ in range(5000):
                d, n, m = rand128(), rand128(), rand128()
                _res, _cls, got = run_fge(words[op], d, n, m, (0, 0))
                self.assertEqual(got, self.oracle(op, d, n, m), op)


if __name__ == "__main__":
    unittest.main()
