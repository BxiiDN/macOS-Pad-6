# Kesiapan integrasi kernel pipa (macOS Tahoe 26.5, xnu-12377.121.6)

Diperbarui: 2026-11-12 (sesi 9). Baseline sesi: `4b5b53b`. Semua angka di bawah berasal dari log run yang ditautkan atau dari perintah yang bisa diulang; tidak ada yang dijalankan di tablet.

**Ringkasan.** Tiga konfigurasi kernel pipa ter-compile, ter-link dan ter-prelink dengan kernelcache 26.5 di runner macOS, masing-masing dengan 0 import chained fixup dan 0 simbol tak ter-resolve, dan build kedua dari nol identik bit demi bit: generik, dengan storage UFS (probe-only), dan dengan **Adreno650** ([run 43145180980](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43145180980)). Empat simbol yang dulu kurang untuk Adreno650 kini didefinisikan oleh kode nyata (presenter GopFramebuffer dan ekspor log di memori), bukan stub. Ter-link bukan berarti berfungsi: tidak ada yang memanggil driver GPU di kernel macOS, dan tidak ada bukti perangkat keras untuk GPU, display, touch, maupun storage.

## Konfigurasi

| | `pipa_macos26_defconfig` (generik) | `pipa_macos26_ufs_defconfig` | `pipa_macos26_gpu_defconfig` (baru) |
| --- | --- | --- | --- |
| Pemilih di workflow | `[kernel-build]`, `[kernel-prelink]` | `[kernel-ufs]` | `[kernel-gpu]` |
| Arsip yang di-link (selain jalur generik) | — | `libShengSourceStorage.a` | `libAdreno650.a`, `libPipaGpu.a` |
| Hasil terakhir | GEN_RESULT | UFS_RESULT | [run 43145180980](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43145180980): 31 anggota ter-link, `__TEXT` `0x188000`, sisa 42.976 byte |
| Perangkat lain | — | file hanya di `devices/pipa` | file hanya di `devices/pipa` |

Setiap kernel step membangun **semua** arsip board (storage, Adreno650, libPipaGpu); defconfig yang menentukan mana yang di-link, dan `--linked yes|no` memeriksa link map. Rantai patch tetap 122/122.

## 1. Empat simbol Adreno650 (G3)

`NativeAdrenoPublish.cpp` fork memanggil empat simbol yang tidak ada di kernel macOS 26.5 (percobaan 15). Semuanya sekarang didefinisikan di `libPipaGpu.a` (`devices/pipa/scripts/build-pipa-gpu.py`, dari record compile kernel ini):

| Simbol | Penyedia | Isi |
| --- | --- | --- |
| `native_gop_handoff_call` | `NativeGOPPresenter.cpp` (GopFramebuffer pin `14c7dffb`, `patches/gopframebuffer/0001`) | operasi hand-off 0 mode, 2 tunggu frame, 3 selesaikan, dengan pemeriksaan ukuran rekaman wire seperti metode service-nya sendiri |
| `native_gop_handoff_memory` | idem | descriptor scanout (retained) hanya dalam mode GPU (`sheng-fb-gpu=1`) |
| `boot_log_export_put` | `package/BootLogExport.c` + `BootLogExportCore.h` | kontrak in-order sheng (`-1` argumen, `-2` memori, `-3` urutan, `-5` terlalu besar); blob lengkap terbaru disimpan di **memori kernel** (batas 16 MiB); tidak ada panggilan storage sama sekali |
| `l_boot_log_export_put.ptrauth` | dibuat Apple clang untuk alamat fungsi weak-import | pointer bertanda tangan ke `_boot_log_export_put`; ter-resolve karena targetnya terdefinisi (dicek `pipa_adreno_xnu_check.py`) |

