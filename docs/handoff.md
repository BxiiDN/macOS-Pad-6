# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-12 (sesi 10: kernel uji pertama UFS + Adreno650, jalur start board, presenter, WindowServer, riset ABI display; baseline sesi `b6ada11`). Laporan kesiapan boot: [boot-readiness.md](boot-readiness.md). Laporan kesiapan: [kernel-integration.md](kernel-integration.md). Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

## Target (tetap)

macOS Tahoe **26.5 (25F71)**, XNU **12377.121.6** (`ac9718fb1af6`), Xiaomi Pad 6 (**pipa**), Snapdragon 870 **SM8250**. macOS asli, bukan simulator/launcher/skin. Tanpa binary Apple di repo, tanpa flashing, tanpa klaim tanpa bukti.

## Keadaan sekarang

| Langkah | Keadaan | Bukti |
| --- | --- | --- |
| Audit Tahoe 26.x, profil `macos-26.5-25F71` | selesai | `docs/tahoe-26-report.md`, `docs/evidence/tahoe-26.5/` |
| Board pipa UniXNU format 2 (`devices/pipa`) | selesai, di-resolve, dicek CI | `docs/board-migration.md`, artefak CI `pipa-board-status` |
| Rantai patch | 123/123 apply ke xnu-12377.121.6 dalam urutan board | `scripts/check_patch_chain.py`, `pipa_unixnu.py check --xnu` |
| Compile + link kernel native (arm64e) | **berhasil**; `__TEXT` `0x188000`, 0 import | `docs/kernel-build.md` percobaan 2, 8, 9 |
| Build reproducible | **ya** untuk ketiga konfigurasi pada input sesi 9 (build kedua dari nol identik); sebelumnya kernel `ce13aea1…`, kernel collection `840488d5…` | percobaan 9, 12, 19–21 |
| Prelink dengan kernelcache 26.5 | **berhasil**: `MH_FILESET` arm64e 135.036.928 byte, 0 import | percobaan 9–12 |
| **Kernel dengan storage UFS** (`pipa_macos26_ufs_defconfig`) | **compile + link + prelink berhasil** (input sesi 9: lihat baris revalidasi; sesi 8: native `6955fd3c…`, kernel collection `9465acd4…`), 0 import, `missing`/`stubbed` {}, sisa `__PRELINK_TEXT` 10.208 byte | `docs/kernel-build.md` percobaan 15, 20 |
| **Kernel dengan Adreno650** (`pipa_macos26_gpu_defconfig`) | **compile + link + prelink berhasil**, reproducible: native `4a6cd55e…`, kernel collection `02de1343…` 135.118.848 byte, 0 import, `missing`/`stubbed` {}, 31 anggota arsip ter-link, 0 simbol tak ter-resolve, `__TEXT` tetap `0x188000` (sisa 42.976 byte) | `docs/kernel-build.md` percobaan 17–18, 21 |
| Revalidasi kernel generik dan UFS (input sesi 9) | generik: native `f1fc02b0…`, kernel collection `52795685…` 135.036.928 byte, sisa `__PRELINK_TEXT` 42.976; UFS: native `9d5e23ee…`, kernel collection `a951ff56…` 135.102.464 byte, sisa 10.208; keduanya 0 import, `missing`/`stubbed` {}, build kedua identik | percobaan 19–20 |
| **Kernel uji pertama** (`pipa_macos26_ufs_gpu_defconfig`, `[kernel-ufs-gpu]`) | **compile + link + prelink berhasil**; native `92d5a0d6…`, kernel collection `fbc82f22…` 135.217.152 byte, 0 import, `missing`/`stubbed` {}; storage 12, Adreno650 29, libPipaGpu 6 anggota; build kedua **dan** run kedua identik (native, UUID, link map, simbol, kernel collection); `__TEXT` `0x190000` (sisa 10.208) dengan ambang assert 40 | `docs/kernel-build.md` percobaan 22–25 |
| Jalur start board | `zzzzd` (rantai 123): `bsd_init` → `pipa_board_start` → presenter GOP (`pipa-gop=1`) lalu GPU (`pipa-gpu=<1..11>`, tulis butuh `pipa-gpu-writes=1`); dicek dari `bsd_init.o` | percobaan 24 |
| `pacstrip` + gerbang ISA, payload, boot image, boot di tablet | **belum** (ditunda atas instruksi pemilik) | |
| **G2 UFS** | patch UniXNU `0001` (`NATIVE_UFS_<SoC>`) + `0003` (storage tanpa root); lima sumber package storage pipa (baca-saja, tanpa root userdata, tanpa tulis UFS); patch feed PipaUfs `patches/shengufs/0001`–`0002`; patch `0004` (tanpa root → probe-only: tanpa publikasi blok/root); arsip **di-link** oleh `pipa_macos26_ufs_defconfig` (12 anggota, 385 simbol kernel ter-resolve, 0 konflik); berjalan hanya dengan `native-source-storage=1` + `native-ufs-probe` ∈ {2,6,7,8} | percobaan 13–15, `PipaStorageGuard.h` |
| **G3 Adreno 650** | known-fail alias BO selesai (sesi 8); empat simbol yang kurang **didefinisikan kode nyata** di `libPipaGpu.a`: presenter GopFramebuffer (`patches/gopframebuffer/0001`, tanpa `NativeLegacyDisplay`) dan `package/BootLogExport.c` (ekspor di memori, tanpa UFS); **di-link** oleh `pipa_macos26_gpu_defconfig` (31 anggota, 398 simbol, 0 tak ter-resolve). Tidak ada pemanggil driver; presenter tidak dibuat; ekspor fork hanya menerima `backboardd` | `build-pipa-gpu.py`, `pipa_adreno_xnu_check.py` |
| **GENI I2C / KTZ8866** | shim kernel `PipaBacklight.c` (baca-saja, `pipa-backlight=1`); **audit statis**: tulis hanya lewat callback engine ke register transfer, register konfigurasi tidak pernah ditulis, tulis KTZ8866 terkunci; diuji pada tablet simulasi; **ter-compile terhadap xnu-12377** (`pipa_board_xnu_check.py`), simbolnya ada di kernel; belum di-link | `package/PipaBacklight.c`, `GeniI2cBoard.h`, `PipaBacklightTests.c` |
| **Display / touch** | pemisahan iPadOS/macOS dari resep build (`scripts/pipa_os_abi.py`: kode kernel macOS tidak menyebut antarmuka iPadOS; 21 berkas bring-up hanya iPadOS; model panel/touch/backlight = model host); reset TLMM 75 (setiap pengguna di DT vendor = reset panel DSI/pin state `sde_dsi`; cek pin state baca-saja); `PanelLink.h`: dua host DSI + DSC 1.1 rate control (= Linux, nilai dihitung tangan); varian TM/CSOT dipisah; firmware NT36532 per varian, **tidak ada untuk panel tak dikenal** | `docs/display-touch.md`, `PanelLink.h`, `TouchVendor.h` |
| **G6 memori** | sisi kernel tabel rentang terlarang dimodelkan; 6 GiB = maksimum kolam bootstrap 4 KiB di setiap base dan slide; **audit alamat** (DTS = board, jendela di satu bank, head, image ≥ kernel collection, rentang terlarang) | `scripts/pipa_memory.py`, `tests/hw/test_pipa_memory.py` |
| **Fuel gauge / charger** | PM8150B FG gen4 + SMB5, charge pump bq2597x, profil baterai: 22 fakta = DT vendor | `docs/power-supply.md`, `PowerSupplyBoard.h` |

