# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-11 (setelah riset perangkat keras pipa; build kernel terakhir: percobaan 12). Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

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
| Backlight KTZ8866 | model board + host test; **belum ada driver**, belum ditulis ke chip | `devices/pipa/package/BacklightBoard.h` |

## Hasil pengujian menurut jenis bukti

| Jenis | Yang terbukti | Yang tidak |
| --- | --- | --- |
| **Build** (runner `macos-26`) | kernel native arm64e ter-compile dan ter-link; prelink dengan kernelcache 26.5 berhasil; reproducible | bahwa kernel berjalan |
| **Analisis statis** | rantai 121/121; board di-resolve; DTS → ADT; 52 konstanta perangkat keras = mainline; FGE/null-PAC ada di kode mesin; sensus ISA | perilaku perangkat keras |
| **Host test** | 63 unit test Python; 6 host test C paket board (x86 + arm64); `A650GmuTests` di CI arm64 | perilaku chip sebenarnya: register dimodelkan |
| **Perangkat nyata** | **tidak ada** oleh repo ini | — |

Yang dilaporkan berjalan di tablet (iPadOS 17: UFS, layar frame buffer, touch, tombol, GPU/Metal) adalah klaim upstream UniXNU-pipa, tidak diulang di sini.

CI (`ci.yml`) hijau di setiap commit cabang ini.

## Cara melanjutkan

```sh
git clone https://github.com/BxiiDN/macOS-Pad-6 && cd macOS-Pad-6 && git checkout board-migration-wip
git submodule update --init --depth 1 third_party/UniXNU
git -C third_party/UniXNU submodule update --init --depth 1
scripts/pipa-unixnu.sh check --adt          # butuh dtc; --xnu DIR untuk cek apply
```

Build kernel tidak bisa di Linux tanpa toolchain UniXNU (LLVM yang di-patch, cctools-port, root). Jalurnya adalah `.github/workflows/kernel-build.yml` di runner `macos-26`:

- push ke `board-migration-wip` dengan `[kernel-build]` di pesan commit: fetch, defconfig, compile + link (`--skip-prelink`), laporan;
- `[kernel-prelink]`: sama, ditambah `build prelink`, tata letak `__PRELINK_TEXT` (`prelink_layout.py`) dan laporan kernel collection serta catatan XnuPrelink (`prelink_record.py`);
- `[kernel-repro]`: build kedua dari nol di tempat yang sama, dibandingkan per section (`kernel_report.py --compare`);
- setiap build menjalankan `kernel_size_audit.py` (section, asal per link map, string per patch).
- `workflow_dispatch` baru bisa setelah workflow ada di `main`.

Log job dibaca lewat `gh api repos/BxiiDN/macOS-Pad-6/actions/jobs/<id>/logs` (unduhan artefak diblokir proxy sesi Claude). Laporan kernel ada di log langkah "Report on the kernel".

## Kendala yang ditemukan

