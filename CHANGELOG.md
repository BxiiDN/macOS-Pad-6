# Changelog

## 0.1.0 (2026-11-11)

Pertama kali. Tidak ada yang berjalan di perangkat.

- Audit UniXNU `3fd6a3cf0e6f`, UniXNU-pipa `cdb3d62771e3`, uefi-pipa `1f6a1520f84c` (`docs/audit.md`).
- Analisis kelayakan: hambatan arm64e/PAC di Cortex-A77/A55 (`docs/feasibility.md`).
- FGE: emulator instruksi ARMv8.3–8.5 dengan tes host dan fuzz silang terhadap LLVM.
- Patch XNU xnu-12377.121.6 yang memasang FGE di `sleh_synchronous()`; compile-check dengan shim header.
- `tools/isa/pacstrip` dan `tools/isa/audit` untuk Mach-O, MH_FILESET, dan dyld shared cache.
- Probe fitur CPU untuk tablet (dibangun, belum dijalankan).
- CI: validasi sumber, shellcheck, tes, cross-build, gerbang ISA, cek patch, CMake/Ninja.
