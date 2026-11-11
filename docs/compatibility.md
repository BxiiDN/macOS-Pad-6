# Kompatibilitas

Status mengikuti aturan proyek: **WORKING** hanya dengan bukti pengujian. Tabel A adalah macOS di Xiaomi Pad 6, target repo ini. Tabel B adalah hasil upstream (iPadOS 17) sebagai pembanding, bukan klaim repo ini.

Diperbarui: 2026-11-11 (setelah audit Tahoe 26.x, lihat [tahoe-26-report.md](tahoe-26-report.md)). Target: **Tahoe 26.5 (25F71)**.

## A. macOS di Xiaomi Pad 6 (repo ini)

| Area | Status | Bukti / alasan |
| --- | --- | --- |
| Board pipa format 2 (`devices/pipa`) | EXPERIMENTAL | di-resolve `unixnu status` untuk 26.5 dan iPadOS 17, ADT dihasilkan dari DTS (CI); belum di-build ([board-migration.md](board-migration.md)) |
| Boot macOS Tahoe di pipa | NOT IMPLEMENTED | belum ada kernel yang di-build ([kernel-build.md](kernel-build.md)) |
| Profil UniXNU `macos-26.5-25F71` | EXPERIMENTAL | nilai dari IPSW resmi; di-resolve oleh `unixnu status` (135 patch, nol patch Darwin 26); belum di-build |
| Rantai patch XNU Tahoe 26.5 untuk pipa | WORKING (apply) | 120/120 apply di xnu-12377.121.6 dalam urutan board (CI); belum di-build |
| Mode null-PAC (`HAS_NULL_PAC`) | EXPERIMENTAL | patch apply; belum di-build |
| pacstrip pada kernelcache Tahoe 26.5 asli | WORKING (host) | 778.340 instruksi PAC ditulis ulang, sisa 42 PACGA (bukti tahoe-26.5) |
| Emulasi SHA3/SHA512 (FGE) | WORKING (host) | model Python + oracle QEMU |
| Emulasi FCMA, FHM, FRINTTS | NOT IMPLEMENTED | FCMA/FHM ada di libBLAS, libSparseBLAS, libBNNS, libsystem_m (1×) |
| Kernel XNU target macOS untuk pipa | NOT IMPLEMENTED | belum di-build |
| Emulasi PAuth/JSCVT/FlagM/SB/LRCPC2/DIT (FGE), logika | WORKING (host) | `tests/fge`, termasuk 40.000 vektor acak FJCVTZS vs model rasional, fuzz decoder vs LLVM |
| FGE di dalam XNU | EXPERIMENTAL | patch apply bersih, glue lolos compile-check dengan shim; belum di-build atau di-boot |
| Penulisan ulang PAC statis (pacstrip) | WORKING (host) | kesetaraan setiap rewrite dicek via decode LLVM; data-in-code tidak disentuh |
| Sensus ISA dyld shared cache Tahoe | WORKING (data) | 26.7.2 di runner macos-26; 26,9 juta PAC non-hint |
| Userland macOS (launchd → WindowServer) | NOT IMPLEMENTED | masalah terbuka (feasibility.md §4) |
| Finder, Dock, Menu Bar, System Settings, Terminal, Safari | NOT IMPLEMENTED | bergantung userland |
| Display 2880×1800, rotasi, kecerahan | NOT IMPLEMENTED (macOS) | iPadOS memakai framebuffer firmware; macOS butuh `IOMFBUUID` (UniXNU macOS profile) |
| Touchscreen, multitouch, gesture | NOT IMPLEMENTED (macOS) | driver iPadOS ada; pemasangan WindowServer belum |
| Keyboard/mouse USB & Bluetooth | NOT IMPLEMENTED | USB host dan Bluetooth belum ada di pipa |
| Wi-Fi, Bluetooth | NOT IMPLEMENTED | belum ada di pipa sama sekali |
| Audio | NOT IMPLEMENTED | belum ada di pipa sama sekali |
| GPU / Metal | NOT IMPLEMENTED (macOS) | jalur Metal→Vulkan ada untuk iPadOS; bundle macOS belum dibuat untuk pipa |
| USB-C, baterai, charging, thermal, sleep/wake | NOT IMPLEMENTED | baterai ditulis upstream, belum dijalankan |
| Probe fitur CPU di tablet | EXPERIMENTAL | biner dibangun; belum dijalankan di perangkat |

## B. Pembanding: iPadOS 17.7.11 di pipa (upstream xVanTuring/UniXNU-pipa)

Dilaporkan upstream sebagai berjalan di tablet pada 2026-10-23/24: firmware dan menu, XNU 8 core, root UFS, layar framebuffer, touch, tombol, GPU Adreno 650 dengan Metal lewat Turnip (40–54 fps). Belum ada: audio, jaringan. Rincian ada di [audit.md](audit.md).
