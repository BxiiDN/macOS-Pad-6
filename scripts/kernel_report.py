#!/usr/bin/env python3
"""Describe a native XNU kernel that "unixnu build kernel" produced, without publishing it.

    scripts/kernel_report.py --work UNIXNU_OUT_DIR [--json OUT]
    scripts/kernel_report.py --file KERNEL_MACHO [--json OUT]       e.g. the prelinked kernel collection
    scripts/kernel_report.py --compare A.json B.json                which parts of two builds differ

Finds mach.development.bcm2837 (the linked native kernel) under the build output and reports:
- size, SHA-256, Mach-O header (file type, CPU type and subtype: arm64e or not);
- every segment and section with its size and the SHA-256 of its bytes, LC_UUID, and the
  link-edit blobs (symbol and string tables, fixups, function starts, split info) hashed
  separately, so two builds can be compared part by part (--compare);
- the kernel version strings and the debug-map (N_OSO) object timestamps, the usual sources of
  differences between two builds of the same source;
- the chained-fixup imports by name (XnuPrelink accepts a native kernel with none);
- the ARMv8.2 layer of devices/pipa, from the machine code: sleh_synchronous calls (BL or tail B)
  fge_xnu_handle (FGE), and ml_addrperm_pacga starts with the null-PAC body (orr x0, x0, #1;
  ret) instead of PACGA;
- the census of tools/isa/audit (instructions SM8250 cores cannot execute).

The kernel itself is never copied anywhere: it is built from Apple's source and stays on the
build machine. Exit status 1 if no linked kernel exists.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("mach.development.bcm2837.unstripped.noctf", "mach.development.bcm2837.unstripped",
         "mach.development.bcm2837")
CPU_ARM64 = 0x0100000c
SUBTYPE = {0: "arm64 (all)", 1: "arm64v8", 2: "arm64e"}
FILETYPE = {2: "MH_EXECUTE", 11: "MH_KEXT_BUNDLE", 12: "MH_FILESET"}
FGE_SYMBOLS = ("_fge_xnu_init", "_fge_xnu_handle", "_fge_emulate")
LC_SEGMENT_64, LC_SYMTAB, LC_UUID = 0x19, 0x2, 0x1b
LINKEDIT_BLOBS = {0x26: "function_starts", 0x1e: "segment_split_info", 0x29: "data_in_code",
                  0x80000034: "chained_fixups", 0x80000033: "exports_trie", 0x1d: "code_signature"}
N_OSO, N_STAB, N_TYPE, N_SECT = 0x66, 0xe0, 0x0e, 0x0e
ORR_X0_X0_1, RET = 0xb2400000, 0xd65f03c0


def sha(b):
    return hashlib.sha256(b).hexdigest()


def parse(data):
    """Header, segments with sections, UUID, link-edit blobs, symbols (defined, by name) and N_OSO stabs."""
    magic, cputype, cpusubtype, filetype, ncmds, _ = struct.unpack_from("<IiIIII", data)
    if magic != 0xfeedfacf:
        return {"magic": hex(magic)}
    out = {"cputype": cputype, "cpusubtype": cpusubtype, "filetype": filetype, "ncmds": ncmds,
           "segments": [], "uuid": None, "blobs": {}, "symbols": {}, "oso": []}
    offset = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, offset)
        if cmd == LC_SEGMENT_64:
            name = data[offset + 8:offset + 24].split(b"\0")[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, offset + 24)
            nsects = struct.unpack_from("<I", data, offset + 64)[0]
            sections = []
            for i in range(nsects):
                at = offset + 72 + 80 * i
                sname = data[at:at + 16].split(b"\0")[0].decode()
                addr, ssize = struct.unpack_from("<QQ", data, at + 32)
                soff = struct.unpack_from("<I", data, at + 48)[0]
                flags = struct.unpack_from("<I", data, at + 64)[0]
                zerofill = (flags & 0xff) in (0x1, 0xc, 0x12) or soff == 0
                sections.append({"name": sname, "addr": addr, "size": ssize, "offset": soff,
                                 "sha256": None if zerofill else sha(data[soff:soff + ssize])})
            out["segments"].append({"name": name, "vmaddr": vmaddr, "vmsize": vmsize, "fileoff": fileoff,
                                    "filesize": filesize, "sections": sections})
        elif cmd == LC_UUID:
            out["uuid"] = data[offset + 8:offset + 24].hex()
        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, offset + 8)
            out["blobs"]["symbol_table"] = sha(data[symoff:symoff + 16 * nsyms])
            out["blobs"]["string_table"] = sha(data[stroff:stroff + strsize])
            for i in range(nsyms):
                strx, ntype, nsect, _, value = struct.unpack_from("<IBBHQ", data, symoff + 16 * i)
                end = data.index(b"\0", stroff + strx)
                name = data[stroff + strx:end].decode("utf-8", "replace")
                if ntype == N_OSO:
                    out["oso"].append((name, value))
                elif not ntype & N_STAB and ntype & N_TYPE == N_SECT:
                    out["symbols"].setdefault(name, value)
        elif cmd in LINKEDIT_BLOBS:
            dataoff, datasize = struct.unpack_from("<II", data, offset + 8)
            out["blobs"][LINKEDIT_BLOBS[cmd]] = sha(data[dataoff:dataoff + datasize])
            if cmd == 0x80000034:
                out["chained_imports"] = chained_imports(data[dataoff:dataoff + datasize])
        offset += size
    return out


def chained_imports(blob):
    """Names of the imports of an LC_DYLD_CHAINED_FIXUPS blob (dyld_chained_fixups_header). A kernel that
    XnuPrelink joins to a collection must have none ("Chained fixup imports are not supported")."""
    if len(blob) < 28:
        return []
    _, _, imports_offset, symbols_offset, count, fmt, _ = struct.unpack_from("<IIIIIII", blob)
    width = {1: 4, 2: 8, 3: 16}.get(fmt)
    names = []
    for i in range(count if width else 0):
        at = imports_offset + width * i
        if fmt == 3:
            raw = struct.unpack_from("<Q", blob, at)[0]
            ordinal, weak, name_off = raw & 0xffff, (raw >> 16) & 1, raw >> 32
            ordinal = ordinal - 0x10000 if ordinal & 0x8000 else ordinal
        else:
            raw = struct.unpack_from("<I", blob, at)[0]
            ordinal, weak, name_off = raw & 0xff, (raw >> 8) & 1, raw >> 9
            ordinal = ordinal - 0x100 if ordinal & 0x80 else ordinal
        end = blob.index(b"\0", symbols_offset + name_off)
        names.append({"name": blob[symbols_offset + name_off:end].decode("utf-8", "replace"),
                      "lib_ordinal": ordinal, "weak_import": bool(weak)})
    return names


def word_at(m, data, va):
    for seg in m["segments"]:
        if seg["vmaddr"] <= va < seg["vmaddr"] + seg["filesize"]:
            off = seg["fileoff"] + va - seg["vmaddr"]
            return struct.unpack_from("<I", data, off)[0]
    return None


def function_end(m, start):
    later = sorted(v for v in m["symbols"].values() if v > start)
    return later[0] if later else start + 0x1000


def calls(m, data, caller, callee):
    """Number of BL (call) or B (tail call) instructions in caller's body that target callee."""
    a, b = m["symbols"].get(caller), m["symbols"].get(callee)
    if a is None or b is None:
        return None
    n = 0
    for va in range(a, function_end(m, a), 4):
        w = word_at(m, data, va)
        if w is not None and w & 0x7c000000 == 0x14000000:
            imm = w & 0x3ffffff
            if imm & 0x2000000:
                imm -= 1 << 26
            n += va + imm * 4 == b
    return n


