# Build kernel macOS Tahoe 26.5 untuk pipa

Status: **belum ada kernel yang berhasil dibangun.** Halaman ini mencatat apa yang dimaksud "kernel step", apa yang sudah siap, dan hasil setiap percobaan build. Klaim "kernel berhasil dibuat" hanya ditulis bila kompilasi dan linking XNU selesai dan biner Mach-O-nya diperiksa.

## Apa yang dibangun

`unixnu build kernel` untuk `devices/pipa` dengan profil `macos-26.5-25F71`:

1. Sumber xnu-12377.121.6 (`ac9718fb1af6`) ditambah 120 patch, urut sesuai `board.toml` (arch arm64e UniXNU → SoC SM8250 arm64e → OS macOS 26.5 → device pipa: AMP, null-PAC, FGE, default fitur yang belum ada).
2. Konfigurasi: `configs/common.config` (arm64e) + `sm8250.config` + `macos.config` + `pipa_macos26_defconfig`.
3. Arsip yang di-link ke kernel: corecrypto sumber (dua kali, kedua dengan namespace), ArmDTPlatform, ArmCpu cabang pipa, libpthread kernel.
4. Hasil: kernel native `mach.development.bcm2837` (Mach-O `MH_EXECUTE`, arm64e), lalu (tanpa `--skip-prelink`) prelink dengan kext dari kernelcache J274AP 26.5 asli.

Kernel ini sengaja hanya jalur generik: CPU, interrupt, timer, platform expert. Tanpa storage, display, input, dan GPU (celah G2, G3, G5 di [board-migration.md](board-migration.md)), jadi akhir yang diharapkan saat boot adalah panic `Failed to mount root device`, seperti kernel pertama format 1.

## Kesiapan (diperiksa di setiap push oleh CI)

| Syarat | Status | Bukti |
| --- | --- | --- |
| Board format 2 di-resolve UniXNU untuk 26.5 dan override iPadOS | siap | `scripts/pipa-unixnu.sh check` |
| 120/120 patch apply ke xnu-12377.121.6 dalam urutan board | siap | `check --xnu`, `check_patch_chain.py` |
| Patch ARMv8.2 (null-PAC, FGE) sesuai sumber `kernel/` | siap | `gen_tahoe_patches.py --check` |
| Device tree → ADT dengan nilai board | siap | `check --adt` |
| ArmCpu cabang pipa dari pin `feeds.toml` | siap (resolusi) | G1 di board-migration.md |
| Toolchain kernel step (macos-26, Xcode 26.6, SDK iphoneos 26.5) | siap | percobaan 1 |
| Kompilasi XNU arm64e dengan 119 patch percobaan 1 | **berhasil** (semua objek; link gagal) | percobaan 1 |
| Arsip: corecrypto ×2, ArmDTPlatform, ArmCpu cabang pipa, libpthread | **berhasil dibangun** terhadap header xnu-12377 | percobaan 1 |
| Linking kernel native | **gagal** di percobaan 1 (5 simbol); perbaikan di percobaan 2 | lihat riwayat |
| Prelink dengan kernelcache 26.5 | belum (butuh kernelcache dari IPSW resmi, tidak disimpan di repo) | |

## Toolchain

- **macOS**: Xcode dengan SDK iphoneos, plus `cmake`, `ninja`, `unifdef` (Homebrew). UniXNU dikembangkan di sini.
- **Linux**: `sudo third_party/UniXNU/scripts/linux/setup-toolchain.py` membangun clang dengan `__builtin_xnu_type_*` (patch LLVM), cctools-port `1030.6.3-ld64-956.6`, mig, iig-port, lzfse. Butuh root, paket distro, dan build LLVM penuh.

## Menjalankan

```sh
git submodule update --init --depth 1 third_party/UniXNU
git clone https://github.com/UniXNU/UniXNU ../UniXNU-build && git -C ../UniXNU-build checkout 3fd6a3cf0e6f2eba5d3de3a4d1912e2db23a0fc4
git -C ../UniXNU-build submodule update --init --depth 1
scripts/pipa_unixnu.py prepare --unixnu ../UniXNU-build --in-place
scripts/pipa-unixnu.sh fetch
scripts/pipa-unixnu.sh defconfig pipa_macos26_defconfig
scripts/pipa-unixnu.sh build kernel --skip-prelink      # kompilasi + link kernel native saja
```

Di GitHub Actions: `.github/workflows/kernel-build.yml` (runner `macos-26`, Xcode 26.6) menjalankan langkah yang sama, lalu `scripts/kernel_report.py` (ukuran, SHA-256, header Mach-O, simbol FGE, sensus ISA). Workflow berjalan lewat `workflow_dispatch` atau push ke `board-migration-wip` yang pesan commit-nya memuat `[kernel-build]`. Yang diunggah hanya log teks dan laporan JSON; kernel dan input Apple dihapus di akhir job.

`--in-place` memasang profil 26.5 ke clone UniXNU tersendiri, karena `unixnu fetch` memperbarui submodul checkout tempat ia berjalan. Tidak ada langkah di atas yang menyentuh tablet.

## Riwayat percobaan

### Percobaan 1 — 2026-11-11, commit `7f9368b`, run [42978533038](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42978533038): link gagal

- Runner `macos-26`, Xcode 26.6, SDK iphoneos 26.5. Board check lolos di runner (sama dengan CI).
- `unixnu fetch` dan `defconfig pipa_macos26_defconfig` berhasil. 119 patch apply di pohon build.
- Pass bootstrap: seluruh XNU ter-compile; link gagal (diharapkan pada pass ini, ia hanya meninggalkan compile record).
- Arsip: `build-corecrypto-14.py` (dua kali), `component-ArmDTPlatform`, `component-ArmCpu` (cabang pipa `a9c4585`, `-Werror`), `build-libpthread-kernel.py` semuanya selesai.
- Pass penuh: kompilasi selesai, **link `mach.development.bcm2837.unstripped.noctf` gagal**, `Undefined symbols for architecture arm64e.kernel`:
  - `_source_corecrypto14_original`, `_source_corecrypto14_start_once` (dari `OSKext.cpo`): `macos.config` memilih `XNU_CRYPTO_BOOTSTRAP="prelinked"`, yang meng-compile `prng_random.c` dengan `-UXNU_SOURCE_CORECRYPTO14`, sedangkan hunk OSKext di `native-security-init.patch` (seri arm64e) tetap memanggil keduanya. UniXNU-sheng (macOS, satu-satunya kernel macOS UniXNU yang sudah jalan) memakai `"source"`.
  - `_native_owner_root_accepted`, `_native_owner_root_mount_device` (dari `vfs_syscalls.o`): `macos-owner-root-authenticated-open.patch` (seri OS) memakai global audit owner-root yang hanya didefinisikan dengan `XNU_OWNER_ROOT_AUDIT` (butuh driver storage sumber; pipa belum punya).
  - `_native_exit_trace` (dari `kern_exit.o`): hook board dari `macos-droidvm-k27-parity.patch`; UniXNU-sheng mendefinisikannya di package board.
- Tidak ada kernel yang ter-link. Laporan kernel: tidak ada biner.

Perbaikan (commit berikutnya): `pipa_macos26_defconfig` memilih `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"`; patch device baru `zzzz-pipa-macos-absent-features.patch` memberi default "fitur tidak ada": tidak ada root owner yang diterima (open terautentikasi tetap `EAUTH`, seperti XNU asli) dan `native_exit_trace` weak no-op. Rantai menjadi 120/120.
