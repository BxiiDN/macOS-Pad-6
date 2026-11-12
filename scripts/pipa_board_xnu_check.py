#!/usr/bin/env python3
"""Compile board package code that no kernel links yet against the xnu-12377 kernel this run built (compile only).

    scripts/pipa_board_xnu_check.py --unixnu UNIXNU [--modules MODULES.json] [--json OUT]   (macOS runner, after build kernel)

Two groups, both compiled with the flags XNU's own sources were (the tree's compile records, -Werror) and then looked up
symbol by symbol in the native kernel this run linked; nothing is archived or linked:
  backlight  package/PipaBacklight.c
  touch      UniXNU's drivers/QcomGeniSpi/GeniSpi.c (GENI SPI engine), the NT36532 protocol NvtProtocol.c of the
             ShengNovatekTouch pin (feeds.toml, PipaNovatekTouch), package/TouchProbe.cpp (the iPadOS kernel's touch
             bring-up: SPI, firmware download, reports) and package/TouchState.cpp (finger state for NativeHidInput)
Symbols the touch group needs from each other or from the display/HID side are listed separately from those the kernel
must provide, so the report says what a macOS touch build would still need. HID (NativeHidInput.cpp) is not compiled:
it subclasses the original IOHIDDevice through a per-fileset ABI fixture, which no 26.5 fixture exists for.

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
# (group, where the file lives, relative path); "package" is the tree's kits/pipa, "unixnu" the UniXNU checkout, "module:X"
# a feeds.toml source from modules.json.
SOURCES = [
    ("backlight", "package", "PipaBacklight.c"),
    ("touch", "unixnu", "drivers/QcomGeniSpi/GeniSpi.c"),
    ("touch", "module:driver:ShengNovatekTouch", "NvtProtocol.c"),
    ("touch", "package", "TouchProbe.cpp"),
    ("touch", "package", "TouchState.cpp"),
]


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
    ap.add_argument("--modules", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    tree, kernel = find_tree(args.unixnu)
    records = tree / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837"
    c_recipe = json.loads((records / "bsd/DEVELOPMENT/bsd_init.o.json").read_text().strip().rstrip(","))
    cxx_recipe = json.loads((records / "iokit/DEVELOPMENT/IOPlatformExpert.cpo.json").read_text().strip().rstrip(","))
    package = tree / "kits/pipa" if (tree / "kits/pipa").is_dir() else ROOT / "devices/pipa/package"
    modules = json.loads(args.modules.read_text())["modules"] if args.modules and args.modules.is_file() else {}

    def locate(where, rel):
        if where == "package":
            return package / rel
        if where == "unixnu":
            return Path(args.unixnu) / rel
        return Path(modules[where.split(":", 1)[1]]) / rel if where.split(":", 1)[1] in modules else None
    provided = nm(kernel, "-PU")   # local ones too: a hidden definition still resolves the link
    result, problems = {"tree": str(tree), "kernel": str(kernel), "sources": {}}, []
    sources = [(group, locate(where, rel)) for group, where, rel in SOURCES]
    includes = ["-I", str(package)] + [x for _, src in sources if src for x in ("-I", str(src.parent))] + \
               ["-I", str(tree / ".cache/xnu-work/osfmk")]
    defined_here = {}
    with tempfile.TemporaryDirectory(prefix="pipa-board-") as d:
        for group, path in sources:
            name = path.name if path else "?"
            if not path or not path.is_file():
                result["sources"][f"{group}:{path}"] = {"group": group, "compiled": False, "stderr": "source missing"}
                if group == "backlight":
                    problems.append(f"{group}: source missing: {path}")
                continue
            obj = Path(d) / (path.stem + ".o")
            recipe = c_recipe if path.suffix == ".c" else cxx_recipe
            extra = [] if path.suffix == ".c" else ["-Wno-unused-parameter", "-Wno-c99-designator",
                                                     "-Wno-reorder-init-list", "-Wno-unnecessary-virtual-specifier"]
            # The relaxations after -Wall -Wextra, which would turn them back on (-Wreorder-init-list fired in
            # XNU's own IOMallocType macro).
            command = command_for(recipe, path, obj, includes) + extra
            p = subprocess.run(command, cwd=recipe["directory"], capture_output=True, text=True)
            row = {"group": group, "compiled": p.returncode == 0, "stderr": p.stderr[-3000:]}
            # The backlight group must build (it is the one meant for this kernel); the touch group is an evaluation of
            # what a macOS touch build would need, so its compile errors are reported, not a failure of the step.
            if p.returncode:
                if group == "backlight":
                    problems.append(f"{name} does not compile against xnu-12377")
            else:
                row["needed"] = sorted(nm(obj, "-gPu"))
                row["defines"] = sorted(nm(obj, "-gPU"))
                for sym in row["defines"]:
                    defined_here.setdefault(group, set()).add(sym)
            result["sources"][name] = row
            print(f"{group} {name}: compiled {row['compiled']}")
            if p.stderr:
                print(p.stderr[-3000:])
    # What each source still needs once its group's own definitions are counted: from the kernel (must exist) and
    # from elsewhere (the display/HID side, firmware), which a macOS build of the group would have to bring.
    for name, row in result["sources"].items():
        if not row.get("compiled"):
            continue
        own = defined_here.get(row["group"], set())
        outside = [s for s in row["needed"] if s not in own]
        row["from_kernel"] = [s for s in outside if s in provided]
        row["not_in_kernel"] = [s for s in outside if s not in provided]
        print(f"{row['group']} {name}: {len(row['from_kernel'])} symbols from the kernel; not in it: "
              f"{' '.join(row['not_in_kernel']) or 'none'}")
        if row["group"] == "backlight" and row["not_in_kernel"]:
            problems.append(f"{name}: the kernel does not define {' '.join(row['not_in_kernel'])}")
    touch_missing = sorted({s for r in result["sources"].values() if r.get("group") == "touch" for s in r.get("not_in_kernel", [])})
    result["touch_needs_from_outside"] = touch_missing
    result["problems"] = problems
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    if problems:
        sys.exit("; ".join(problems))


if __name__ == "__main__":
    main()