## Hasil pengujian menurut jenis bukti

| Jenis | Yang terbukti | Yang tidak |
| --- | --- | --- |
| **Build** (runner `macos-26`) | kernel generik, UFS, dan GPU ter-compile, ter-link, ter-prelink, masing-masing reproducible (sesi 9); arsip storage/Adreno650/libPipaGpu ter-link hanya di defconfig-nya (link map); `PipaBacklight.c` ter-compile | bahwa kernel berjalan; bahwa storage, GPU, display bekerja |
| **Analisis statis** | rantai 123/123; board di-resolve; DTS → ADT; 52 konstanta = DT mainline; **107 fakta driver** = sumber Linux (GENI/KTZ8866/GCC/TLMM 95, DSC 12); **82 fakta = DT vendor Xiaomi**; 50/50 konstanta A650 GMU; audit tulis backlight | perilaku perangkat keras |
| **Host test** | 141 unit test Python (1 dilewati); **14 host test C** paket board di x86 (14 di arm64 dengan `A650GmuTests`); shim backlight pada tablet simulasi + cek sintaks mode kernel; fork Adreno650 pin (2 known-fail tercatat) dan patched (0 known-fail); `MemoryWindow.h` + model kernel pada peta pipa | perilaku chip: register disimulasikan, peta memori dimodelkan |
| **Perangkat nyata** | **tidak ada** oleh repo ini | — |

