# Kesiapan uji boot pertama (pipa, macOS Tahoe 26.5)

Diperbarui: 2026-11-12 (sesi 11: riset boot architecture, memory map, root filesystem; rebuild empat konfigurasi). Baseline sesi: `b6ada11`. Tidak ada yang di-boot, di-flash, atau dijalankan di tablet. Laporan ini memisahkan tiga hal: apa yang terbukti oleh build dan host test, apa yang sudah terintegrasi tetapi belum pernah berjalan di perangkat, dan apa yang masih menghalangi boot.

**Kesimpulan: macOS belum siap di-boot.** Kernel untuk uji pertama (`pipa_macos26_ufs_gpu_defconfig`) sudah ter-build, ter-link, ter-prelink dan reproducible, tetapi `pacstrip`/gerbang ISA, payload dan boot image belum dibuat (ditunda atas instruksi pemilik), tidak ada root filesystem, dan jalur pemulihan Android belum diverifikasi di perangkat. Bagian 3 merincinya.

## Kernel uji pertama

`pipa_macos26_ufs_gpu_defconfig` = generik + storage UFS probe-only (`XNU_PIPA_SOURCE_STORAGE`, `zzzzc`) + Adreno650 dan jalur start board (`XNU_PIPA_BOARD_START`, `zzzzd`). Pemilih workflow: `[kernel-ufs-gpu]`.

| | Hasil ([run 43170501593](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43170501593), commit `d8362c3`) |
| --- | --- |
| Kernel native | 25.479.080 byte, SHA-256 `92d5a0d62f4cbb224d2b3fc7a14c39c221ef3f2adaef09a4a153ded158c7c887`, UUID `e39686803a0d3a78a1877eca9976b1a5`, **0 import** chained fixup |
| Arsip di link map | `libShengSourceStorage.a` 12/12, `libAdreno650.a` 29/29, `libPipaGpu.a` 6/6; link tanpa duplicate symbol |
| Simbol | 385 dari storage dan 419 dari kedua arsip GPU, **0** tak terdefinisi |
| Jalur init | `bsd_init.o` memanggil `pipa_board_start` (dicek dari objek XNU sendiri) |
| Kernel collection | `MH_FILESET` arm64e 135.217.152 byte, SHA-256 `fbc82f2247ea5c2026759db4e67f908b7567755d5fbb6f7a68238e2c74db7671`, `missing`/`stubbed` {}, `mapping_complete` true, 87 kext |
| Batas prelink | `__TEXT` `0x190000` di celah `__PRELINK_TEXT` (sisa 10.208 byte); `__DATA_CONST` sisa 902.184; `__TEXT_EXEC` sisa 5.242.880 |
| Build kedua dari nol (+ prelink kedua) | kernel native, UUID, link map (9.528.859 byte), 26.078 simbol eksternal dan kernel collection **identik** |
| Server render Adreno650 | `-DNATIVE_ADRENO_RENDER_SERVER="WindowServer"` (dari command line compile) |
| Teks assert | ekspresi ≥ 40 byte memakai catatan bersama (`-DMACH_ASSERT_EXPR_MAX=40`, hanya kernel ini) agar `__TEXT` muat; pemeriksaan, trap dan file:line tetap |
| Firmware GPU | GMU, SQE, zap: 0 byte (runner tidak punya image; tidak di Git) |

Tanpa argumen boot board apa pun (board.toml tidak memberikannya), kernel ini berperilaku seperti kernel generik: `native_source_storage_start` dan `pipa_board_start` dipanggil dari `bsd_init` tetapi kembali seketika.

| Argumen boot | Yang berjalan | Menulis register? |
| --- | --- | --- |
| `native-source-storage=1 native-ufs-probe=2\|6\|7\|8` | inspeksi register UFS (`PipaStorageGuard.h`); mode lain ditolak | tidak (probe-only; publikasi blok/root tidak di-compile) |
| `pipa-gop=1` | presenter GopFramebuffer pada frame buffer firmware (`PipaGop.cpp`) | tidak (memetakan buffer yang sudah dipakai konsol) |
| `pipa-gop=1 sheng-fb-gpu=1` | presenter dalam mode GPU: hand-off frame ke klien GPU | tidak |
| `pipa-gpu=1` | baca GCC, GPUCC, SMMU, RBBM (`GpuProbe.cpp` versi macOS) | tidak |
| `pipa-gpu=2..11 pipa-gpu-writes=1` | bring-up bertahap Adreno 650 seperti yang berjalan di iPadOS 2026-10-24: clock, GDSC, GMU (butuh firmware), GX, CP, zap, interrupt, publikasi | **ya** |
| `pipa-gpu=2..11` tanpa `pipa-gpu-writes=1` | diturunkan ke mode 1, dicatat di log | tidak |
| `pipa-gpu=12` | diturunkan ke 11: akselerator Metal iPadOS tidak ada di macOS | — |

