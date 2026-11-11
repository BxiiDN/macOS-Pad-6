"""Host tests of kernel/fge against llvm-mc encodings and independent Python models.

Run: python3 -m unittest discover -s tests -t .
SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import itertools
import math
import random
import struct
import unittest
from fractions import Fraction

from tests.fge.fgelib import (C, HANDLED, MEM_FAULT, N, NOT_HANDLED, V, Z, Machine, assemble,
                              load)

LIB = load()
RNG = random.Random(20261111)


def f64_bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def ref_fjcvtzs(bits, fz=False):
    """Arm FPToFixedJS() written from the pseudocode with exact rationals."""
    sign = bits >> 63
    exp = (bits >> 52) & 0x7FF
    frac = bits & ((1 << 52) - 1)
    if exp == 0x7FF:
        return 0, 0, {"IOC"}
    if exp == 0 and frac and fz:
        return 0, 0, {"IDC"}
    if exp == 0:
        value = Fraction(frac, 1 << 1074)
    else:
        value = Fraction((1 << 52) | frac) * Fraction(2) ** (exp - 1075)
    if sign:
        value = -value
    int_result = math.floor(value)
    error = value - int_result
    if error != 0 and int_result < 0:
        int_result += 1
    result = int_result % (1 << 32)
    flags = set()
    zflag = 1
    if int_result < -(1 << 31) or int_result > (1 << 31) - 1:
        flags.add("IOC")
        zflag = 0
    elif error != 0:
        flags.add("IXC")
        zflag = 0
    elif sign and value == 0:
        zflag = 0
    return result, zflag, flags


FLAG_BITS = {"IOC": 1 << 0, "IXC": 1 << 4, "IDC": 1 << 7}


class Classification(unittest.TestCase):
    EMULATED = {
        "pacia x1, x2": "pac-dp1", "autdzb x9": "pac-dp1", "xpaci x5": "pac-dp1",
        "xpacd x6": "pac-dp1", "autda x1, sp": "pac-dp1", "pacizb x7": "pac-dp1",
        "pacga x0, x1, sp": "pacga",
        "retab": "pac-branch", "retaa": "pac-branch", "braaz x3": "pac-branch",
        "blrabz x4": "pac-branch", "braa x5, x6": "pac-branch", "blraa x8, x17": "pac-branch",
        "ldraa x0, [x1, #-8]!": "pac-load", "ldrab x2, [sp, #4088]": "pac-load",
        "fjcvtzs w0, d1": "jscvt",
        "cfinv": "flagm", "rmif x3, #5, #9": "flagm", "setf8 w1": "flagm", "setf16 w4": "flagm",
        "axflag": "flagm2", "xaflag": "flagm2", "sb": "sb",
        "ldapur x1, [x2, #-256]": "rcpc2", "ldapursw x3, [x4, #4]": "rcpc2",
        "stlurh w5, [sp, #255]": "rcpc2",
        "msr dit, #1": "pstate", "mrs x3, dit": "pstate", "msr ssbs, #0": "pstate",
    }
    # Instructions the Cortex-A77/A55 execute natively: FGE must leave them alone.
    NATIVE = [
        "ret", "blr x8", "br x16", "ldr x0, [x1, #8]", "ldapr x0, [x1]", "add x0, x1, x2",
        "paciasp", "autibsp", "pacia1716", "xpaclri", "fcvtzs w0, d1", "eret", "nop",
        "msr pan, #1", "mrs x0, nzcv", "ldr x0, [x1], #8", "dsb ish", "isb",
        "eretaa", "eretab",
    ]

    def test_emulated_classes(self):
        lines = list(self.EMULATED)
        for line, word in zip(lines, assemble(lines)):
            got = LIB.fge_classify(word, 0)
            self.assertEqual(
                ["none", "pac-dp1", "pacga", "pac-branch", "pac-load", "pac-keyreg", "jscvt",
                 "flagm", "flagm2", "sb", "rcpc2", "pstate"][got], self.EMULATED[line], line)

    def test_native_left_alone(self):
        for line, word in zip(self.NATIVE, assemble(self.NATIVE)):
            self.assertEqual(LIB.fge_classify(word, 0), 0, line)
            self.assertEqual(LIB.fge_classify(word, 1), 0, line)

    def test_key_registers_only_at_el1(self):
        lines = ["msr apiakeylo_el1, x0", "mrs x1, apgakeyhi_el1", "msr apdbkeyhi_el1, x2"]
        for line, word in zip(lines, assemble(lines)):
            self.assertEqual(LIB.fge_classify(word, 0), 0, line)
            self.assertEqual(LIB.fge_classify(word, 1), 5, line)

    def test_unallocated_neighbours(self):
        # PAC dp1 opcodes 18..63, and *Z forms with Rn != 31, are unallocated.
        base = assemble(["pacizb x7"])[0]
        self.assertEqual(LIB.fge_classify(base & ~(0x1F << 5) | (3 << 5), 0), 0)
        self.assertEqual(LIB.fge_classify(0xDAC10000 | (18 << 10) | (31 << 5), 0), 0)


class PointerAuth(unittest.TestCase):
    def test_dp1_is_identity(self):
        lines = ["pacia x1, x2", "autia x1, x2", "pacdzb x3", "autdzb x3", "xpaci x4",
                 "xpacd x4", "autib x5, sp"]
        for line, word in zip(lines, assemble(lines)):
            m = Machine(LIB)
            for r in range(31):
                m.ctx.x[r] = RNG.getrandbits(64)
            before = list(m.ctx.x)
            res, cls = m.run(word)
            self.assertEqual((res, cls), (HANDLED, "pac-dp1"), line)
            self.assertEqual(list(m.ctx.x), before, line)
            self.assertEqual(m.ctx.pc, 0x100004, line)

    def test_blraa_links_after_reading_target(self):
        m = Machine(LIB)
        m.ctx.x[30] = 0x5000
        res, _ = m.run(assemble(["blraa x30, x17"])[0])
        self.assertEqual(res, HANDLED)
        self.assertEqual((m.ctx.pc, m.ctx.x[30]), (0x5000, 0x100004))

    def test_branches(self):
        cases = [("braaz x3", 0x7000, None), ("brab x3, sp", 0x7000, None),
                 ("blrabz x3", 0x7000, 0x100004), ("retaa", 0x9000, 0x9000),
                 ("retab", 0x9000, 0x9000)]
        for line, target, lr in cases:
            m = Machine(LIB)
            m.ctx.x[3] = 0x7000
            m.ctx.x[30] = 0x9000
            res, cls = m.run(assemble([line])[0])
            self.assertEqual((res, cls), (HANDLED, "pac-branch"), line)
            self.assertEqual(m.ctx.pc, target, line)
            self.assertEqual(m.ctx.x[30], lr if lr is not None else 0x9000, line)

    def test_ldraa_offsets_and_writeback(self):
        for off in (-4096, -8, 0, 8, 4088):
            for wb in (False, True):
                line = f"ldrab x0, [x1, #{off}]" + ("!" if wb else "")
                m = Machine(LIB)
                m.ctx.x[1] = 0x20000
                m.poke(0x20000 + off, 0x1122334455667788)
                res, cls = m.run(assemble([line])[0])
                self.assertEqual((res, cls), (HANDLED, "pac-load"), line)
                self.assertEqual(m.ctx.x[0], 0x1122334455667788, line)
                self.assertEqual(m.ctx.x[1], 0x20000 + off if wb else 0x20000, line)

    def test_ldraa_sp_base_and_fault(self):
        m = Machine(LIB)
        m.ctx.sp = 0x30010
        m.poke(0x30000, 42)
        res, _ = m.run(assemble(["ldraa x2, [sp, #-16]!"])[0])
        self.assertEqual((res, m.ctx.x[2], m.ctx.sp), (HANDLED, 42, 0x30000))

        m = Machine(LIB)
        m.ctx.x[1] = 0x40008
        m.faulting.add(0x40)
        before = m.snapshot()
        res, _ = m.run(assemble(["ldraa x0, [x1, #-8]!"])[0])
        self.assertEqual(res, MEM_FAULT)
        self.assertEqual(m.snapshot(), before, "a fault must leave the state unchanged")

    def test_pacga(self):
        m = Machine(LIB)
        m.ctx.x[1] = 0xDEADBEEF
        m.ctx.sp = 0x7FFF0000
        word = assemble(["pacga x0, x1, sp"])[0]
        m.run(word)
        first = m.ctx.x[0]
        self.assertEqual(first & 0xFFFFFFFF, 0)
        m.ctx.pc = 0x100000
        m.run(word)
        self.assertEqual(m.ctx.x[0], first, "PACGA must be deterministic")
        m.ctx.x[1] ^= 1
        m.run(word)
        self.assertNotEqual(m.ctx.x[0], first)
        m2 = Machine(LIB)
        m2.run(assemble(["pacga xzr, x1, x2"])[0])
        self.assertEqual(m2.ctx.pc, 0x100004)

    def test_key_registers_at_el1(self):
        m = Machine(LIB, el=1)
        m.ctx.x[1] = 0xFFFF
        res, cls = m.run(assemble(["mrs x1, apiakeyhi_el1"])[0])
        self.assertEqual((res, cls, m.ctx.x[1]), (HANDLED, "pac-keyreg", 0))
        m = Machine(LIB, el=0)
        res, _ = m.run(assemble(["msr apiakeylo_el1, x0"])[0])
        self.assertEqual(res, NOT_HANDLED)


class JavaScriptConvert(unittest.TestCase):
    SPECIAL = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, -1.5, 2147483647.0, 2147483648.0,
               -2147483648.0, -2147483649.0, 4294967296.0, 4294967297.5, -4294967297.0,
               2.0 ** 52, 2.0 ** 52 + 1, 2.0 ** 53, -(2.0 ** 63), 2.0 ** 84 + 2.0 ** 33,
               1e300, -1e300, 5e-324, -5e-324, 2.2250738585072014e-308, math.inf, -math.inf,
               math.nan, 123456789.75, -987654321.25, 3.0e9, -3.0e9]

    def check(self, bits, fz):
        z = __import__("ctypes").c_int()
        fl = __import__("ctypes").c_uint32()
        got = LIB.fge_fjcvtzs(bits, (1 << 24) if fz else 0, z, fl)
        want, wz, wflags = ref_fjcvtzs(bits, fz)
        wfl = sum(FLAG_BITS[f] for f in wflags)
        self.assertEqual((got, z.value, fl.value), (want, wz, wfl), hex(bits))

    def test_special_values(self):
        for x in self.SPECIAL:
            for fz in (False, True):
                self.check(f64_bits(x), fz)
        self.check(0x7FF0000000000001, False)   # signalling NaN

    def test_random_bits(self):
        for _ in range(20000):
            self.check(RNG.getrandbits(64), RNG.random() < 0.2)

    def test_random_in_range(self):
        for _ in range(20000):
            x = RNG.uniform(-2.0 ** 34, 2.0 ** 34)
            if RNG.random() < 0.3:
                x = float(round(x))
            self.check(f64_bits(x), False)

    def test_instruction_writes_w_and_flags(self):
        m = Machine(LIB)
        m.vregs[1].lo = f64_bits(-1.0)
        m.ctx.x[0] = 0xFFFFFFFF_FFFFFFFF
        m.ctx.nzcv = N | C | V
        res, cls = m.run(assemble(["fjcvtzs w0, d1"])[0])
        self.assertEqual((res, cls), (HANDLED, "jscvt"))
        self.assertEqual(m.ctx.x[0], 0xFFFFFFFF, "a W write clears the upper half")
        self.assertEqual(m.ctx.nzcv, Z)
        m.vregs[1].lo = f64_bits(0.25)
        m.ctx.pc = 0x100000
        m.run(assemble(["fjcvtzs w0, d1"])[0])
        self.assertEqual((m.ctx.x[0], m.ctx.nzcv, m.fpsr.value & 0x10), (0, 0, 0x10))


def flags_tuple(f):
    return bool(f & N), bool(f & Z), bool(f & C), bool(f & V)


def pack(n, z, c, v):
    return (N if n else 0) | (Z if z else 0) | (C if c else 0) | (V if v else 0)


class FlagManipulation(unittest.TestCase):
    def run_flags(self, line, nzcv, setup=None):
        m = Machine(LIB)
        m.ctx.nzcv = nzcv | 0x3C0          # unrelated low bits must survive
        if setup:
            setup(m)
        res, _ = m.run(assemble([line])[0])
        self.assertEqual(res, HANDLED, line)
        self.assertEqual(m.ctx.nzcv & 0x0FFFFFFF, 0x3C0, line)
        return m.ctx.nzcv & 0xF0000000

    def test_cfinv_axflag_xaflag_exhaustive(self):
        for n, z, c, v in itertools.product((0, 1), repeat=4):
            f = pack(n, z, c, v)
            self.assertEqual(self.run_flags("cfinv", f), pack(n, z, not c, v))
            self.assertEqual(self.run_flags("axflag", f), pack(0, z or v, c and not v, 0))
            self.assertEqual(self.run_flags("xaflag", f),
                             pack(not c and not z, z and c, c or z, not c and z))

    def test_setf(self):
        for _ in range(300):
            w = RNG.getrandbits(32)
            f = pack(*(RNG.getrandbits(1) for _ in range(4)))
            for bits_ in (8, 16):
                got = self.run_flags(f"setf{bits_} w9", f,
                                     lambda m, w=w: m.ctx.x.__setitem__(9, w | (7 << 40)))
                low = w & ((1 << bits_) - 1)
                want = pack(low >> (bits_ - 1), low == 0, f & C,
                            ((w >> bits_) ^ (w >> (bits_ - 1))) & 1)
                self.assertEqual(got, want, (hex(w), bits_))

    def test_rmif(self):
        for _ in range(300):
            xn = RNG.getrandbits(64)
            sh, mask = RNG.randrange(64), RNG.randrange(16)
            f = pack(*(RNG.getrandbits(1) for _ in range(4)))
            got = self.run_flags(f"rmif x7, #{sh}, #{mask}", f,
                                 lambda m, xn=xn: m.ctx.x.__setitem__(7, xn))
            t = ((xn >> sh) | (xn << (64 - sh))) & (2 ** 64 - 1) if sh else xn
            want = 0
            for k, bit in enumerate((V, C, Z, N)):
                src = (t >> k) & 1 if mask & (1 << k) else bool(f & bit)
                want |= bit if src else 0
            self.assertEqual(got, want, (hex(xn), sh, mask))

    def test_sb(self):
        m = Machine(LIB)
        res, cls = m.run(assemble(["sb"])[0])
        self.assertEqual((res, cls, m.ctx.pc), (HANDLED, "sb", 0x100004))


class Rcpc2(unittest.TestCase):
    def test_loads(self):
        cases = [("ldapurb", 1, False, False), ("ldapurh", 2, False, False),
                 ("ldapur w", 4, False, False), ("ldapur x", 8, False, False),
                 ("ldapursb x", 1, True, False), ("ldapursh x", 2, True, False),
                 ("ldapursw", 4, True, False), ("ldapursb w", 1, True, True),
                 ("ldapursh w", 2, True, True)]
        for name, size, signed, to32 in cases:
            for off in (-256, -3, 0, 7, 255):
                val = RNG.getrandbits(8 * size) | (1 << (8 * size - 1))
                mnem, reg = (name.split() + [""])[:2]
                if not reg:
                    reg = "x" if mnem == "ldapursw" else "w"
                line = f"{mnem} {reg}3, [x2, #{off}]"
                m = Machine(LIB)
                m.ctx.x[2] = 0x8000
                m.ctx.x[3] = 2 ** 64 - 1
                m.poke(0x8000 + off, val, size)
                res, cls = m.run(assemble([line])[0])
                self.assertEqual((res, cls), (HANDLED, "rcpc2"), line)
                want = val
                if signed:
                    want = val - (1 << (8 * size)) if val >> (8 * size - 1) else val
                    want &= (1 << (32 if to32 else 64)) - 1
                self.assertEqual(m.ctx.x[3], want, line)
                self.assertEqual(m.barriers, 1, line)

    def test_stores(self):
        for name, size in (("stlurb w", 1), ("stlurh w", 2), ("stlur w", 4), ("stlur x", 8)):
            mnem, reg = name.split()
            m = Machine(LIB)
            m.ctx.sp = 0x9100
            m.ctx.x[5] = 0x0102030405060708
            res, _ = m.run(assemble([f"{mnem} {reg}5, [sp, #-16]"])[0])
            self.assertEqual(res, HANDLED, name)
            self.assertEqual(m.peek(0x90F0, size), 0x0102030405060708 & ((1 << (8 * size)) - 1))
            self.assertEqual(m.peek(0x90F0 + size, 1), 0, "no bytes beyond the size")

    def test_fault_leaves_state(self):
        m = Machine(LIB)
        m.ctx.x[2] = 0x5000
        m.faulting.add(0x5)
        before = m.snapshot()
        res, _ = m.run(assemble(["ldapur x3, [x2, #8]"])[0])
        self.assertEqual(res, MEM_FAULT)
        self.assertEqual(m.snapshot(), before)


class PstateHints(unittest.TestCase):
    def test_dit_ssbs(self):
        m = Machine(LIB)
        m.ctx.x[3] = 77
        for line in ("msr dit, #1", "msr ssbs, #1", "msr dit, x4", "mrs x3, dit"):
            m.ctx.pc = 0x100000
            res, cls = m.run(assemble([line])[0])
            self.assertEqual((res, cls, m.ctx.pc), (HANDLED, "pstate", 0x100004), line)
        self.assertEqual(m.ctx.x[3], 0)


if __name__ == "__main__":
    unittest.main()
