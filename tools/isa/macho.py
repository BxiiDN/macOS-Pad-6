"""Minimal Mach-O / dyld shared cache reader: where is the AArch64 code?

Yields CodeRange(file_offset, size, name, exclude) for:
  - thin 64-bit Mach-O (MH_EXECUTE, MH_DYLIB, MH_OBJECT, MH_KEXT_BUNDLE, ...)
  - universal (fat) files: every arm64 / arm64e slice
  - MH_FILESET (kernel collections): every LC_FILESET_ENTRY image
  - dyld shared cache files (main cache and .NN sub-caches): executable mappings

Code is taken from sections with S_ATTR_PURE_INSTRUCTIONS or
S_ATTR_SOME_INSTRUCTIONS; LC_DATA_IN_CODE ranges are reported as exclusions.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import struct
from dataclasses import dataclass, field

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
CPU_TYPE_ARM64 = 0x0100000C
MH_FILESET = 0xC
MH_OBJECT = 0x1
LC_SEGMENT_64 = 0x19
LC_DATA_IN_CODE = 0x29
LC_CODE_SIGNATURE = 0x1D
LC_FILESET_ENTRY = 0x80000035
S_ATTR_PURE_INSTRUCTIONS = 0x80000000
S_ATTR_SOME_INSTRUCTIONS = 0x00000400
VM_PROT_EXECUTE = 4


@dataclass
class CodeRange:
    offset: int
    size: int
    name: str
    exclude: list = field(default_factory=list)   # [(file_offset, size)]


@dataclass
class Image:
    name: str
    header_offset: int
    cpusubtype: int
    filetype: int
    ranges: list
    has_code_signature: bool = False


class FormatError(Exception):
    pass


def _cstr(b):
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


def parse_macho(data, base=0, name="", limit=None):
    """Parse the thin Mach-O at data[base:]; return [Image] (several for filesets)."""
    if len(data) < base + 32:
        raise FormatError("truncated header")
    magic, cputype, cpusub, filetype, ncmds, sizeofcmds, _flags, _res = struct.unpack_from(
        "<IiiIIIII", data, base)
    if magic != MH_MAGIC_64:
        raise FormatError(f"not a 64-bit little-endian Mach-O at {base:#x}")
    if cputype != CPU_TYPE_ARM64:
        return []
    off = base + 32
    end = off + sizeofcmds
    if end > len(data):
        raise FormatError("load commands run past the end of the file")
    ranges, dic_raw, entries, signed = [], [], [], False
    sections, text_vmaddr = [], None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize < 8 or off + cmdsize > end:
            raise FormatError("bad load command size")
        if cmd == LC_SEGMENT_64:
            segname = _cstr(data[off + 8:off + 24])
            seg_vmaddr, _vmsize, seg_fileoff = struct.unpack_from("<QQQ", data, off + 24)
            if seg_fileoff == 0 and filetype != MH_OBJECT and text_vmaddr is None:
                text_vmaddr = seg_vmaddr            # the segment that maps the header
            nsects = struct.unpack_from("<I", data, off + 64)[0]
            s = off + 72
            for _k in range(nsects):
                sectname = _cstr(data[s:s + 16])
                addr, size, offset = struct.unpack_from("<QQI", data, s + 32)
                flags = struct.unpack_from("<I", data, s + 64)[0]
                if offset and size:
                    # Offsets inside a fat slice are relative to the slice; inside a
                    # fileset they are relative to the collection (base of the file).
                    fo = offset + (0 if limit == "fileset" else base)
                    sections.append((addr, size, fo))
                    if flags & (S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS):
                        ranges.append(CodeRange(fo, size, f"{segname},{sectname}"))
                s += 80
        elif cmd == LC_DATA_IN_CODE:
            dataoff, datasize = struct.unpack_from("<II", data, off + 8)
            for k in range(0, datasize, 8):
                d_off, d_len, _kind = struct.unpack_from("<IHH", data,
                                                         dataoff + (0 if limit == "fileset" else base) + k)
                dic_raw.append((d_off, d_len))
        elif cmd == LC_CODE_SIGNATURE:
            signed = True
        elif cmd == LC_FILESET_ENTRY:
            _vmaddr, fileoff, name_off = struct.unpack_from("<QQI", data, off + 8)
            entries.append((fileoff, _cstr(data[off + name_off:off + cmdsize])))
        off += cmdsize
    # data_in_code_entry.offset is an address relative to the image's header
    # (linked images: the segment at file offset 0; objects: address 0).
    dic = []
    for d_off, d_len in dic_raw:
        vm = (text_vmaddr or 0) + d_off
        for addr, size, fo in sections:
            if addr <= vm < addr + size:
                dic.append((fo + (vm - addr), d_len))
                break
        else:
            raise FormatError(f"data-in-code entry at {d_off:#x} maps to no section")
    for r in ranges:
        r.exclude = [(o, n) for o, n in dic if o < r.offset + r.size and o + n > r.offset]
    images = []
    if ranges:
        images.append(Image(name or "main", base, cpusub & 0xFF, filetype, ranges, signed))
    if filetype == MH_FILESET:
        for fileoff, ename in entries:
            images += parse_macho(data, fileoff, ename, limit="fileset")
    return images


def parse_fat(data):
    magic = struct.unpack_from(">I", data, 0)[0]
    wide = magic == FAT_MAGIC_64
    nfat = struct.unpack_from(">I", data, 4)[0]
    images = []
    for k in range(nfat):
        if wide:
            cputype, cpusub, offset, _size, _align, _r = struct.unpack_from(">iiQQII", data, 8 + 32 * k)
        else:
            cputype, cpusub, offset, _size, _align = struct.unpack_from(">iiIII", data, 8 + 20 * k)
        if cputype == CPU_TYPE_ARM64:
            sub = "arm64e" if (cpusub & 0xFF) == 2 else "arm64"
            images += parse_macho(data, offset, f"slice:{sub}")
    return images


def parse_dyld_cache(data, name="dyld_shared_cache"):
    if not data.startswith(b"dyld_v1"):
        raise FormatError("not a dyld shared cache")
    arch = _cstr(data[7:16]).strip()
    mapping_off, mapping_count = struct.unpack_from("<II", data, 0x10)
    ranges = []
    for k in range(mapping_count):
        addr, size, fileoff, _maxp, initp = struct.unpack_from("<QQQII", data, mapping_off + 32 * k)
        if initp & VM_PROT_EXECUTE and size:
            ranges.append(CodeRange(fileoff, size, f"mapping@{addr:#x}"))
    return [Image(f"{name} ({arch})", 0, 2 if arch == "arm64e" else 0, 0, ranges)]


def images_of(data, name=""):
    if len(data) < 8:
        raise FormatError("file too small")
    if data.startswith(b"dyld_v1"):
        return parse_dyld_cache(data, name)
    be = struct.unpack_from(">I", data, 0)[0]
    if be in (FAT_MAGIC, FAT_MAGIC_64):
        return parse_fat(data)
    return parse_macho(data, 0, name)


def iter_words(data, rng):
    """(file_offset, word) for every aligned 32-bit word of a code range, minus exclusions."""
    start = rng.offset + (-rng.offset % 4)
    stop = min(rng.offset + rng.size, len(data))
    excl = sorted(rng.exclude)
    for off in range(start, stop - 3, 4):
        if excl and any(o <= off < o + n or o <= off + 3 < o + n for o, n in excl):
            continue
        yield off, struct.unpack_from("<I", data, off)[0]
