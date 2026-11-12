# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-12 (sesi 7: hambatan integrasi perangkat keras; baseline sesi `5553e69`). Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

## Target (tetap)

macOS Tahoe **26.5 (25F71)**, XNU **12377.121.6** (`ac9718fb1af6`), Xiaomi Pad 6 (**pipa**), Snapdragon 870 **SM8250**. macOS asli, bukan simulator/launcher/skin. Tanpa binary Apple di repo, tanpa flashing, tanpa klaim tanpa bukti.

## Keadaan sekarang

| Langkah | Keadaan | Bukti |
| --- | --- | --- |
| Audit Tahoe 26.x, profil `macos-26.5-25F71` | selesai | `docs/tahoe-26-report.md`, `docs/evidence/tahoe-26.5/` |
| Board pipa UniXNU format 2 (`devices/pipa`) | selesai, di-resolve, dicek CI | `docs/board-migration.md`, artefak CI `pipa-board-status` |
| Rantai patch | 121/121 apply ke xnu-12377.121.6 dalam urutan board | `scripts/check_patch_chain.py`, `pipa_unixnu.py check --xnu` |
| Compile + link kernel native (arm64e) | **berhasil**; `__TEXT` `0x188000`, 0 import | `docs/kernel-build.md` percobaan 2, 8, 9 |
| Build reproducible | **ya** (kernel `ce13aea1…`, kernel collection `840488d5…`) | percobaan 9, 12 |
| Prelink dengan kernelcache 26.5 | **berhasil**: `MH_FILESET` arm64e 135.036.928 byte, 0 import | percobaan 9–12 |
| `pacstrip` + gerbang ISA, payload, boot image, boot di tablet | **belum** (ditunda atas instruksi pemilik) | |
| **G2 UFS** | patch UniXNU `0001` (`NATIVE_UFS_<SoC>`) + `0003` (storage tanpa root); lima sumber package storage pipa (baca-saja, tanpa root userdata, tanpa tulis UFS); patch feed PipaUfs `patches/shengufs/0001`–`0002`; **arsip `libShengSourceStorage.a` ter-compile arm64e terhadap header xnu-12377** di runner macOS (1.511.112 byte, semua simbol, `-DNATIVE_UFS_SM8250=1`, 0 kebijakan); tidak di-link | `docs/kernel-build.md` percobaan 13, `scripts/pipa_storage_build.py` |
| **G3 Adreno 650** | penyebab kegagalan `write64` ditelusuri; `ShengGmuSource.h` A650 dihasilkan dari DT + Linux; komponen katalog `Adreno650` (patch `0002`) dan format 2 (`feeds.toml`, override iPadOS); 2 patch fork | `scripts/gen_pipa_gmu.py`, `scripts/test_adreno650.py`, `patches/adreno650/` |
| **GENI I2C / KTZ8866** | shim kernel `PipaBacklight.c` (baca-saja, di belakang `pipa-backlight=1`); validasi clock, DFS, pin dari pembacaan saja; tidak ada tulis GCC/TLMM/KTZ8866/konfigurasi engine; diuji pada tablet simulasi | `package/PipaBacklight.c`, `GeniI2cBoard.h`, `PipaBacklightTests.c` |
| **Display / touch** | reset panel **TLMM 75** (DT board Xiaomi, bukan dugaan); analisis dual DSI + DSC (pixel clock 167,84 MHz, byte clock 125,88 MHz, 900 byte/baris); kebutuhan driver touch NT36532 TDDI; struktur integrasi XNU | `docs/display-touch.md`, `PanelBoard.h`, `TouchVendor.h` |
| **G6 memori** | sisi kernel tabel rentang terlarang dimodelkan; kapasitas tabel bootstrap 4 KiB dihitung (6 GiB = maksimum di setiap base dan slide); batas sumber dibaca | `scripts/pipa_memory.py`, `tests/hw/test_pipa_memory.py` |
| **Fuel gauge / charger** | PM8150B FG gen4 + SMB5, charge pump bq2597x, profil baterai: 22 fakta = DT vendor | `docs/power-supply.md`, `PowerSupplyBoard.h` |

## Hasil pengujian menurut jenis bukti

