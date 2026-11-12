#!/usr/bin/env python3
"""pipa's macOS support for Adreno650: build/pipa-gpu/libPipaGpu.a, which pipa_macos26_gpu_defconfig force-loads next to
build/adreno650/libAdreno650.a. It defines the kernel symbols the A650 fork's NativeAdrenoPublish.cpp calls and that no
other part of the macOS 26.5 kernel provides:

  native_gop_handoff_call, native_gop_handoff_memory   drivers/GopFramebuffer/NativeGOPPresenter.cpp (the feed pin of
                                                       feeds.toml with patches/gopframebuffer), the firmware frame
                                                       buffer presenter, compiled with -DNATIVE_GOP_OFFER_WITH_ONLY=1
  boot_log_export_put                                  package/BootLogExport.c, the export kept in kernel memory

The presenter is compiled as it is; only the offer entry point that needs NativeLegacyDisplay (an iPadOS / macOS 27.3
class binding, not buildable for 26.5) is left out by the patch's switch. Nothing creates a presenter on pipa's macOS
kernel yet: native_gop_presenter_create has no caller, so the hand-off answers kIOReturnNotReady and the scanout
descriptor is null, which is what NativeAdrenoPublish.cpp handles. No firmware, no personality, nothing that starts.

Compiled with this kernel's compile records, as build-adreno650.py. The checks are the link's own conditions: every
symbol above is defined here, as a strong external definition (a weak one would become a chained-fixup import that
XnuPrelink refuses), and nothing here refers to native_legacy_gpu_complete.

SPDX-License-Identifier: BSD-2-Clause-Patent"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
c_recipe = json.loads((RECORDS / 'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))
cxx_recipe = json.loads((RECORDS / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
out = ROOT / 'build/pipa-gpu'
out.mkdir(parents=True, exist_ok=True)
SOURCES = [
    (ROOT / 'drivers/GopFramebuffer/NativeGOPPresenter.cpp', ['-DNATIVE_GOP_OFFER_WITH_ONLY=1']),
    (ROOT / 'kits/pipa/BootLogExport.c', []),
]
PROVIDES = ('_native_gop_handoff_call', '_native_gop_handoff_memory', '_boot_log_export_put')
FORBIDDEN = ('_native_legacy_gpu_complete',)


def command_for(source, obj, extra):
    recipe = c_recipe if source.suffix == '.c' else cxx_recipe
    command, i = [], 0
    args = recipe['arguments']
    while i < len(args):
        value = args[i]
        if value == recipe['file']:
            command.append(str(source))
        elif value == '-o':
            command += ['-o', str(obj)]
            i += 1
        elif value in ('-MF', '-MJ'):
            i += 1
        elif value == '-Xclang' and args[i + 1].startswith('-W'):
            i += 1
        elif not value.startswith('-W') and value not in ('-MD', '-MP'):
            command.append(value)
        i += 1
    command += ['-I', str(source.parent), '-I', str(ROOT / '.cache/xnu-work/osfmk'), *extra,
                '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-incompatible-sysroot',
                '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-unnecessary-virtual-specifier']
    return recipe['directory'], command


def main():
    objects = []
    for source, extra in SOURCES:
        if not source.is_file():
            sys.exit(f'{source}: missing (GopFramebuffer must be a selected component; the board kit must be pipa)')
        obj = out / (source.stem + '.o')
        cwd, command = command_for(source, obj, extra)
        (out / (source.stem + '.command.json')).write_text(json.dumps(command) + '\n')
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode:
            sys.exit(f'{source}:\n' + result.stderr[-4000:])
        objects.append(obj)
    archive = out / 'libPipaGpu.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, *objects], check=True)
    listing = subprocess.run(['xcrun', 'nm', '-m', archive], capture_output=True, text=True, check=True).stdout
    defined, weak, undefined = set(), set(), set()
    for line in listing.splitlines():
        name = line.split()[-1] if line.split() else ''
        if '(undefined)' in line:
            undefined.add(name)
        elif 'external' in line and 'non-external' not in line:
            defined.add(name)
            if 'weak' in line:
                weak.add(name)
    report = {'archive': str(archive.relative_to(ROOT)), 'bytes': archive.stat().st_size,
              'objects': [o.name for o in objects], 'provides': {s: s in defined for s in PROVIDES},
              'weak_definitions': sorted(weak), 'forbidden_references': sorted(set(FORBIDDEN) & undefined),
              'undefined': sorted(undefined - defined)}
    (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    problems = [f'{s} not defined' for s, ok in report['provides'].items() if not ok]
    problems += [f'{s} is a weak definition' for s in PROVIDES if s in weak]
    problems += [f'{s} is referenced' for s in report['forbidden_references']]
    if problems:
        sys.exit('libPipaGpu.a: ' + '; '.join(problems))
    print(f"PASS: libPipaGpu.a ({report['bytes']} bytes, {len(objects)} objects) defines {', '.join(PROVIDES)}; "
          f"{len(report['undefined'])} symbols left to the kernel")


if __name__ == '__main__':
    main()
