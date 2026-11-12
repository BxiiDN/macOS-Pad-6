#!/usr/bin/env python3
"""Compile board package code that no kernel links yet against the xnu-12377 kernel this run built (compile only).

    scripts/pipa_board_xnu_check.py --unixnu UNIXNU [--json OUT]      (macOS runner, after build kernel)

PipaBacklight.c (the GENI I2C engine and KTZ8866 attach of package/GeniI2cCore.h and Ktz8866Driver.h behind
pipa-backlight=1) is a host-tested model: scripts/test_board_package.sh runs it on a simulated tablet and checks it
in kernel mode against tests/xnu_shim, which are stand-in headers. This compiles the same file with the flags XNU's own
bsd_init.c was compiled with (the compile record of this tree, -Werror), and looks up every symbol the object needs in
the native kernel this run linked. The object is not archived and not linked: nothing calls pipa_backlight_attach in
any macOS kernel, and the KTZ8866 stays read only (allow_writes 0; tests/hw/test_backlight_audit.py proves from the
code that no configuration register is written). A pass means the code builds for this kernel, not that it works.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["PipaBacklight.c"]


def find_tree(unixnu):
    kernels = sorted(Path(unixnu, "out").rglob("mach.development.bcm2837.unstripped.noctf"))
    if not kernels:
        sys.exit(f"{unixnu}/out: no kernel step output")
    text = str(kernels[0])
    return Path(text[:text.index("/build/xnu/")]), kernels[0]


def command_for(recipe, source, obj, includes):
    command, i, args = [], 0, recipe["arguments"]
    while i < len(args):
        value = args[i]
        if value == recipe["file"]:
            command.append(str(source))
        elif value == "-o":
            command += ["-o", str(obj)]
            i += 1
        elif value in ("-MF", "-MJ"):
            i += 1
        elif value == "-Xclang" and args[i + 1].startswith("-W"):
            i += 1
        elif not value.startswith("-W") and value not in ("-MD", "-MP"):
            command.append(value)
        i += 1
    return command + includes + ["-Wall", "-Wextra", "-Werror", "-Wno-incompatible-sysroot"]


def nm(path, flag):
    out = subprocess.run(["xcrun", "nm", flag, str(path)], capture_output=True, text=True, check=True).stdout
    return {line.split()[0] for line in out.splitlines() if line.split() and not line.split()[0].endswith(":")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unixnu", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    tree, kernel = find_tree(args.unixnu)
    recipe = json.loads((tree / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/bsd_init.o.json")
                        .read_text().strip().rstrip(","))
    package = tree / "kits/pipa" if (tree / "kits/pipa").is_dir() else ROOT / "devices/pipa/package"
    provided = nm(kernel, "-gPU")
    result, problems = {"tree": str(tree), "kernel": str(kernel), "sources": {}}, []
    with tempfile.TemporaryDirectory(prefix="pipa-board-") as d:
        for name in SOURCES:
            obj = Path(d) / (Path(name).stem + ".o")
            command = command_for(recipe, package / name, obj, ["-I", str(package)])
            p = subprocess.run(command, cwd=recipe["directory"], capture_output=True, text=True)
            row = {"compiled": p.returncode == 0, "stderr": p.stderr[-3000:]}
            if p.returncode:
                problems.append(f"{name} does not compile against xnu-12377")
            else:
                needed = sorted(nm(obj, "-gPu"))
                row["kernel_symbols_needed"] = needed
                row["absent_from_kernel"] = [s for s in needed if s not in provided]
                row["defines"] = sorted(nm(obj, "-gPU"))
                if row["absent_from_kernel"]:
                    problems.append(f"{name}: the kernel does not define {' '.join(row['absent_from_kernel'])}")
            result["sources"][name] = row
            print(f"{name}: compiled {row['compiled']}; needs {' '.join(row.get('kernel_symbols_needed', []))}; "
                  f"absent {row.get('absent_from_kernel')}")
            if p.stderr:
                print(p.stderr[-3000:])
    result["problems"] = problems
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if problems:
        sys.exit("; ".join(problems))


if __name__ == "__main__":
    main()
