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

Then the kernel side (window-memory-excluded-ranges.patch, modelled in Python as kernel_table): XNU's own copy of the
table (clipped, rounded to its 4 KiB page, joined), the first-range check against its boot allocations (no excluded
range in the first max(span / 64, 32 MiB) behind the image), and that its excluded bytes equal the loader's (so
hw.memsize = memSizeActual). The bootstrap tables (native-4k-bootstrap-capacity.patch, start.s): the pages the V=P
and KVA block mappings take for the window at every 2 MiB slide, against the 16-page pool. The bounds UniXNU's ADT
generator enforces (window size and step, 1..4096 table slots) and both reserve formulas are read from the sources.

--check fails unless every configured window is placed, the macOS window's exclusions fit its table without
merging, the kernel accepts its table without a panic and counts the same bytes, every slide fits the bootstrap pool,
the window spans no DRAM bank gap, the board's values are inside the sources' bounds, the reserve formulas agree, and
the largest window the 4 KiB bootstrap pool maps at every base and slide is the 6 GiB board.toml states.

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
UNIXNU = ROOT / "third_party/UniXNU"
HEADER = UNIXNU / "drivers/DarwinBoot/DarwinBootPkg/Driver/MemoryWindow.h"
BOARD = ROOT / "devices/pipa/board.toml"
# The kernel side, read as source each time (source_limits): the excluded-range patch of the board's chain, the native
# 4 KiB bootstrap table patch, and UniXNU's ADT generator (window and table bounds).
EXCLUDED_PATCH = UNIXNU / "profiles/os/macos-27.3-26C5035r/patches/xnu-12377/window-memory-excluded-ranges.patch"
BOOTSTRAP_PATCH = UNIXNU / "patches/xnu-12377/native-4k-bootstrap-capacity.patch"
DEVICETREE = UNIXNU / "scripts/unixnu/devicetree.py"
MIB, GIB = 1 << 20, 1 << 30
BLOCK = 2 * MIB
BOOTSTRAP_MAX = 6 * GIB          # board.toml / UniXNU-sheng: the most the 4 KiB bootstrap tables map
KERNEL_PAGE = 4096               # pipa_macos26_defconfig builds the native 4 KiB kernel (build-xnu-4k-baseline.sh)
L2_REGION = 1 * GIB              # one 4 KiB-granule L2 table maps 512 x 2 MiB blocks
BOOTSTRAP_PAGES = 16             # native-4k-bootstrap-capacity.patch: BOOTSTRAP_TABLE_SIZE = ARM_PGBYTES * 16
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


# The kernel side: what XNU does with the table (window-memory-excluded-ranges.patch, arm_vm_init.c) ------------------