## 1. Terbukti oleh build dan host test

| Hal | Bukti |
| --- | --- |
| Kernel uji pertama compile + link + prelink, reproducible | run 43170501593 (tabel di atas); run 43172672651 (commit `ccf2e57`, input kernel sama) menghasilkan kernel native `92d5a0d6…` dan kernel collection `fbc82f22…` yang sama, dan build kedua di dalamnya juga identik |
| Storage tetap probe-only | `PipaStorageGuard.h` hanya 2, 6, 7, 8 (host test 64 nilai); resep tanpa root (`0003`) + probe-only (`0004`); `[storage] root = "none"`; `tests/hw/test_gpu_macos_gate.py` |
| GPU di belakang dua argumen | `tests/hw/test_gpu_macos_gate.py`: mode dibatasi 11, mode ≥ 2 butuh `pipa-gpu-writes=1`, akselerator Metal iPadOS tidak di-compile di macOS, filter tulis `gpb` (mode 1 tidak menulis) |
| Presenter tidak menyentuh register | test statis: tanpa `ml_io_map`/MMIO; peta terhadap `PE_current_console` |
| Kode kernel macOS tanpa antarmuka iPadOS | `scripts/pipa_os_abi.py --check` (cabang `#if` versi macOS dihitung) |
| Ekspor log | `BootLogExportTests.c` (kontrak in-order, memori, tanpa storage) |
| Server render per OS | `patches/adreno650/0004`; test patch; flag compile di runner |
| Display ABI 26.5 diukur | `legacy_display_abi_probe.py` (run 43168676072, 43170501593): semua simbol fixture ada; 473 slot, instance 6.904, offset berpindah |
| Host test | 149 unit test Python (1 dilewati), 14 host test C paket board |

## 2. Terintegrasi, belum diuji di perangkat

| Bagian | Keadaan |
| --- | --- |
| Storage UFS | dipanggil dari `bsd_init`; hanya inspeksi register 2, 6, 7, 8; tidak ada root dari `userdata`, tidak ada tulis UFS |
| Jalur start board | `zzzzd` → `pipa_board_start` → presenter lalu GPU; urutan diuji statis |
| Presenter GOP | nub frame buffer di bawah platform expert, presenter memeriksa pemetaan terhadap `PE_current_console`; belum pernah dibuat di kernel mana pun |
| Hand-off GPU | `native_gop_handoff_call`/`_memory` mencapai presenter itu; butuh klien GPU (plugin Metal macOS) yang belum ada |
| Adreno650 | dijalankan `GpuProbe.cpp` mode 7–11 (GMU, GX, CP, publikasi `AGXDeviceUserClient`); mode ≥ 7 berhenti di "no firmware" pada kernel yang dibangun tanpa image GMU/SQE/zap (CI selalu tanpa) |
| Server render | Adreno650 versi macOS memberi slot 0, mailbox dan ekspor ke `WindowServer` (`patches/adreno650/0004`); `backboardd` tidak mendapat apa pun di macOS |
| Ekspor log | `boot_log_export_put` menyimpan blob di memori (16 MiB), tanpa UFS |
| Backlight | `PipaBacklight.c` ter-compile terhadap xnu-12377, tidak di-link (baca-saja) |

## Root filesystem macOS Tahoe 26.5 dan storage SM8250

Riset dari `third_party/UniXNU/docs/concepts/userdata.md`, `porting/dual-system-partition.md`, profil 26.5, dan `docs/evidence/tahoe-26.5`. Belum dikerjakan: `[storage] root = "none"`, storage probe-only. Yang dibutuhkan agar kernel melanjutkan boot setelah inisialisasi:

| Komponen | Keadaan | Bukti/sumber |
| --- | --- | --- |
| Driver host UFS SM8250 | `PipaUfs 5c64c01` (ShengUfs) ter-compile dan ter-link (probe-only); jalur baca blok penuh tidak di-compile (`NATIVE_UFS_PROBE_ONLY`) | RP, run UFS |
| Image root (OS + SystemOS) | OS `402ec952…` (13,07 GB, UDIF+LZFSE), SystemOS cryptex `c775864e…` (7,10 GB, raw), AppOS `3eb6ec4a…`; UUID OS `47719F50-…` | `docs/evidence/tahoe-26.5/images-26.5.json` |
| Tempat image | jendela di `userdata` lewat manifest `SHNGROOT` (header 1 MiB, window 1 MiB aligned, OS di 0x100000) | `userdata.md` |
| Pencocokan root | `/chosen/root-matching` = UUID volume OS; `root_match_volume_uuid` profil = `47719F50-…` | profil 26.5 `[payload.adt]` |
| Kebijakan owner | `trusted-key.bin` + `manifest.bin` (OS, SystemOS) yang ditandatangani, cocok dengan `os_image_sha256`/`systemos_image_sha256` profil | `SourceRootPolicies.cpp`, profil `[root]` |
| Volume Data (tulis) | seed ramdisk di payload, disajikan dari jendela di akhir `userdata` (FUA); `data-persist=2` untuk tulis | `userdata.md` |

**Penghalang root (keputusan pemilik):** menulis image root ke `userdata` **menghapus data Android**. Alternatif UniXNU `dual-system-partition.md` membuat partisi `unixnu` dari ujung `userdata` (F2FS di-shrink lewat TWRP), yang **mengubah tabel partisi** — keduanya di luar batasan proyek saat ini ("Jangan mengubah partisi, UFS, userdata"). Tanpa salah satunya, tidak ada root, dan akhir boot yang diharapkan tetap panic `Failed to mount root device` di konsol frame buffer. Repo tidak menyediakan langkah untuk keduanya; keduanya butuh izin dan prosedur pemulihan pemilik.

## 3. Masih menghalangi boot

1. **`pacstrip` dan gerbang ISA** untuk kext Apple di kernel collection (Cortex-A77/A55 tidak punya PAC/ARMv8.3): ditunda atas instruksi pemilik. Tanpa itu kext Apple tidak bisa berjalan di SM8250.
2. **Payload dan boot image**: volume `PIPAESP`, DarwinBoot, firmware uefi-pipa dengan UniXNU: tidak dibangun (ditunda). `boot.img` tidak ada.
3. **Root filesystem**: `[storage] root = "none"`, storage probe-only. Akhir boot yang diharapkan tetap panic `Failed to mount root device`. Root di `userdata` menghapus Android; butuh keputusan pemilik.
4. **Display di bawah macOS**: hanya konsol frame buffer firmware. `NativeLegacyDisplay` butuh fixture kelas 26.5 (26.5: 473 slot vs 483, instance 6.904 vs 9.120 byte, `display_width` dan mask layer pindah; oracle VM 26.5 belum diambil; lihat `docs/display-touch.md`); dual DSI/DSC/panel tidak punya driver (MDSS tanpa clock/GDSC menyebabkan SError).
5. **Input**: touch (GENI SPI + NT36532) dan HID belum dibangun untuk macOS (GENI SPI, protokol NT36532, `TouchProbe.cpp`, `TouchState.cpp` ter-compile terhadap xnu-12377; kurang firmware NT36532 dan jalur start macOS); HID butuh fixture `IOHIDDevice` 26.5.
6. **GPU**: firmware GMU/SQE/zap harus disediakan dari partisi vendor tablet saat build (tidak di Git); plugin Metal macOS tidak ada.
7. **Peta memori**: jendela 6 GiB dan tabel rentang terlarang adalah model; peta firmware uefi-pipa yang nyata belum diketahui.
8. **Pemulihan Android belum diverifikasi** (lihat di bawah).

### Syarat pemulihan Android (belum diverifikasi; harus dicek pemilik sebelum uji)

| Syarat | Keadaan |
| --- | --- |
| Bootloader ter-unlock, `fastboot boot` (RAM saja) diterima ABL | tidak dicek oleh repo ini |
| Image yang diuji hanya dimuat dengan `fastboot boot`, tidak pernah `fastboot flash` | kebijakan repo; tidak ada skrip flash |
| Tidak ada tulis ke UFS/`userdata`/partisi dari kernel | dari kode: storage probe-only, GPU/presenter tidak menyentuh storage; belum diamati di perangkat |
| Kembali ke fastboot setelah panic atau hang (kombinasi tombol reset hardware) | dijelaskan `docs/boot-process.md` untuk UniXNU-pipa; belum dicoba dengan kernel ini |
| Android boot normal setelah itu, data utuh | belum dicek |
| Cadangan partisi kritis (boot, vendor_boot, dtbo, persist) sebelum uji | tanggung jawab pemilik; tidak ada di repo |

Sampai semua baris di atas terverifikasi di perangkat oleh pemilik, laporan ini tidak menyatakan macOS siap boot.