Patch GopFramebuffer: presenter dulu menyelesaikan swap lewat `native_legacy_gpu_complete` milik `NativeLegacyDisplay.cpp`, yang mengikat kelas asli `IOMobileFramebufferLegacy` lewat fixture ABI per fileset (iPadOS 17/27, macOS 27.3) dan tidak bisa dibangun untuk 26.5. Patch menyimpan fungsi penyelesaian bersama swap (`native_gop_gpu_offer_with`); `native_gop_gpu_offer` untuk NativeLegacyDisplay tetap ada dan sama, kecuali dengan `-DNATIVE_GOP_OFFER_WITH_ONLY=1` (build macOS pipa). Tidak ada definisi yang dikarang untuk driver yang tidak ada. Pemeriksaan linker tidak dimatikan: definisinya **strong** (weak akan menjadi import yang ditolak XnuPrelink), dan `build-pipa-gpu.py` gagal bila ada yang weak atau ada referensi ke `native_legacy_gpu_complete`.

Perilaku yang jujur di kernel ini: tidak ada yang memanggil `native_gop_presenter_create`, jadi hand-off menjawab `kIOReturnNotReady` dan descriptor scanout null (keduanya ditangani pemanggil). Metode ekspor fork hanya menerima proses `backboardd` (server render iPadOS); di macOS servernya WindowServer, jadi ekspor belum terjangkau. Blob tidak bertahan melewati restart.

## 2. Adreno650 di konfigurasi khusus pipa

| Pemeriksaan | Hasil | Bukti |
| --- | --- | --- |
| Compile terhadap xnu-12377 | 29 objek `libAdreno650.a` (1.229.456 byte) + 2 objek `libPipaGpu.a` (324.056 byte), `-Werror` | run 43145180980 |
| Simbol | 398 simbol dibutuhkan kedua arsip; **0** tidak terdefinisi di kernel; ketiga simbol hand-off/ekspor ada di kernel | `adreno-xnu.json` |
| Link | 29 + 2 anggota di link map; 0 import chained fixup; kernel native 25.263.616 byte, SHA-256 `121cf27cf58759cf4a9517a67dc2119ac1cc2d4f2316fea29ee02d9c2ee1e67d` | `kernel-report.json` |
| Prelink | kernel collection `MH_FILESET` arm64e 135.118.848 byte, SHA-256 `8de717f72bc5e96dcea104510571c377d21e774135346515dd1980d2aba920ea`; `missing`/`stubbed` {}, `mapping_complete` true, 87 kext | `prelink-record-summary.json` |
| Reproducibility | build kedua dari nol: SHA-256, UUID dan string versi sama; run 43143696276 (commit lain, input kernel sama) menghasilkan kernel dan kernel collection yang sama | langkah repro |
| Katalog | `patches/unixnu/0002`: `os_abi` sekarang juga `macos-26.5-25F71`; `verified_devices` tetap kosong | `pipa_unixnu.py check` |
| Pemanggil | tidak ada: tanpa personality, `GpuProbe.cpp` (bring-up iPadOS yang menulis register GPU) tidak termasuk; kelas-kelas hanya terdaftar lewat start C++ kernel | `pipa_macos26_gpu_defconfig` |

Akselerasi GPU tidak diklaim.

## 3. Display (audit macOS vs iPadOS)

