#!/usr/bin/env python3
"""What a macOS Metal accelerator for pipa would bind to in the 26.5 collection (research, numbers and yes/no only).

    scripts/gpu_metal_abi_probe.py --xnuprelink DIR --kernelcache KC [--json OUT]        (macOS runner, after prelink)

Adreno650's GPU hand-off and user client are driven; Metal is not. On iPadOS the staged accelerator
(NativeAdrenoAccelerator.cpp, GpuProbe.cpp mode 12) binds the class IOAcceleratorES of IOGPUFamily (class size 136) and
registers a plugin named NativeAdrenoMetal. macOS 26.5 is a Mac collection (J274AP, Apple M1), whose Metal stack is AGX,
not IOAcceleratorES, so the iPadOS path cannot bind here. This looks up, in the collection this run prelinked against,
the GPU and accelerator classes a macOS plugin would have to match or subclass, and reports which exist and their vtable
and instance sizes. It writes no fixture and makes no claim that Metal works: like the display probe, a real macOS plugin
needs an AGX-class ABI fixture (gen-board-abi.py style) and review.

Only class names, counts and sizes are printed; no collection code or address.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import struct
import sys
from pathlib import Path

# Classes a macOS GPU/Metal stack is built from, by the kext that defines each. IOAcceleratorES is the iPadOS one the
# fork's staged accelerator binds; the AGX* are the Mac Metal driver's; IOGPUFamily/IOAccelerator are the families.
CLASSES = {
    "com.apple.iokit.IOGPUFamily": ["IOGPUDevice", "IOGPU", "IOAccelerator", "IOAcceleratorES"],
    "com.apple.iokit.IOSurface": ["IOSurfaceRoot", "IOSurface"],
}
# AGX kexts vary by collection; probe any that are present.
AGX_HINTS = ["com.apple.AGXG13X", "com.apple.AGXG14X", "com.apple.AGXFirmwareKextRTBuddy64", "com.apple.iokit.IOGPUFamily"]


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
    entries = {}
    for name, (_, offset) in cache.entries.items():
        img = Image(data, offset)
        entries[name] = (img, {n: a for a, ns in img.symbols().items() for n in ns})
    fixups = cache.fixups()
    symbol_sites = {a for _, table in entries.values() for a in table.values()}

    def vtable_count(entry, cls):
        img, table = entries.get(entry, (None, {}))
        ztv = f"__ZTV{len(cls)}{cls}"
        if ztv not in table:
            return None
        start, count = table[ztv] + 16, 0
        while True:
            site = start + 8 * count
            p = fixups.get(site)
            if not p or not p[1] or (count and site in symbol_sites):
                return count
            count += 1

    def instance_size(entry, cls):
        img, table = entries.get(entry, (None, {}))
        sym = f"__ZN{len(cls)}{cls}9MetaClassC2Ev"
        if sym not in table:
            return None
        blob = img.read(table[sym], 128)
        for i in range(0, len(blob), 4):
            w = struct.unpack_from("<I", blob, i)[0]
            if w & 0xffe0001f == 0x52800003:
                return (w >> 5) & 0xffff
        return None

    gpu_kexts = sorted(k for k in cache.entries if "GPU" in k or "AGX" in k or "Accelerator" in k or "Metal" in k)
    report = {"kernelcache": args.kernelcache.name, "entries": len(cache.entries),
              "gpu_related_kexts": gpu_kexts, "classes": {}}
    for entry, classes in CLASSES.items():
        for cls in classes:
            report["classes"][cls] = {"entry": entry, "entry_present": entry in cache.entries,
                                      "vtable_slots": vtable_count(entry, cls), "instance_size": instance_size(entry, cls)}
    report["ipados_accelerator_class_present"] = report["classes"]["IOAcceleratorES"]["vtable_slots"] is not None
    report["summary"] = {
        "collection_is_mac_agx": any(k.startswith("com.apple.AGX") for k in cache.entries),
        "ipados_IOAcceleratorES_bindable": report["ipados_accelerator_class_present"],
        "needs": "a macOS AGX-class ABI fixture and a macOS Metal plugin; the iPadOS staged accelerator does not apply",
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")


if __name__ == "__main__":
    main()