Yang dilaporkan berjalan di tablet (iPadOS 17: UFS, layar frame buffer, touch, tombol, GPU/Metal) adalah klaim upstream UniXNU-pipa, tidak diulang di sini.

## Cara melanjutkan

```sh
git clone https://github.com/BxiiDN/macOS-Pad-6 && cd macOS-Pad-6 && git checkout board-migration-wip
git submodule update --init --depth 1 third_party/UniXNU
git -C third_party/UniXNU submodule update --init --depth 1
scripts/pipa-unixnu.sh check --adt          # butuh dtc; --xnu DIR untuk cek apply
scripts/test.sh && scripts/test_board_package.sh                   # unit test Python, host test C paket board
python3 scripts/pipa_hw.py fetch --linux /tmp/linux && python3 scripts/pipa_hw.py compile --linux /tmp/linux --out /tmp/pipa.dtb
python3 scripts/pipa_hw.py check --dtb /tmp/pipa.dtb             # board = DT mainline
python3 scripts/pipa_hw.py drivers --linux /tmp/linux            # GENI/KTZ8866/GCC/TLMM = sumber Linux
python3 scripts/pipa_hw.py fetch-vendor --vendor /tmp/micode && python3 scripts/pipa_hw.py vendor --vendor /tmp/micode
python3 scripts/pipa_memory.py --dtb /tmp/pipa.dtb --check       # G6, loader + kernel + bootstrap pada model peta
python3 scripts/gen_pipa_gmu.py --linux /tmp/linux --dtb /tmp/pipa.dtb --check   # G3, ShengGmuSource.h A650
python3 scripts/test_adreno650.py --dtb /tmp/pipa.dtb            # G3, fork Adreno650 pin + patched
python3 scripts/pipa_storage_build.py --plan                     # G2, lingkungan build arsip storage (runner macOS)
```

Build kernel dan arsip storage hanya di runner `macos-26` (`.github/workflows/kernel-build.yml`):

- `[kernel-build]` di pesan commit: fetch, defconfig, compile + link, laporan; `[kernel-prelink]`: + prelink; `[kernel-repro]`: build kedua dibandingkan;
- setiap kernel step membangun arsip storage (`component:ShengUfs`); `scripts/pipa_storage_build.py --check-only --linked yes|no` memeriksa simbol, saklar SoC/probe-only dari command line, bundle kebijakan kosong, simbol yang dibutuhkan dari kernel, dan link map;
- `[kernel-ufs]`: `pipa_macos26_ufs_defconfig` (storage di-link); `[kernel-gpu]`: `pipa_macos26_gpu_defconfig` (Adreno650 + libPipaGpu di-link). Setiap kernel step membangun `component:Adreno650` dan `build-pipa-gpu.py`; `scripts/pipa_adreno_xnu_check.py --linked yes|no` memeriksa simbol kedua arsip terhadap kernel, link map, dan ukuran per section; `scripts/pipa_board_xnu_check.py` mengompilasi `PipaBacklight.c`;
- `[kernel-ufs-gpu]`: `pipa_macos26_ufs_gpu_defconfig` (kernel uji pertama);
- `[kernel-repro]` membangun ulang defconfig yang sama dari nol, mem-prelink ulang, dan `scripts/repro_compare.py` membandingkan kernel native, link map, simbol eksternal dan kernel collection; sebut satu konfigurasi saja (workflow menolak dua);
- setiap prelink juga menjalankan `scripts/legacy_display_abi_probe.py` (riset ABI display 26.5, angka saja);
- `workflow_dispatch` baru bisa setelah workflow ada di `main`.

