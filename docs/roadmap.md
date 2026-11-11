# Roadmap

Milestone sesuai urutan dalam brief proyek. Status per 2026-11-11.

| | Milestone | Status | Langkah berikutnya yang konkret |
| --- | --- | --- | --- |
| A | Audit UniXNU-pipa | selesai | [audit.md](audit.md) |
| B | Validasi XNU di Snapdragon 870 | upstream: XNU iPadOS 17 jalan. Fitur CPU: probe dibangun | Jalankan `cpu_features_probe` di tablet (adb, tanpa root), lampirkan output ke `docs/evidence/` |
| C | Integrasi storage | upstream: UFS root jalan (iPadOS) | Sama untuk macOS setelah E |
| D | Validasi root filesystem | upstream: jalan (iPadOS) | Tiga window macOS (`OS`, `SystemOS`, `App`) |
| E | Kompatibilitas macOS | analisis selesai, alat siap | 1) Migrasi board pipa ke format 2 (UniXNU migration guide), pindahkan `[kernel.prelink]` ke override iPadOS, tambah override `macos-27.3-26C5035r`; verifikasi dengan `unixnu status --os macos-27`. 2) Jalankan `tools/isa/audit` pada kernelcache dan dyld shared cache 26C5035r. 3) Build kernel macOS + patch FGE, pacstrip KC, gerbang audit. 4) `fastboot boot`, targetkan launchd. |
| F | Display & touch untuk macOS | belum | `IOMFBUUID`/`displayUUID` seperti sheng, fixture binding kelas 26C5035r |
| G | Input | belum | Keyboard & pointer HID mengikuti pola sheng |
| H | Networking | belum (juga belum ada di iPadOS pipa) | Identifikasi chip Wi-Fi dari DTS stok, lalu driver |
| I | Audio | belum | — |
| J | GPU | upstream: Metal→Vulkan di iPadOS | Bundle macOS `NativeAdrenoMetal.bundle` (target macos27) |
| K | Power | baterai ditulis upstream | Uji di tablet; sleep/wake |
| L | Userland macOS | **masalah terbuka** | Pilih trap-only vs pacstrip dyld cache berdasarkan sensus dan uji trust (feasibility.md §4) |
| M | Integrasi sistem | belum | — |
| N | Uji kompatibilitas penuh | belum | — |

## Pekerjaan perbaikan yang sudah diketahui

- FGE mengembalikan `false` saat akses memori gagal, sehingga XNU melaporkan SIGILL, bukan data abort yang presisi. Perlu mensintesis `EXC_BAD_ACCESS` dengan alamat yang benar.
- `fge_xnu_counts` belum diekspos ke log ramoops pipa; tambahkan ke `BootRamoops.c` (upstream) sebagai baris `fge:`.
- Tahoe 26.x: buat profil OS sendiri bila pengguna menyediakan IPSW Tahoe (feasibility.md §5).
