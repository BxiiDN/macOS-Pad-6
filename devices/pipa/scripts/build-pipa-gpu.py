#!/usr/bin/env python3
"""pipa's macOS support for Adreno650: build/pipa-gpu/libPipaGpu.a, which pipa_macos26_gpu_defconfig and
pipa_macos26_ufs_gpu_defconfig force-load next to build/adreno650/libAdreno650.a. Two parts.

The board's start path on macOS (zzzzd-pipa-board-start.patch calls pipa_board_start from bsd_init):
  pipa_board_start                                     package/PipaBoardStart.c
  pipa_gop_start                                       package/PipaGop.cpp: the presenter below on the firmware frame
                                                       buffer (pipa-gop=1)
  native_gpu_probe                                     package/GpuProbe.cpp with -DPIPA_GPU_MACOS=1: the staged Adreno
                                                       650 bring-up that drives the Adreno650 objects (pipa-gpu=<1..11>;
                                                       writing modes need pipa-gpu-writes=1)
  native_gpu_{gmu,sqe,zap}_firmware[_size]             GpuFirmware.c, generated here: the images the build machine has
                                                       in .cache/firmware (never in Git), in __DATA_CONST, else empty

The kernel symbols the A650 fork's NativeAdrenoPublish.cpp calls and that no other part of the macOS 26.5 kernel
provides:

  native_gop_handoff_call, native_gop_handoff_memory   drivers/GopFramebuffer/NativeGOPPresenter.cpp (the feed pin of
                                                       feeds.toml with patches/gopframebuffer), the firmware frame
                                                       buffer presenter, compiled with -DNATIVE_GOP_OFFER_WITH_ONLY=1
  boot_log_export_put                                  package/BootLogExport.c, the export kept in kernel memory

The presenter is compiled as it is; only the offer entry point that needs NativeLegacyDisplay (an iPadOS / macOS 27.3
class binding, not buildable for 26.5) is left out by the patch's switch. PipaGop.cpp creates the presenter when asked;
until then the hand-off answers kIOReturnNotReady and the scanout descriptor is null, which NativeAdrenoPublish.cpp
handles. No personality: nothing starts by matching.

Compiled with this kernel's compile records, as build-adreno650.py. The checks are the link's own conditions: every
symbol above is defined here, as a strong external definition (a weak one would become a chained-fixup import that
XnuPrelink refuses), and nothing here refers to native_legacy_gpu_complete.

SPDX-License-Identifier: BSD-2-Clause-Patent"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
c_recipe = json.loads((RECORDS / 'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))
cxx_recipe = json.loads((RECORDS / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
out = ROOT / 'build/pipa-gpu'
out.mkdir(parents=True, exist_ok=True)
# The GPU probe sees the driver and its kits as build-adreno650.py compiles them.
GPU_INCLUDES = ['-I', str(ROOT / 'drivers/Adreno650'), '-I', str(ROOT / 'kits/AdrenoPM4'), '-I', str(ROOT / 'kits/ArmSmmu4K'),
                '-I', str(ROOT / 'kits/AdrenoFirmware'), '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion']
SOURCES = [
    (ROOT / 'drivers/GopFramebuffer/NativeGOPPresenter.cpp', ['-DNATIVE_GOP_OFFER_WITH_ONLY=1']),
    (ROOT / 'kits/pipa/BootLogExport.c', []),
    (ROOT / 'kits/pipa/PipaGop.cpp', []),
    (ROOT / 'kits/pipa/PipaBoardStart.c', []),
    (ROOT / 'kits/pipa/GpuProbe.cpp', ['-DPIPA_GPU_MACOS=1', *GPU_INCLUDES]),
    (out / 'GpuFirmware.c', []),
]
PROVIDES = ('_native_gop_handoff_call', '_native_gop_handoff_memory', '_boot_log_export_put', '_pipa_board_start',
            '_pipa_gop_start', '_native_gpu_probe', '_native_gpu_gmu_firmware', '_native_gpu_gmu_firmware_size',
            '_native_gpu_sqe_firmware', '_native_gpu_sqe_firmware_size', '_native_gpu_zap_firmware',
            '_native_gpu_zap_firmware_size')
# NativeLegacyDisplay's completion, and the iPadOS Metal accelerator of GpuProbe's mode 12.
FORBIDDEN = ('_native_legacy_gpu_complete', '___GLOBAL__sub_I_NativeAdrenoAccelerator.cpp',
             '_native_adreno_accelerator_allocate', '_native_adreno_accelerator_instance_size')
# The GPU images, as build-gop-legacy-display.py finds them for the iPadOS kernel (environment variable, else the board's
# .cache/firmware, which UniXNU links into the tree). Never in Git; absent on the CI runner.
FIRMWARE = {
    'gmu': ('PIPA_GMU_FIRMWARE', '.cache/firmware/gpu/a650_gmu.bin'),
    'sqe': ('PIPA_SQE_FIRMWARE', '.cache/firmware/linux-firmware/a650_sqe.fw'),
    'zap': ('PIPA_ZAP_FIRMWARE', '.cache/firmware/gpu/a650_zap.elf'),
}


def firmware_source():
    """GpuFirmware.c: each image the build machine has, in __DATA_CONST (read only after the kernel's lockdown, and not
    in the native __TEXT that has to fit the collection's __PRELINK_TEXT); an absent one has size 0, which GpuProbe.cpp
    reports ("no firmware") and stops at, before it touches the GMU."""
    lines, record = ['// Generated by devices/pipa/scripts/build-pipa-gpu.py.', '#include <stdint.h>'], {}
    for name, (variable, default) in FIRMWARE.items():
        path = Path(os.environ.get(variable) or ROOT / default)
        blob = path.read_bytes() if path.is_file() else b''
        record[name] = {'path': str(path), 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest() if blob else None}
        body = ','.join(map(str, blob)) if blob else '0'
        lines.append(f'// {path.name}: ' + (f'{len(blob)} bytes, sha256 {record[name]["sha256"]}' if blob else 'absent'))
        lines.append(f'const uint8_t native_gpu_{name}_firmware[] __attribute__((aligned(16), section("__DATA_CONST,__pipa_fw"))) = {{{body}}};')
        lines.append(f'const uint32_t native_gpu_{name}_firmware_size = {len(blob)};')
    (out / 'GpuFirmware.c').write_text('\n'.join(lines) + '\n')
    return record


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
    firmware = firmware_source()
    objects, failed = [], []
    for source, extra in SOURCES:
        if not source.is_file():
            sys.exit(f'{source}: missing (GopFramebuffer must be a selected component; the board kit must be pipa)')
        obj = out / (source.stem + '.o')
        cwd, command = command_for(source, obj, extra)
        (out / (source.stem + '.command.json')).write_text(json.dumps(command) + '\n')
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode:
            failed.append(f'{source}:\n' + result.stderr[-4000:])   # every source is tried, so one round shows all errors
            continue
        objects.append(obj)
    if failed:
        sys.exit('\n'.join(failed))
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
    report = {'archive': str(archive.relative_to(ROOT)), 'bytes': archive.stat().st_size, 'firmware': firmware,
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
          f"{len(report['undefined'])} symbols left to the kernel; firmware "
          + ', '.join(f"{k} {v['bytes']} bytes" for k, v in firmware.items()))


if __name__ == '__main__':
    main()
