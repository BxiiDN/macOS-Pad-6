#!/usr/bin/env python3
"""Compare two kernel builds of the same source made in the same place: native kernel, link map, symbols, kernel collection.

    scripts/repro_compare.py --first OUT/pipa.first --second OUT/pipa [--json OUT]      (macOS runner)

kernel-build.yml's "[kernel-repro]" moves the first build aside and builds again from scratch (and prelinks again when the
run prelinks). This compares, file by file: SHA-256 and size of the native kernel and of the kernel collection, their
LC_UUID, the external symbol table of the native kernel (xcrun nm -gP: name, type and address of every symbol), and
ld64's link map (which object put which atom where). Any difference fails, with the first differing lines shown. Only
hashes, sizes, counts and short excerpts are printed; no Apple code.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

LC_UUID = 0x1B


def find(root, pattern):
    hits = sorted(Path(root).rglob(pattern))
    return hits[0] if hits else None


def collection(root):
    """kernel/kernel.macho when it is a kernel collection (MH_FILESET); without a prelink the step leaves the native
    kernel there instead."""
    for path in sorted(Path(root).rglob("kernel.macho")):
        if path.parent.name == "kernel" and struct.unpack_from("<I", path.read_bytes()[:16], 12)[0] == 0xC:
            return path
    return None


def uuid(path):
    data = path.read_bytes()
    _, _, _, _, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", data, 0)
    at = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, at)
        if cmd == LC_UUID:
            return data[at + 8:at + 24].hex()
        at += size
    return None


def describe(path):
    if path is None or not path.is_file():
        return None
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def first_difference(a, b, limit=5):
    la, lb = a.read_text(errors="replace").splitlines(), b.read_text(errors="replace").splitlines()
    out = []
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            out.append({"line": i + 1, "first": x[:200], "second": y[:200]})
            if len(out) >= limit:
                break
    if not out and len(la) != len(lb):
        out.append({"line": min(len(la), len(lb)) + 1, "first_lines": len(la), "second_lines": len(lb)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--first", type=Path, required=True)
    ap.add_argument("--second", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    result, problems = {}, []
    files = {}
    for side, root in (("first", args.first), ("second", args.second)):
        files[side] = {"kernel": find(root, "mach.development.bcm2837.unstripped.noctf"),
                       "link_map": find(root, "kernel-link.map"),
                       "collection": collection(root)}
    for kind in ("kernel", "collection", "link_map"):
        a, b = describe(files["first"][kind]), describe(files["second"][kind])
        row = {"first": a, "second": b}
        if a is None and b is None:
            row["compared"] = False
        else:
            row["compared"] = True
            row["equal"] = bool(a and b and a["sha256"] == b["sha256"] and a["bytes"] == b["bytes"])
            if kind != "link_map" and a and b:
                row["uuid"] = [uuid(files["first"][kind]), uuid(files["second"][kind])]
                row["uuid_equal"] = row["uuid"][0] == row["uuid"][1]
            if not row["equal"]:
                problems.append(f"{kind} differs")
                if kind == "link_map" and a and b:
                    row["first_differences"] = first_difference(files["first"][kind], files["second"][kind])
        result[kind] = row
    if files["first"]["kernel"] and files["second"]["kernel"]:
        tables = [subprocess.run(["xcrun", "nm", "-gP", str(files[s]["kernel"])], capture_output=True, text=True,
                                 check=True).stdout.splitlines() for s in ("first", "second")]
        result["symbols"] = {"first": len(tables[0]), "second": len(tables[1]), "equal": tables[0] == tables[1]}
        if not result["symbols"]["equal"]:
            problems.append("external symbol tables differ")
            result["symbols"]["only_first"] = sorted(set(tables[0]) - set(tables[1]))[:10]
            result["symbols"]["only_second"] = sorted(set(tables[1]) - set(tables[0]))[:10]
    else:
        problems.append("a native kernel is missing")
    result["problems"] = problems
    text = json.dumps(result, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    if problems:
        sys.exit("builds differ: " + "; ".join(problems))
    print("identical: native kernel, link map, external symbols"
          + (", kernel collection" if result["collection"]["compared"] else ""))


if __name__ == "__main__":
    main()
