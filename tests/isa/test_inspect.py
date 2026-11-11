"""Tests of tools/isa/inspect_macho.py on synthetic files laid out per dyld-1378's
headers (chained fixups, fileset entries, symbols, a two-file dyld shared cache).

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import struct
import tempfile
import unittest
from pathlib import Path

from tools.isa import fast, inspect_macho, macho

RETAB = 0xD65F0FFF
FJCVTZS = 0x1E7E0020
NOP = 0xD503201F


def segment(name, vmaddr, vmsize, fileoff, filesize, sections=()):
    body = struct.pack("<16sQQQQiiII", name.encode(), vmaddr, vmsize, fileoff, filesize, 7, 5,
                       len(sections), 0)
    for sname, addr, size, off, flags in sections:
        body += struct.pack("<16s16sQQIIIIIIII", sname.encode(), name.encode(), addr, size, off, 2, 0, 0,
                            flags, 0, 0, 0)
    return struct.pack("<II", macho.LC_SEGMENT_64, 8 + len(body)) + body


def macho_header(filetype, cmds, cpusub=2):
    lc = b"".join(cmds)
    return struct.pack("<IiiIIIII", macho.MH_MAGIC_64, macho.CPU_TYPE_ARM64, cpusub, filetype,
                       len(cmds), len(lc), 0, 0) + lc


class Fixups(unittest.TestCase):
    def test_chained_formats_per_segment(self):
        # header + LC_DYLD_CHAINED_FIXUPS pointing at a fixups blob with 3 segments,
        # two of them with starts (formats ARM64E_USERLAND24 and ARM64E).
        blob = bytearray(struct.pack("<IIIIIII", 0, 28, 0, 0, 0, 1, 0))
        starts = 28
        seg_info = struct.pack("<I", 3) + struct.pack("<III", 0, 16, 40)
        blob += seg_info
        blob += struct.pack("<IHHQIHH", 24, 0x4000, 12, 0, 0, 1, 0)
        blob += struct.pack("<IHHQIHH", 24, 0x4000, 1, 0, 0, 1, 0)
        assert starts == 28
        fix_off = 0x200
        lc = struct.pack("<IIII", inspect_macho.LC_DYLD_CHAINED_FIXUPS, 16, fix_off, len(blob))
        data = bytearray(macho_header(6, [lc]).ljust(fix_off, b"\0")) + blob
        self.assertEqual(dict(inspect_macho.fixup_kind(bytes(data))),
                         {"ARM64E_USERLAND24": 1, "ARM64E": 1})

    def test_dyld_info_opcodes(self):
        lc = struct.pack("<II", inspect_macho.LC_DYLD_INFO_ONLY, 48) + b"\0" * 40
        self.assertEqual(dict(inspect_macho.fixup_kind(macho_header(2, [lc]))), {"dyld_info opcodes": 1})


class FilesetAndSymbols(unittest.TestCase):
    def test_entry_and_symbol(self):
        entry_off = 0x1000
        name = b"com.apple.driver.AppleMobileFileIntegrity\0"
        fe = struct.pack("<IIQQII", macho.LC_FILESET_ENTRY, 32 + len(name) + 6, 0xFFFFFE0007000000, entry_off,
                         32, 0) + name + b"\0" * 6
        top = macho_header(macho.MH_FILESET, [fe])
        strtab = b"\0_other\0_amfi_register_mac_policy\0"
        symoff, stroff = 0x2000, 0x2100
        symtab = struct.pack("<IIIIII", inspect_macho.LC_SYMTAB, 24, symoff, 2, stroff, len(strtab))
        entry = macho_header(0xB, [symtab])
        data = bytearray(top.ljust(entry_off, b"\0") + entry)
        data = data.ljust(symoff, b"\0")
        data += struct.pack("<IBBhQ", 1, 0xF, 1, 0, 0x1111)
        data += struct.pack("<IBBhQ", 8, 0xF, 1, 0, 0xFFFFFE0009840DD4)
        data = data.ljust(stroff, b"\0") + strtab
        self.assertEqual(inspect_macho.fileset_entries(bytes(data)),
                         [("com.apple.driver.AppleMobileFileIntegrity", entry_off, 0xFFFFFE0007000000)])
        self.assertEqual(inspect_macho.find_symbol(bytes(data), entry_off, "_amfi_register_mac_policy", True),
                         0xFFFFFE0009840DD4)
        self.assertIsNone(inspect_macho.find_symbol(bytes(data), entry_off, "_missing", True))


class DyldCacheTest(unittest.TestCase):
    """Main file: header, one text mapping holding libA's Mach-O header and code,
    and the image list. Subcache .01: header and libB's text."""

    def build(self, tmp):
        base = 0x180000000

        def header(mappings, images=(), subcaches=(), path_blob=b""):
            h = bytearray(0x400)
            h[0:16] = b"dyld_v1  arm64e\0"
            struct.pack_into("<I", h, 0xD8, 1)
            struct.pack_into("<I", h, 0x16C, (26 << 16) | (5 << 8))
            ms = 0x200
            struct.pack_into("<II", h, 0x138, ms, len(mappings))
            for k, m in enumerate(mappings):
                struct.pack_into("<QQQQQQII", h, ms + 56 * k, *m)
            struct.pack_into("<II", h, 0x188, 0x300, len(subcaches))
            for k, (off, suffix) in enumerate(subcaches):
                struct.pack_into("<16sQ32s", h, 0x300 + 56 * k, b"\0" * 16, off, suffix.encode())
            struct.pack_into("<II", h, 0x1C0, 0x380, len(images))
            for k, (addr, poff) in enumerate(images):
                struct.pack_into("<QQQI", h, 0x380 + 32 * k, addr, 0, 0, poff)
            return h

        def lib(textaddr, code):
            seg = segment("__TEXT", textaddr, 0x1000, 0, 0x1000)
            mh = macho_header(6, [seg])
            return mh.ljust(0x100, b"\0") + b"".join(struct.pack("<I", w) for w in code)

        liba = lib(base + 0x1000, [NOP, RETAB, FJCVTZS, RETAB])
        libb = lib(base + 0x10000, [FJCVTZS, FJCVTZS, NOP])
        names = b"/usr/lib/libA.dylib\0/System/Library/Frameworks/B.framework/B\0"
        main = header([(base, 0x1000, 0, 0, 0, 0, 5, 5), (base + 0x1000, 0x1000, 0x1000, 0, 0, 0, 5, 5)],
                      images=[(base + 0x1000, 0x800), (base + 0x10000, 0x800 + 20)],
                      subcaches=[(0x10000, ".01")])
        main = bytes(main).ljust(0x800, b"\0") + names
        main = main.ljust(0x1000, b"\0") + liba.ljust(0x1000, b"\0")
        sub = bytes(header([(base + 0x10000, 0x1000, 0x1000, 0x1800, 4, 1, 3, 5)]))
        sub = sub.ljust(0x1000, b"\0") + libb.ljust(0x800, b"\0") + struct.pack("<I", 3).ljust(0x800, b"\0")
        p = Path(tmp) / "dyld_shared_cache_arm64e"
        p.write_bytes(main)
        Path(str(p) + ".01").write_bytes(sub)
        return p

    def test_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.build(tmp)
            cache = inspect_macho.DyldCache(p, lambda path: bytearray(Path(path).read_bytes()))
            self.assertEqual([s.name for s in cache.subcaches], ["dyld_shared_cache_arm64e",
                                                                 "dyld_shared_cache_arm64e.01"])
            self.assertEqual(cache.os_version, (26 << 16) | (5 << 8))
            self.assertEqual(len(cache.images), 2)
            index = cache.text_index()
            self.assertEqual([n for _s, _e, n in index],
                             ["/usr/lib/libA.dylib", "/System/Library/Frameworks/B.framework/B"])
            seen = {}
            for path in cache.subcaches:
                buf = cache._file(path)
                counts, hits = fast.scan(buf, cache.code_ranges(path), record=["jscvt"])
                vms = [cache.file_offset_to_vm(path, o) for o in hits["jscvt"]]
                for k, v in inspect_macho.attribute(index, vms).items():
                    seen[k] = seen.get(k, 0) + v
            self.assertEqual(seen, {"/usr/lib/libA.dylib": 1, "/System/Library/Frameworks/B.framework/B": 2})
            self.assertEqual(dict(cache.slide_versions()), {3: 1})


if __name__ == "__main__":
    unittest.main()
