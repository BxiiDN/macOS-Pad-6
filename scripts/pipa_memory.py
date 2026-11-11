#!/usr/bin/env python3
"""The XNU memory window DarwinBoot would choose on pipa, computed with DarwinBoot's own MemoryWindow.h (G6).

    scripts/pipa_memory.py [--dtb pipa-mainline.dtb] [--json OUT] [--check]

The memory map is a model: the three DRAM banks of the reference tablet (16 GB, read in Android by UniXNU-pipa)
as free memory, minus every no-map region of mainline Linux's sm8250-xiaomi-pipa.dts (with --dtb; without it the
list committed below, which `--dtb` also checks) as reserved. The firmware's own allocations are not known here, so
the result is what the loader's code does with that map, not what the tablet's firmware map will give.

For each window the board configures (devices/pipa/board.toml payload.adt, the macOS profile and the iPadOS
override) and for a few sizes around them, it runs:
  - without the excluded-range table: AllocateWindow's rule (one free run holds the whole window, first fit in map
    order, start aligned to 2 MiB plus the kernel's offset);
  - with the table: DarwinWindowStart (the start with the most usable memory whose head is free) and
    DarwinWindowExclusions (the ranges XNU must not use, at the board's table capacity), checked against an
    independent Python computation of the same ranges.
MemoryWindow.h is compiled from the UniXNU submodule with the host C compiler through a small EFI shim.

--check fails unless every configured window is placed, the macOS window's exclusions fit its table without
merging, and the configured window does not exceed what the board notes say the 4 KiB bootstrap tables map.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import ctypes
import json
import os
import struct
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HEADER = ROOT / "third_party/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/MemoryWindow.h"
BOARD = ROOT / "devices/pipa/board.toml"
MIB, GIB = 1 << 20, 1 << 30
BLOCK = 2 * MIB
BOOTSTRAP_MAX = 6 * GIB          # board.toml / UniXNU-sheng: the most the 4 KiB bootstrap tables map
# DRAM banks of the reference tablet (AN: UniXNU-pipa, read in Android; docs/hardware-pipa.md).
BANKS = [(0x80000000, 0x37700000), (0xc0000000, 0x1c0000000), (0x800000000, 0x200000000)]
# no-map reserved-memory of mainline sm8250-xiaomi-pipa.dts + sm8250.dtsi (docs/evidence/hardware/pipa-mainline-inventory.md).
RESERVED = [(0x80000000, 0x600000), (0x80600000, 0x260000), (0x80860000, 0x20000), (0x80900000, 0x200000),
            (0x80b00000, 0x5300000), (0x86200000, 0x500000), (0x86700000, 0x100000), (0x86800000, 0x10000),
            (0x86810000, 0xa000), (0x8681a000, 0x2000), (0x86900000, 0x500000), (0x86e00000, 0x500000),
            (0x87300000, 0x500000), (0x87800000, 0x1400000), (0x88c00000, 0x2f00000), (0x8bb00000, 0x2500000),
            (0x8e000000, 0x100000), (0x8e100000, 0x4600000), (0x9c000000, 0x2300000), (0xb0000000, 0x400000)]
# The head the loader allocates first: the kernel collection (135,036,928 bytes, docs/kernel-build.md attempt 12) and
# what PlaceImage puts behind it, rounded up, plus DARWIN_WINDOW_RESERVE. An estimate; it only decides which starts fit.
IMAGE_ESTIMATE = 192 * MIB
KERNEL_OFFSET = 0                # Kernel.Base & (2 MiB - 1) of the arm64e kernel collection: 2 MiB aligned
RESERVED_TYPE, LOADER_CODE, LOADER_DATA, FREE = 0, 1, 2, 7
STRIDE = 48                      # firmware descriptors are larger than the structure; the loader steps by the reported size

SHIM = r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef size_t UINTN; typedef int BOOLEAN;
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
#define MAX_UINT64 UINT64_MAX
#define EFI_PAGE_SIZE 4096
enum { EfiReservedMemoryType, EfiLoaderCode, EfiLoaderData, EfiBootServicesCode, EfiBootServicesData,
       EfiRuntimeServicesCode, EfiRuntimeServicesData, EfiConventionalMemory };
typedef struct { UINT32 Type; UINT64 PhysicalStart; UINT64 VirtualStart; UINT64 NumberOfPages; UINT64 Attribute; } EFI_MEMORY_DESCRIPTOR;
static UINT64 ReadUnaligned64(const UINT64 *p) { UINT64 v; memcpy(&v, p, 8); return v; }
static void WriteUnaligned64(UINT64 *p, UINT64 v) { memcpy(p, &v, 8); }
#include "MemoryWindow.h"
UINT64 window_start(const void *map, size_t size, size_t stride, UINT64 offset, UINT64 head, UINT64 window, UINT64 *usable) {
  return DarwinWindowStart(map, size, stride, 0x200000, offset, head, window, UINT64_MAX, 0, usable);
}
size_t window_exclusions(const void *map, size_t size, size_t stride, UINT64 base, UINT64 window, UINT8 *table,
                         size_t capacity, UINT64 *excluded) {
  return DarwinWindowExclusions(map, size, stride, base, window, table, capacity, excluded);
}
UINT64 window_usable(const void *map, size_t size, size_t stride, UINT64 base, UINT64 window) {
  return DarwinWindowUsable(map, size, stride, base, window);
}
UINT64 window_reserve(UINT64 window) { return DARWIN_WINDOW_RESERVE(window); }
size_t window_outside(const void *map, size_t size, size_t stride, UINT8 *table, UINT64 *bytes) {  /* not used here */
  return DarwinOutsideRanges(map, size, stride, 0, 0, 0x10000, 0x100000, table, 0, bytes);
}
'''


class Window:
    """MemoryWindow.h, compiled once."""

    def __init__(self, header=HEADER, cc=None):
        if not Path(header).is_file():
            raise FileNotFoundError(f"{header}: run git submodule update --init third_party/UniXNU")
        self.tmp = tempfile.TemporaryDirectory(prefix="pipa-window-")
        work = Path(self.tmp.name)
        (work / "shim.c").write_text(SHIM)
        lib = work / "window.so"
        cc = cc or os.environ.get("CC") or "cc"
        subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-I",
                        str(Path(header).parent), str(work / "shim.c"), "-o", str(lib)], check=True)
        self.lib = ctypes.CDLL(str(lib))
        u64, sz, p = ctypes.c_uint64, ctypes.c_size_t, ctypes.c_char_p
        self.lib.window_start.restype = u64
        self.lib.window_start.argtypes = [p, sz, sz, u64, u64, u64, ctypes.POINTER(u64)]
        self.lib.window_exclusions.restype = sz
        self.lib.window_exclusions.argtypes = [p, sz, sz, u64, u64, ctypes.c_void_p, sz, ctypes.POINTER(u64)]
        self.lib.window_usable.restype = u64
        self.lib.window_usable.argtypes = [p, sz, sz, u64, u64]
        self.lib.window_reserve.restype = u64
        self.lib.window_reserve.argtypes = [u64]

    def start(self, blob, head, size):
        usable = ctypes.c_uint64()
        base = self.lib.window_start(blob, len(blob), STRIDE, KERNEL_OFFSET, head, size, ctypes.byref(usable))
        return base, usable.value

    def exclusions(self, blob, base, size, capacity):
        table = ctypes.create_string_buffer(16 * capacity)
        excluded = ctypes.c_uint64()
        count = self.lib.window_exclusions(blob, len(blob), STRIDE, base, size, table, capacity, ctypes.byref(excluded))
        pairs = [struct.unpack_from("<QQ", table.raw, 16 * i) for i in range(capacity)]
        return count, excluded.value, [p for p in pairs if p[1]]

    def usable(self, blob, base, size):
        return self.lib.window_usable(blob, len(blob), STRIDE, base, size)

    def reserve(self, size):
        return self.lib.window_reserve(size)


# The memory map model ----------------------------------------------------------------------------------------------

def reserved_from_dtb(dtb):
    from tools.hw.fdt import Tree
    tree = Tree.load(dtb)
    out = []
    for node in tree.path("/reserved-memory").children:
        if "no-map" in node.props:
            out += [(a, s) for a, s in tree.regs(node)]
    return sorted(out)


def model_map(banks=BANKS, reserved=RESERVED):
    """Descriptors (type, start, size): each bank free except the reserved ranges inside it, in address order."""
    out = []
    for base, size in banks:
        cursor, end = base, base + size
        for r, rs in sorted(reserved):
            r0, r1 = max(r, base), min(r + rs, end)
            if r0 >= r1:
                continue
            if r0 > cursor:
                out.append((FREE, cursor, r0 - cursor))
            out.append((RESERVED_TYPE, r0, r1 - r0))
            cursor = max(cursor, r1)
        if cursor < end:
            out.append((FREE, cursor, end - cursor))
    return out


def pack(descriptors):
    return b"".join(struct.pack("<I4xQQQQ8x", kind, start, 0, size >> 12, 0) for kind, start, size in descriptors)


def usable_runs(descriptors, kinds=(FREE, LOADER_CODE, LOADER_DATA)):
    out = []
    for kind, start, size in sorted((d for d in descriptors if d[0] in kinds and d[2]), key=lambda d: d[1]):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], start + size)
        else:
            out.append([start, start + size])
    return out


def reference_exclusions(descriptors, base, size):
    """The complement of the usable memory inside [base, base + size), independent of MemoryWindow.h."""
    out, cursor = [], base
    for start, end in usable_runs(descriptors):
        start, end = max(start, base), min(end, base + size)
        if start >= end:
            continue
        if start > cursor:
            out.append((cursor, start - cursor))
        cursor = max(cursor, end)
    if cursor < base + size:
        out.append((cursor, base + size - cursor))
    return out


def window_without_table(descriptors, size):
    """AllocateWindow (DarwinBoot.c): the first free descriptor, in map order, whose run holds the whole window."""
    runs = usable_runs(descriptors, kinds=(FREE,))
    for kind, start, length in descriptors:
        if kind != FREE or not length:
            continue
        end = next(e for s, e in runs if s <= start < e)
        candidate = ((start + BLOCK - 1) & ~(BLOCK - 1)) + KERNEL_OFFSET
        if candidate >= start and end >= candidate and end - candidate >= size:
            return candidate
    return 0


# Scenarios ----------------------------------------------------------------------------------------------------------

def board_windows(board=BOARD):
    raw = tomllib.loads(Path(board).read_text())
    out = []
    adt = raw.get("payload", {}).get("adt", {})
    os_profile = raw.get("board", {}).get("os_profile", "base")
    out.append({"profile": os_profile, "size": int(adt["owned_memory_size"], 0),
                "table": int(adt.get("owned_memory_excluded_ranges") or 0)})
    for name, ov in raw.get("os_overrides", {}).items():
        oadt = ov.get("payload", {}).get("adt", {})
        removed = set(ov.get("remove", []))
        size = int(oadt.get("owned_memory_size", adt["owned_memory_size"]), 0)
        table = 0 if "payload.adt.owned_memory_excluded_ranges" in removed else \
            int(oadt.get("owned_memory_excluded_ranges", adt.get("owned_memory_excluded_ranges") or 0) or 0)
        out.append({"profile": name, "size": size, "table": table})
    return out


def evaluate(win, descriptors, size, table):
    blob = pack(descriptors)
    head = IMAGE_ESTIMATE + win.reserve(size)
    head = (head + 0xfff) & ~0xfff
    row = {"size": size, "table": table, "head": head}
    if table == 0:
        base = window_without_table(descriptors, size)
        row.update(mode="single run", base=base, usable=size if base else 0, exclusions=[], merged=False)
        return row
    base, usable = win.start(blob, head, size)
    row.update(mode="excluded ranges", base=base, usable=usable)
    if not base:
        row.update(exclusions=[], merged=False)
        return row
    count, excluded, pairs = win.exclusions(blob, base, size, table)
    ref = reference_exclusions(descriptors, base, size)
    row.update(exclusions=pairs, excluded=excluded, count=count, reference=len(ref), merged=len(ref) > table,
               agrees=(pairs == ref) if len(ref) <= table else excluded >= sum(s for _, s in ref),
               usable_check=win.usable(blob, base, size) == usable == size - sum(s for _, s in ref))
    return row


def scenarios(win, descriptors, board=BOARD):
    rows = []
    for w in board_windows(board):
        rows.append({"configured": w["profile"], **evaluate(win, descriptors, w["size"], w["table"])})
    for size in (0x170000000, 0x180000000, 0x200000000):
        for table in (0, 64):
            rows.append({"configured": None, **evaluate(win, descriptors, size, table)})
    return rows


def perturbed(descriptors, holes, rng, banks=(BANKS[1], BANKS[2]), hole=2 * MIB):
    """The model map with `holes` firmware allocations (boot services data, never usable by XNU) at random 2 MiB
    aligned places in each of the big banks: what the tablet's firmware map may add, which the model cannot know."""
    extra = []
    for base, size in banks:
        extra += [(base + i * hole, hole) for i in sorted(rng.sample(range(size // hole), holes))]
    out = []
    for kind, start, length in descriptors:
        if kind != FREE or not any(start <= a < start + length for a, _ in extra):
            out.append((kind, start, length))
            continue
        cursor = start
        for a, n in extra:
            if not start <= a < start + length:
                continue
            if a > cursor:
                out.append((FREE, cursor, a - cursor))
            out.append((4, a, n))                       # EfiBootServicesData
            cursor = a + n
        if cursor < start + length:
            out.append((FREE, cursor, start + length - cursor))
    return sorted(out, key=lambda d: d[1])


def robustness(win, descriptors, size, table, trials=200, max_holes=24, seed=26):
    """How the single-run and the excluded-range rules fare when the firmware map has holes in the big bank."""
    import random
    rng = random.Random(seed)
    stats = {"trials": trials, "single_run_placed": 0, "table_placed": 0, "table_merged": 0, "disagreements": 0,
             "table_min_usable": None, "table_max_ranges": 0}
    for _ in range(trials):
        d = perturbed(descriptors, rng.randint(1, max_holes), rng)
        one = evaluate(win, d, size, 0)
        many = evaluate(win, d, size, table)
        stats["single_run_placed"] += bool(one["base"])
        if many["base"]:
            stats["table_placed"] += 1
            stats["table_merged"] += many["merged"]
            stats["table_max_ranges"] = max(stats["table_max_ranges"], many["reference"])
            stats["disagreements"] += not (many["agrees"] and many["usable_check"])
            u = many["usable"]
            stats["table_min_usable"] = u if stats["table_min_usable"] is None else min(stats["table_min_usable"], u)
    return stats


def fmt_size(v):
    return f"{v / GIB:.2f} GiB" if v >= GIB else f"{v / MIB:.0f} MiB"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dtb", type=Path, help="mainline pipa DTB: take the reserved ranges from it and check RESERVED")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    reserved = RESERVED
    problems = []
    if args.dtb:
        reserved = reserved_from_dtb(args.dtb)
        if reserved != sorted(RESERVED):
            problems.append("RESERVED differs from the mainline DTB's no-map regions")
    descriptors = model_map(BANKS, reserved)
    win = Window()
    rows = scenarios(win, descriptors)
    for r in rows:
        name = r["configured"] or "-"
        ex = f"{len(r['exclusions'])} excluded ({fmt_size(r.get('excluded', 0))})" if r["table"] else "-"
        print(f"{name:28} {fmt_size(r['size']):>9} table={r['table']:<3} {r['mode']:15} base={r['base']:#x} "
              f"usable={fmt_size(r['usable'])} {ex}{' MERGED' if r.get('merged') else ''}")
        if r["table"] and r["base"] and not (r["agrees"] and r["usable_check"]):
            problems.append(f"{fmt_size(r['size'])}: MemoryWindow.h and the reference disagree")
        if r["configured"]:
            if not r["base"]:
                problems.append(f"{name}: no window of {fmt_size(r['size'])} in the model map")
            if r.get("merged"):
                problems.append(f"{name}: {r['reference']} excluded ranges exceed the table of {r['table']}")
            if r["size"] > BOOTSTRAP_MAX:
                problems.append(f"{name}: {fmt_size(r['size'])} exceeds the {fmt_size(BOOTSTRAP_MAX)} the bootstrap tables map")
    mac = board_windows()[0]
    robust = None
    if mac["table"]:
        robust = robustness(win, descriptors, mac["size"], mac["table"])
        print(f"robustness ({mac['profile']}, {robust['trials']} maps with 1-24 random 2 MiB firmware holes in banks 1 "
              f"and 2): single run placed {robust['single_run_placed']}, excluded-range table placed "
              f"{robust['table_placed']} (merged {robust['table_merged']}, at most {robust['table_max_ranges']} ranges, "
              f"min usable {fmt_size(robust['table_min_usable'] or 0)})")
        if robust["disagreements"]:
            problems.append("MemoryWindow.h and the reference disagree on a perturbed map")
        if robust["table_placed"] != robust["trials"] or robust["table_merged"]:
            problems.append("the excluded-range table did not place every perturbed window without merging")
    if args.json:
        args.json.write_text(json.dumps({"banks": BANKS, "reserved": reserved, "rows": rows, "robustness": robust,
                                         "problems": problems},
                                        indent=2, default=lambda v: hex(v) if isinstance(v, int) else str(v)) + "\n")
    for p in problems:
        print("PROBLEM:", p)
    if args.check and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
