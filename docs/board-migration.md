# Migrasi board pipa ke UniXNU format 2

Status: **konfigurasi selesai dan di-resolve oleh UniXNU; belum ada kernel yang dibangun dari board ini.** Yang dibuktikan dan yang belum ada di bawah, dengan perintah untuk mengulanginya.

| | |
| --- | --- |
| Sumber | `xVanTuring/UniXNU-pipa` `cdb3d62771e3` (format 1), disimpan apa adanya di [evidence/board-migration/](evidence/board-migration/) |
| Hasil | [`devices/pipa/`](../devices/pipa/) (format 2, `schema_version = 2`) |
| UniXNU | `3fd6a3cf0e6f` (submodul `third_party/UniXNU`) |
| SoC | `FFT-infra/UniXNU-sm8250-common` `a67a9bf33e44` (`devices/pipa/feeds.toml`) |
| Profil OS default | `macos-26.5-25F71` (macOS Tahoe 26.5, xnu-12377.121.6), dari `profiles/macos-26.5/unixnu` |
| Profil override | `ipados-17.7.11-21H461` (port iPadOS 17 UniXNU-pipa, nilai format 1 dipertahankan) |
| Panduan | UniXNU `docs/porting/migration.md` |

## Cara memeriksa

```sh
git submodule update --init --depth 1 third_party/UniXNU
git -C third_party/UniXNU submodule update --init --depth 1   # driver dan kit UniXNU
scripts/pipa-unixnu.sh check --adt --xnu /path/ke/xnu          # --adt butuh dtc; --xnu: checkout xnu ac9718fb1af6
scripts/pipa-unixnu.sh status --os macos-26.5-25F71            # tampilan unixnu status biasa
```

`check` menyalin UniXNU ke `build/pipa-unixnu/UniXNU`, memasang profil 26.5, meng-clone setiap `[[source]]` di `feeds.toml` pada commit pin-nya, lalu menjalankan `unixnu status --json` untuk kedua profil. CI (`.github/workflows/ci.yml`, job `test`) menjalankan perintah yang sama di setiap push dan menyimpan hasilnya sebagai artefak `pipa-board-status`.

Yang diperiksa dan harus benar:

1. Profil default `macos-26.5-25F71`: IPSW 26.5 (25F71), pin kernelcache sama dengan `profile.toml`, defconfig `pipa_macos26_defconfig`, nol patch Darwin 26.
2. Urutan patch yang dipakai board (**120 patch**) sama persis dengan rantai `scripts/check_patch_chain.py --profile tahoe-26.5`, dan dengan `--xnu` ke-120 patch itu apply ke xnu-12377.121.6.
3. Override `ipados-17.7.11-21H461` masih ter-resolve (IPSW 17.7.11, 61 patch, 17 komponen).
4. SoC `sm8250` dan setiap komponen terpilih yang dipin `feeds.toml` benar-benar berasal dari pin itu (lihat G1).
5. Dengan `--adt`: `dts/pipa.dts` dikompilasi `dtc` dengan `sm8250.dtsi` dari feed SoC, lalu generator ADT UniXNU (`unixnu.devicetree.generate`, jalur yang sama dengan `build payload`) menghasilkan ADT yang nilainya cocok dengan `board.toml`: dram-base `0x80000000`, dram-size `0x980000000`, darwinboot-memory-size `0x170000000`, chip-id `0x8103`, `kernel-ctrr-to-be-enabled = 0`, `vmm-present = 1`, `sleep-disabled = 1`, delapan CPU (MPIDR `0x000..0x700`, empat Cortex-A55 klaster E lalu empat Cortex-A77 klaster P, timebase 19,2 MHz), `intc` = `arm,gic-v3`.

## Pemetaan kunci format 1 → format 2

