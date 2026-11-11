"""Cross-check fge_classify() against LLVM's disassembler on random encodings.

For each emulated class, words are drawn around its fixed bits (free fields
random, sometimes one fixed bit flipped), disassembled by llvm-mc, and the
two decoders must agree: FGE claims a word if and only if LLVM decodes it to
one of that class's mnemonics.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import random
import re
import subprocess
import unittest

from tests.fge.fgelib import CLASSES, LLVM_MATTR, find_tool, load

LIB = load()
RNG = random.Random(87011)

# (base, fixed-bit mask) per class, and the LLVM mnemonics that belong to it.
FAMILIES = {
    "pac-dp1": ((0xDAC10000, 0xFFFF0000),
                {"pacia", "pacib", "pacda", "pacdb", "autia", "autib", "autda", "autdb",
                 "paciza", "pacizb", "pacdza", "pacdzb", "autiza", "autizb", "autdza", "autdzb",
                 "xpaci", "xpacd"}),
    "pacga": ((0x9AC03000, 0xFFE0FC00), {"pacga"}),
    "pac-branch": ((0xD61F0800, 0xFE1FF800),
                   {"braa", "brab", "blraa", "blrab", "braaz", "brabz", "blraaz", "blrabz",
                    "retaa", "retab"}),
    "pac-load": ((0xF8200400, 0xFF200400), {"ldraa", "ldrab"}),
    "jscvt": ((0x1E7E0000, 0xFFFFFC00), {"fjcvtzs"}),
    "flagm": ((0xBA000400, 0xFFE07C10), {"rmif", "setf8", "setf16", "cfinv"}),
    "rcpc2": ((0x19000000, 0x3F200C00),
              {"ldapurb", "ldapurh", "ldapur", "ldapursb", "ldapursh", "ldapursw",
               "stlurb", "stlurh", "stlur"}),
}
ALL_EMULATED = set().union(*(m for _, m in FAMILIES.values())) | {"axflag", "xaflag", "sb"}

_WARN = re.compile(r"<stdin>:(\d+):\d+: warning: invalid instruction encoding")


def disassemble(words):
    src = "".join(" ".join(f"0x{(w >> s) & 0xFF:02x}" for s in (0, 8, 16, 24)) + "\n"
                  for w in words)
    p = subprocess.run([find_tool("llvm-mc"), "--disassemble", "-triple=aarch64",
                        f"-mattr={LLVM_MATTR}"], input=src, capture_output=True, text=True)
    bad = {int(m.group(1)) - 1 for m in _WARN.finditer(p.stderr)}
    good = [ln.strip() for ln in p.stdout.splitlines()
            if ln.strip() and not ln.strip().startswith(".")]
    it = iter(good)
    return [None if k in bad else next(it) for k in range(len(words))]


class FuzzAgreement(unittest.TestCase):
    def sample(self, base, mask, n):
        out = []
        for _ in range(n):
            w = (base & mask) | (RNG.getrandbits(32) & ~mask & 0xFFFFFFFF)
            if RNG.random() < 0.3:
                w ^= 1 << RNG.choice([b for b in range(32) if mask >> b & 1])
            out.append(w)
        return out

    def test_agreement(self):
        words = []
        for (base, mask), _ in FAMILIES.values():
            words += self.sample(base, mask, 4000)
        texts = disassemble(words)
        checked = 0
        for w, text in zip(words, texts):
            cls = CLASSES[LIB.fge_classify(w, 0)]
            mnem = text.split()[0] if text else None
            if cls != "none":
                self.assertIsNotNone(mnem, f"FGE claims an invalid encoding {w:#010x}")
                self.assertIn(mnem, FAMILIES.get(cls, (None, ALL_EMULATED))[1],
                              f"{w:#010x}: FGE says {cls}, LLVM says {text}")
                checked += 1
            elif mnem in ALL_EMULATED:
                self.fail(f"{w:#010x}: LLVM decodes {text!r} but FGE does not claim it")
        self.assertGreater(checked, 5000)


if __name__ == "__main__":
    unittest.main()
