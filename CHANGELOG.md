# Changelog

## 0.2.0 (2026-11-11)

Audit Tahoe 26.x. Tahoe belum boot.

- Versi: tag distribution-macOS memetakan 26.0–26.5 ke xnu-12377.{1.9…121.6} dan dyld-{1323.3…1378}; 26.5 = xnu `ac9718fb1af6`.
- Audit biner Apple asli di CI:
  - Tahoe 26.7.2 di runner macos-26 (dyld cache, kernel per-SoC, executable);
  - kernelcache, DeviceTree, dan image OS/cryptex Tahoe 26.5 J274AP dari IPSW resmi.
  - Bukti ada di `docs/evidence/tahoe-26.5/`.
- `docs/tahoe-26-report.md`: persyaratan CPU, kernel, userland, GPU; hambatan PAC; status solusi.
- `profiles/macos-26.5`: profil UniXNU `macos-26.5-25F71` (di-resolve oleh `unixnu status`), seri SoC SM8250, patch null-PAC (`HAS_NULL_PAC`) dan FGE; rantai 118/118 apply.
- Perbaikan audit FGE: akses teremulasi single-copy atomic; glue menerima null-PAC dan menolak thread state bertanda tangan; tes host glue.
- FGE: emulasi SHA3 (EOR3, BCAX, RAX1, XAR) dan SHA512, dicek terhadap oracle QEMU.
- tools/isa:
  - scanner C dengan paritas Python dan aturan FHM;
  - pembaca dyld cache multi-file dengan atribusi per image;
  - chained fixups, simbol fileset, pembaca IPSW (ZIP64, CRC-32, IM4P, LZFSE, ADT).
- Koreksi: run audit pertama menghitung data `__TEXT` sebagai kode; angka di laporan berasal dari run yang sudah diperbaiki.

## 0.1.0 (2026-11-11)

Pertama kali. Tidak ada yang berjalan di perangkat.

- Audit UniXNU `3fd6a3cf0e6f`, UniXNU-pipa `cdb3d62771e3`, uefi-pipa `1f6a1520f84c` (`docs/audit.md`).
- Analisis kelayakan: hambatan arm64e/PAC di Cortex-A77/A55 (`docs/feasibility.md`).
- FGE: emulator instruksi ARMv8.3–8.5 dengan tes host dan fuzz silang terhadap LLVM.
- Patch XNU xnu-12377.121.6 yang memasang FGE di `sleh_synchronous()`; compile-check dengan shim header.
- `tools/isa/pacstrip` dan `tools/isa/audit` untuk Mach-O, MH_FILESET, dan dyld shared cache.
- Probe fitur CPU untuk tablet (dibangun, belum dijalankan).
- CI: validasi sumber, shellcheck, tes, cross-build, gerbang ISA, cek patch, CMake/Ninja.
