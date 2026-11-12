#!/usr/bin/env python3
"""Compile the pinned Adreno650 fork against the xnu-12377 kernel this run built, and list what it needs (G3).

    scripts/pipa_adreno_xnu_check.py --unixnu UNIXNU [--modules M] [--json OUT]      (macOS runner, after build kernel)

The macOS profile does not select Adreno650 (the catalog entry of patches/unixnu/0002 is for iPadOS 17), so the kernel
step's tree has neither the driver nor its kits. This puts them next to that tree's compile records in a scratch root
and runs the device recipe devices/pipa/scripts/build-adreno650.py there, unchanged: every A650 object (the GPU half of
NativeAdreno, the GMU's SMMU context, the SMMU, PM4 and HFI kits, package/A650Gmu.c) compiled with the flags XNU's own
IOPlatformExpert.cpp and bsd_init.c were compiled with, archived, and its own symbol checks (no NativeAdreno or kit
symbol left undefined; the bring-up entry points defined).
  driver   drivers/Adreno650   the feeds.toml pin with patches/adreno650 (pipa_unixnu.py's modules.json)
  kit      kits/ArmSmmu4K      the feeds.toml pin
  kits     AdrenoPM4, AdrenoFirmware: the UniXNU checkout (its submodules)
  package  kits/pipa           the tree's own (devices/pipa/package)
Then: the kernel symbols the archive needs, each looked up in the kernel this run linked (nm of the native kernel), so a
symbol XNU 12377 does not have is named. The archive is not linked; nothing here runs a GPU. A pass means the fork's code
compiles against these headers and finds its kernel symbols, not that it works.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "devices/pipa/scripts/build-adreno650.py"


def find_tree(unixnu):
    kernels = sorted(Path(unixnu, "out").rglob("mach.development.bcm2837.unstripped.noctf"))
    if not kernels:
        sys.exit(f"{unixnu}/out: no kernel step output")
    text = str(kernels[0])
    return Path(text[:text.index("/build/xnu/")]), kernels[0]


def layout(scratch, tree, unixnu, modules):
    """The directories build-adreno650.py reads, as links into the tree, the feeds and the UniXNU checkout."""
    links = {
        "build/xnu": tree / "build/xnu",
        ".cache/xnu-work": tree / ".cache/xnu-work",
        "drivers/Adreno650": Path(modules["driver:Adreno650"]),
        "kits/ArmSmmu4K": Path(modules["kit:ArmSmmu4K"]),
        "kits/AdrenoPM4": Path(unixnu) / "kits/AdrenoPM4",
        "kits/AdrenoFirmware": Path(unixnu) / "kits/AdrenoFirmware",
        "kits/pipa": tree / "kits/pipa" if (tree / "kits/pipa").is_dir() else ROOT / "devices/pipa/package",
    }
    for rel, src in links.items():
        if not src.is_dir():
            sys.exit(f"{rel}: {src} is missing")
        dest = scratch / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src.resolve(), target_is_directory=True)
    (scratch / "scripts").mkdir()
    shutil.copy(RECIPE, scratch / "scripts/build-adreno650.py")     # copied: the recipe's ROOT is its parent's parent
    return {rel: str(src) for rel, src in links.items()}


def symbols(path, undefined):
    out = subprocess.run(["xcrun", "nm", "-gP" + ("u" if undefined else "U"), str(path)], capture_output=True, text=True,
                         check=True).stdout
    return {line.split()[0] for line in out.splitlines() if line.split() and not line.split()[0].endswith(":")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--modules", type=Path,
                    default=Path(os.environ["WORK"]) / "modules.json" if os.environ.get("WORK") else None)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    tree, kernel = find_tree(args.unixnu)
    modules = json.loads(args.modules.read_text())["modules"]
    result = {"tree": str(tree), "kernel": str(kernel), "problems": []}
    with tempfile.TemporaryDirectory(prefix="pipa-adreno-") as d:
        scratch = Path(d)
        result["inputs"] = layout(scratch, tree, args.unixnu, modules)
        env = dict(os.environ)
        env["PATH"] = ":".join(p for p in ("/opt/homebrew/opt/llvm/bin", env.get("PATH", "")) if p)
        p = subprocess.run([sys.executable, str(scratch / "scripts/build-adreno650.py")], cwd=scratch, env=env,
                           capture_output=True, text=True)
        result["recipe"] = {"returncode": p.returncode, "output": (p.stdout + p.stderr)[-6000:]}
        print(p.stdout + p.stderr)
        archive = scratch / "build/adreno650/libAdreno650.a"
        if p.returncode or not archive.is_file():
            result["problems"].append("build-adreno650.py failed against the xnu-12377 compile records")
        else:
            result["archive_bytes"] = archive.stat().st_size
            needed = sorted(symbols(archive, undefined=True) - symbols(archive, undefined=False))
            provided = symbols(kernel, undefined=False)
            absent = [s for s in needed if s not in provided]
            result["kernel_symbols_needed"] = len(needed)
            result["absent_from_kernel"] = absent
            print(f"{len(needed)} kernel symbols needed; {len(absent)} not defined by this kernel: {' '.join(absent)}")
            if absent:
                result["problems"].append(f"{len(absent)} symbols the kernel does not define")
    print(json.dumps({k: v for k, v in result.items() if k != "recipe"}, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if result["problems"]:
        sys.exit("Adreno650 is not ready for this kernel: " + "; ".join(result["problems"]))


if __name__ == "__main__":
    main()
