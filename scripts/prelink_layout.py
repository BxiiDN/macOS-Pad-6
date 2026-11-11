#!/usr/bin/env python3
"""Where the native kernel's __TEXT could go in a kernel collection, as UniXNU's XnuPrelink sees it.

    scripts/prelink_layout.py --xnuprelink DIR --kernelcache KC --kernel NATIVE --profile PROFILE.toml [--json OUT]

XnuPrelink (fileset_layout.Layout) places the native __TEXT in a hole of the collection's
__PRELINK_TEXT that no retained kext (the dependency closure of the profile's prelink roots)
occupies. This prints, for that segment: its range, every fileset entry with a segment inside it
(retained or not, with sizes), the holes between retained kexts, the largest hole, and the
native __TEXT size. Only addresses, sizes and bundle identifiers are printed; no Apple code.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import sys
import tomllib
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xnuprelink", type=Path, required=True)
    ap.add_argument("--kernelcache", type=Path, required=True)
    ap.add_argument("--kernel", type=Path, required=True)
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    sys.path.insert(0, str(args.xnuprelink))
    from kc_image import Image
    from fileset_emit import dependency_closure

    cache = Image(args.kernelcache.read_bytes())
    native = Image(args.kernel.read_bytes())
    roots = tomllib.loads(args.profile.read_text())["kernel"]["prelink"]["roots"]
    closure = dependency_closure(cache, roots)
    root = next(s for s in cache.segments if s["name"] == "__PRELINK_TEXT")
    lo, hi = root["va"], root["va"] + root["size"]
    entries = []
    for name, (_, offset) in cache.entries.items():
        for seg in Image(cache.data, offset).segments:
            if seg["size"] and seg["name"] != "__LINKEDIT" and lo <= seg["va"] < hi:
                entries.append({"bundle": name, "segment": seg["name"], "va": seg["va"], "size": seg["size"],
                                "retained": name != "com.apple.kernel" and (closure is None or name in closure)})
    entries.sort(key=lambda e: e["va"])
    occupied = sorted((e["va"], e["va"] + e["size"]) for e in entries if e["retained"])
    holes, cursor = [], lo
    for begin, end in occupied:
        if begin > cursor:
            holes.append((cursor, begin))
        cursor = max(cursor, end)
    if cursor < hi:
        holes.append((cursor, hi))
    need = next(s["size"] for s in native.segments if s["name"] == "__TEXT")
    kernel_text = [e for e in entries if e["bundle"] == "com.apple.kernel"]
    largest = max((b - a for a, b in holes), default=0)
    page = 0x4000   # XnuPrelink's PAGE: the native __TEXT starts on a 16 KiB boundary inside the hole
    usable = [(b - ((a + page - 1) & -page), a, b) for a, b in holes]
    fit = max(usable, default=(0, 0, 0))
    report = {
        "prelink_text": {"va": hex(lo), "size": hex(root["size"])},
        "native_text_size": hex(need),
        "original_kernel_segments_in_prelink_text": [
            {"segment": e["segment"], "va": hex(e["va"]), "size": hex(e["size"])} for e in kernel_text],
        "retained_kexts": len(closure or []),
        "holes": [{"va": hex(a), "size": hex(b - a)} for a, b in holes],
        "largest_hole": hex(largest),
        "short_by": hex(max(0, need - largest)),
        "largest_usable_after_alignment": hex(fit[0]),
        "fits": fit[0] >= need,
        "margin_bytes": fit[0] - need,
        "first_entries": [dict(e, va=hex(e["va"]), size=hex(e["size"])) for e in entries[:40]],
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
