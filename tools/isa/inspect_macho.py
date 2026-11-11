"""Structure facts for the Tahoe audit: fileset entries, symbols, chained fixups,
dyld shared cache subcaches, images, slide info and per-image attribution.

Field offsets of the dyld cache header come from dyld-1378 (macOS 26.5)
include/mach-o/dyld_cache_format.h, checked with offsetof() when written:
mappingWithSlideOffset 0x138, osVersion 0x16c, subCacheArrayOffset 0x188,
imagesOffset 0x1c0; dyld_subcache_entry and dyld_cache_mapping_and_slide_info
are 56 bytes, dyld_cache_image_info 32 bytes.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import bisect
import struct
from collections import Counter
from pathlib import Path

from tools.isa import macho

LC_SYMTAB = 0x2
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_CHAINED_FIXUPS = 0x80000034

POINTER_FORMATS = {
    1: "ARM64E", 2: "64", 3: "32", 4: "32_CACHE", 5: "32_FIRMWARE", 6: "64_OFFSET",
    7: "ARM64E_KERNEL", 8: "64_KERNEL_CACHE", 9: "ARM64E_USERLAND", 10: "ARM64E_FIRMWARE",
    11: "X86_64_KERNEL_CACHE", 12: "ARM64E_USERLAND24", 13: "ARM64E_SHARED_CACHE",
    14: "ARM64E_SEGMENTED",
}
ARM64E_FORMATS = {"ARM64E", "ARM64E_KERNEL", "ARM64E_USERLAND", "ARM64E_FIRMWARE",
                  "ARM64E_USERLAND24", "ARM64E_SHARED_CACHE", "ARM64E_SEGMENTED"}


def _cstr(b):
    return bytes(b).split(b"\0", 1)[0].decode("utf-8", "replace")


def load_commands(data, base):
    """Yield (cmd, offset, size) of the Mach-O at data[base:]."""
    magic, _ct, _cs, _ft, ncmds, sizeofcmds = struct.unpack_from("<IiiIII", data, base)
    if magic != macho.MH_MAGIC_64:
        raise macho.FormatError(f"no 64-bit Mach-O at {base:#x}")
    off = base + 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        yield cmd, off, size
        off += size


def fileset_entries(data):
    """[(entry id, file offset, vmaddr)] of an MH_FILESET kernel collection."""
    out = []
    for cmd, off, size in load_commands(data, 0):
        if cmd == macho.LC_FILESET_ENTRY:
            vmaddr, fileoff, name_off = struct.unpack_from("<QQI", data, off + 8)
            out.append((_cstr(data[off + name_off:off + size]), fileoff, vmaddr))
    return out


def find_symbol(data, base, name, absolute_offsets):
    """Address of an external or local symbol in one image (LC_SYMTAB), or None.
    absolute_offsets: symoff/stroff are file offsets of the whole file (filesets)."""
    want = name.encode()
    for cmd, off, _size in load_commands(data, base):
        if cmd != LC_SYMTAB:
            continue
        symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, off + 8)
        delta = 0 if absolute_offsets else base
        strtab = data[stroff + delta:stroff + delta + strsize]
        for k in range(nsyms):
            strx, _type, _sect, _desc, value = struct.unpack_from("<IBBhQ", data, symoff + delta + 16 * k)
            if strtab[strx:strx + len(want) + 1] == want + b"\0":
                return value
    return None


def fixup_kind(data, base=0, absolute_offsets=False):
    """Counter of chained pointer formats (per segment), or {'dyld_info opcodes': 1}."""
    kinds = Counter()
    delta = 0 if absolute_offsets else base
    for cmd, off, _size in load_commands(data, base):
        if cmd == LC_DYLD_CHAINED_FIXUPS:
            dataoff, _datasize = struct.unpack_from("<II", data, off + 8)
            h = dataoff + delta
            _ver, starts_offset = struct.unpack_from("<II", data, h)
            s = h + starts_offset
            seg_count = struct.unpack_from("<I", data, s)[0]
            for k in range(seg_count):
                seg_off = struct.unpack_from("<I", data, s + 4 + 4 * k)[0]
                if seg_off:
                    fmt = struct.unpack_from("<H", data, s + seg_off + 6)[0]
                    kinds[POINTER_FORMATS.get(fmt, f"format-{fmt}")] += 1
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            kinds["dyld_info opcodes"] += 1
    return kinds


class DyldCache:
    """A dyld shared cache: the main file and every subcache next to it."""

    def __init__(self, main_path, reader):
        """reader(path) returns a buffer (bytes, bytearray or mmap) for a cache file."""
        self.main_path = Path(main_path)
        self.reader = reader
        self.files = {}
        main = self._file(self.main_path)
        self.arch = _cstr(main[7:16]).strip()
        self.os_version = struct.unpack_from("<I", main, 0x16C)[0]
        self.platform = struct.unpack_from("<I", main, 0xD8)[0]
        sub_off, sub_count = struct.unpack_from("<II", main, 0x188)
        self.subcaches = [self.main_path]
        for k in range(sub_count):
            suffix = _cstr(main[sub_off + 56 * k + 24:sub_off + 56 * k + 56])
            self.subcaches.append(Path(str(self.main_path) + suffix))
        self.mappings = []            # (vmaddr, size, fileoff, path, initprot, slide_version, flags)
        for path in self.subcaches:
            buf = self._file(path)
            ms_off, ms_count = struct.unpack_from("<II", buf, 0x138)
            for k in range(ms_count):
                (addr, size, fileoff, slide_off, slide_size, flags, _maxp,
                 initp) = struct.unpack_from("<QQQQQQII", buf, ms_off + 56 * k)
                version = struct.unpack_from("<I", buf, slide_off)[0] if slide_off and slide_size else None
                self.mappings.append((addr, size, fileoff, path, initp, version, flags))
        self.mappings.sort()
        img_off, img_count = struct.unpack_from("<II", main, 0x1C0)
        self.images = []
        for k in range(img_count):
            addr, _mt, _ino, path_off = struct.unpack_from("<QQQI", main, img_off + 32 * k)
            self.images.append((addr, _cstr(main[path_off:path_off + 1024])))

    def _file(self, path):
        if path not in self.files:
            self.files[path] = self.reader(path)
        return self.files[path]

    def locate(self, vmaddr):
        """(path, file offset) of a cache address."""
        for addr, size, fileoff, path, *_rest in self.mappings:
            if addr <= vmaddr < addr + size:
                return path, fileoff + (vmaddr - addr)
        return None, None

    def code_ranges(self, path):
        """macho.CodeRange list of the executable mappings in one cache file."""
        return [macho.CodeRange(fo, size, f"{p.name}@{addr:#x}")
                for addr, size, fo, p, initp, *_r in self.mappings
                if p == path and initp & macho.VM_PROT_EXECUTE and size]

    def slide_versions(self):
        return Counter(v for *_x, v, _f in self.mappings if v is not None)

    def text_index(self):
        """Sorted [(text start, text end, install name)] for attribution."""
        out = []
        for addr, name in self.images:
            path, off = self.locate(addr)
            if path is None:
                continue
            buf = self._file(path)
            try:
                for cmd, lc, _size in load_commands(buf, off):
                    if cmd == macho.LC_SEGMENT_64 and _cstr(buf[lc + 8:lc + 24]) == "__TEXT":
                        vmaddr, vmsize = struct.unpack_from("<QQ", buf, lc + 24)
                        out.append((vmaddr, vmaddr + vmsize, name))
                        break
            except (macho.FormatError, struct.error):
                continue
        out.sort()
        return out

    def file_offset_to_vm(self, path, off):
        for addr, size, fileoff, p, *_rest in self.mappings:
            if p == path and fileoff <= off < fileoff + size:
                return addr + (off - fileoff)
        return None


def attribute(index, vmaddrs):
    """Counter of install names for a list of cache addresses."""
    starts = [s for s, _e, _n in index]
    out = Counter()
    for a in vmaddrs:
        k = bisect.bisect_right(starts, a) - 1
        if k >= 0 and a < index[k][1]:
            out[index[k][2]] += 1
        else:
            out["(outside any image __TEXT)"] += 1
    return out
