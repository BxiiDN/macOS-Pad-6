# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-11 (sesi 6: integrasi komponen board; build kernel terakhir: percobaan 12). Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

## Target (tetap)

macOS Tahoe **26.5 (25F71)**, XNU **12377.121.6** (`ac9718fb1af6`), Xiaomi Pad 6 (**pipa**), Snapdragon 870 **SM8250**. macOS asli, bukan simulator/launcher/skin. Tanpa binary Apple di repo, tanpa flashing otomatis, tanpa klaim tanpa bukti.

## Keadaan sekarang

| Langkah | Keadaan | Bukti |
| --- | --- | --- |
| Audit Tahoe 26.x, profil `macos-26.5-25F71` | selesai | `docs/tahoe-26-report.md`, `docs/evidence/tahoe-26.5/` |
| Board pipa UniXNU format 2 (`devices/pipa`) | selesai, di-resolve, dicek CI | `docs/board-migration.md`, artefak CI `pipa-board-status` |
| Rantai patch | 121/121 apply ke xnu-12377.121.6 dalam urutan board | `scripts/check_patch_chain.py`, `pipa_unixnu.py check --xnu` |
| Compile + link kernel native (arm64e) | **berhasil**; `__TEXT` `0x188000`, 0 import | `docs/kernel-build.md` percobaan 2, 8, 9 |
| Build reproducible | **ya**: kernel native `ce13aea1…` dan kernel collection `840488d5…` identik antar-build dan antar-commit | percobaan 9, 12 |
| Prelink dengan kernelcache 26.5 | **berhasil**: `MH_FILESET` arm64e 135.036.928 byte (`840488d5…`), 0 import, XnuPrelink `missing` {} `stubbed` {} | percobaan 9–12 |
| `pacstrip` + gerbang ISA pada kernel collection | belum | |
| Payload, boot image | belum | |
| Boot di tablet | belum | |
| Riset perangkat keras pipa | konstanta kode board = DT mainline Linux (52 cocok, 0 berbeda); inventaris; kebutuhan G2–G6 dipetakan | `docs/hardware-pipa.md`, `docs/board-migration.md#kebutuhan-driver-g2g6` |
| GENI I2C | inti driver portabel (FIFO, polling, probe baca-saja, NACK/bus/arbitrase, cancel/abort) + simulator register; 80 konstanta = Linux | `package/GeniI2cCore.h`, `GeniI2cTests.c`, `pipa_hw.py drivers` |
| Backlight KTZ8866 | model board + inti driver (`ktz_attach` baca-saja, tulis dikunci, init, brightness) di atas GENI I2C, diuji pada simulator; **belum ada shim kernel**, belum ditulis ke chip | `package/BacklightBoard.h`, `Ktz8866Driver.h` |
| Panel DSI dan touch (DT Android) | model panel (dual DSI, DSC, timing, dfps, rail, ID) + host test; panel/touch/backlight = DT vendor Xiaomi (41 fakta) | `package/PanelBoard.h`, `pipa_hw.py vendor`, `tools/hw/dts_source.py` |
| G2 UFS: migrasi UniXNU | patch UniXNU `0001` (saklar `NATIVE_UFS_<SoC>` dari `[board] soc`) diterapkan ke salinan; `probe()` PipaUfs mencari `qcom,sm8250-ufshc` = DTB. Lima sumber package storage dan root di userdata: terbuka | `patches/unixnu/`, `pipa_unixnu.py check --adt` |
| G3 Adreno 650 | host test fork `Adreno650 01db67e0` (x86: 9 lulus, 12 dilewati beralasan; arm64: 14 lulus, 2 known-fail) + parser DT fork pada node GPU/GMU pipa; komponen katalog belum ada | `scripts/test_adreno650.py`, `tests/gpu/A650PipaBoard.cpp` |
| G6 jendela memori | macOS: 6 GiB + tabel rentang terlarang 64 slot (ADT dicek); iPadOS: 5,75 GiB satu run; `MemoryWindow.h` disimulasikan pada model peta pipa | `devices/pipa/board.toml`, `scripts/pipa_memory.py` |

## Hasil pengujian menurut jenis bukti

