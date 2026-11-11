#!/usr/bin/env python3
"""Audit a macOS Tahoe system for what an ARMv8.2 CPU (SM8250) cannot execute.

    python3 -m tools.isa.tahoe_audit host OUT_DIR
        the macOS installed on this machine (a GitHub macos-26 runner): sw_vers,
        CPU features, dyld shared cache, kernels, kernel collections, key
        executables
    python3 -m tools.isa.tahoe_audit kernelcache KC_DIR OUT_DIR [--prelink-roots FILE]
        a kernelcache extracted from an official IPSW by tools.isa.ipsw

Writes JSON evidence and a Markdown summary. Only counts, names, versions and
hashes are written: no Apple code leaves the machine.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import glob
import hashlib
import json
import mmap
import os
import platform
import struct
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

from tools.isa import fast, features, inspect_macho, macho, pacstrip

DYLD_DIRS = ["/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld", "/System/Library/dyld"]
KEY_EXECUTABLES = [
    "/usr/lib/dyld", "/sbin/launchd", "/usr/libexec/xpcproxy", "/bin/ls", "/bin/zsh",
    "/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer",
    "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder",
    "/System/Library/CoreServices/Dock.app/Contents/MacOS/Dock",
    "/System/Library/CoreServices/SystemUIServer.app/Contents/MacOS/SystemUIServer",
    "/System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow",
    "/System/Applications/System Settings.app/Contents/MacOS/System Settings",
    "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
    "/Applications/Safari.app/Contents/MacOS/Safari",
    "/usr/libexec/amfid", "/usr/sbin/kextd", "/usr/libexec/kernelmanagerd",
]
NON_PAC = [r[0] for r in features.RULES if r[3] != "PAuth"] + ["pacga", "pac-load", "pac-keyreg", "pac-eret"]
FEATURE_OF = {r[0]: r[3] for r in features.RULES}
FGE_OF = {r[0]: r[4] for r in features.RULES}


def sh(*cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else f"(exit {p.returncode}) {p.stderr.strip()[:200]}"


def mm_open(path):
    f = open(path, "rb")
    try:
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_COPY)
    finally:
        f.close()


def summarize_counts(counts):
    return {rule: {"count": n, "feature": FEATURE_OF[rule], "fge": FGE_OF[rule]}
            for rule, n in sorted(counts.items(), key=lambda kv: -kv[1])}


def pac_rewrite_stats(buf, images):
    """What pacstrip would do, without writing: rewritten vs left for FGE, per rule."""
    done, kept = Counter(), Counter()
    for img in images:
        _c, hits = fast.scan(buf, img.ranges, record=pacstrip.PAC_RULES)
        for offs in hits.values():
            for off in offs:
                new, rule = pacstrip.rewrite_word(struct.unpack_from("<I", buf, off)[0])
                (kept if new is None else done)[rule] += 1
    return {"rewritten": dict(done), "left_for_fge": dict(kept)}


def audit_macho_file(path, rewrite=False, entries=False):
    buf = mm_open(path)
    try:
        images = macho.images_of(buf, os.path.basename(path))
        counts = Counter()
        for img in images:
            c, _ = fast.scan(buf, img.ranges)
            counts.update(c)
        out = {"path": path, "size": len(buf), "sha256": hashlib.sha256(buf).hexdigest(),
               "images": len(images), "arm64e_images": sum(i.cpusubtype == 2 for i in images),
               "counts": summarize_counts(counts)}
        head = struct.unpack_from("<I", buf, 0)[0]
        if head == macho.MH_MAGIC_64:
            ftype = struct.unpack_from("<I", buf, 12)[0]
            out["filetype"] = {2: "MH_EXECUTE", 6: "MH_DYLIB", 0xB: "MH_KEXT_BUNDLE",
                               0xC: "MH_FILESET"}.get(ftype, ftype)
            out["fixups"] = dict(inspect_macho.fixup_kind(buf))
            if ftype == macho.MH_FILESET and entries:
                ents = inspect_macho.fileset_entries(buf)
                out["fileset_entries"] = [e[0] for e in ents]
        if rewrite:
            out["pacstrip"] = pac_rewrite_stats(buf, images)
        return out
    finally:
        buf.close()


def slices(path):
    return sh("lipo", "-archs", path)


def host(out_dir):
    t0 = time.time()
    rep = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "host"}
    rep["sw_vers"] = sh("sw_vers")
    rep["uname"] = sh("uname", "-v")
    rep["machine"] = platform.machine()
    rep["hw_model"] = sh("sysctl", "-n", "hw.model")
    rep["cpu"] = sh("sysctl", "-n", "machdep.cpu.brand_string")
    feats = {}
    for line in sh("sysctl", "hw.optional").splitlines():
        k, _, v = line.partition(":")
        feats[k.strip()] = v.strip()
    rep["hw_optional"] = feats

    # dyld shared cache
    main = None
    for d in DYLD_DIRS:
        cand = Path(d) / "dyld_shared_cache_arm64e"
        if cand.exists():
            main = cand
            break
    rep["dyld_cache_files"] = sorted(os.path.basename(p) for d in DYLD_DIRS for p in glob.glob(f"{d}/dyld_shared_cache_*"))
    if main:
        cache = inspect_macho.DyldCache(main, mm_open)
        index = cache.text_index()
        totals, per_image = Counter(), {r: Counter() for r in NON_PAC}
        for path in cache.subcaches:
            ranges = cache.code_ranges(path)
            if not ranges:
                continue
            buf = cache._file(path)
            c, hits = fast.scan(buf, ranges, record=NON_PAC)
            totals.update(c)
            for rule, offs in hits.items():
                vms = [cache.file_offset_to_vm(path, o) for o in offs]
                per_image[rule].update(inspect_macho.attribute(index, [v for v in vms if v is not None]))
        rep["dyld_cache"] = {
            "main": str(main), "arch": cache.arch, "subcaches": [p.name for p in cache.subcaches],
            "images": len(cache.images), "os_version": f"{cache.os_version >> 16}.{(cache.os_version >> 8) & 0xFF}.{cache.os_version & 0xFF}",
            "slide_info_versions": dict(cache.slide_versions()),
            "code_bytes": sum(m[1] for m in cache.mappings if m[4] & macho.VM_PROT_EXECUTE),
            "counts": summarize_counts(totals),
            "top_images": {r: c.most_common(25) for r, c in per_image.items() if c},
            "images_using": {r: len(c) for r, c in per_image.items() if c},
        }

    # kernels and kernel collections on disk
    rep["kernels"] = [audit_macho_file(p, rewrite=True) for p in sorted(glob.glob("/System/Library/Kernels/kernel*"))]
    rep["kernel_collections"] = [audit_macho_file(p, rewrite=True, entries=True)
                                 for p in sorted(glob.glob("/System/Library/KernelCollections/*.kc"))]
    exes = []
    for p in KEY_EXECUTABLES:
        if os.path.exists(p):
            e = audit_macho_file(p)
            e["slices"] = slices(p)
            exes.append(e)
        else:
            exes.append({"path": p, "missing": True})
    rep["executables"] = exes
    rep["seconds"] = round(time.time() - t0, 1)
    write(out_dir, "host", rep)


def kernelcache(kc_dir, out_dir, roots_file=None):
    info = json.loads((Path(kc_dir) / "kernelcache.json").read_text())
    path = str(Path(kc_dir) / info["kernelcache"])
    rep = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "ipsw-kernelcache",
           "source": info}
    rep["audit"] = audit_macho_file(path, rewrite=True, entries=True)
    buf = mm_open(path)
    try:
        amfi = None
        for name, fileoff, _vm in inspect_macho.fileset_entries(buf):
            if name == "com.apple.driver.AppleMobileFileIntegrity":
                addr = inspect_macho.find_symbol(buf, fileoff, "_amfi_register_mac_policy", True)
                amfi = f"{name}={addr:#x}" if addr else f"{name}=(symbol not found)"
        rep["early_security_init"] = amfi
    finally:
        buf.close()
    if roots_file:
        prof = tomllib.loads(Path(roots_file).read_text())
        roots = prof["kernel"]["prelink"]["roots"]
        present = set(rep["audit"].get("fileset_entries", []))
        rep["prelink_roots_27_3"] = {
            "missing_in_this_kernelcache": [r for r in roots if not r.startswith("!") and r not in present],
            "present": sum(1 for r in roots if r in present), "total": len([r for r in roots if not r.startswith("!")]),
        }
    write(out_dir, f"kernelcache-{info['device_class']}-{info['build']}", rep)


def write(out_dir, stem, rep):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(rep, indent=2, default=str) + "\n")
    (out / f"{stem}.md").write_text(markdown(rep))
    print((out / f"{stem}.md").read_text())


def _table(counts):
    rows = ["| rule | feature | count | FGE |", "| --- | --- | ---: | --- |"]
    for rule, v in counts.items():
        rows.append(f"| {rule} | {v['feature']} | {v['count']} | {'yes' if v['fge'] else 'no'} |")
    return "\n".join(rows)


def markdown(rep):
    lines = [f"# {rep['kind']} audit ({rep['generated']})", ""]
    if rep["kind"] == "host":
        lines += ["```", rep["sw_vers"], rep["uname"], f"{rep['hw_model']} {rep['cpu']}", "```", ""]
        dc = rep.get("dyld_cache")
        if dc:
            lines += [f"## dyld shared cache ({dc['arch']}, {dc['images']} images, OS {dc['os_version']})", "",
                      f"Files: {', '.join(rep['dyld_cache_files'])}", "",
                      f"Slide info versions: {dc['slide_info_versions']}; executable bytes: {dc['code_bytes']}", "",
                      _table(dc["counts"]), "", "Images containing each non-PAC rule:", ""]
            for rule, n in dc["images_using"].items():
                top = ", ".join(f"{Path(name).name} {k}" for name, k in dc["top_images"][rule][:8])
                lines.append(f"- **{rule}** in {n} images: {top}")
            lines.append("")
        for title, key in (("Kernels", "kernels"), ("Kernel collections", "kernel_collections")):
            lines += [f"## {title}", ""]
            for k in rep[key]:
                lines += [f"### {Path(k['path']).name}", "", f"fixups {k.get('fixups')}; "
                          f"pacstrip {k.get('pacstrip')}" + (f"; {len(k['fileset_entries'])} fileset entries"
                                                             if k.get("fileset_entries") else ""), "",
                          _table(k["counts"]), ""]
        lines += ["## Executables", "", "| path | slices | fixups | non-PAC rules |", "| --- | --- | --- | --- |"]
        for e in rep["executables"]:
            if e.get("missing"):
                lines.append(f"| {e['path']} | missing | | |")
                continue
            non_pac = {r: v["count"] for r, v in e["counts"].items() if v["feature"] != "PAuth"}
            lines.append(f"| {e['path']} | {e['slices']} | {e.get('fixups')} | {non_pac or '-'} |")
    else:
        s, a = rep["source"], rep["audit"]
        lines += [f"{s['version']} ({s['build']}), {s['device_class']}, `{s['member']}`", "",
                  f"- kernelcache SHA-256 (decompressed): `{s['kernelcache_sha256']}`",
                  f"- IM4P SHA-256: `{s['im4p_sha256']}`",
                  f"- fileset entries: {len(a.get('fileset_entries', []))}",
                  f"- early_security_init: `{rep.get('early_security_init')}`",
                  f"- fixups: {a.get('fixups')}", f"- pacstrip: {a.get('pacstrip')}", ""]
        if "prelink_roots_27_3" in rep:
            p = rep["prelink_roots_27_3"]
            lines += [f"UniXNU macOS 27.3 prelink roots present: {p['present']}/{p['total']}; missing: "
                      f"{', '.join(p['missing_in_this_kernelcache']) or 'none'}", ""]
        lines += [_table(a["counts"]), ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("host")
    a.add_argument("out_dir")
    a = sub.add_parser("kernelcache")
    a.add_argument("kc_dir")
    a.add_argument("out_dir")
    a.add_argument("--prelink-roots", help="a UniXNU profile.toml whose [kernel.prelink] roots to compare")
    args = ap.parse_args(argv)
    if args.cmd == "host":
        host(args.out_dir)
    else:
        kernelcache(args.kc_dir, args.out_dir, args.prelink_roots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