def kernel_reserve(span):
    """ARM_VM_EXCLUDED_RESERVE: the room behind the loaded image that must hold no excluded range."""
    return max(span // 64, 32 * MIB)


def kernel_table(pairs, phys_base, mem_size, top_of_kernel_data, page=KERNEL_PAGE):
    """arm_vm_excluded_init, in Python: drop empty slots, clip to the span, round outward to the kernel's page, insert
    sorted, join neighbours that touch, then the first-range check against the boot allocations. Returns the table,
    its bytes (arm_vm_excluded_bytes over the span), the panic message the kernel would print (None if none), and the
    avail_start after the table (the kernel keeps the table in the page(s) at the old avail_start)."""
    span_end = phys_base + mem_size
    table = []
    for base, size in pairs:
        if size == 0:
            continue
        end = base + size
        if end < base or end > span_end:
            end = span_end
        base = max(base & ~(page - 1), phys_base)
        end = (end + page - 1) & ~(page - 1)
        if base >= end:
            continue
        table.append([base, end])
        table.sort()
        merged = []
        for b, e in table:
            if merged and merged[-1][1] >= b:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([b, e])
        table = merged
    avail = (top_of_kernel_data + page - 1) & ~(page - 1)
    out = {"table": [tuple(r) for r in table], "panic": None, "avail_start": avail,
           "bytes": sum(min(e, span_end) - max(b, phys_base) for b, e in table)}
    if not table:
        return out
    if table[0][0] < top_of_kernel_data + kernel_reserve(mem_size):
        out["panic"] = (f"excluded memory at {table[0][0]:#x} is inside the kernel's boot allocations "
                        f"({top_of_kernel_data:#x} + {kernel_reserve(mem_size):#x})")
    out["avail_start"] = (avail + 16 * len(table) + page - 1) & ~(page - 1)
    return out


def l2_tables(vbase, length):
    """create_bootstrap_mapping (start.s): one L2 table per 1 GiB region the virtual range of the 2 MiB blocks
    touches (the first one partly used from vbase's L2 index)."""
    blocks = length >> 21
    if blocks == 0:
        return 1
    return ((vbase + blocks * BLOCK - 1) // L2_REGION) - (vbase // L2_REGION) + 1


def bootstrap_pages(phys_base, length, virt_offset):
    """Pages of bootstrap_pagetables the V=P and the KVA mapping use: two L1 roots and the L2 tables of each.
    virt_offset is the kernel's virtual base modulo 1 GiB (KASLR moves it in 2 MiB steps)."""
    return 2 + l2_tables(phys_base, length) + l2_tables(virt_offset, length)


def bootstrap_worst(phys_base, length):
    """The most pages any 2 MiB-aligned virtual slide needs, and the offsets that need them."""
    counts = {off: bootstrap_pages(phys_base, length, off) for off in range(0, L2_REGION, BLOCK)}
    worst = max(counts.values())
    return worst, sum(1 for c in counts.values() if c == worst)


def max_bootstrap_window(phys_base=None, step=256 * MIB, limit=8 * GIB):
    """The largest window (in `step`s) every slide can map with BOOTSTRAP_PAGES; with phys_base None, also every
    2 MiB-aligned physical base."""
    best = 0
    for size in range(step, limit + 1, step):
        bases = [phys_base] if phys_base is not None else range(0, L2_REGION, BLOCK)
        if all(bootstrap_worst(b, size)[0] <= BOOTSTRAP_PAGES for b in bases):
            best = size
        else:
            break
    return best


def bank_gaps(base, size, banks=BANKS):
    """Address ranges of [base, base + size) that no DRAM bank backs: the bootstrap block mappings cover the whole
    span as normal memory until arm_vm_init replaces them, so a gap there is mapped for that time."""
    out, cursor = [], base
    for b, s in sorted(banks):
        b0, b1 = max(b, base), min(b + s, base + size)
        if b0 >= b1:
            continue
        if b0 > cursor:
            out.append((cursor, b0 - cursor))
        cursor = max(cursor, b1)
    if cursor < base + size:
        out.append((cursor, base + size - cursor))
    return out


def source_limits():
    """The bounds the sources state, read each time: UniXNU's ADT generator (window size and step, table slots),
    the reserve formula of the kernel patch and of MemoryWindow.h, and the bootstrap pool of the 4 KiB patch.
    Missing text is an error, not a default."""
    import re
    out, errors = {}, []

    def find(path, pattern, name):
        m = re.search(pattern, Path(path).read_text()) if Path(path).is_file() else None
        if not m:
            errors.append(f"{Path(path).name}: {name} not found")
        return m
    m = find(DEVICETREE, r"if not (0x[0-9a-f]+) <= size <= (0x[0-9a-f]+) or size % (0x[0-9a-f]+):", "owned_memory_size bounds")
    if m:
        out["window_min"], out["window_max"], out["window_step"] = (int(g, 16) for g in m.groups())
    m = find(DEVICETREE, r"if not (\d+) <= slots <= (\d+):\s*\n\s*raise Error\('Owned memory excluded ranges", "table bounds")
    if m:
        out["slots_min"], out["slots_max"] = int(m.group(1)), int(m.group(2))
    m = find(EXCLUDED_PATCH, r"#define ARM_VM_EXCLUDED_RESERVE\(span\) MAX\(\(span\) / (\d+), \(uint64_t\)(\d+) \* 1024 \* 1024\)",
             "ARM_VM_EXCLUDED_RESERVE")
    if m:
        out["kernel_reserve"] = (int(m.group(1)), int(m.group(2)) * MIB)
    m = find(HEADER, r"#define DARWIN_WINDOW_RESERVE\(Size\)\s+\(\(\(\(Size\) / (\d+)\) > (0x[0-9a-fA-F]+)ULL\)", "DARWIN_WINDOW_RESERVE")
    if m:
        out["loader_reserve"] = (int(m.group(1)), int(m.group(2), 16))
    m = find(BOOTSTRAP_PATCH, r"\+#define BOOTSTRAP_TABLE_SIZE \(ARM_PGBYTES \* (\d+)\)", "BOOTSTRAP_TABLE_SIZE")
    if m:
        out["bootstrap_pages"] = int(m.group(1))
    m = find(EXCLUDED_PATCH, r"if \(table\[0\]\.base < args->topOfKernelData \+ ARM_VM_EXCLUDED_RESERVE\(mem_size\)\)",
             "first-range check")
    out["first_range_check"] = bool(m)
    return out, errors


def kernel_view(row, size, page=KERNEL_PAGE):
    """What the kernel makes of a placed window's table: its own table, bytes, and whether it would panic. The
    loaded image is IMAGE_ESTIMATE bytes from the window base (the loader's head is that plus its reserve)."""
    k = kernel_table(row["exclusions"], row["base"], size, row["base"] + IMAGE_ESTIMATE, page)
    return {"ranges": len(k["table"]), "bytes": k["bytes"], "panic": k["panic"],
            "table_bytes": 16 * len(k["table"]), "memsize_agrees": k["bytes"] == row.get("excluded", 0)}


# Address consistency: board, DTS, loader head, kernel image --------------------------------------------------------

KC_BYTES = 135036928             # the prelinked macOS 26.5 kernel collection (docs/kernel-build.md, attempts 9-12)
DTS = ROOT / "devices/pipa/dts/pipa.dts"


def dts_memory(path=DTS):
    """The (base, size) of the DTS memory node: reg = <hi lo hi lo>."""
    import re
    m = re.search(r"memory@[0-9a-f]+\s*\{[^}]*?reg\s*=\s*<([^>]*)>", Path(path).read_text(), re.S)
    if not m:
        raise ValueError(f"{path}: no memory node")
    c = [int(x, 0) for x in m.group(1).split()]
    return (c[0] << 32 | c[1], c[2] << 32 | c[3])


def address_audit(base, size, exclusions, board=BOARD, page=KERNEL_PAGE):
    """Whether the window, the head the loader keeps free, the image and the excluded ranges agree with each other and
    with the board: a list of (check, ok, detail)."""
    raw = tomllib.loads(Path(board).read_text())
    dram_size = int(raw["payload"]["dram_size"], 0)
    dts_base, dts_size = dts_memory()
    span_end = base + size
    head = IMAGE_ESTIMATE + kernel_reserve(size)
    out = [
        ("DTS memory = board dram range", (dts_base, dts_size) == (0x80000000, dram_size),
         f"DTS {dts_base:#x}+{dts_size:#x}, board 0x80000000+{dram_size:#x}"),
        ("window inside the dram range", dts_base <= base and span_end <= dts_base + dts_size,
         f"{base:#x}..{span_end:#x}"),
        ("window inside one DRAM bank", not bank_gaps(base, size), f"gaps {bank_gaps(base, size)}"),
        ("window 2 MiB aligned (block mappings, kernel offset 0)", base % BLOCK == 0 and size % BLOCK == 0, f"{base:#x}"),
        ("image estimate holds the kernel collection", IMAGE_ESTIMATE >= KC_BYTES,
         f"{IMAGE_ESTIMATE:#x} >= {KC_BYTES:#x}"),
        ("head (image + reserve) inside the window", head < size, f"head {head:#x}"),
        ("excluded ranges page aligned, sorted, inside the window, past the head",
         all(b % page == 0 and s % page == 0 and base + head <= b and b + s <= span_end for b, s in exclusions) and
         [b for b, _ in exclusions] == sorted(b for b, _ in exclusions),
         f"{len(exclusions)} ranges"),
        ("kernel table fits one page", 16 * len(exclusions) <= page, f"{16 * len(exclusions)} bytes"),
    ]
    return out


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
    row["kernel"] = kernel_view(row, size)
    row["bank_gaps"] = bank_gaps(base, size)
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
             "table_min_usable": None, "table_max_ranges": 0, "kernel_panics": 0, "kernel_disagreements": 0}
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
            stats["kernel_panics"] += bool(many["kernel"]["panic"])
            stats["kernel_disagreements"] += not many["kernel"]["memsize_agrees"]
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
        if r["configured"] and r["table"] and r["base"]:
            k = r["kernel"]
            print(f"  kernel: {k['ranges']} ranges, {fmt_size(k['bytes'])} excluded, table {k['table_bytes']} bytes, "
                  f"{'PANIC ' + k['panic'] if k['panic'] else 'no panic'}; bank gaps in the span: {len(r['bank_gaps'])}")
            if k["panic"]:
                problems.append(f"{name}: the kernel would panic: {k['panic']}")
            if not k["memsize_agrees"]:
                problems.append(f"{name}: the kernel's excluded bytes differ from the loader's (hw.memsize)")
            if r["bank_gaps"]:
                problems.append(f"{name}: the window spans a DRAM bank gap the bootstrap tables would map")
        if r["configured"] and r["base"]:
            worst, offsets = bootstrap_worst(r["base"], r["size"])
            r["bootstrap"] = {"worst_pages": worst, "worst_offsets": offsets, "pool": BOOTSTRAP_PAGES}
            print(f"  bootstrap tables: at most {worst} of {BOOTSTRAP_PAGES} pages over every 2 MiB slide "
                  f"({offsets} of 512 slides need that many)")
            if worst > BOOTSTRAP_PAGES and r["table"]:
                problems.append(f"{name}: a slide needs {worst} bootstrap table pages, the pool holds {BOOTSTRAP_PAGES}")

    # The bounds the sources state, and the board's values against them.
    limits, errors = source_limits()
    problems += errors
    print(f"source limits: {json.dumps(limits)}")
    if {"window_min", "window_max", "window_step"} <= limits.keys():
        for w in board_windows():
            if not (limits["window_min"] <= w["size"] <= limits["window_max"]) or w["size"] % limits["window_step"]:
                problems.append(f"{w['profile']}: owned_memory_size {w['size']:#x} is outside UniXNU's bounds")
    if {"slots_min", "slots_max"} <= limits.keys():
        for w in board_windows():
            if w["table"] and not limits["slots_min"] <= w["table"] <= limits["slots_max"]:
                problems.append(f"{w['profile']}: {w['table']} table slots outside {limits['slots_min']}..{limits['slots_max']}")
    if limits.get("kernel_reserve") != (64, 32 * MIB) or limits.get("loader_reserve") != (64, 32 * MIB):
        problems.append("the reserve formulas of the kernel patch and MemoryWindow.h are not the ones modelled "
                        f"(kernel {limits.get('kernel_reserve')}, loader {limits.get('loader_reserve')})")
    else:
        for size in range(256 * MIB, 8 * GIB + 1, 256 * MIB):
            if win.reserve(size) != kernel_reserve(size):
                problems.append(f"loader and kernel reserve differ at {fmt_size(size)}")
                break
    if limits.get("bootstrap_pages") != BOOTSTRAP_PAGES:
        problems.append(f"BOOTSTRAP_TABLE_SIZE is {limits.get('bootstrap_pages')} pages, the model assumes {BOOTSTRAP_PAGES}")
    if "slots_max" in limits:
        slots_bytes = 16 * limits["slots_max"]
        if slots_bytes > kernel_reserve(limits.get("window_min", 256 * MIB)):
            problems.append("the largest table does not fit the smallest reserve")
    bootstrap_any = max_bootstrap_window()
    bootstrap_aligned = max_bootstrap_window(L2_REGION)
    print(f"bootstrap pool: largest window every slide maps: {fmt_size(bootstrap_any)} at any 2 MiB base, "
          f"{fmt_size(bootstrap_aligned)} at a 1 GiB aligned base")
    if bootstrap_any != BOOTSTRAP_MAX:
        problems.append(f"the 4 KiB bootstrap pool maps {fmt_size(bootstrap_any)} at every base and slide, "
                        f"not the {fmt_size(BOOTSTRAP_MAX)} board.toml states")

    mac_row = next(r for r in rows if r["configured"] == board_windows()[0]["profile"])
    if mac_row["base"]:
        for name, ok, detail in address_audit(mac_row["base"], mac_row["size"], mac_row["exclusions"]):
            print(f"  address audit: {'ok  ' if ok else 'FAIL'} {name} ({detail})")
            if not ok:
                problems.append(f"address audit: {name} ({detail})")

    mac = board_windows()[0]
    robust = None
    if mac["table"]:
        robust = robustness(win, descriptors, mac["size"], mac["table"])
        print(f"robustness ({mac['profile']}, {robust['trials']} maps with 1-24 random 2 MiB firmware holes in banks 1 "
              f"and 2): single run placed {robust['single_run_placed']}, excluded-range table placed "
              f"{robust['table_placed']} (merged {robust['table_merged']}, at most {robust['table_max_ranges']} ranges, "
              f"min usable {fmt_size(robust['table_min_usable'] or 0)}); kernel panics {robust['kernel_panics']}, "
              f"kernel/loader byte disagreements {robust['kernel_disagreements']}")
        if robust["kernel_panics"] or robust["kernel_disagreements"]:
            problems.append("the kernel's table check fails or disagrees with the loader on a perturbed map")
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
