# Build kernel macOS Tahoe 26.5 untuk pipa

Status: **kernel native XNU untuk pipa (macOS Tahoe 26.5, xnu-12377.121.6, arm64e) berhasil di-compile dan di-link** di runner macOS (percobaan 2, 2026-11-11). Belum di-prelink dengan kext kernelcache 26.5, belum dilewatkan `pacstrip`, belum di-boot. Klaim di halaman ini hanya yang ada buktinya di log run yang ditautkan.

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
| Kompilasi XNU arm64e dengan rantai board | **berhasil** | percobaan 1 (119 patch), percobaan 2 (120 patch) |
| Arsip: corecrypto ×2, ArmDTPlatform, ArmCpu cabang pipa, libpthread | **berhasil dibangun** terhadap header xnu-12377 | percobaan 1 |
| Linking kernel native | **berhasil** di percobaan 2 (percobaan 1 gagal pada 5 simbol) | lihat riwayat |
| Lapisan ARMv8.2 ter-link | **ya**: `_fge_xnu_init`, `_fge_xnu_handle`, `_fge_emulate` ada di tabel simbol | percobaan 2 |
| Prelink dengan kernelcache 26.5 | belum (percobaan 3: `[kernel-prelink]`) | |
| `pacstrip` + gerbang ISA pada kernel collection | belum | |
| Boot di tablet | belum | |

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

### Percobaan 2 — 2026-11-11, commit `699cbbe`, run [42980033161](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42980033161): **compile dan link berhasil**

- Rantai 120 patch, `CONFIG_XNU_CRYPTO_BOOTSTRAP="source"`. Runner, Xcode, SDK sama dengan percobaan 1.
- Pass bootstrap gagal link seperti dirancang (arsip corecrypto belum ada; `_source_corecrypto14_bootstrap` dari `prng_random.o`). Kelima arsip lalu dibangun, dan pass penuh me-link kernel tanpa error. UniXNU menulis `kernel/kernel.macho` (mode `native-only`, `--skip-prelink`).
- Kernel (`scripts/kernel_report.py`, kernel tetap di runner dan dihapus di akhir job):

| | |
| --- | --- |
| File | `tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf` |
| Ukuran | 25.135.384 byte |
| SHA-256 | `8f7257419dfbfe0e998862a15edd5d56f669b26e588a13ca872efd43512c9688` |
| Mach-O | `MH_EXECUTE`, CPU arm64, subtype **arm64e** (caps `0xc0`), 27 load command |
| Segmen | `__TEXT` @ `0xfffffff007004000`, `__TEXT_EXEC` 10,0 MiB, `__DATA`, `__BOOTDATA`, segmen `__PRELINK_*` kosong (belum di-prelink), `__LINKEDIT` |
| Simbol FGE | `_fge_xnu_init`, `_fge_xnu_handle`, `_fge_emulate`: ada |
| Sensus ISA (`tools/isa/audit`, statis) | 2.611.725 word kode; 57.243 butuh PAuth (`pac-branch` 33.119, `pac-dp1` 24.113, `pacga` 7, `pac-keyreg` 4); semuanya di kelas yang ditangani FGE, **0 di luar FGE** |

Arti angka sensus: kernel arm64e ini masih berisi instruksi PAC non-hint yang akan trap di Cortex-A77/A55. FGE mengemulasikannya (null PAC), tetapi setiap trap mahal; langkah yang direncanakan adalah `tools/isa/pacstrip` pada kernel collection hasil prelink, lalu gerbang `audit --fail-on pac-dp1,pac-branch,pac-eret,pac-keyreg`. Sensus ini statis (hitungan word di section kode), bukan bukti eksekusi.

Yang **tidak** dibuktikan percobaan 2: kernel belum digabung dengan kext Tahoe 26.5 (prelink), belum di-`pacstrip`, belum dimasukkan ke payload, dan belum dijalankan di perangkat atau emulator.