| Jenis | Yang terbukti | Yang tidak |
| --- | --- | --- |
| **Build** (runner `macos-26`) | kernel native arm64e ter-compile dan ter-link (terakhir run 43132343953, `227cbe63…`); prelink berhasil; reproducible; **arsip storage pipa ter-compile** (run 43132343953) | bahwa kernel berjalan; bahwa arsip storage ter-link atau bekerja |
| **Analisis statis** | rantai 121/121; board di-resolve; DTS → ADT; 52 konstanta = DT mainline; 95 konstanta GENI/KTZ8866/GCC/TLMM = sumber Linux; **81 fakta = DT vendor Xiaomi** (display 45, touch 14, daya 22); 50/50 konstanta A650 GMU + tabel RSC/PDC 19 tulis = Linux | perilaku perangkat keras |
| **Host test** | unit test Python (lihat laporan sesi untuk angka terakhir); **12 host test C** paket board di x86 (+ `A650GmuTests` di arm64); shim backlight pada tablet simulasi + cek sintaks mode kernel; fork Adreno650 pin dan patched (`known-fail` tercatat per baris); `MemoryWindow.h` + model kernel pada peta pipa | perilaku chip: register disimulasikan, peta memori dimodelkan |
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
- `[storage-build]`: setelah langkah kernel, `scripts/pipa_storage_build.py` membangun `libShengUfs.a` dari lima sumber pipa di tree yang sama (tidak di-link), lalu memeriksa simbol, string probe `qcom,sm8250-ufshc`, dan bundle kebijakan kosong (`storage-build.json`);
- `workflow_dispatch` baru bisa setelah workflow ada di `main`.

Log job dibaca lewat `gh api repos/BxiiDN/macOS-Pad-6/actions/jobs/<id>/logs` (unduhan artefak diblokir proxy sesi Claude).

## Kendala yang ditemukan

