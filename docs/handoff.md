# Handoff

Untuk sesi berikutnya. Baca ini dulu; jangan ulangi riset atau langkah yang sudah tercatat di sini.

Diperbarui: 2026-11-11. Cabang kerja: `board-migration-wip` (PR #1 ke `main`). `main` tidak diubah sejak `5b89722`.

## Target (tetap)

macOS Tahoe **26.5 (25F71)**, XNU **12377.121.6** (`ac9718fb1af6`), Xiaomi Pad 6 (**pipa**), Snapdragon 870 **SM8250**. macOS asli, bukan simulator/launcher/skin. Tanpa binary Apple di repo, tanpa flashing otomatis, tanpa klaim tanpa bukti.

## Keadaan sekarang

| Langkah | Keadaan | Bukti |
| --- | --- | --- |
| Audit Tahoe 26.x, profil `macos-26.5-25F71` | selesai | `docs/tahoe-26-report.md`, `docs/evidence/tahoe-26.5/` |
| Board pipa UniXNU format 2 (`devices/pipa`) | selesai, di-resolve, dicek CI | `docs/board-migration.md`, artefak CI `pipa-board-status` |
| Rantai patch | 120/120 apply ke xnu-12377.121.6 dalam urutan board | `scripts/check_patch_chain.py`, `pipa_unixnu.py check --xnu` |
| Compile + link kernel native (arm64e) | **berhasil** (percobaan 2) | `docs/kernel-build.md`, run 42980033161 |
| Prelink dengan kernelcache 26.5 | **gagal** (percobaan 3): `No room for 0x19c000 bytes in __PRELINK_TEXT`; percobaan 4 mengukur tata letak | `docs/kernel-build.md` |
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
- `[kernel-prelink]`: sama, ditambah `build prelink` dan laporan kernel collection;
- `workflow_dispatch` baru bisa setelah workflow ada di `main`.

Log job dibaca lewat `gh api repos/BxiiDN/macOS-Pad-6/actions/jobs/<id>/logs` (unduhan artefak diblokir proxy sesi Claude). Laporan kernel ada di log langkah "Report on the kernel".

## Keputusan yang sudah diambil (jangan dibuka ulang tanpa alasan baru)

1. Source `feeds.toml` dioper ke UniXNU sebagai `--local-module` oleh `scripts/pipa_unixnu.py`; tanpa itu UniXNU memakai `UniXNU/ArmCpu` dan bukan cabang pipa (G1).
2. `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"` di `pipa_macos26_defconfig` (seperti UniXNU-sheng macOS); mode `prelinked` dari `macos.config` gagal link.
3. `zzzz-pipa-macos-absent-features.patch`: owner root tidak ada (open terautentikasi tetap `EAUTH`), `native_exit_trace` weak no-op.
4. Kernel macOS pipa sengaja hanya jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). Akhir boot yang diharapkan: panic mount root.

## Langkah berikutnya, berurutan

1. Baca keluaran `scripts/prelink_layout.py` dari percobaan 4 (log langkah "Prelink layout"): celah terbesar di `__PRELINK_TEXT` dan selisihnya terhadap `__TEXT` native 0x19c000. Pilih salah satu perbaikan di `docs/kernel-build.md` (percobaan 3) berdasarkan angka itu, lalu push dengan `[kernel-prelink]`.
2. Pasang `tools/isa/pacstrip` ke kernel collection hasil prelink di workflow, lalu gerbang `python3 -m tools.isa.audit KC --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`.
3. `build payload` (butuh `UNIXNU_UNIQUE_CHIP_ID` sebagai secret repo; board `unique_chip_id = "required"`) dan `bootimg`. Tidak di-commit, tidak diunggah.
4. Uji di tablet hanya oleh pemilik, dengan `fastboot boot` (tidak menulis apa pun). Target pertama: bar entry probe, lalu panic `Failed to mount root device`.
5. Celah terbuka: G2 (UFS arm64e SM8250), G3 (Adreno 650), G5 (display/input), G6 (memori >6 GiB). Rincian di `docs/board-migration.md`.
6. Gabungkan PR #1 ke `main` hanya atas keputusan pemilik repo.