def null_pac_body(m, data):
    """ml_addrperm_pacga: the null-PAC patch returns x0 | 1 right after the prolog, before any PACGA."""
    a = m["symbols"].get("_ml_addrperm_pacga")
    if a is None:
        return None
    words = [word_at(m, data, a + 4 * i) for i in range(4)]
    for i in range(3):
        if words[i] == ORR_X0_X0_1 and words[i + 1] == RET:
            return True
    return False


def report_for(kernel, base):
    data = kernel.read_bytes()
    m = parse(data)
    sub = m["cpusubtype"] & 0xff
    segments = [{"name": s["name"], "vmaddr": hex(s["vmaddr"]), "vmsize": s["vmsize"],
                 "sections": [{k: v for k, v in sec.items() if k in ("name", "size", "sha256")}
                              for sec in sorted(s["sections"], key=lambda x: -x["size"])]}
                for s in m["segments"]]
    version = sorted({x.decode("utf-8", "replace") for x in
                      re.findall(rb"(?:@\(#\)VERSION: )?Darwin Kernel Version [^\0]{0,200}", data)})
    report = {
        "kernel": str(kernel.relative_to(base)),
        "bytes": len(data),
        "sha256": sha(data),
        "macho": {"cputype": "arm64" if m["cputype"] == CPU_ARM64 else hex(m["cputype"]),
                  "cpusubtype": SUBTYPE.get(sub, hex(sub)), "cpusubtype_caps": hex(m["cpusubtype"] >> 24),
                  "filetype": FILETYPE.get(m["filetype"], m["filetype"]), "ncmds": m["ncmds"],
                  "uuid": m["uuid"], "segments": segments, "linkedit": m["blobs"]},
        "version_strings": version,
        "debug_map": {"objects": len(m["oso"]), "nonzero_timestamps": sum(1 for _, t in m["oso"] if t)},
        "chained_fixup_imports": m.get("chained_imports", []),
        "armv82_layer": {
            "symbols": {s: s in m["symbols"] for s in FGE_SYMBOLS},
            "sleh_synchronous_calls_fge_xnu_handle": calls(m, data, "_sleh_synchronous", "_fge_xnu_handle"),
            "ml_addrperm_pacga_null_pac_body": null_pac_body(m, data),
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "census.json"
        census = subprocess.run([sys.executable, "-m", "tools.isa.audit", "--json", str(out), str(kernel)],
                                cwd=ROOT, capture_output=True, text=True)
        if out.is_file():
            entry = json.loads(out.read_text())[0]
            report["isa_census"] = {k: entry.get(k) for k in ("totals", "needs", "emulated", "not_emulated", "words")}
            report["isa_census"]["arm64e"] = [i.get("arm64e") for i in entry.get("images", [])]
        else:
            report["isa_census"] = {"error": (census.stderr or census.stdout)[-1500:]}
    return report


def compare(a, b):
    """Parts of two reports that differ (same source expected)."""
    diff = {"sha256_equal": a["sha256"] == b["sha256"], "bytes": [a["bytes"], b["bytes"]],
            "uuid_equal": a["macho"]["uuid"] == b["macho"]["uuid"], "sections": [], "linkedit": [],
            "version_strings": [a["version_strings"], b["version_strings"]] if a["version_strings"] != b["version_strings"] else "equal"}
    secs = lambda r: {(s["name"], x["name"]): x for s in r["macho"]["segments"] for x in s["sections"]}
    sa, sb = secs(a), secs(b)
    for key in sorted(set(sa) | set(sb)):
        x, y = sa.get(key), sb.get(key)
        if not x or not y or x["size"] != y["size"] or x["sha256"] != y["sha256"]:
            diff["sections"].append({"section": ",".join(key), "size": [x and x["size"], y and y["size"]],
                                     "same_size": bool(x and y and x["size"] == y["size"])})
    for k in sorted(set(a["macho"]["linkedit"]) | set(b["macho"]["linkedit"])):
        if a["macho"]["linkedit"].get(k) != b["macho"]["linkedit"].get(k):
            diff["linkedit"].append(k)
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, help="where to look (UniXNU's out/ or the build tree)")
    ap.add_argument("--file", type=Path, help="report on this file (e.g. the prelinked kernel.macho) instead of searching")
    ap.add_argument("--compare", type=Path, nargs=2, metavar=("A", "B"), help="two reports of this script")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    if args.compare:
        result = compare(*(json.loads(p.read_text()) for p in args.compare))
    else:
        if args.file:
            found = [args.file.resolve()] if args.file.is_file() else []
            base = args.file.resolve().parent
        elif args.work:
            found = [p for name in NAMES for p in sorted(args.work.rglob(name)) if p.is_file()]
            base = args.work
        else:
            ap.error("give --work, --file or --compare")
        if not found:
            print(json.dumps({"kernel": None, "searched": str(args.file or args.work)}, indent=2))
            sys.exit(f"no kernel: {args.file or 'mach.development.bcm2837* under ' + str(args.work)}")
        result = report_for(found[0], base)
        result["other_outputs"] = [str(p.relative_to(base)) for p in found[1:]]
    text = json.dumps(result, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
