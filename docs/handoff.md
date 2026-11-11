# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-11 (setelah percobaan build kernel ke-10). Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

## Target (tetap)

macOS Tahoe **26.5 (25F71)**, XNU **12377.121.6** (`ac9718fb1af6`), Xiaomi Pad 6 (**pipa**), Snapdragon 870 **SM8250**. macOS asli, bukan simulator/launcher/skin. Tanpa binary Apple di repo, tanpa flashing otomatis, tanpa klaim tanpa bukti.

## Keadaan sekarang

| Langkah | Keadaan | Bukti |
| --- | --- | --- |
| Audit Tahoe 26.x, profil `macos-26.5-25F71` | selesai | `docs/tahoe-26-report.md`, `docs/evidence/tahoe-26.5/` |
| Board pipa UniXNU format 2 (`devices/pipa`) | selesai, di-resolve, dicek CI | `docs/board-migration.md`, artefak CI `pipa-board-status` |
| Rantai patch | 121/121 apply ke xnu-12377.121.6 dalam urutan board | `scripts/check_patch_chain.py`, `pipa_unixnu.py check --xnu` |
| Compile + link kernel native (arm64e) | **berhasil**; `__TEXT` `0x188000`, 0 import | `docs/kernel-build.md` percobaan 2, 8, 9 |
| Build reproducible | **ya**: dua build dari nol identik bit demi bit (`ce13aea1…`) | percobaan 8, 9 |
| Prelink dengan kernelcache 26.5 | **berhasil**: `MH_FILESET` arm64e 135.036.928 byte (`840488d5…`), 0 import | percobaan 9, 10, run 42994058285 |
| `pacstrip` + gerbang ISA pada kernel collection | belum | |
| Payload, boot image | belum | |
| Boot di tablet | belum | |

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

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py`; tanpa itu UniXNU memakai `UniXNU/ArmCpu` dan bukan cabang pipa (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig` (seperti UniXNU-sheng macOS); mode `prelinked` dari `macos.config` gagal link.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada (open terautentikasi tetap `EAUTH`), `native_exit_trace` no-op **strong** (versi weak menjadi import chained fixup yang ditolak XnuPrelink).
4. Kernel macOS pipa sengaja hanya jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). Akhir boot yang diharapkan: panic mount root.
5. Ukuran `__TEXT`: `-fmacro-prefix-map` (defconfig) dan `zzzzb-pipa-long-assert-text.patch` (teks `assert()` > 48 byte diganti catatan bersama; pemeriksaan, trap, file:line tetap). String dari patch hanya ±3 KB, jadi memangkas diagnostik patch tidak berguna untuk ukuran. Sisa ruang di celah `__PRELINK_TEXT`: 42.976 byte; bila kernel tumbuh, `prelink_layout.py` menunjukkan sisanya, dan `MACH_ASSERT_EXPR_MAX` bisa diturunkan lewat `CONFIG_XNU_EXTRA_CFLAGS` (`-DMACH_ASSERT_EXPR_MAX=40`).
6. `KERNEL_BUILD_DATE` dipin dari `SOURCE_DATE_EPOCH` atau waktu commit HEAD (`pipa_unixnu.py`); itulah satu-satunya sumber perbedaan antar-build sebelumnya.

## Langkah berikutnya, berurutan

1. ~~Prelink~~: berhasil (percobaan 9). Periksa jumlah target yang tidak terpasang/di-stub di catatan XnuPrelink (percobaan 10, `prelink-record-summary.json`) sebelum menilai kesiapan boot.
2. Pasang `tools/isa/pacstrip` ke kernel collection hasil prelink di workflow, lalu gerbang `python3 -m tools.isa.audit KC --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`.
3. `build payload` (butuh `UNIXNU_UNIQUE_CHIP_ID` sebagai secret repo; board `unique_chip_id = "required"`) dan `bootimg`. Tidak di-commit, tidak diunggah.
4. Uji di tablet hanya oleh pemilik, dengan `fastboot boot` (tidak menulis apa pun). Target pertama: bar entry probe, lalu panic `Failed to mount root device`.
5. Celah terbuka: G2 (UFS arm64e SM8250), G3 (Adreno 650), G5 (display/input), G6 (memori >6 GiB). Rincian di `docs/board-migration.md`.
6. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
