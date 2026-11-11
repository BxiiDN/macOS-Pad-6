#!/usr/bin/env python3
"""Rewrite non-hint PAC instructions into their exact ARMv8.2 equivalents.

    python3 -m tools.isa.pacstrip IN OUT [--report JSON]

Under "null PAC" (signing and authentication are the identity, see
kernel/fge/fge.h) each rewrite below has the same architectural effect as
the original instruction, so code runs without trapping:

    PACIA..AUTDZB, XPACI, XPACD       -> NOP
    RETAA, RETAB                      -> RET
    BRAA(Z), BRAB(Z) Xn               -> BR Xn
    BLRAA(Z), BLRAB(Z) Xn             -> BLR Xn
    ERETAA, ERETAB                    -> ERET
    LDRAA/LDRAB Xt, [Xn, #off]        -> LDR (unsigned offset) or LDUR
    LDRAA/LDRAB Xt, [Xn, #off]!       -> LDR (pre-index) when -256 <= off <= 255
    MSR AP*Key*_EL1, Xt               -> NOP
    MRS Xt, AP*Key*_EL1               -> MOVZ Xt, #0

Left in place (FGE emulates them when they trap): PACGA, and LDRAA forms
whose offset no single LDR can express. Words in LC_DATA_IN_CODE ranges are
never touched. The file size and layout do not change; code signatures in
the file become invalid and are reported.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

from tools.isa import features, macho

NOP = 0xD503201F
RET = 0xD65F03C0
ERET = 0xD69F03E0


def rewrite_word(w):
    """Return (new_word, rule) or (None, rule) when no exact rewrite exists, or None."""
    hit = features.classify(w)
    if not hit or hit[1] != "PAuth":
        return None                                    # not a PAC instruction
    rule = hit[0]
    rn, rt = (w >> 5) & 0x1F, w & 0x1F
    if rule == "pac-dp1":
        return NOP, rule
    if rule == "pac-branch":
        opc = (w >> 21) & 0xF
        if opc == 2:
            return RET, rule
        if opc in (0, 8):
            return 0xD61F0000 | rn << 5, rule
        return 0xD63F0000 | rn << 5, rule            # opc 1, 9
    if rule == "pac-eret":
        return ERET, rule
    if rule == "pac-keyreg":
        if (w >> 21) & 1:                             # MRS
            return (0xD2800000 | rt) if rt != 31 else NOP, rule
        return NOP, rule
    if rule == "pac-load":
        simm10 = ((w >> 22) & 1) << 9 | ((w >> 12) & 0x1FF)
        off = (simm10 - 1024 if simm10 & 512 else simm10) * 8
        if (w >> 11) & 1:                             # pre-index writeback
            if -256 <= off <= 255 and rt != rn:
                return 0xF8400C00 | (off & 0x1FF) << 12 | rn << 5 | rt, rule
            return None, rule
        if off >= 0:
            return 0xF9400000 | (off // 8) << 10 | rn << 5 | rt, rule
        if off >= -256:
            return 0xF8400000 | (off & 0x1FF) << 12 | rn << 5 | rt, rule
        return None, rule
    return None, rule                                  # PACGA


def strip_bytes(data):
    buf = bytearray(data)
    done, kept, signed = Counter(), Counter(), []
    for img in macho.images_of(bytes(buf)):
        if img.has_code_signature:
            signed.append(img.name)
        for rng in img.ranges:
            for off, w in macho.iter_words(buf, rng):
                r = rewrite_word(w)
                if r is None:
                    continue
                new, rule = r
                if new is None:
                    kept[rule] += 1
                else:
                    struct.pack_into("<I", buf, off, new)
                    done[rule] += 1
    return bytes(buf), {"rewritten": dict(done), "left_for_fge": dict(kept),
                        "invalidated_code_signatures": signed}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    out, report = strip_bytes(args.input.read_bytes())
    args.output.write_bytes(out)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