Log job dibaca lewat `gh api repos/BxiiDN/macOS-Pad-6/actions/jobs/<id>/logs` (unduhan artefak diblokir proxy sesi Claude).

## Kendala yang ditemukan

- **Sesi 10**: kernel gabungan semula `__TEXT` `0x194000` (kurang `0x10c0`): GpuProbe/presenter menambah ±6,4 KB; diatasi `-DMACH_ASSERT_EXPR_MAX=40` hanya untuk kernel itu. String board tidak boleh dipindah ke `__DATA_CONST`: os_log membuang format di luar `__TEXT` image. `nm -g` tidak melihat definisi kernel yang hidden (`___ubsan_handle_add_overflow_minimal`): cek simbol memakai `nm -PU`. `-Wextra` setelah relaksasi menyalakan lagi `-Wreorder-init-list` (makro `IOMallocType`).
- **Display 26.5**: semua simbol fixture `NativeLegacyDisplay` ada, tetapi tata letak berbeda dari 27.3 (473 slot vs 483, instance 6.904 vs 9.120, `display_width` dan mask layer pindah); fixture 26.5 butuh collection VM 26.5 sebagai oracle dan tinjauan peran slot. HID sama: fixture `IOHIDDevice` 26.5.
- **Touch**: GENI SPI, NT36532, `TouchProbe.cpp`, `TouchState.cpp` ter-compile terhadap xnu-12377; kurang firmware NT36532 (di luar Git) dan jalur start macOS.