| Jenis | Yang terbukti | Yang tidak |
| --- | --- | --- |
| **Build** (runner `macos-26`) | kernel native arm64e ter-compile dan ter-link; prelink dengan kernelcache 26.5 berhasil; reproducible | bahwa kernel berjalan |
| **Analisis statis** | rantai 121/121; board di-resolve; DTS → ADT (termasuk tabel G6 dan compatible UFS); 52 konstanta = DT mainline; 80 konstanta GENI/KTZ8866 = sumber driver Linux; 41 fakta panel/touch/backlight = DT vendor Xiaomi; FGE/null-PAC ada di kode mesin; sensus ISA | perilaku perangkat keras |
| **Host test** | 97 unit test Python; 8 host test C paket board (x86 + arm64), termasuk GENI I2C + KTZ8866 pada simulator register dan panel; `A650GmuTests` di CI arm64; fork Adreno650 (x86: 9 lulus; arm64: 14 lulus, 2 known-fail) + parser DT-nya pada node pipa; `MemoryWindow.h` DarwinBoot pada model peta pipa | perilaku chip sebenarnya: register disimulasikan, peta memori dimodelkan |
| **Perangkat nyata** | **tidak ada** oleh repo ini | — |

Yang dilaporkan berjalan di tablet (iPadOS 17: UFS, layar frame buffer, touch, tombol, GPU/Metal) adalah klaim upstream UniXNU-pipa, tidak diulang di sini.

CI (`ci.yml`) hijau di setiap commit cabang ini.

## Cara melanjutkan

```sh
git clone https://github.com/BxiiDN/macOS-Pad-6 && cd macOS-Pad-6 && git checkout board-migration-wip
git submodule update --init --depth 1 third_party/UniXNU
git -C third_party/UniXNU submodule update --init --depth 1
scripts/pipa-unixnu.sh check --adt          # butuh dtc; --xnu DIR untuk cek apply
scripts/test.sh && scripts/test_board_package.sh                   # unit test Python, host test C paket board
python3 scripts/pipa_hw.py fetch --linux /tmp/linux && python3 scripts/pipa_hw.py compile --linux /tmp/linux --out /tmp/pipa.dtb
python3 scripts/pipa_hw.py check --dtb /tmp/pipa.dtb             # board = DT mainline
python3 scripts/pipa_hw.py drivers --linux /tmp/linux            # GENI/KTZ8866 = sumber driver Linux
python3 scripts/pipa_hw.py fetch-vendor --vendor /tmp/micode && python3 scripts/pipa_hw.py vendor --vendor /tmp/micode
python3 scripts/pipa_memory.py --dtb /tmp/pipa.dtb --check       # G6, MemoryWindow.h pada model peta
python3 scripts/test_adreno650.py --dtb /tmp/pipa.dtb            # G3, host test fork Adreno650
```

Build kernel tidak bisa di Linux tanpa toolchain UniXNU (LLVM yang di-patch, cctools-port, root). Jalurnya adalah `.github/workflows/kernel-build.yml` di runner `macos-26`:

- push ke `board-migration-wip` dengan `[kernel-build]` di pesan commit: fetch, defconfig, compile + link (`--skip-prelink`), laporan;
- `[kernel-prelink]`: sama, ditambah `build prelink`, tata letak `__PRELINK_TEXT` (`prelink_layout.py`) dan laporan kernel collection serta catatan XnuPrelink (`prelink_record.py`);
- `[kernel-repro]`: build kedua dari nol di tempat yang sama, dibandingkan per section (`kernel_report.py --compare`);
- setiap build menjalankan `kernel_size_audit.py` (section, asal per link map, string per patch).
- `workflow_dispatch` baru bisa setelah workflow ada di `main`.

Log job dibaca lewat `gh api repos/BxiiDN/macOS-Pad-6/actions/jobs/<id>/logs` (unduhan artefak diblokir proxy sesi Claude). Laporan kernel ada di log langkah "Report on the kernel".

## Kendala yang ditemukan

