# Roadmap

Milestone sesuai urutan dalam brief proyek. Status per 2026-11-11. Target: **Tahoe 26.5 (25F71)**, rilis Tahoe terbaru yang source kernelnya dipublikasikan ([tahoe-26-report.md](tahoe-26-report.md)).

| | Milestone | Status | Langkah berikutnya yang konkret |
| --- | --- | --- | --- |
| A | Audit UniXNU-pipa | selesai | [audit.md](audit.md) |
| B | Validasi XNU di Snapdragon 870 | upstream: XNU iPadOS 17 jalan. Fitur CPU: probe dibangun | Jalankan `cpu_features_probe` di tablet (adb, tanpa root), lampirkan output ke `docs/evidence/` |
| C | Integrasi storage | upstream: UFS root jalan (iPadOS) | Sama untuk macOS setelah E |
| D | Validasi root filesystem | upstream: jalan (iPadOS) | Tiga window macOS (`OS`, `SystemOS`, `App`) |
| E | Kompatibilitas macOS Tahoe | audit 26.x selesai; profil 26.5, rantai patch 121/121 dan board format 2 (`devices/pipa`) siap dan dicek CI | 1) ~~Build kernel native~~: compile + link berhasil 2026-11-11 ([kernel-build.md](kernel-build.md)). 2) Prelink dengan kernelcache 26.5, lalu `pacstrip` pada KC, gerbang `audit --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`. 3) `fastboot boot`; target pertama: panic mount root, lalu launchd. |
| F | Display & touch untuk macOS | belum | `IOMFBUUID`/`displayUUID` seperti sheng, fixture binding kelas 26C5035r |
| G | Input | belum | Keyboard & pointer HID mengikuti pola sheng |
| H | Networking | belum (juga belum ada di iPadOS pipa) | Identifikasi chip Wi-Fi dari DTS stok, lalu driver |
| I | Audio | belum | — |
| J | GPU | upstream: Metal→Vulkan di iPadOS | Bundle macOS `NativeAdrenoMetal.bundle` (target macos27) |
| K | Power | baterai ditulis upstream | Uji di tablet; sleep/wake |
| L | Userland macOS | **masalah terbuka** | Pilih trap-only vs pacstrip dyld cache berdasarkan sensus dan uji trust (feasibility.md §4) |
| M | Integrasi sistem | belum | — |
| N | Uji kompatibilitas penuh | belum | — |

## Hasil audit Tahoe yang membuka pekerjaan baru

- Emulasi FCMA (FCADD, FCMLA) dan FHM (FMLAL/FMLSL) dengan pembulatan IEEE yang benar, atau bukti bahwa libBLAS, libBNNS, dan libsystem_m memakai function variants / pemeriksaan CPU.
- Sensus dengan pemisahan function variants (tabel `functionVariantInfo` di header dyld cache).
- pacstrip untuk dyld shared cache, lalu jalur trust untuk halaman kode yang diubah.
- Sensus isi image OS 26.5 sendiri (bukan 26.7.2 runner).

## Pekerjaan perbaikan yang sudah diketahui

- FGE mengembalikan `false` saat akses memori gagal, sehingga XNU melaporkan SIGILL, bukan data abort yang presisi. Perlu mensintesis `EXC_BAD_ACCESS` dengan alamat yang benar.
- `fge_xnu_counts` belum diekspos ke log ramoops pipa; tambahkan ke `BootRamoops.c` (upstream) sebagai baris `fge:`.