- **G2**: storage di-link hanya pada `pipa_macos26_ufs_defconfig`; yang diizinkan hanya inspeksi register (`native-ufs-probe` 2, 6, 7, 8); perilakunya di tablet belum diuji. Root macOS tetap tidak ada: `[storage] root = "none"`, dan dengan probe-only kode publikasi blok/root tidak di-compile. Root di `userdata` menghapus Android; alternatif UniXNU mengubah tabel partisi — keduanya butuh keputusan pemilik. Patch `0001`, `0003`, `0004` dan `patches/shengufs` belum dikirim ke upstream.
- **Ruang prelink**: sisa `__PRELINK_TEXT` 42.976 byte (generik dan GPU: Adreno650 tidak menambah halaman `__TEXT`), 10.208 byte (UFS). `__DATA_CONST` sisa ±918 KB, `__TEXT_EXEC` ±5,3 MB (`prelink_layout.py`). Memindah `__cstring` ke `__DATA_CONST` dievaluasi dan ditinggalkan (tidak perlu; sedikit melemahkan perlindungan sebelum lockdown).
- **G3**: driver ter-link tetapi tidak ada pemanggil macOS (`GpuProbe.cpp` adalah bring-up iPadOS yang menulis register GPU, sengaja tidak dipakai); presenter GopFramebuffer tidak dibuat (butuh titik attach frame buffer di macOS); metode ekspor fork hanya menerima `backboardd`; blob ekspor tidak bertahan melewati restart; Metal macOS butuh plugin macOS. Apple clang membuat `l_<fungsi>.ptrauth` untuk fungsi weak-import (nm menyebutnya undefined): cek memeriksa targetnya. Tanpa patch fork: `test_gmumap` dan `test_vm` known-fail (peer SMMU basi). `test_client`, `test_submit`, `test_userclient` dilewati di host (butuh `kern/cpu_data.h`), tetapi ikut ter-compile di runner macOS terhadap header XNU.
- **GENI / backlight**: shim belum masuk arsip kernel; tidak ada nilai `DEVICE_ID` yang diharapkan di sumber publik; clock wrap1/s3 dan pin dianggap disiapkan firmware (shim menolak bila tidak, tanpa memperbaikinya).
- **Display**: membaca MDSS dari XNU pernah menyebabkan SError fatal (`MdssProbe.cpp`); panel penuh butuh driver clock/GDSC MDSS lebih dulu. Identitas panel saat boot (TM/CSOT) tidak ada di tabel publik mana pun: bootloader Android yang mendeteksinya; di jalur XNU harus datang dari firmware atau boot-arg. `GopFramebuffer`, `QcomGeniSpi`, `ShengNovatekTouch`, `ShengHidInput` hanya ABI iPadOS. Nilai DSC adalah turunan Linux, bukan dari panel.
- **G6**: peta memori firmware uefi-pipa nyata tidak diketahui (model). Lebih dari 6 GiB butuh kolam tabel bootstrap lebih besar dari 16 halaman.
- **Daya**: tabel FCC JEITA vendor memuat 48,0 °C di dua baris; gauge bq27z561 dijelaskan di DT tetapi bus-nya `disabled`.
- Lingkungan sesi Claude: unduhan artefak GitHub diblokir proxy (log dibaca lewat API); `dtc` dibangun dari sumber Linux 4.16. Beberapa run CI lama sempat `queued`/`cancelled` karena kapasitas runner.
- Mengubah file di `devices/pipa` memindahkan tanggal build kernel (keputusan 6). Patch `zzzzc` menggeser nomor baris `bsd_init.c`, jadi kernel generik juga punya hash baru walau kodenya sama.

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py` (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig`.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada, `native_exit_trace` no-op **strong**.
4. Kernel macOS pipa default (`pipa_macos26_defconfig`) hanya jalur generik; `pipa_macos26_ufs_defconfig` menambah storage UFS probe-only. Keduanya tanpa root: akhir boot yang diharapkan tetap panic mount root.
5. Ukuran `__TEXT`: `-fmacro-prefix-map` dan `zzzzb-pipa-long-assert-text.patch`; sisa celah `__PRELINK_TEXT` 42.976 byte (generik), 10.208 byte (dengan storage).
6. `KERNEL_BUILD_DATE` dipin dari commit terakhir yang mengubah input kernel (`devices/pipa`, `profiles`, `kernel`, `third_party`, `.gitmodules`, `patches`).
7. Pemeriksaan perangkat keras membaca konstanta **dari sumber** setiap kali dan membandingkan dengan DT mainline Linux pada commit yang dipin.
8. Fakta yang tidak ada di mainline dicek terhadap DT Android Xiaomi (`MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf`), berkas dimuat dalam urutan include (`VENDOR_FILES`), dilaporkan sebagai "vendor".
9. Driver ditulis sebagai inti C portabel + simulator; shim kernel tipis; tulis ke chip dikunci (`allow_writes`) sampai pemilik menguji jalur baca-saja.
10. Perubahan UniXNU dibawa sebagai patch di `patches/unixnu/` (seri dinilai utuh: `0003` menyentuh baris `0001`; pada checkout `--in-place` terhadap `git show HEAD:`); perubahan feed sebagai `patches/<feed>/` (`FEED_PATCHES`: `adreno650`, `shengufs`, `gopframebuffer`). Keduanya termasuk `KERNEL_INPUTS`.
11. G6: jendela macOS 6 GiB dengan tabel 64 rentang; iPadOS 5,75 GiB satu run. 6 GiB adalah batas kolam bootstrap 4 KiB di setiap base dan slide (dihitung, bukan asumsi).
12. G2: tidak ada root macOS dari UFS (`[storage] root = "none"` → probe-only, patch 0004); `PipaStorageGuard.h` hanya mengizinkan inspeksi register 2, 6, 7, 8 dan menolak setiap mode yang menulis `userdata`, me-mount root, atau mempublikasikan blok.
14. Panggilan ke komponen board dari XNU dibuat strong dan di belakang saklar compile (`XNU_PIPA_SOURCE_STORAGE`), bukan weak: weak menjadi import yang ditolak XnuPrelink.
15. Firmware touch dan urutan panel dipilih dari varian yang teridentifikasi; varian tak dikenal → tidak ada firmware.
13. Kegagalan test fork tidak disembunyikan: `KNOWN_FAILURES` menyebut baris dan sebab; kegagalan yang tercatat tetapi lulus, atau gagal di tempat lain, dilaporkan FAILED. Sejak sesi 9 langkah Adreno650 di workflow tidak lagi `continue-on-error`: kegagalannya menggagalkan run.
16. Simbol yang dibutuhkan driver dari board didefinisikan oleh kode yang punya perilaku sendiri (presenter, ekspor di memori), strong, tanpa definisi palsu untuk driver yang tidak ada; patch feed menjaga API lama untuk iPadOS.
17. GPU di-link oleh `pipa_macos26_gpu_defconfig` dan `pipa_macos26_ufs_gpu_defconfig`; dipanggil dari `bsd_init` (`zzzzd`) hanya dengan `pipa-gpu`; mode yang menulis register butuh `pipa-gpu-writes=1`; mode 12 (akselerator Metal iPadOS) tidak ada di macOS.
18. Server render Adreno650 satu nama per build (`NATIVE_ADRENO_RENDER_SERVER`): WindowServer di macOS, backboardd di iPadOS; bukan pengganti satu sama lain.
19. Firmware GPU disematkan hanya bila ada di mesin build (`.cache/firmware`), di `__DATA_CONST` (bukan `__TEXT`); tidak pernah di Git.
20. Ambang teks assert boleh diturunkan per konfigurasi (`MACH_ASSERT_EXPR_MAX`) bila `__TEXT` tidak muat; pemeriksaan dan file:line tidak pernah dibuang.