- **G2 (UFS)**: penghalang makro ditangani oleh `patches/unixnu/0001` (belum dikirim ke upstream, belum di-build di runner macOS). Tersisa: lima sumber package storage (`SourceStorage.cpp`, `SourceRootPolicies.cpp`, `SourceRootBinding.cpp`, `BootLog.c`, `BootReset.c`) tidak ada di pipa dan hanya bisa dikompilasi di build tree xnu runner macOS; root macOS di `userdata` menghapus Android (alternatif UniXNU mengubah partisi). Butuh keputusan pemilik; repo ini tidak menulis ke UFS atau partisi.
- **G3 (GPU)**: fork Adreno650 butuh `ShengGmu.h` yang dihasilkan dari tabel GMU A650 (`build-adreno650.py` UniXNU-pipa) dan komponen katalog; tanpa itu tidak bisa dipilih format 2. Sumber `NativeAdrenoMemory`/`NativeAdrenoSubmit`/`ArmSmmu4KMmio` hanya AArch64, jadi testnya hanya berjalan di runner arm64. Di arm64, `test_gmumap` dan `test_vm` fork gagal pada larangan tulis 64-bit peer SMMU-nya bila dipasangkan dengan ArmSmmu4K pin `feeds.toml` (`known-fail`, belum ditelusuri).
- **GENI I2C / backlight**: inti portabel selesai dan diuji di simulator; shim kernel (pemetaan MMIO SE, delay) belum ada dan butuh kompilasi di runner macOS. Clock QUP1 dan pin dianggap sudah disiapkan firmware (`ktz_attach` menolak bila SCL counter bukan nilai 400 kHz); itu asumsi sampai diuji di tablet. Tidak ada nilai `DEVICE_ID` yang diharapkan di sumber publik.
- **Display**: MDSS/DSI pipa tidak ada di mainline; panel diambil dari DT Android Xiaomi (vendor). Reset GPIO panel pipa tidak ditemukan di berkas vendor yang di-fetch (`xiaomi-sm8250-common.dtsi` tidak ada di cabang itu). Frame buffer boot dan backlight tetap jalur yang terdokumentasi.
- **G6**: peta memori firmware uefi-pipa yang nyata tidak diketahui; simulasi memakai model. Lebih dari 6 GiB butuh tabel bootstrap kernel yang lebih besar.
- **Fuel gauge, charger**: pengontrolnya tidak ada di DT mainline pipa; hanya dari DT Android (belum dicek dengan `pipa_hw.py vendor`).
- `A650GmuTests` hanya bisa dibangun untuk AArch64 (kit `AdrenoFirmware`); berjalan di runner `ubuntu-24.04-arm`.
- Lingkungan sesi Claude: unduhan artefak GitHub diblokir proxy (baca log lewat API); tidak ada `dtc` dari paket (dibangun dari sumber `scripts/dtc` Linux 4.16 secara lokal; CI memakai `device-tree-compiler`).
- Mengubah file di `devices/pipa` (termasuk `package/`) memindahkan tanggal build kernel (keputusan 6), jadi build kernel berikutnya punya hash baru walau `package/` tidak di-compile ke kernel macOS. Itu sesuai aturan yang sudah dicatat; pin bisa dipersempit bila perlu.

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py`; tanpa itu UniXNU memakai `UniXNU/ArmCpu` dan bukan cabang pipa (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig` (seperti UniXNU-sheng macOS); mode `prelinked` dari `macos.config` gagal link.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada (open terautentikasi tetap `EAUTH`), `native_exit_trace` no-op **strong** (versi weak menjadi import chained fixup yang ditolak XnuPrelink).
4. Kernel macOS pipa sengaja hanya jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). Akhir boot yang diharapkan: panic mount root.
5. Ukuran `__TEXT`: `-fmacro-prefix-map` (defconfig) dan `zzzzb-pipa-long-assert-text.patch` (teks `assert()` > 48 byte diganti catatan bersama; pemeriksaan, trap, file:line tetap). String dari patch hanya ±3 KB, jadi memangkas diagnostik patch tidak berguna untuk ukuran. Sisa ruang di celah `__PRELINK_TEXT`: 42.976 byte; bila kernel tumbuh, `prelink_layout.py` menunjukkan sisanya, dan `MACH_ASSERT_EXPR_MAX` bisa diturunkan lewat `CONFIG_XNU_EXTRA_CFLAGS` (`-DMACH_ASSERT_EXPR_MAX=40`).
6. `KERNEL_BUILD_DATE` dipin dari `SOURCE_DATE_EPOCH` atau waktu commit terakhir yang mengubah input kernel (`devices/pipa`, `profiles`, `kernel`, `third_party`, `.gitmodules`, `patches`), lewat `pipa_unixnu.py`; itu satu-satunya sumber perbedaan antar-build. Butuh clone penuh (`fetch-depth: 0`); di clone dangkal skrip memberi peringatan. Jadi commit yang hanya mengubah dokumen, CI, atau alat menghasilkan kernel yang sama bit demi bit; perubahan di path input mengganti tanggal (dan hash), seperti seharusnya.
7. Pemeriksaan perangkat keras membaca konstanta **dari sumber** setiap kali (bukan salinan), dan membandingkan dengan DT mainline Linux pada commit yang dipin (`LINUX_COMMIT` di `scripts/pipa_hw.py`). Fakta yang tidak ada di mainline dilaporkan terpisah, bukan dianggap cocok. Node GPU feed dicek "berisi semua range mainline", node USB feed (dinonaktifkan, ukuran vendor) dicek alamat dasarnya saja.
8. Fakta yang tidak ada di mainline dicek terhadap DT Android Xiaomi yang dipublikasikan (`MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf`), dibaca sebagai sumber DTS (`tools/hw/dts_source.py`, karena berkas vendor tidak bisa dikompilasi sendiri), dan dilaporkan sebagai "vendor", bukan "mainline". Konstanta driver (GENI, KTZ8866) dicek terhadap sumber driver Linux pada commit mainline yang sama.
9. Driver ditulis sebagai inti C portabel (akses register lewat callback) + simulator register untuk host test; shim kernel tipis menyusul dan dikompilasi di runner macOS. Tulis ke chip dikunci (`allow_writes`) sampai pemilik menguji jalur baca-saja.
10. Perubahan UniXNU dibawa sebagai patch di `patches/unixnu/` yang diterapkan `pipa_unixnu.py` ke salinan (dan ke checkout `--in-place` di workflow kernel), bukan dengan memindah pin submodul; setiap patch juga usulan upstream. `patches` termasuk `KERNEL_INPUTS`.
11. G6: jendela macOS 6 GiB dengan tabel 64 rentang (pola UniXNU-sheng); iPadOS tetap 5,75 GiB satu run.