| Format 1 (`board-before.toml`) | Format 2 (`devices/pipa`) | Catatan |
| --- | --- | --- |
| `[board]` name, soc, description, kit | `[board]` sama, ditambah `soc_source = "sm8250"`, `os_profile = "macos-26.5-25F71"` | |
| `[ipsw]` (iPad7,1 17.7.11) | dari profil OS | Format 2 mengambil IPSW dari profil; 26.5 → J274AP 25F71 |
| `[userdata]` first/last LBA, lba_bytes | `[userdata]` sama | `windows` sekarang milik profil OS |
| `[kernel] defconfig = "pipa_defconfig"` | `pipa_macos26_defconfig` (default), `pipa_defconfig` di override iPadOS | `[package.defconfig]` memetakan profil → defconfig |
| `[kernel] archives` (17 entri) | `[kernel] archives` macOS (5 entri) dan override iPadOS (daftar format 1 dengan nama komponen katalog) | lihat G2, G3, G5 |
| `[kernel.prelink]` di level board | dihapus dari board; datang dari profil OS | Temuan 3 di [audit.md](audit.md): prelink di level board akan menimpa milik profil macOS |
| — | `[kernel] config_fragments`, `patch_series` | Lapisan arch/SoC/OS/device eksplisit |
| `package/xnu-patches/native-smp-type-clusters.patch` | seri SoC `sm8250` (iPadOS); `patches/xnu-12377/zzyf-pipa-amp.patch` (macOS) | API scheduler xnu-12377 berbeda |
| `profiles/macos-26.5/patches` (repo ini) | `devices/pipa/patches/xnu-12377/{null-pac,fge}-armv82.patch` | Dihasilkan `scripts/gen_tahoe_patches.py`, dicek CI |
| `[firmware]`, `[firmware.defines]` | sama | Tidak berubah |
| `[payload]` | sama; `size_mib` 200, `title`, `kernel_args` macOS | Argumen iPadOS di override |
| `[payload.adt] tool = make-pipa-adt.py`, `cpu_regs`, `ipad_identity` | `[device_tree] source = device:dts/pipa.dts` + `include_dirs = soc:dts`; `[payload.adt]` hanya chip_id, owned_memory_size, packed_data_ramdisk, unique_chip_id | Inti CPU, GIC, timer sekarang dari DTS; `make-pipa-adt.py` tetap disalin untuk referensi |
| `root_match_volume_uuid` | hanya di override iPadOS | UUID volume OS iPadOS |
| driver sebagai submodul repo UniXNU-pipa | `[[source]]` di `feeds.toml`, pin sama | lihat G1 |
| — | `[adt.chosen.u32]`, `[adt.defaults.u32]` | `kernel-ctrr-to-be-enabled`, `sleep-disabled`, `vmm-present` (nilai macOS UniXNU-sheng) |

## Celah (gap) yang diketahui

| ID | Celah | Status |
| --- | --- | --- |
| G1 | Urutan resolusi modul UniXNU memilih checkout UniXNU sendiri (langkah 6) sebelum git source di `feeds.toml` (langkah 7). Dengan submodul UniXNU terisi, board akan memakai `UniXNU/ArmCpu` dan bukan cabang pipa `xVanTuring/ArmCpu@a9c4585` (registrasi klaster, IPI lewat SPI). | **Ditangani**: `scripts/pipa_unixnu.py` mengoper setiap source sebagai `--local-module` (langkah 1) dari clone pada pin `feeds.toml`; `check` gagal bila revisi yang ter-resolve bukan pin. |
| G2 | `ShengUfs` di bawah arm64e dibangun oleh `build-sheng-source-storage.py` (storage sumber SM8550). Resep UniXNU 3fd6a3c tidak punya saklar `NATIVE_UFS_SM8250` seperti format 1. | Terbuka. Kernel macOS tidak memilih storage; berhenti di mount root. |
| G3 | Adreno650 (`xVanTuring/Adreno650 01db67e0`) dan AdrenoMetal fork bukan komponen katalog; AdrenoMetal katalog bergantung Adreno740 dan Sm8550Platform. | Terbuka. Tidak ada GPU di kernel macOS. |
| G4 | Override iPadOS butuh input di luar Git (audit ABI storage dan kunci owner dari UniXNU-tb128fu, firmware GPU/touch dari tablet). | Terbuka. Override hanya di-resolve, tidak di-build oleh repo ini. |
| G5 | Belum ada driver arm64e untuk storage, display, input, dan GPU SM8250 di bawah profil macOS. | Terbuka. Kernel macOS = jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). |
| G6 | XNU memakai satu rentang memori: 5,75 GiB dari bank kedua (`owned_memory_size`). Seluruh 16 GB butuh beberapa rentang di pmap/VM. | Terbuka, sama seperti format 1. |
| G7 | Revisi submodul UniXNU 3fd6a3c tidak sama dengan revisi katalog `components.toml` (mis. ArmDTPlatform: submodul `e8bd8d5`, katalog `417ff95`). Build memakai submodul. | Dicatat; `check` menulis keduanya ke JSON (`revision`, `catalog_pin`). |

## Yang tidak dibuktikan

- Tidak ada kernel, payload, atau boot image yang dibangun dari board format 2 ini. Kesiapan build kernel: [kernel-build.md](kernel-build.md).
- `ArmCpu` cabang pipa ditulis untuk kernel arm64 iPadOS 17; kompilasinya terhadap header xnu-12377 (arm64e) belum dijalankan.
- Tidak ada yang dijalankan di tablet.
