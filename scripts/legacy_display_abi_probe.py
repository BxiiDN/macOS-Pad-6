#!/usr/bin/env python3
"""What NativeLegacyDisplay needs from a macOS kernel collection, looked up in the 26.5 one (numbers and yes/no only).

    scripts/legacy_display_abi_probe.py --xnuprelink DIR --kernelcache KC [--json OUT]       (macOS runner, after prelink)

GopFramebuffer's NativeLegacyDisplay is a subclass of the original IOMobileFramebufferLegacy (IOMobileGraphicsFamily) that
replaces its hardware back end; WindowServer then drives it like any Apple display. It binds to one fileset through a
fixture (UniXNU-sheng's scripts/legacy-display-<build>.json, written by gen-board-abi.py from that collection). For
macOS 27.3 (26C5035r) the fixture holds: the class's vtable (483 slots, each with the diversity its callers authenticate
with), IOService's slot count (272), the class's instance size, the pure-virtual target, the four class bindings, eleven
getters and dispatchers of IOMobileGraphicsFamily, IOSurface and IOAVFamily, code checks of six accessors, and field
offsets of the display, its swap request and its notification block, each verified against the code that uses it. The
pure slots take their diversity from an oracle: the same release's virtual-machine collection (AppleParavirtDisplay).

This looks up, in the collection this run prelinked against, every symbol the fixture is built from, counts the two
vtables, reads the instance size the way gen-board-abi.py does, and tests the 27.3 field offsets against the 26.5 code
with the same instruction patterns. It prints only symbol names, counts, sizes and whether each check holds: nothing
of the collection's code or data, and no address. It writes no fixture: that needs the 26.5 oracle collection and a
review of every role, which is the next step if the counts say the 27.3 layout is close.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import struct
import sys
from pathlib import Path

FAMILY, CLS = "com.apple.iokit.IOMobileGraphicsFamily", "IOMobileFramebufferLegacy"
N = f"{len(CLS)}{CLS}"
# Everything gen-board-abi.py's legacy_fixture reads, by owner.
SYMBOLS = {
    FAMILY: [f"__ZN{N}C2EPK11OSMetaClass", f"__ZN{N}D2Ev", f"__ZN{N}10gMetaClassE", f"__ZTV{N}", f"__ZN{N}9MetaClassC2Ev",
             f"__ZN{N}26swap_notify_dispatch_gatedEyyy", f"__ZN{N}27setDisplayRefreshPropertiesEv",
             f"__ZN{N}31swap_info_notify_dispatch_gatedEPNS_12SwapInfoBlobE", f"__ZN{N}14hotPlug_notifyEy",
             f"__ZN{N}23getCurrentSrcRect_gatedEj", f"__ZN{N}23getCurrentDstRect_gatedEj", f"__ZNK{N}13display_widthEv",
             "__ZTV19IOMobileFramebuffer"],
    "com.apple.iokit.IOSurface": ["__ZNK9IOSurface19getMemoryDescriptorEv", "__ZNK9IOSurface8getWidthEv",
                                  "__ZNK9IOSurface9getHeightEv", "__ZNK9IOSurface14getBytesPerRowEv",
                                  "__ZNK9IOSurface14getPixelFormatEv", "__ZNK9IOSurface13getPlaneCountEv",
                                  "__ZN13IOSurfaceRoot13createSurfaceEP4taskP12OSDictionary", "__ZN9IOSurface8allocateEv"],
    "com.apple.iokit.IOAVFamily": [
        "__ZN22IOAVVideoTimingElement8withDataEPK19IOAVVideoTimingData16IOAVStandardType23IOAVVideoTimingStandard",
        "__ZN22IOAVVideoTimingElement16setColorElementsEP7OSArray",
        "__ZN21IOAVVideoColorElement16withCapabilitiesE16IOAVStandardTypej22IOAVVideoPixelEncoding26IOAVVideoColorDynamicRange"
        "18IOAVVideoColorEOTF20IOAVVideoColorimetrybPK12OSDictionaryS7_S7_PK5OSSet"],
    "com.apple.kernel": ["__ZTV9IOService", "___cxa_pure_virtual"],
}
# macOS 27.3's fixture (legacy-display-26C5035r.json), for comparison.
REFERENCE = {"build": "26C5035r", "slots": 483, "base_slots": 272, "instance_size": 0x23a0,
             "display_width": 0x21b0, "masks": 0x478, "rect0": 0x11, "rect1": 0x51}
ORACLE = "com.apple.driver.AppleParavirtGPUIOGPUFamily"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xnuprelink", type=Path, required=True)
    ap.add_argument("--kernelcache", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    sys.path.insert(0, str(args.xnuprelink))
    from kc_image import Image

    data = args.kernelcache.read_bytes()
    cache = Image(data)
    names, images = {}, {}
    for entry, (_, offset) in cache.entries.items():
        image = Image(data, offset)
        images[entry] = image
        names[entry] = {n: a for a, ns in image.symbols().items() for n in ns}
    fixups = cache.fixups()
    symbol_sites = {a for table in names.values() for a in table.values()}
    report = {"kernelcache": args.kernelcache.name, "entries": len(cache.entries),
              "family_present": FAMILY in cache.entries, "oracle_in_this_collection": ORACLE in cache.entries,
              "symbols": {}, "reference": REFERENCE}
    for owner, wanted in SYMBOLS.items():
        table = names.get(owner, {})
        report["symbols"][owner] = {"entry_present": owner in cache.entries, "symbols_in_entry": len(table),
                                    "found": {w: w in table for w in wanted}}

    def code(entry, symbol, length):
        address = names[entry][symbol]
        return images[entry].read(address, length)

    def vtable_slots(entry, ztv):
        if ztv not in names.get(entry, {}):
            return None
        start, count = names[entry][ztv] + 16, 0
        while True:
            site = start + 8 * count
            pointer = fixups.get(site)
            if not pointer or not pointer[1] or (count and site in symbol_sites):
                return count
            count += 1

    found = report["symbols"]
    measured = {"slots": vtable_slots(FAMILY, f"__ZTV{N}"), "base_slots": vtable_slots("com.apple.kernel", "__ZTV9IOService"),
                "parent_slots": vtable_slots(FAMILY, "__ZTV19IOMobileFramebuffer")}
    if found[FAMILY]["found"][f"__ZN{N}9MetaClassC2Ev"]:
        blob = code(FAMILY, f"__ZN{N}9MetaClassC2Ev", 128)
        for i in range(0, len(blob), 4):
            word = struct.unpack_from("<I", blob, i)[0]
            if word & 0xffe0001f == 0x52800003:
                measured["instance_size"] = (word >> 5) & 0xffff
                break
    checks = {}
    if found[FAMILY]["found"][f"__ZNK{N}13display_widthEv"]:
        word = struct.unpack_from("<I", code(FAMILY, f"__ZNK{N}13display_widthEv", 12), 4)[0]
        checks["display_width_at_27.3_offset"] = word == 0xb9400000 | (REFERENCE["display_width"] // 4) << 10
    for key, symbol in (("rect0", f"__ZN{N}23getCurrentSrcRect_gatedEj"), ("rect1", f"__ZN{N}23getCurrentDstRect_gatedEj")):
        if found[FAMILY]["found"][symbol]:
            words = struct.unpack("<16I", code(FAMILY, symbol, 64))
            checks[f"{key}_layer_mask_at_27.3_offset"] = (0xb9400000 | (REFERENCE["masks"] // 4) << 10 | 9 << 5 | 10) in words
            checks[f"{key}_rect_at_27.3_offset"] = (0x91000000 | REFERENCE[key] << 10 | 9 << 5 | 9) in words
    report["measured"] = measured
    report["checks_against_27.3_offsets"] = checks
    missing = [s for o in found.values() for s, ok in o["found"].items() if not ok]
    report["missing_symbols"] = missing
    report["summary"] = {
        "all_fixture_symbols_present": not missing,
        "slots_equal_27.3": measured.get("slots") == REFERENCE["slots"],
        "base_slots_equal_27.3": measured.get("base_slots") == REFERENCE["base_slots"],
        "instance_size_equal_27.3": measured.get("instance_size") == REFERENCE["instance_size"],
        "offsets_equal_27.3": bool(checks) and all(checks.values()),
        "needs_oracle": "the 26.5 virtual-machine collection (AppleParavirtDisplay) for the pure slots' diversities",
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