## Langkah berikutnya, berurutan

1. ~~Prelink~~: berhasil dan reproducible (percobaan 9–12); catatan XnuPrelink tanpa target hilang atau stub.
2. (Ditunda atas instruksi pemilik di sesi 6: tidak ada PAC stripping, gerbang ISA, atau payload sampai pemilik memutuskan lain.) Pasang `tools/isa/pacstrip` ke kernel collection hasil prelink di workflow, lalu gerbang `python3 -m tools.isa.audit KC --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`.
3. `build payload` (butuh `UNIXNU_UNIQUE_CHIP_ID` sebagai secret repo; board `unique_chip_id = "required"`) dan `bootimg`. Tidak di-commit, tidak diunggah.
4. Uji di tablet hanya oleh pemilik, dengan `fastboot boot` (tidak menulis apa pun). Target pertama: bar entry probe, lalu panic `Failed to mount root device`.
5. Celah terbuka: G2 (sumber package storage, root), G3 (komponen katalog Adreno650), G5 (shim kernel GENI I2C/backlight, MDSS/DSI, HID touch), G6 (>6 GiB). Rincian di `docs/board-migration.md#kebutuhan-driver-g2g6`. Urutan yang aman (tanpa menulis ke perangkat): (a) kirim `patches/unixnu/0001` ke UniXNU dan build `ShengUfs` arm64e di runner macOS; (b) porting lima sumber package storage dari UniXNU-sheng; (c) shim kernel untuk `GeniI2cCore.h` + `Ktz8866Driver.h` (uji pertama di tablet oleh pemilik: `ktz_attach` saja); (d) `ShengGmu.h` A650 dan komponen katalog `Adreno650`; (e) cek fuel gauge/charger terhadap DT vendor.
6. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