- **G2**: arsip storage ter-compile tetapi belum di-link ke kernel macOS (profil macOS tidak memilih ShengUfs; memasukkannya butuh komponen dan keputusan uji). PipaUfs `5c64c01` tertinggal dari ShengUfs katalog (antarmuka VM xnu-12377, factory source API): dua patch feed menutup yang ditemukan compile, sisanya tidak diketahui sampai link. Root macOS tetap tidak ada: `[storage] root = "none"`; root di `userdata` menghapus Android, dan alternatif UniXNU mengubah tabel partisi — keduanya butuh keputusan pemilik. Patch `0001`/`0003` belum dikirim ke upstream UniXNU.
- **G3**: setelah patch fork, `test_vm` masih gagal di baris alias dua BO milik sendiri (`s.vm.map(&second,0,0x802000…`): fork `1c4065c` membuang pemindaian alias tetapi test tidak diperbarui. Dicatat `known-fail`, tidak disembunyikan. Tanpa patch: `test_gmumap` dan `test_vm` gagal di `CHECK(0)` peer SMMU (`write64` TLBIVAL di context bank + `0x620`). `test_client`, `test_submit`, `test_userclient` dilewati: butuh `kern/cpu_data.h`. Override iPadOS memilih `Adreno650`; macOS tidak punya GPU.
- **GENI / backlight**: shim belum masuk arsip kernel; tidak ada nilai `DEVICE_ID` yang diharapkan di sumber publik; clock wrap1/s3 dan pin dianggap disiapkan firmware (shim menolak bila tidak, tanpa memperbaikinya).
- **Display**: membaca MDSS dari XNU pernah menyebabkan SError fatal (`MdssProbe.cpp`); panel penuh butuh driver clock/GDSC MDSS lebih dulu. UniXNU-pipa hanya membangun firmware touch TM (`0x36`); panel CSOT (`0x42`) akan dapat firmware pembuat lain (`tv_config_for_panel` belum disambungkan). Komponen `GopFramebuffer`, `QcomGeniSpi`, `ShengNovatekTouch`, `ShengHidInput` hanya ABI iPadOS.
- **G6**: peta memori firmware uefi-pipa nyata tidak diketahui (model). Lebih dari 6 GiB butuh kolam tabel bootstrap lebih besar dari 16 halaman (6,25 GiB pada base tak sejajar butuh 17). Pemetaan bootstrap memetakan seluruh span sebagai memori normal sampai `arm_vm_init`; jendela 6 GiB di `0xc0000000` seluruhnya di bank 1, jadi tidak ada celah bank yang terpetakan.
- **Daya**: tabel FCC JEITA vendor memuat 48,0 °C di dua baris; baris yang berlaku tergantung driver vendor (tidak dicek). Gauge bq27z561 dijelaskan di DT tetapi bus-nya `disabled`.
- Lingkungan sesi Claude: unduhan artefak GitHub diblokir proxy; `dtc` dibangun dari sumber Linux 4.16 secara lokal. Actions sesi 7: run untuk `d365971`, `b104e4c`, `fd0b31c` tertahan `queued` tanpa job dan tidak bisa dibatalkan; beberapa run CI berikutnya `cancelled` karena "job was not acquired by Runner" (kapasitas runner, bukan kegagalan test).
- Mengubah file di `devices/pipa` memindahkan tanggal build kernel (keputusan 6); build berikutnya punya hash baru walau `package/` tidak di-compile ke kernel macOS.

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py` (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig`.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada, `native_exit_trace` no-op **strong**.
4. Kernel macOS pipa sengaja hanya jalur generik. Akhir boot yang diharapkan: panic mount root.
5. Ukuran `__TEXT`: `-fmacro-prefix-map` dan `zzzzb-pipa-long-assert-text.patch`; sisa celah `__PRELINK_TEXT` 42.976 byte.
6. `KERNEL_BUILD_DATE` dipin dari commit terakhir yang mengubah input kernel (`devices/pipa`, `profiles`, `kernel`, `third_party`, `.gitmodules`, `patches`).
7. Pemeriksaan perangkat keras membaca konstanta **dari sumber** setiap kali dan membandingkan dengan DT mainline Linux pada commit yang dipin.
8. Fakta yang tidak ada di mainline dicek terhadap DT Android Xiaomi (`MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf`), berkas dimuat dalam urutan include (`VENDOR_FILES`), dilaporkan sebagai "vendor".
9. Driver ditulis sebagai inti C portabel + simulator; shim kernel tipis; tulis ke chip dikunci (`allow_writes`) sampai pemilik menguji jalur baca-saja.
10. Perubahan UniXNU dibawa sebagai patch di `patches/unixnu/` (seri dinilai utuh: `0003` menyentuh baris `0001`; pada checkout `--in-place` terhadap `git show HEAD:`); perubahan feed sebagai `patches/<feed>/` (`FEED_PATCHES`: `adreno650`, `shengufs`). Keduanya termasuk `KERNEL_INPUTS`.
11. G6: jendela macOS 6 GiB dengan tabel 64 rentang; iPadOS 5,75 GiB satu run. 6 GiB adalah batas kolam bootstrap 4 KiB di setiap base dan slide (dihitung, bukan asumsi).
12. G2: tidak ada root macOS dari UFS (`[storage] root = "none"`); `PipaStorageGuard.h` menolak setiap mode NativeUfs yang menulis `userdata` atau me-mount root darinya.
13. Kegagalan test fork tidak disembunyikan: `KNOWN_FAILURES` menyebut baris dan sebab; kegagalan yang tercatat tetapi lulus, atau gagal di tempat lain, dilaporkan FAILED.

## Langkah berikutnya, berurutan

1. G2: putuskan (pemilik) apakah `ShengUfs` masuk profil macOS untuk link (tetap tanpa root, `native-ufs-probe=2` baca-saja sebagai uji pertama); kirim `patches/shengufs` ke xVanTuring/PipaUfs.
2. (Ditunda atas instruksi pemilik) `pacstrip`, gerbang ISA, payload, boot image.
3. Kirim `patches/unixnu/0001`–`0003`, `patches/adreno650/` dan `patches/shengufs/` ke upstream masing-masing.
4. Sambungkan `PipaBacklight.c` ke arsip kernel macOS (tetap baca-saja); uji pertama di tablet **hanya oleh pemilik**: `pipa-backlight=1`, baca `pipa_backlight_stats`.
5. Touch: kompilasi `QcomGeniSpi` + `ShengNovatekTouch` untuk arm64e; pilih firmware dari ID panel; HID untuk macOS.
6. G3: perbarui `test_vm` fork untuk perilaku alias sejak `1c4065c` (usulan upstream), lalu build arm64e `Adreno650` terhadap header xnu-12377.
7. G6: bandingkan peta UEFI nyata dengan model hanya bila pemilik menguji.
8. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
