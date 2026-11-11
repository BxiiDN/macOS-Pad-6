"""The C scanner (tools/isa/scan.c) and the Python rules (features.py) must agree.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import random
import struct
import subprocess
import sys
import unittest

from tools.isa import fast, features, macho

RNG = random.Random(99)


class Parity(unittest.TestCase):
    def test_rules_header_current(self):
        p = subprocess.run([sys.executable, "-m", "tools.isa.gen_rules", "--check"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_random_and_near_rule_words(self):
        words = [RNG.getrandbits(32) for _ in range(200000)]
        for _n, mask, value, _f, _e in features.RULES:
            for _ in range(5000):
                w = (value & mask) | (RNG.getrandbits(32) & ~mask & 0xFFFFFFFF)
                if RNG.random() < 0.3:
                    w ^= 1 << RNG.choice([b for b in range(32) if mask >> b & 1])
                words.append(w)
        for w in words:
            py = features.classify(w)
            self.assertEqual(fast.classify(w), py[0] if py else None, hex(w))

    def test_scan_counts_and_offsets(self):
        words = [RNG.getrandbits(32) for _ in range(50000)] + [0xD65F0FFF] * 7
        RNG.shuffle(words)
        buf = bytearray(struct.pack(f"<{len(words)}I", *words))
        rng = macho.CodeRange(0, len(buf), "all", exclude=[(40, 8)])
        counts, hits = fast.scan(buf, [rng], record=["pac-branch"])
        want = {}
        want_offs = []
        for k, w in enumerate(words):
            if k in (10, 11):
                continue
            hit = features.classify(w)
            if hit:
                want[hit[0]] = want.get(hit[0], 0) + 1
                if hit[0] == "pac-branch":
                    want_offs.append(4 * k)
        self.assertEqual(dict(counts), want)
        self.assertEqual(hits["pac-branch"], want_offs)


if __name__ == "__main__":
    unittest.main()
