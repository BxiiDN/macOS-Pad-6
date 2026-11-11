#!/usr/bin/env python3
"""Where the bytes of a native XNU kernel come from.

    scripts/kernel_size_audit.py --kernel K --map LINK.map [--patches LIST] [--xnu-source DIR]
                                 [--strip-prefix P ...] [--json OUT] [--markdown OUT]

--map is ld64's link map of K (-Wl,-map,FILE): it names the object file of every atom, so each
section's bytes can be split by origin (XNU osfmk, bsd, iokit, libkern ..., or an archive:
corecrypto, ArmCpu, ArmDTPlatform, pthread ...).

The C strings of __TEXT,__cstring and __TEXT,__os_log are also attributed to the patch that
added them: a string counts for a patch when it appears as a string literal on an added line of
that patch (--patches: one patch path per line, in application order) and nowhere as a literal
in the unpatched XNU source (--xnu-source). Strings that contain a --strip-prefix (the build
directory, from __FILE__) are counted with the bytes a -fmacro-prefix-map would remove.

Only sizes, counts, object and patch names are printed; no kernel content beyond the build-path
prefixes themselves.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel_report import parse  # noqa: E402

LITERAL = re.compile(rb'"((?:[^"\\\n]|\\.)*)"')
ESCAPES = {b"n": b"\n", b"t": b"\t", b"r": b"\r", b"0": b"\0", b"\\": b"\\", b'"': b'"', b"'": b"'",
           b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v", b"e": b"\x1b"}
STRING_SECTIONS = ("__cstring", "__os_log")


def unescape(raw):
    out, i = bytearray(), 0
    while i < len(raw):
        c = raw[i:i + 1]
        if c == b"\\" and i + 1 < len(raw):
            n = raw[i + 1:i + 2]
            if n == b"x":
                m = re.match(rb"[0-9a-fA-F]{1,2}", raw[i + 2:])
                if m:
                    out.append(int(m.group(), 16))
                    i += 2 + len(m.group())
                    continue
            if n in ESCAPES:
                out += ESCAPES[n]
                i += 2
                continue
            if n.isdigit():
                m = re.match(rb"[0-7]{1,3}", raw[i + 1:])
                out.append(int(m.group(), 8) & 0xff)
                i += 1 + len(m.group())
                continue
            out += n
            i += 2
            continue
        out += c
        i += 1
    return bytes(out)


def literals(text):
    """String literals of C text, adjacent literals joined ("a" "b" -> "ab")."""
    result, pending, last_end = set(), None, -1
    for m in LITERAL.finditer(text):
        value = unescape(m.group(1))
        if pending is not None and text[last_end:m.start()].strip() == b"":
            pending += value
        else:
            if pending is not None:
                result.add(pending)
            pending = value
        last_end = m.end()
    if pending is not None:
        result.add(pending)
    return result


def patch_literals(path):
    added = b"\n".join(line[1:] for line in Path(path).read_bytes().splitlines()
                       if line.startswith(b"+") and not line.startswith(b"+++"))
    return literals(added)


def source_literals(root):
    found = set()
    for path in Path(root).rglob("*"):
        if path.suffix in (".c", ".cpp", ".h", ".hpp", ".s", ".S", ".iig", ".defs", ".mm", ".m") and path.is_file():
            try:
                found |= literals(path.read_bytes())
            except OSError:
                pass
    return found


def read_map(path):
    """Object files, sections and atoms (address, size, object index) of an ld64 link map."""
    objects, sections, atoms, part = {}, [], [], None
    for raw in Path(path).read_bytes().splitlines():
        line = raw.decode("utf-8", "replace")
        if line.startswith("# Object files:"):
            part = "objects"
            continue
        if line.startswith("# Sections:"):
            part = "sections"
            continue
        if line.startswith("# Symbols:"):
            part = "symbols"
            continue
        if line.startswith("# Dead Stripped"):
            part = None
            continue
        if not line or line.startswith("#"):
            continue
        if part == "objects":
            m = re.match(r"\[\s*(\d+)\]\s+(.*)", line)
            if m:
                objects[int(m.group(1))] = m.group(2)
        elif part == "sections":
            f = line.split()
            if len(f) >= 4:
                sections.append((int(f[0], 16), int(f[1], 16), f[2], f[3]))
        elif part == "symbols":
            m = re.match(r"(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+\[\s*(\d+)\]\s", line)
            if m:
                atoms.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3))))
    return objects, sections, atoms


def origin(obj):
    m = re.search(r"/(lib[^/()]+)\.a\(([^)]+)\)", obj)
    if m:
        return f"archive {m.group(1)[3:]}"
    m = re.search(r"/DEVELOPMENT_ARM64_[A-Z0-9]+/([^/]+)/", obj)
    if m:
        return f"xnu {m.group(1)}"
    if obj.startswith("linker synthesized") or not obj.startswith("/"):
        return "linker"
    return "other " + obj.rsplit("/", 1)[-1]


def strings_of(data, section):
    """(address, bytes including the NUL) of every C string in a string section."""
    base, blob, out, i = section["addr"], data[section["offset"]:section["offset"] + section["size"]], [], 0
    while i < len(blob):
        j = blob.find(b"\0", i)
        j = len(blob) if j < 0 else j
        out.append((base + i, blob[i:j]))
        i = j + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", type=Path, required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--patches", type=Path, help="file with one patch path per line, in application order")
    ap.add_argument("--xnu-source", type=Path, help="unpatched XNU checkout (literals there are Apple's)")
    ap.add_argument("--strip-prefix", action="append", default=[], help="build directory prefix of __FILE__ strings")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    args = ap.parse_args()

    data = args.kernel.read_bytes()
    m = parse(data)
    objects, map_sections, atoms = read_map(args.map)
    # Section of every atom by address.
    ranges = sorted(map_sections)

    def section_of(addr):
        for a, size, seg, sec in ranges:
            if a <= addr < a + size:
                return f"{seg},{sec}"
        return None

    by_section = defaultdict(Counter)
    by_object = defaultdict(Counter)
    atom_object = {}
    for addr, size, idx in atoms:
        sec = section_of(addr)
        if sec is None:
            continue
        obj = objects.get(idx, "?")
        by_section[sec][origin(obj)] += size
        by_object[sec][obj.rsplit("/", 1)[-1]] += size
        if sec.split(",")[1] in STRING_SECTIONS:
            atom_object[addr] = obj

    sizes = {f"{s['name']},{x['name']}": x["size"] for s in m["segments"] for x in s["sections"]}
    report = {"kernel_bytes": len(data), "sections": sizes,
              "segments": {s["name"]: s["vmsize"] for s in m["segments"]},
              "by_origin": {sec: dict(c.most_common()) for sec, c in sorted(by_section.items())},
              "top_objects": {sec: dict(c.most_common(args.top)) for sec, c in sorted(by_object.items())
                              if sec.startswith("__TEXT")}}

    apple = source_literals(args.xnu_source) if args.xnu_source else set()
    patches = [Path(p) for p in args.patches.read_text().split()] if args.patches else []
    added = [(p.name, patch_literals(p)) for p in patches]
    prefixes = [p.encode() for p in args.strip_prefix]
    strings = {}
    for seg in m["segments"]:
        for sec in seg["sections"]:
            if seg["name"] == "__TEXT" and sec["name"] in STRING_SECTIONS:
                rows = strings_of(data, sec)
                attribution, prefix_bytes, prefix_count, unique = Counter(), 0, 0, Counter()
                for addr, s in rows:
                    n = len(s) + 1
                    who = None
                    if s and s not in apple:
                        for name, lits in added:
                            if s in lits:
                                who = "patch " + name
                                break
                    if who is None:
                        obj = atom_object.get(addr)
                        who = origin(obj) if obj else "unmapped"
                        if who.startswith("xnu "):
                            who = "xnu (Apple source or not matched to a patch)"
                    attribution[who] += n
                    unique[s] += 1
                    for pre in prefixes:
                        if pre in s:
                            prefix_count += 1
                            prefix_bytes += s.count(pre) * len(pre)
                            break
                strings[sec["name"]] = {
                    "bytes": sec["size"], "strings": len(rows),
                    "duplicates_in_section": sum(c - 1 for c in unique.values() if c > 1),
                    "by_source": dict(attribution.most_common()),
                    "build_path_strings": prefix_count, "build_path_prefix_bytes": prefix_bytes,
                }
    report["strings"] = strings
    report["patches_considered"] = len(patches)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    if args.markdown:
        lines = ["| Section | Bytes |", "| --- | ---: |"]
        lines += [f"| `{k}` | {v:,} |" for k, v in sorted(sizes.items(), key=lambda kv: -kv[1]) if v]
        for name, st in strings.items():
            lines += ["", f"`__TEXT,{name}`: {st['strings']:,} strings, {st['bytes']:,} bytes; build-path prefix "
                      f"{st['build_path_prefix_bytes']:,} bytes in {st['build_path_strings']:,} strings", "",
                      "| Source | Bytes |", "| --- | ---: |"]
            lines += [f"| {k} | {v:,} |" for k, v in list(st["by_source"].items())[:25]]
        args.markdown.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
