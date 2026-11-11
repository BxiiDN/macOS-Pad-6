# Audit: UniXNU, UniXNU-pipa, uefi-pipa

Diaudit 2026-11-11 dari clone dangkal (`git clone --depth 1`) di revisi berikut. Semua klaim status di bawah dikutip dari README/record proyek tersebut, **bukan** hasil uji repo ini.

| Repositori | Revisi diaudit | Cabang | Lisensi | Peran |
| --- | --- | --- | --- | --- |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU) | `3fd6a3cf0e6f` (2026-11-11) | `main` = `feat/macos` | BSD-2-Clause-Patent | Build driver `unixnu`, katalog komponen, profil OS (iPadOS 17/26/27, **macOS 27.3**), paket UEFI, DarwinBoot, dokumentasi |
| [xVanTuring/UniXNU-pipa](https://github.com/xVanTuring/UniXNU-pipa) | `cdb3d62771e3` (2026-10-26) | `main` | BSD-2-Clause-Patent (sebagian MIT, lihat SPDX) | Repo perangkat Xiaomi Pad 6 (pipa, SM8250) |
| [xVanTuring/uefi-pipa](https://github.com/xVanTuring/uefi-pipa) | `1f6a1520f84c` (2026-10-22) | `pipa` (juga `main`, `sheng`) | BSD-2-Clause-Patent (Mu-Silicium) | Firmware UEFI pipa, fork uefi-sheng / Mu-Silicium dengan UniXNU + DarwinBoot |

XNU yang dipin profil macOS UniXNU: `apple-oss-distributions/xnu` `ac9718fb1af6` (xnu-12377.121.6, APSL 2.0).

## Status yang dilaporkan UniXNU-pipa

Sumber: README UniXNU-pipa. Semua di **iPadOS 17.7.11 (iPad7,1, arm64 tanpa PAC)**, bukan macOS.

| Area | Dilaporkan | Tanggal |
| --- | --- | --- |
| Firmware → menu UniXNU | jalan (`fastboot boot`, tanpa menulis apa pun) | 2026-10-23 |
| XNU boot, 8 core (A55 + A77), EPSS ke clock puncak | jalan | 2026-10-24 |
| Root dari UFS (`PipaUfs`, SMMU passthrough stream 0xe0/0x4e0) | jalan | 2026-10-24 |
| Layar (framebuffer firmware, skala UI 2, 900×1440 point) | jalan, tanpa vsync (tearing) | 2026-10-24 |
| Sentuh Novatek NT36532 (GENI SPI, ~120 laporan/detik) | jalan | 2026-10-24 |
| Tombol power/volume (PM8150 lewat SPMI) | jalan | 2026-10-24 |
| Baterai (`NativeBattery`, PM8150B gauge + SMB5) | ditulis, **belum dijalankan** di tablet | — |
| GPU Adreno 650: GMU, GX, SQE, zap shader, interrupt | jalan | 2026-10-24 |
| Metal → Vulkan (Turnip) lewat NativeAdreno/AdrenoMetal | jalan, 40–54 fps di home screen; sudut membulat salah di GMEM pass | 2026-10-24 |
| Audio, jaringan | belum ada | — |
| Memori | 5,75 GiB satu rentang; 16 GB penuh butuh banyak rentang fisik di pmap | — |

Peringatan dari README itu sendiri: `fastboot flash userdata` **menghapus data Android**.

## Isi yang dipakai ulang (tidak dibuat ulang di sini)

Submodul UniXNU-pipa (semua cabang `pipa` milik xVanTuring kecuali yang ditandai):

| Path | Repo | Fungsi |
| --- | --- | --- |
| `drivers/PipaUfs` | xVanTuring/PipaUfs | host UFS SM8250 |
| `drivers/GopFramebuffer` | xVanTuring/GopFramebuffer | display lewat framebuffer GOP |
| `drivers/ArmCpu` | xVanTuring/ArmCpu | 8 core, IPI sebagai SPI |
| `drivers/PipaNovatekTouch` | xVanTuring/PipaNovatekTouch | touchscreen |
| `drivers/Adreno650` | xVanTuring/Adreno650 | NativeAdreno untuk A650 |
| `kits/ArmSmmu4K` | xVanTuring/ArmSmmu4K | SMMU |
| `drivers/AdrenoMetal` | xVanTuring/AdrenoMetal | plugin Metal → Vulkan |
| `drivers/ShengHidInput` | UniXNU/ShengHidInput (default) | input HID |

Repo ini mem-pin ketiga repo utama sebagai submodul di `third_party/` pada revisi di atas.

## Profil macOS di UniXNU

`profiles/os/macos-27.3-26C5035r` (UniversalMac 27.3, Mac17,11):

- `arch = "arm64e"`: kernel dikompilasi dengan PAC dan me-link kext arm64e asli dari kernelcache Mac.
- `target = "macosx"`: XNU dengan `XNU_TARGET_OS_OSX` di atas konfigurasi mesin iOS (BCM2837).
- Komentar profil: belum ada sumber XNU Darwin 26 yang dipublikasikan; 27.3 berjalan di xnu-12377 dengan syscall Darwin 26 ditambahkan lewat patch.
- `docs/porting/arm64e.md`: **"arm64e needs native PAC hardware"**; perangkat yang didukung hanya `sheng` (SM8550), status *In development*.

Bukti macOS di perangkat (record UniXNU-sheng, Xiaomi Pad 6S Pro): macOS 27.3 sampai WindowServer, keyboard setup selesai dan pointer bergerak di tablet (2026-11-10). Itu SM8550 dengan PAC.

## Temuan audit

1. **Pipa belum bisa memakai profil macOS secara konfigurasi** (ditangani di repo ini: `devices/pipa` format 2, [board-migration.md](board-migration.md)). `board.toml` UniXNU-pipa adalah format 1 (tanpa `schema_version`). `./unixnu status --json --os macos-27 -D UniXNU-pipa` (dijalankan 2026-11-11) tetap mengembalikan IPSW iPad7,1 17.7.11 dan `patch_order: []`: flag `--os` diabaikan. Profil OS butuh board format 2 ([panduan migrasi](https://unixnu.com/porting/migration)). Belum ada repo SoC SM8250 bersama di `feeds.toml`.
2. **Profil macOS mensyaratkan PAC; Kryo 585 tidak punya.** Lihat [feasibility.md](feasibility.md).
3. `[kernel.prelink]` pipa berada di level board, jadi di format 2 ia akan menimpa daftar prelink profil macOS. UniXNU-sheng memindahkannya ke `os_overrides."ipados-..."`; pipa perlu hal yang sama.
4. Firmware, kernelcache, Turnip, dan firmware GPU/touch diambil dari IPSW Apple atau partisi vendor tablet dan disimpan di luar Git. Itu benar secara lisensi dan harus dipertahankan.
