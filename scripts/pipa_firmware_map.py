#!/usr/bin/env python3
"""The boot path and memory map that uefi-pipa's source states, checked against the board and the G6 model.

    scripts/pipa_firmware_map.py [--uefi third_party/uefi-pipa] [--json OUT] [--markdown OUT] [--check]

pipa boots no standard UEFI from its flash: Qualcomm's chain (PBL in ROM, XBL, TZ, the hypervisor, Xiaomi's ABL) ends in
ABL loading an Android boot image. The route this repository uses (docs/boot-architecture.md) keeps every partition: ABL
is given a boot image with `fastboot boot` (RAM only), whose "kernel" is Mu-Silicium's firmware volume behind a 64-byte
Linux arm64 Image header (BootShim), so ABL treats it as a Linux kernel and jumps to it with the device tree in x0. That
UEFI then runs UniXNU's menu and DarwinBoot, which loads XNU. This reads what the firmware source fixes about that path:

  Resources/Configs/pipa.toml                       boot image header version, base, offsets, page size, kernel
                                                    compression, appended DTB, the FD's base and size
  BootShim/BootShim.S                               the Image header (text offset = FD base, "ARM\\x64") and the copy
                                                    of the FD to its base
  Platforms/Xiaomi/pipaPkg/Library/MemoryMapLib     the static memory descriptors (DDR reservations, MMIO)

and checks them against each other, against devices/pipa/board.toml, and against scripts/pipa_memory.py's model: the
reserved DDR ranges of the firmware source next to the mainline DT's no-map ranges the model uses, and MemoryWindow.h's
window and excluded-range table run on a map built from the firmware's own reservations.

Evidence class FS (firmware source): what the source the tablet would run says. Not a measurement: the DDR banks come at
boot from the RAM partition table XBL leaves (RamManagerDxe), and ABL's /memory node is known to be unreliable
(U-Boot's Qualcomm phone notes). The runtime map can only come from the tablet (docs/firmware-acquisition.md).

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_memory as pm  # noqa: E402

UEFI = ROOT / "third_party/uefi-pipa"
MEMORY_MAP = Path("Platforms/Xiaomi/pipaPkg/Library/MemoryMapLib/MemoryMapLib.c")
CONFIG = Path("Resources/Configs/pipa.toml")
SHIM = Path("BootShim/BootShim.S")
DDR_START = 0x80000000


def descriptors(text):
    """{"Name", base, length, hob, resource type, attribute, memory type, arm attribute} rows of gMemoryDescriptor."""
    body = text[text.index("gMemoryDescriptor[]"):]
    body = re.sub(r"//[^\n]*", "", body[:body.index("};")])
    rows = []
    for m in re.finditer(r'\{\s*"([^"]+)"\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,([^}]*)\}', body):
        rest = [x.strip() for x in m.group(4).split(",")]
        rows.append({"name": m.group(1), "base": int(m.group(2), 16), "length": int(m.group(3), 16),
                     "hob": rest[0], "resource": rest[1], "attribute": rest[2], "type": rest[3], "arm": rest[4]})
    return rows


def ddr_reserved(rows):
    """DDR ranges nothing may allocate from: reserved memory type, or a reserved resource (TZ apps keep only a HOB)."""
    return sorted((r["base"], r["length"]) for r in rows
                  if r["base"] >= DDR_START and (r["type"] == "Reserv" or r["resource"] == "MEM_RES"))


def ddr_firmware(rows):
    """DDR the firmware itself occupies while it runs (its FD, stack, info block, heap): free for the loader only as
    the UEFI map of that moment says."""
    return sorted((r["base"], r["length"], r["type"]) for r in rows
                  if r["base"] >= DDR_START and r["type"] in ("BsData", "RtData", "Conv"))


def overlaps(a, b):
    return a[0] < b[0] + b[1] and b[0] < a[0] + a[1]


def covered(rng, ranges):
    """Whether rng lies inside the union of ranges."""
    cursor, end = rng[0], rng[0] + rng[1]
    for s, n in sorted(ranges):
        if s <= cursor < s + n:
            cursor = s + n
            if cursor >= end:
                return True
    return cursor >= end


def shim_header(text):
    words = re.findall(r"^\s*\.(quad|long|ascii)\s+([^/\n]+)", text[text.index("#if REQUIRES_KERNEL_HEADER"):], re.M)
    return {"text_offset": words[0][1].strip() if words else None,
            "magic": next((w[1].strip() for w in words if w[0] == "ascii"), None)}


def analyse(uefi=UEFI, board=pm.BOARD):
    config = tomllib.loads((uefi / CONFIG).read_text())
    rows = descriptors((uefi / MEMORY_MAP).read_text())
    shim = shim_header((uefi / SHIM).read_text())
    board_raw = tomllib.loads(Path(board).read_text())
    named = {r["name"]: r for r in rows}
    fd = config["uefi_fd"]
    reserved = ddr_reserved(rows)
    dt_reserved = sorted(pm.RESERVED)
    window = next(w for w in pm.board_windows(board) if w["profile"] == board_raw["board"]["os_profile"])
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("boot image: header v1, base 0x10000000, kernel offset 0x8000, tags 0x100, page 2048 (mkbootimg defaults)",
          config["boot_image"] == {"header_version": 1, "base": 0x10000000, "kernel_offset": 0x8000,
                                   "tags_offset": 0x100, "pagesize": 2048}, json.dumps(config["boot_image"]))
    check("kernel: gzip with the DTB appended (ABL takes the tree behind the kernel)",
          config["boot_image_kernel"] == {"kernel_compression": "gzip", "append_dtb": True},
          json.dumps(config["boot_image_kernel"]))
    check("BootShim: Linux arm64 Image header (text offset = FD base, magic ARM\\x64)",
          config["boot_shim"]["requires_kernel_header"] and shim["text_offset"] == "FD_BASE" and shim["magic"] == '"ARM\\x64"',
          json.dumps(shim))
    check("FD base and size = the 'UEFI FD' descriptor", "UEFI FD" in named and
          (named["UEFI FD"]["base"], named["UEFI FD"]["length"]) == (fd["base"], fd["size"]),
          f"config {fd['base']:#x}+{fd['size']:#x}")
    check("ABL's kernel/ramdisk load area is reserved ('Kernel' descriptor)", "Kernel" in named and
          named["Kernel"]["type"] == "Reserv", f"{named.get('Kernel', {}).get('base', 0):#x}+"
          f"{named.get('Kernel', {}).get('length', 0):#x}")
    check("frame buffer 0x9c000000 (DT cont_splash) inside 'Display Reserved'", "Display Reserved" in named and
          covered((0x9c000000, 0x2300000), [(named["Display Reserved"]["base"], named["Display Reserved"]["length"])]),
          "0x9c000000+0x2300000")
    # The model (mainline DT no-map) against the firmware source, both ways.
    only_dt = [r for r in dt_reserved if not covered(r, reserved)]
    only_fw = [r for r in reserved if not any(overlaps(r, d) for d in dt_reserved)]
    check("every no-map range of the mainline DT (the G6 model) is reserved by the firmware source", not only_dt,
          ", ".join(f"{a:#x}+{n:#x}" for a, n in only_dt) or "all covered")
    # The macOS window on a map with the firmware's reservations.
    descriptors_fw = pm.model_map(pm.BANKS, reserved)
    win = pm.Window()
    row = pm.evaluate(win, descriptors_fw, window["size"], window["table"])
    model = pm.evaluate(win, pm.model_map(pm.BANKS, dt_reserved), window["size"], window["table"])
    in_window = [r for r in reserved if row["base"] and overlaps(r, (row["base"], window["size"]))]
    excluded = row.get("exclusions", [])
    check("a window of the board's size is placed on the firmware-source map", row["base"],
          f"base {row['base']:#x}, {window['size']:#x} bytes")
    check("every firmware reservation inside the window is in its excluded-range table",
          all(covered(r, excluded) for r in in_window),
          ", ".join(f"{a:#x}+{n:#x}" for a, n in in_window) or "none inside")
    if row["base"]:
        k = pm.kernel_view(row, window["size"])
        check("the kernel takes that table without a panic", not k["panic"], k["panic"] or f"{k['ranges']} ranges")
    return {
        "evidence": "FS (firmware source); not measured on the tablet",
        "uefi_revision_file": str(uefi / MEMORY_MAP),
        "boot_image": config["boot_image"], "boot_image_kernel": config["boot_image_kernel"], "uefi_fd": fd,
        "shim": shim,
        "ddr_reserved": [{"base": hex(a), "length": hex(n),
                          "name": next(r["name"] for r in rows if r["base"] == a)} for a, n in reserved],
        "ddr_firmware": [{"base": hex(a), "length": hex(n), "type": t} for a, n, t in ddr_firmware(rows)],
        "firmware_only_reservations": [{"base": hex(a), "length": hex(n)} for a, n in only_fw],
        "window": {"size": hex(window["size"]), "table": window["table"], "base": hex(row["base"]),
                   "model_base": hex(model["base"]),
                   "excluded": [[hex(a), hex(n)] for a, n in excluded], "reservations_inside": len(in_window)},
        "mmio": len([r for r in rows if r["base"] < DDR_START]),
        "checks": checks,
    }


def markdown(report):
    lines = ["| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {c['check']} | {'ok' if c['ok'] else '**FAIL**'} | {c['detail']} |" for c in report["checks"]]
    w = report["window"]
    lines += ["", f"Window ({w['size']} bytes, {w['table']} table slots): base {w['base']} on the firmware-source map, "
              f"{w['model_base']} on the mainline-DT model. DarwinBoot picks the base from the UEFI map at boot.", ""]
    lines += ["Firmware-source DDR reservations the mainline DT does not have (G6 model blind spots):", ""]
    lines += [f"- {r['base']}+{r['length']}" for r in report["firmware_only_reservations"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--uefi", type=Path, default=UEFI)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not (args.uefi / MEMORY_MAP).is_file():
        sys.exit(f"{args.uefi}: run git submodule update --init --depth 1 third_party/uefi-pipa")
    report = analyse(args.uefi)
    text = markdown(report)
    print(text, end="")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.markdown:
        args.markdown.write_text(text)
    failed = [c["check"] for c in report["checks"] if not c["ok"]]
    if args.check and failed:
        sys.exit("firmware source and board disagree: " + "; ".join(failed))


if __name__ == "__main__":
    main()