`scripts/pipa_os_abi.py` membagi package dari resep build; rinciannya di [display-touch.md](display-touch.md#pemisahan-kode-analisis-ipados-dan-kode-yang-kompatibel-macos-sesi-9). Hasil: kode yang dikompilasi kernel macOS (lima sumber storage, `A650Gmu.c`, `BootLogExport.c`) tidak menyebut antarmuka iPadOS; 21 berkas bring-up/analisis hanya untuk kernel iPadOS (`LegacyDisplayProbe.cpp`, `MdssProbe.cpp`, `TouchProbe.cpp`, `GpuProbe.cpp`, …); model dual DSI, DSC 1.1, TLMM 75, varian TM/CSOT dan firmware NT36532 adalah model host OS-netral yang belum dipakai kernel mana pun. Dari driver feed, hanya `NativeGOPPresenter.cpp` yang kompatibel macOS 26.5 (dan kini ter-compile); `NativeLegacyDisplay`/`NativeMobileDisplay`, `QcomGeniSpi`, `ShengNovatekTouch`, `ShengHidInput` tetap ABI iPadOS.

## 4. GENI I2C dan KTZ8866

| Pemeriksaan | Hasil |
| --- | --- |
| Compile terhadap xnu-12377 | `PipaBacklight.c` dengan record compile `bsd_init.c`, `-Werror`: berhasil (`scripts/pipa_board_xnu_check.py`, run 43145180980) |
| Simbol | `IODelay`, `PE_parse_boot_argn`, `ml_io_map_unmappable`, `ml_io_unmap`, `printf`, `__stack_chk_*`: semua ada di kernel |
| Tulis register | audit statis tetap: hanya register transfer GENI; KTZ8866 lewat `ktz_write`, ditolak selama `allow_writes` = 0 |
| Di-link | **tidak**: tidak ada pemanggil `pipa_backlight_attach`. Menautkannya mengubah kernel tanpa manfaat sampai pemilik mau menguji jalur baca-saja (`pipa-backlight=1`) |

## 5. Ruang prelink

| Batas XnuPrelink | Generik | UFS | GPU |
| --- | --- | --- | --- |
| `__TEXT` native di celah `__PRELINK_TEXT` (`0x1927e0`) | GEN_TEXT | UFS_TEXT | `0x188000`, sisa **42.976** |
| `__DATA_CONST` + `__LASTDATA_CONST` sebelum konstanta kext pertama | GEN_DC | UFS_DC | sisa **918.568** |
| `__TEXT_EXEC` + `__KLD` di bawah `__DATA` collection | GEN_EX | UFS_EX | sisa **5.341.184** |

Adreno650 hampir seluruhnya kode (`__TEXT,__text` 117.828 byte, ke `__TEXT_EXEC`); bagian `__TEXT` non-eksekusinya ±1,5 KB dan tidak menambah satu halaman pun. Jadi tidak ada yang perlu dipangkas, dan tidak ada simbol, driver atau pemeriksaan yang dibuang. Opsi yang dievaluasi tetapi **tidak** dipakai: memindah `__cstring` arsip board ke `__DATA_CONST` (preseden: XNU sendiri memindah `__HIB,__cstring` ke `__DATA_CONST,__hib_const`). Uji dengan `ld64.lld` lokal: segmen input saja tidak cukup (linker menggabung literal C ke `__TEXT,__cstring`), perlu ganti nama dan tipe section; dan `__DATA_CONST` bisa ditulis sampai lockdown. Karena tidak dibutuhkan dan sedikit melemahkan perlindungan sebelum lockdown, opsi itu ditinggalkan. Batas yang paling dekat tetap `__PRELINK_TEXT` untuk kernel UFS (10.208 byte).

## 6. Hambatan yang tersisa

1. **GPU di macOS**: driver ter-link tetapi tidak ada pemanggil (tidak ada probe macOS, presenter tidak dibuat); Metal macOS butuh bundle plugin macOS dan publikasi akselerator yang dicocokkan WindowServer; ekspor fork menerima `backboardd` saja; firmware GMU/SQE/zap tidak disematkan. Uji apa pun hanya oleh pemilik.
2. **Display/touch**: belum ada driver macOS; `NativeLegacyDisplay` butuh fixture kelas 26.5; `QcomGeniSpi`, `ShengNovatekTouch`, `ShengHidInput` hanya iPadOS; identitas panel saat boot harus dari firmware atau boot-arg.
3. **Backlight**: ter-compile, belum di-link (keputusan pemilik; tetap baca-saja).
4. **UFS**: hanya inspeksi register; tidak diuji di tablet. Sisa `__PRELINK_TEXT` 10.208 byte.
5. Konfigurasi gabungan UFS + GPU belum dibangun (secara ruang muat: GPU tidak menambah halaman `__TEXT`).
6. Ditunda atas instruksi: `pacstrip`, gerbang ISA, payload, boot.