- **G2 (UFS)**: resep storage arm64e UniXNU tidak meneruskan `NATIVE_UFS_SM8250`, sehingga driver pipa mencari `qcom,sm8550-ufshc`; lima sumber package storage tidak ada di pipa; root macOS di `userdata` menghapus Android (alternatif UniXNU mengubah partisi). Butuh perubahan UniXNU dan keputusan pemilik.
- **Display**: MDSS/DSI pipa tidak ada di mainline; panel hanya dari DT Android. Frame buffer boot dan backlight adalah jalur yang terdokumentasi.
- **Touch, fuel gauge, charger**: pengontrolnya tidak ada di DT mainline pipa; hanya dari DT Android.
- `A650GmuTests` hanya bisa dibangun untuk AArch64 (kit `AdrenoFirmware`); berjalan di runner `ubuntu-24.04-arm`.
- Lingkungan sesi Claude: unduhan artefak GitHub diblokir proxy (baca log lewat API); tidak ada `dtc` dari paket (dibangun dari sumber `scripts/dtc` Linux 4.16 secara lokal; CI memakai `device-tree-compiler`).
- Mengubah file di `devices/pipa` (termasuk `package/`) memindahkan tanggal build kernel (keputusan 6), jadi build kernel berikutnya punya hash baru walau `package/` tidak di-compile ke kernel macOS. Itu sesuai aturan yang sudah dicatat; pin bisa dipersempit bila perlu.

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py`; tanpa itu UniXNU memakai `UniXNU/ArmCpu` dan bukan cabang pipa (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig` (seperti UniXNU-sheng macOS); mode `prelinked` dari `macos.config` gagal link.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada (open terautentikasi tetap `EAUTH`), `native_exit_trace` no-op **strong** (versi weak menjadi import chained fixup yang ditolak XnuPrelink).
4. Kernel macOS pipa sengaja hanya jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). Akhir boot yang diharapkan: panic mount root.
5. Ukuran `__TEXT`: `-fmacro-prefix-map` (defconfig) dan `zzzzb-pipa-long-assert-text.patch` (teks `assert()` > 48 byte diganti catatan bersama; pemeriksaan, trap, file:line tetap). String dari patch hanya ±3 KB, jadi memangkas diagnostik patch tidak berguna untuk ukuran. Sisa ruang di celah `__PRELINK_TEXT`: 42.976 byte; bila kernel tumbuh, `prelink_layout.py` menunjukkan sisanya, dan `MACH_ASSERT_EXPR_MAX` bisa diturunkan lewat `CONFIG_XNU_EXTRA_CFLAGS` (`-DMACH_ASSERT_EXPR_MAX=40`).
6. `KERNEL_BUILD_DATE` dipin dari `SOURCE_DATE_EPOCH` atau waktu commit terakhir yang mengubah input kernel (`devices/pipa`, `profiles`, `kernel`, `third_party`, `.gitmodules`), lewat `pipa_unixnu.py`; itu satu-satunya sumber perbedaan antar-build. Butuh clone penuh (`fetch-depth: 0`); di clone dangkal skrip memberi peringatan. Jadi commit yang hanya mengubah dokumen, CI, atau alat menghasilkan kernel yang sama bit demi bit; perubahan di path input mengganti tanggal (dan hash), seperti seharusnya.
7. Pemeriksaan perangkat keras membaca konstanta **dari sumber** setiap kali (bukan salinan), dan membandingkan dengan DT mainline Linux pada commit yang dipin (`LINUX_COMMIT` di `scripts/pipa_hw.py`). Fakta yang tidak ada di mainline dilaporkan terpisah, bukan dianggap cocok. Node GPU feed dicek "berisi semua range mainline", node USB feed (dinonaktifkan, ukuran vendor) dicek alamat dasarnya saja.

## Langkah berikutnya, berurutan

1. ~~Prelink~~: berhasil dan reproducible (percobaan 9–12); catatan XnuPrelink tanpa target hilang atau stub.
2. Pasang `tools/isa/pacstrip` ke kernel collection hasil prelink di workflow, lalu gerbang `python3 -m tools.isa.audit KC --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`.
3. `build payload` (butuh `UNIXNU_UNIQUE_CHIP_ID` sebagai secret repo; board `unique_chip_id = "required"`) dan `bootimg`. Tidak di-commit, tidak diunggah.
4. Uji di tablet hanya oleh pemilik, dengan `fastboot boot` (tidak menulis apa pun). Target pertama: bar entry probe, lalu panic `Failed to mount root device`.
5. Celah terbuka: G2 (UFS arm64e SM8250), G3 (Adreno 650), G5 (display/input), G6 (memori >6 GiB). Rincian dan langkah per celah di `docs/board-migration.md#kebutuhan-driver-g2g6`. Urutan yang aman (tanpa menulis ke perangkat): (a) usulkan ke UniXNU makro UFS per SoC di resep arm64e; (b) porting sumber package storage dari UniXNU-sheng dan build-nya; (c) komponen katalog `Adreno650`; (d) driver GENI I2C + backlight memakai `BacklightBoard.h`, uji pertama baca-saja `DEVICE_ID`.
6. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