## Langkah berikutnya, berurutan

Rincian per kategori ada di [boot-readiness.md](boot-readiness.md). Urutan yang aman:

1. (Ditunda atas instruksi pemilik) `pacstrip` + gerbang ISA pada kernel collection `pipa_macos26_ufs_gpu_defconfig`, lalu payload dan boot image. Tanpa ini tidak ada yang bisa di-boot.
2. Pemilik memverifikasi pemulihan Android **sebelum** uji: unlock, `fastboot boot` (RAM saja) diterima, kombinasi tombol kembali ke fastboot, Android boot normal, cadangan partisi kritis.
3. Uji pertama hanya oleh pemilik, bertahap: tanpa argumen board (harapan: panic mount root di konsol); lalu `pipa-gop=1`; lalu `native-source-storage=1 native-ufs-probe=2`; lalu `pipa-gpu=1`. Mode GPU yang menulis (`pipa-gpu-writes=1`) hanya setelah itu, dan butuh firmware dari partisi vendor.
4. Display: ambil collection VM 26.5 di runner, jalankan `gen-board-abi.py`, tinjau peran slot dan offset; tambahkan build 25F71 ke `build-gop-legacy-display-27.py`.
5. Touch/HID: jalur start macOS untuk `TouchProbe.cpp`, firmware NT36532 per varian, fixture `IOHIDDevice` 26.5.
6. Bangun ulang kernel generik, UFS dan GPU tunggal pada input sesi 10 (`[kernel-prelink] [kernel-repro]` per konfigurasi).
7. Kirim `patches/unixnu/0001`–`0004`, `patches/adreno650/` (termasuk `0004`), `patches/shengufs/`, `patches/gopframebuffer/` ke upstream.
8. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
