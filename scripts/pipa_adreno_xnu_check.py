#!/usr/bin/env python3
"""Adreno650 and the kernel symbols it needs, as the kernel step built them against xnu-12377 (G3).

    scripts/pipa_adreno_xnu_check.py --unixnu UNIXNU [--linked yes|no] [--json OUT]   (macOS runner, after build kernel)

The board's [kernel] archives build two archives in every kernel step, from the compile records XNU itself was built
with (devices/pipa/board.toml):
  build/adreno650/libAdreno650.a   component:Adreno650 (build-adreno650.py): the feeds.toml pin with patches/adreno650,
                                   the kits ArmSmmu4K (pin), AdrenoPM4, AdrenoFirmware, and package/A650Gmu.c
  build/pipa-gpu/libPipaGpu.a      build-pipa-gpu.py: GopFramebuffer's NativeGOPPresenter (patches/gopframebuffer) and
                                   package/BootLogExport.c
This checks them together: every external symbol their members reference that neither defines must be defined by the
kernel this run linked (nm of the native kernel), so nothing is left for the link to leave unresolved. With
--linked yes (pipa_macos26_gpu_defconfig) every member of both archives must be in ld64's link map, with --linked no
none. It also measures what the archives would add to each section (an upper bound: ld merges equal C strings), since
the native __TEXT must fit the 26.5 collection's __PRELINK_TEXT (scripts/prelink_layout.py). A pass means the code
compiles against these headers and links; nothing here runs a GPU, and it does not show that the GPU works.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import re
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ARCHIVES = {"Adreno650": "build/adreno650/libAdreno650.a", "PipaGpu": "build/pipa-gpu/libPipaGpu.a"}
# What the fork needed and the macOS 26.5 kernel alone did not have (kernel-build attempt 15): now libPipaGpu.a's.
HANDOFF = ("_native_gop_handoff_call", "_native_gop_handoff_memory", "_boot_log_export_put")


def find_tree(unixnu):
    kernels = sorted(Path(unixnu, "out").rglob("mach.development.bcm2837.unstripped.noctf"))
    if not kernels:
        sys.exit(f"{unixnu}/out: no kernel step output")
    text = str(kernels[0])
    return Path(text[:text.index("/build/xnu/")]), kernels[0]


def members(data):
    """(name, bytes) of each member of a BSD ar archive (the format xcrun ar writes), symbol tables left out."""
    if data[:8] != b"!<arch>\n":
        raise ValueError("not an ar archive")
    at, out = 8, []
    while at + 60 <= len(data):
        header = data[at:at + 60]
        name, size = header[:16].decode().strip(), int(header[48:58].decode().strip())
        body = data[at + 60:at + 60 + size]
        if name.startswith("#1/"):
            n = int(name[3:])
            name, body = body[:n].rstrip(b"\0").decode(), body[n:]
        if not name.startswith("__.SYMDEF"):
            out.append((name, body))
        at += 60 + size + (size & 1)
    return out


def object_sections(blob):
    """{(segment, section): size} of a 64-bit Mach-O object."""
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", blob, 0)
    if magic != 0xFEEDFACF:
        raise ValueError("not a 64-bit Mach-O object")
    sizes, at = defaultdict(int), 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", blob, at)
        if cmd == 0x19:   # LC_SEGMENT_64
            nsects = struct.unpack_from("<I", blob, at + 64)[0]
            for i in range(nsects):
                s = at + 72 + i * 80
                sect = blob[s:s + 16].rstrip(b"\0").decode()
                seg = blob[s + 16:s + 32].rstrip(b"\0").decode()
                sizes[(seg, sect)] += struct.unpack_from("<Q", blob, s + 40)[0]
        at += cmdsize
    return sizes


def archive_sections(path):
    total, per_member = defaultdict(int), {}
    for name, blob in members(Path(path).read_bytes()):
        sizes = object_sections(blob)
        per_member[name] = sizes
        for key, n in sizes.items():
            total[key] += n
    return total, per_member


def symbols(path, undefined):
    out = subprocess.run(["xcrun", "nm", "-gP" + ("u" if undefined else "U"), str(path)], capture_output=True, text=True,
                         check=True).stdout
    return {line.split()[0] for line in out.splitlines() if line.split() and not line.split()[0].endswith(":")}


def map_members(link_map, archive_name):
    if not Path(link_map).is_file():
        return None
    out = []
    for line in Path(link_map).read_text(errors="replace").splitlines():
        if line.startswith("# Sections:"):
            break
        m = re.match(r"^\[\s*\d+\]\s+(.*)$", line)
        if m and "/" + archive_name + "(" in m.group(1):
            out.append(re.search(r"\(([^()]+)\)\s*$", m.group(1)).group(1))
    return out


def recipe_logs(unixnu):
    """The kernel step's logs of the two archive builders, for a failure."""
    return sorted(p for p in Path(unixnu, "out").rglob("*.log")
                  if p.name.startswith("component-Adreno650") or "build-pipa-gpu" in p.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--linked", choices=("yes", "no"))
    ap.add_argument("--json", type=Path)
    ap.add_argument("--logs", action="store_true", help="only print the two builders' logs (the kernel step failed)")
    args = ap.parse_args()
    if args.logs:
        for log in recipe_logs(args.unixnu):
            print(f"== {log.name}\n" + log.read_text(errors="replace")[-8000:])
        return
    tree, kernel = find_tree(args.unixnu)
    result = {"tree": str(tree), "kernel": str(kernel), "problems": [], "archives": {}}
    paths = {name: tree / rel for name, rel in ARCHIVES.items()}
    for name, path in paths.items():
        if not path.is_file():
            result["problems"].append(f"{ARCHIVES[name]} was not built")
    if result["problems"]:
        for log in recipe_logs(args.unixnu):
            print(f"== {log.name}\n" + log.read_text(errors="replace")[-6000:])
    else:
        defined, undefined = set(), set()
        for name, path in paths.items():
            d, u = symbols(path, undefined=False), symbols(path, undefined=True)
            defined |= d
            undefined |= u
            total, per_member = archive_sections(path)
            result["archives"][name] = {
                "path": ARCHIVES[name], "bytes": path.stat().st_size, "members": len(per_member),
                "sections": {f"{seg},{sect}": n for (seg, sect), n in sorted(total.items())},
                "text_segment_bytes": sum(n for (seg, _), n in total.items() if seg == "__TEXT"),
            }
        needed = sorted(undefined - defined)
        provided = symbols(kernel, undefined=False)
        absent = [s for s in needed if s not in provided]
        result["kernel_symbols_needed"] = len(needed)
        result["absent_from_kernel"] = absent
        result["handoff_defined_by_PipaGpu"] = {s: s in symbols(paths["PipaGpu"], undefined=False) for s in HANDOFF}
        result["handoff_in_kernel"] = {s: s in provided for s in HANDOFF}
        if absent:
            result["problems"].append(f"{len(absent)} symbols neither the archives nor the kernel define: {' '.join(absent)}")
        if not all(result["handoff_defined_by_PipaGpu"].values()):
            result["problems"].append("libPipaGpu.a does not define the hand-off and export symbols")
        link_map = tree / "build/kernel-link.map"
        result["linked"] = {}
        for name, path in paths.items():
            linked = map_members(link_map, path.name)
            result["linked"][name] = None if linked is None else len(linked)
            if args.linked and linked is None:
                result["problems"].append("no link map")
            elif args.linked == "yes" and len(linked) != result["archives"][name]["members"]:
                result["problems"].append(f"{path.name}: {len(linked)} of {result['archives'][name]['members']} members linked")
            elif args.linked == "no" and linked:
                result["problems"].append(f"{path.name}: {len(linked)} members linked into a kernel that should not have them")
        print(f"{len(needed)} kernel symbols needed by the two archives; {len(absent)} not defined by this kernel")
        for name, a in result["archives"].items():
            print(f"{a['path']}: {a['bytes']} bytes, {a['members']} members, __TEXT sections {a['text_segment_bytes']} bytes "
                  f"(upper bound), linked members {result['linked'][name]}")
            for key, n in a["sections"].items():
                print(f"  {key:32} {n:>10}")
    print(json.dumps({k: v for k, v in result.items() if k != "archives"}, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if result["problems"]:
        sys.exit("Adreno650 integration check failed: " + "; ".join(result["problems"]))


if __name__ == "__main__":
    main()
