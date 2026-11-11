# Kompatibilitas

Status mengikuti aturan proyek: **WORKING** hanya dengan bukti pengujian. Tabel A adalah macOS di Xiaomi Pad 6, target repo ini. Tabel B adalah hasil upstream (iPadOS 17) sebagai pembanding, bukan klaim repo ini.

Diperbarui: 2026-11-11.

## A. macOS di Xiaomi Pad 6 (repo ini)

| Area | Status | Bukti / alasan |
| --- | --- | --- |
| Boot macOS di pipa | NOT IMPLEMENTED | board pipa masih format 1; profil macOS belum bisa dipilih (audit.md, temuan 1) |
| Kernel XNU target macOS untuk pipa | NOT IMPLEMENTED | belum di-build |
| Emulasi PAuth/JSCVT/FlagM/SB/LRCPC2/DIT (FGE), logika | WORKING (host) | `tests/fge`: 24 tes, termasuk 40.000 vektor acak FJCVTZS vs model rasional, fuzz decoder vs LLVM |
| FGE di dalam XNU | EXPERIMENTAL | patch apply bersih, glue lolos compile-check dengan shim; belum di-build atau di-boot |
| Penulisan ulang PAC statis (pacstrip) | WORKING (host) | kesetaraan setiap rewrite dicek via decode LLVM; data-in-code tidak disentuh |
| pacstrip pada kernel collection macOS asli | NOT IMPLEMENTED | butuh kernelcache 26C5035r dari IPSW pengguna |
| Sensus ISA (audit) pada dyld shared cache macOS | NOT IMPLEMENTED | alat siap; butuh IPSW pengguna |
| FCMA, SHA3/SHA512, FRINTTS | NOT IMPLEMENTED | menunggu hasil sensus |
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
