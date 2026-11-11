"""Tests of tools/isa: feature masks vs LLVM, pacstrip rewrites, Mach-O parsing.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import random
import re
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fge.fgelib import CLASSES, LLVM_MATTR, find_tool, load
from tests.fge.test_fge_fuzz import disassemble
from tools.isa import audit, features, macho, pacstrip

RNG = random.Random(4242)
MATTR = LLVM_MATTR + ",+complxnum,+sha3,+fptoint,+fullfp16,+fp16fml"

MNEMONICS = {
    "pac-dp1": {"pacia", "pacib", "pacda", "pacdb", "autia", "autib", "autda", "autdb",
                "paciza", "pacizb", "pacdza", "pacdzb", "autiza", "autizb", "autdza",
                "autdzb", "xpaci", "xpacd"},
    "pacga": {"pacga"},
    "pac-branch": {"braa", "brab", "blraa", "blrab", "braaz", "brabz", "blraaz", "blrabz",
                   "retaa", "retab"},
    "pac-eret": {"eretaa", "eretab"},
    "pac-load": {"ldraa", "ldrab"},
    "pac-keyreg": {"msr", "mrs"},
    "jscvt": {"fjcvtzs"},
    "fcadd": {"fcadd"}, "fcmla": {"fcmla"}, "fcmla-elem": {"fcmla"},
    "cfinv": {"cfinv"}, "rmif": {"rmif"}, "setf": {"setf8", "setf16"},
    "axflag": {"axflag"}, "xaflag": {"xaflag"}, "sb": {"sb"},
    "rcpc2": {"ldapurb", "ldapurh", "ldapur", "ldapursb", "ldapursh", "ldapursw",
              "stlurb", "stlurh", "stlur"},
    "msr-dit": {"msr"}, "dit-reg": {"msr", "mrs"}, "msr-ssbs": {"msr"},
    "eor3-bcax": {"eor3", "bcax"},
    "sha512-rax1": {"sha512h", "sha512h2", "sha512su1", "rax1"},
    "xar": {"xar"}, "sha512su0": {"sha512su0"},
    "fmlal-vec": {"fmlal", "fmlsl"}, "fmlal2-vec": {"fmlal2", "fmlsl2"},
    "fmlal-elem": {"fmlal", "fmlsl"}, "fmlal2-elem": {"fmlal2", "fmlsl2"},
    "frint-scalar": {"frint32z", "frint32x", "frint64z", "frint64x"},
    "frint-vector": {"frint32z", "frint32x", "frint64z", "frint64x"},
}
ALL = set().union(*MNEMONICS.values()) - {"msr", "mrs"}


def disasm(words):
    src = "".join(" ".join(f"0x{(w >> s) & 0xFF:02x}" for s in (0, 8, 16, 24)) + "\n"
                  for w in words)
    p = subprocess.run([find_tool("llvm-mc"), "--disassemble", "-triple=aarch64",
                        f"-mattr={MATTR}"], input=src, capture_output=True, text=True)
    bad = {int(m.group(1)) - 1 for m in
           re.finditer(r"<stdin>:(\d+):\d+: warning: invalid instruction encoding", p.stderr)}
    good = iter([ln.strip() for ln in p.stdout.splitlines()
                 if ln.strip() and not ln.strip().startswith(".")])
    return [None if k in bad else next(good) for k in range(len(words))]


class FeatureMasks(unittest.TestCase):
    def test_rules_agree_with_llvm(self):
        words = []
        for _name, mask, value, _n, _f in features.RULES:
            for _ in range(1500):
                w = (value & mask) | (RNG.getrandbits(32) & ~mask & 0xFFFFFFFF)
                if RNG.random() < 0.25:
                    w ^= 1 << RNG.choice([b for b in range(32) if mask >> b & 1])
                words.append(w)
        hits = 0
        for w, text in zip(words, disasm(words)):
            hit = features.classify(w)
            mnem = text.split()[0] if text else None
            if hit:
                self.assertIsNotNone(mnem, f"{w:#010x} classified {hit[0]} but invalid for LLVM")
                self.assertIn(mnem, MNEMONICS[hit[0]], f"{w:#010x}: {hit[0]} vs {text}")
                if mnem in ("msr", "mrs"):
                    self.assertRegex(text.upper(), r"AP[A-Z]+KEY|DIT|SSBS")
                hits += 1
            elif mnem in ALL:
                # LLVM also decodes CFINV/AXFLAG/XAFLAG/SB with a nonzero should-be-zero
                # CRm; no assembler emits those, and the rules take canonical forms only.
                if mnem in ("cfinv", "axflag", "xaflag", "sb") and (w & 0xFFFFF0FF) in (
                        0xD500401F, 0xD500405F, 0xD500403F, 0xD50330FF):
                    continue
                self.fail(f"{w:#010x}: LLVM decodes {text!r}, no rule matches")
        self.assertGreater(hits, 20000)

    def test_native_v82_words_are_clean(self):
        # A sample of ordinary ARMv8.2 + RCpc + DotProd code must classify as runnable.
        lines = ["ret", "blr x8", "ldr x0, [x1, #8]", "ldapr x0, [x1]", "udot v0.4s, v1.16b, v2.16b",
                 "paciasp", "autibsp", "fmla v0.4s, v1.4s, v2.4s", "casal x0, x1, [x2]",
                 "sqrdmlah v0.4s, v1.4s, v2.4s", "fcvtzs w0, d1", "dc cvap, x0", "msr pan, #1"]
        out = subprocess.run([find_tool("llvm-mc"), "-triple=aarch64", f"-mattr={MATTR},+v8.2a",
                              "-show-encoding"], input="\n".join(lines) + "\n",
                             capture_output=True, text=True, check=True).stdout
        for enc in re.findall(r"encoding: \[([^\]]+)\]", out):
            b = [int(x, 16) for x in enc.split(",")]
            w = b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24
            self.assertIsNone(features.classify(w), hex(w))

    def test_fge_and_rules_agree(self):
        """Every word the C emulator claims is a rule marked fge=True, and vice versa."""
        lib = load()
        rule_to_fge = {"pac-dp1": "pac-dp1", "pacga": "pacga", "pac-branch": "pac-branch",
                       "pac-load": "pac-load", "pac-keyreg": "pac-keyreg", "jscvt": "jscvt",
                       "cfinv": "flagm", "rmif": "flagm", "setf": "flagm", "axflag": "flagm2",
                       "xaflag": "flagm2", "sb": "sb", "rcpc2": "rcpc2", "msr-dit": "pstate",
                       "dit-reg": "pstate", "msr-ssbs": "pstate"}
        for name, mask, value, _n, fge in features.RULES:
            for _ in range(2000):
                w = (value & mask) | (RNG.getrandbits(32) & ~mask & 0xFFFFFFFF)
                hit = features.classify(w)
                c_cls = CLASSES[lib.fge_classify(w, 1)]
                if hit and hit[2]:
                    self.assertEqual(c_cls, rule_to_fge[hit[0]], f"{w:#010x} {hit}")
                elif c_cls != "none":
                    self.fail(f"{w:#010x}: FGE claims {c_cls}, rules say {hit}")


FIXTURE = """
\t.text
\t.globl _f
_f:
\tpacibsp
\tpaciza x1
\tautdzb x2
\txpaci x3
\tautia x9, sp
\tpacga x4, x5, x6
\tldraa x0, [x1, #-8]!
\tldrab x7, [sp, #4088]
\tldraa x8, [x9, #-4096]
\tldraa x10, [x11, #-200]
\tldrab x12, [x13, #8]!
\tldraa x14, [x15, #-512]!
\tldraa xzr, [x2]
\tblraa x8, x17
\tblrabz x30
\tbraaz x16
\tbrab x1, sp
\tretab
\t.data_region
\t.long 0xd65f0fff
\t.long 0xdac10000
\t.end_data_region
\tfjcvtzs w0, d1
\tmsr apiakeylo_el1, x0
\tmrs x5, apdbkeyhi_el1
\tmrs xzr, apgakeylo_el1
\teretab
\tretaa
"""


def assemble_macho(src, path):
    subprocess.run([find_tool("llvm-mc"), "-triple=arm64e-apple-macos13",
                    "-mattr=+v8.5a,+pauth,+jsconv", "-filetype=obj", "-o", str(path)],
                   input=src, text=True, check=True)
    return path.read_bytes()


def text_words(data):
    img = macho.images_of(data)[0]
    rng = img.ranges[0]
    return [struct.unpack_from("<I", data, o)[0] for o in range(rng.offset, rng.offset + rng.size, 4)]


def operands(text):
    regs = re.findall(r"\b([xw]\d+|xzr|sp|lr)\b", text)
    regs = ["x30" if r == "lr" else r for r in regs]
    imm = re.findall(r"#(-?0x[0-9a-f]+|-?\d+)", text)
    return regs, [int(i, 0) for i in imm], text.rstrip().endswith("!")


class Pacstrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.obj = assemble_macho(FIXTURE, Path(cls.tmp.name) / "f.o")
        cls.out, cls.report = pacstrip.strip_bytes(cls.obj)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_size_and_non_code_unchanged(self):
        self.assertEqual(len(self.out), len(self.obj))
        rng = macho.images_of(self.obj)[0].ranges[0]
        self.assertEqual(self.out[:rng.offset], self.obj[:rng.offset])
        self.assertEqual(self.out[rng.offset + rng.size:], self.obj[rng.offset + rng.size:])

    def test_data_in_code_untouched(self):
        before, after = text_words(self.obj), text_words(self.out)
        k = before.index(0xDAC10000)                     # second data word
        self.assertEqual(before[k - 1:k + 1], [0xD65F0FFF, 0xDAC10000])
        self.assertEqual(after[k - 1:k + 1], before[k - 1:k + 1])

    def test_each_rewrite_is_equivalent(self):
        before, after = text_words(self.obj), text_words(self.out)
        tb, ta = disasm(before), disasm(after)
        changed = 0
        for wb, wa, b, a in zip(before, after, tb, ta):
            if wb == wa:
                continue
            changed += 1
            mb, ma = b.split()[0], a.split()[0]
            rb, ib, wbk = operands(b)
            ra, ia, wak = operands(a)
            if mb in MNEMONICS["pac-dp1"] or mb == "msr":
                self.assertEqual(ma, "nop", b)
            elif mb == "mrs" and rb[0] == "xzr":
                self.assertEqual(ma, "nop", b)
            elif mb == "mrs":
                self.assertIn(ma, ("mov", "movz"), b)
                self.assertEqual((ra[0], ia), (rb[0], [0]), b)
            elif mb in ("retaa", "retab"):
                self.assertEqual(a, "ret", b)
            elif mb in ("eretaa", "eretab"):
                self.assertEqual(a, "eret", b)
            elif mb in ("braa", "brab", "braaz", "brabz"):
                self.assertEqual((ma, ra[0]), ("br", rb[0]), b)
            elif mb in ("blraa", "blrab", "blraaz", "blrabz"):
                self.assertEqual((ma, ra[0]), ("blr", rb[0]), b)
            elif mb in ("ldraa", "ldrab"):
                self.assertIn(ma, ("ldr", "ldur"), a)
                self.assertEqual(ra[:2], rb[:2], (b, a))           # Xt and base
                self.assertEqual((ia or [0])[0], (ib or [0])[0], (b, a))
                self.assertEqual(wak, wbk, (b, a))
            else:
                self.fail(f"unexpected rewrite {b!r} -> {a!r}")
        self.assertEqual(changed, sum(self.report["rewritten"].values()))

    def test_residue_and_audit_gate(self):
        self.assertEqual(self.report["left_for_fge"], {"pacga": 1, "pac-load": 2})
        r = audit.audit_bytes(self.out, "f2.o")
        self.assertEqual(dict(r["totals"]), {"pacga": 1, "pac-load": 2, "jscvt": 1})
        path = Path(self.tmp.name) / "f2.o"
        path.write_bytes(self.out)
        self.assertEqual(audit.main([str(path), "--fail-on", "pac-branch,pac-dp1"]), 0)
        self.assertEqual(audit.main([str(path), "--fail-on", "PAuth"]), 1)


class Containers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.obj = assemble_macho(FIXTURE, Path(self.tmp.name) / "f.o")
        self.base = audit.audit_bytes(self.obj, "f.o")["totals"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_fat(self):
        off = 0x4000
        hdr = struct.pack(">II", macho.FAT_MAGIC, 2)
        hdr += struct.pack(">iiIII", 7, 3, 0, 0, 12)                       # an x86_64 slice entry
        hdr += struct.pack(">iiIII", macho.CPU_TYPE_ARM64, 2, off, len(self.obj), 14)
        fat = hdr.ljust(off, b"\0") + self.obj
        r = audit.audit_bytes(fat, "fat")
        self.assertEqual(r["totals"], self.base)
        self.assertEqual(r["images"][0]["name"], "slice:arm64e")
        out, rep = pacstrip.strip_bytes(fat)
        self.assertEqual(out[off:], pacstrip.strip_bytes(self.obj)[0])

    def test_fileset(self):
        # A fileset whose single entry is the object, with its section offsets made
        # relative to the collection as in a real kernel collection.
        off = 0x1000
        entry = bytearray(self.obj)
        ncmds, sizeofcmds = struct.unpack_from("<II", entry, 16)
        p = 32
        for _ in range(ncmds):
            cmd, size = struct.unpack_from("<II", entry, p)
            if cmd == macho.LC_SEGMENT_64:
                fo = struct.unpack_from("<Q", entry, p + 40)[0]
                struct.pack_into("<Q", entry, p + 40, fo + off)
                for k in range(struct.unpack_from("<I", entry, p + 64)[0]):
                    s = p + 72 + 80 * k
                    so = struct.unpack_from("<I", entry, s + 48)[0]
                    if so:
                        struct.pack_into("<I", entry, s + 48, so + off)
            elif cmd == macho.LC_DATA_IN_CODE:
                do = struct.unpack_from("<I", entry, p + 8)[0]
                struct.pack_into("<I", entry, p + 8, do + off)
            p += size
        name = b"com.example.kext\0"
        lc = struct.pack("<IIQQII", macho.LC_FILESET_ENTRY, 32 + len(name), 0, off, 32, 0) + name
        lc = lc.ljust((len(lc) + 7) & ~7, b"\0")
        lc = struct.pack("<II", macho.LC_FILESET_ENTRY, len(lc)) + lc[8:]
        hdr = struct.pack("<IiiIIIII", macho.MH_MAGIC_64, macho.CPU_TYPE_ARM64, 2,
                          macho.MH_FILESET, 1, len(lc), 0, 0)
        kc = (hdr + lc).ljust(off, b"\0") + bytes(entry)
        imgs = macho.images_of(kc)
        self.assertEqual([i.name for i in imgs], ["com.example.kext"])
        self.assertEqual(audit.audit_bytes(kc, "kc")["totals"], self.base)

    def test_dyld_cache_header(self):
        code = self.obj
        rng = macho.images_of(code)[0].ranges[0]
        body = code[rng.offset:rng.offset + rng.size]
        hdr = bytearray(b"dyld_v1   arm64e\0".ljust(0x20, b"\0"))
        struct.pack_into("<II", hdr, 0x10, 0x20, 2)
        maps = struct.pack("<QQQII", 0x180000000, len(body), 0x1000, 5, 5)
        maps += struct.pack("<QQQII", 0x1C0000000, 0x10, 0x2000, 3, 3)   # rw data: skipped
        cache = (bytes(hdr) + maps).ljust(0x1000, b"\0") + body
        cache = cache.ljust(0x2010, b"\0")
        r = audit.audit_bytes(cache, "cache")
        # The data-in-code words are not marked in a cache, so they count as code here.
        self.assertEqual(r["totals"]["pac-branch"], self.base["pac-branch"] + 1)
        self.assertTrue(r["images"][0]["arm64e"])


if __name__ == "__main__":
    unittest.main()
