#!/usr/bin/env python3
"""Census of AArch64 instructions that Snapdragon 870 cores cannot execute.

    python3 -m tools.isa.audit [--json OUT] [--fail-on CLASSES] FILE...

FILE is a Mach-O (thin, fat, MH_FILESET kernel collection) or a dyld shared
cache file. The scan is static: it counts instruction words in code sections
(minus LC_DATA_IN_CODE), not executions. A word inside code that is really
data can be miscounted; the counts are evidence for planning, not proof.
Hint-space PAC and BTI instructions are NOPs on these cores and not counted.

--fail-on takes rule names or features (comma separated, e.g. "PAuth" or
"pac-branch,jscvt") and exits 1 if any are found: the build gate after
tools/isa/pacstrip on a kernel collection.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import mmap

from tools.isa import fast, features, macho


def audit_bytes(data, name, images=None):
    """Census of one file's code. data: bytes, bytearray or a writable mmap."""
    buf = data if isinstance(data, (bytearray, mmap.mmap)) else bytearray(data)
    report = {"file": name, "images": [], "totals": Counter(), "needs": Counter(),
              "emulated": 0, "not_emulated": 0, "hints": Counter(), "words": 0}
    fge = {r[0]: r[4] for r in features.RULES}
    needs = {r[0]: r[3] for r in features.RULES}
    for img in (images if images is not None else macho.images_of(buf, name)):
        counts, _ = fast.scan(buf, img.ranges)
        words = sum(len(range(lo, hi, 4)) for r in img.ranges for lo, hi in fast._pieces(r, len(buf)))
        for rule, n in counts.items():
            report["needs"][needs[rule]] += n
            report["emulated" if fge[rule] else "not_emulated"] += n
        report["images"].append({"name": img.name, "arm64e": img.cpusubtype == 2,
                                 "code_words": words, "counts": dict(counts),
                                 "code_signature": img.has_code_signature})
        report["totals"].update(counts)
        report["words"] += words
    return report


def audit_file(path):
    """mmap a file privately (copy-on-write, never written back) and audit it."""
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_COPY)
        try:
            return audit_bytes(mm, str(path))
        finally:
            mm.close()


def to_json(report):
    out = dict(report)
    for k in ("totals", "needs", "hints"):
        out[k] = dict(sorted(report[k].items()))
    return out


def print_report(r, out=sys.stdout):
    print(f"{r['file']}: {len(r['images'])} image(s), {r['words']} code words", file=out)
    if not r["totals"]:
        print("  no instruction outside ARMv8.2+RCpc+DotProd", file=out)
    for rule, n in sorted(r["totals"].items(), key=lambda kv: -kv[1]):
        fge = next(x[4] for x in features.RULES if x[0] == rule)
        need = next(x[3] for x in features.RULES if x[0] == rule)
        print(f"  {rule:14} {n:>10}  needs {need:12} {'FGE' if fge else 'NOT EMULATED'}", file=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--fail-on", default="")
    args = ap.parse_args(argv)
    reports = []
    for f in args.files:
        try:
            r = audit_file(f)
        except macho.FormatError as e:
            print(f"{f}: {e}", file=sys.stderr)
            return 2
        print_report(r)
        reports.append(r)
    if args.json:
        args.json.write_text(json.dumps([to_json(r) for r in reports], indent=2) + "\n")
    gate = {x.strip() for x in args.fail_on.split(",") if x.strip()}
    if gate:
        bad = {rule: n for r in reports for rule, n in r["totals"].items()
               if rule in gate or next(x[3] for x in features.RULES if x[0] == rule) in gate}
        if bad:
            print(f"FAIL: {bad}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
