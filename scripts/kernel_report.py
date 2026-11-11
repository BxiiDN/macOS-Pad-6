#!/usr/bin/env python3
"""Describe a native XNU kernel that "unixnu build kernel" produced, without publishing it.

    scripts/kernel_report.py --work UNIXNU_OUT_DIR [--json OUT]

Finds mach.development.bcm2837 (the linked native kernel) under the build output and reports
its size, SHA-256, Mach-O header (file type, CPU type and subtype: arm64e or not), segments,
whether the ARMv8.2 layer of devices/pipa is linked in (FGE entry points, from the symbol
table), and the census of tools/isa/audit (instructions SM8250 cores cannot execute). The
kernel itself is never copied anywhere: it is built from Apple's source and stays on the
build machine. Exit status 1 if no linked kernel exists.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
import shutil
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


def macho(data):
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from("<IiIIII", data)
    if magic != 0xfeedfacf:
        return {"magic": hex(magic)}
    segments, offset = [], 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, offset)
        if cmd == 0x19:   # LC_SEGMENT_64
            name = data[offset + 8:offset + 24].split(b"\0")[0].decode()
            vmaddr, vmsize = struct.unpack_from("<QQ", data, offset + 24)
            segments.append({"name": name, "vmaddr": hex(vmaddr), "vmsize": vmsize})
        offset += size
    sub = cpusubtype & 0xff
    return {"magic": "MH_MAGIC_64", "cputype": "arm64" if cputype == CPU_ARM64 else hex(cputype),
            "cpusubtype": SUBTYPE.get(sub, hex(sub)), "cpusubtype_caps": hex(cpusubtype >> 24),
            "filetype": FILETYPE.get(filetype, filetype), "ncmds": ncmds, "segments": segments}


def symbols(path):
    nm = shutil.which("nm") or shutil.which("llvm-nm")
    if not nm:
        return None
    out = subprocess.run([nm, "-U", str(path)], capture_output=True, text=True)
    if out.returncode:
        return {"error": out.stderr.strip()[-300:]}
    names = {line.split()[-1] for line in out.stdout.splitlines() if line.split()}
    return {s: s in names for s in FGE_SYMBOLS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True, help="where to look (UniXNU's out/ or the build tree)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    found = [p for name in NAMES for p in sorted(args.work.rglob(name)) if p.is_file()]
    if not found:
        print(json.dumps({"kernel": None, "searched": str(args.work)}, indent=2))
        sys.exit("no linked native kernel (mach.development.bcm2837*) under " + str(args.work))
    kernel = found[0]
    data = kernel.read_bytes()
    report = {
        "kernel": str(kernel.relative_to(args.work)),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "macho": macho(data),
        "fge_symbols": symbols(kernel),
        "other_outputs": [str(p.relative_to(args.work)) for p in found[1:]],
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
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
