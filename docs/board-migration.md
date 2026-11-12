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

`check` menyalin UniXNU ke `build/pipa-unixnu/UniXNU`, menerapkan `patches/unixnu/series` ke salinan itu (lihat G2), memasang profil 26.5, meng-clone setiap `[[source]]` di `feeds.toml` pada commit pin-nya, lalu menjalankan `unixnu status --json` untuk kedua profil. CI (`.github/workflows/ci.yml`, job `test`) menjalankan perintah yang sama di setiap push dan menyimpan hasilnya sebagai artefak `pipa-board-status`.

Yang diperiksa dan harus benar:

1. Profil default `macos-26.5-25F71`: IPSW 26.5 (25F71), pin kernelcache sama dengan `profile.toml`, defconfig `pipa_macos26_defconfig`, nol patch Darwin 26.
2. Urutan patch yang dipakai board (**121 patch**) sama persis dengan rantai `scripts/check_patch_chain.py --profile tahoe-26.5`, dan dengan `--xnu` ke-121 patch itu apply ke xnu-12377.121.6.
3. Override `ipados-17.7.11-21H461` masih ter-resolve (IPSW 17.7.11, 61 patch, 17 komponen).
4. SoC `sm8250` dan setiap komponen terpilih yang dipin `feeds.toml` benar-benar berasal dari pin itu (lihat G1).
5. Dengan `--adt`: `dts/pipa.dts` dikompilasi `dtc` dengan `sm8250.dtsi` dari feed SoC, lalu generator ADT UniXNU (`unixnu.devicetree.generate`, jalur yang sama dengan `build payload`) menghasilkan ADT yang nilainya cocok dengan `board.toml`: dram-base `0x80000000`, dram-size `0x980000000`, darwinboot-memory-size `0x180000000`, tabel `darwinboot-memory-excluded` 64 slot (G6), chip-id `0x8103`, `kernel-ctrr-to-be-enabled = 0`, `vmm-present = 1`, `sleep-disabled = 1`, delapan CPU (MPIDR `0x000..0x700`, empat Cortex-A55 klaster E lalu empat Cortex-A77 klaster P, timebase 19,2 MHz), `intc` = `arm,gic-v3`. Juga: string compatible yang dicari `probe()` PipaUfs, setelah blok `#if` `NativeUfs.cpp` diproses preprocessor C dengan define dari `[board] soc`, harus = compatible host UFS yang aktif di DTB (`qcom,sm8250-ufshc`).
6. Override iPadOS tidak membawa `owned_memory_excluded_ranges` (kernel iPadOS 17 tidak membacanya), dan semua patch `patches/unixnu` ada di salinan UniXNU.

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
| `[payload.adt] tool = make-pipa-adt.py`, `cpu_regs`, `ipad_identity` | `[device_tree] source = device:dts/pipa.dts` + `include_dirs = soc:dts`; `[payload.adt]` hanya chip_id, owned_memory_size, owned_memory_excluded_ranges (macOS), packed_data_ramdisk, unique_chip_id | Inti CPU, GIC, timer sekarang dari DTS; `make-pipa-adt.py` tetap disalin untuk referensi |
| `root_match_volume_uuid` | hanya di override iPadOS | UUID volume OS iPadOS |
| driver sebagai submodul repo UniXNU-pipa | `[[source]]` di `feeds.toml`, pin sama | lihat G1 |
| — | `[adt.chosen.u32]`, `[adt.defaults.u32]` | `kernel-ctrr-to-be-enabled`, `sleep-disabled`, `vmm-present` (nilai macOS UniXNU-sheng) |

## Celah (gap) yang diketahui

| ID | Celah | Status |
| --- | --- | --- |
| G1 | Urutan resolusi modul UniXNU memilih checkout UniXNU sendiri (langkah 6) sebelum git source di `feeds.toml` (langkah 7). Dengan submodul UniXNU terisi, board akan memakai `UniXNU/ArmCpu` dan bukan cabang pipa `xVanTuring/ArmCpu@a9c4585` (registrasi klaster, IPI lewat SPI). | **Ditangani**: `scripts/pipa_unixnu.py` mengoper setiap source sebagai `--local-module` (langkah 1) dari clone pada pin `feeds.toml`; `check` gagal bila revisi yang ter-resolve bukan pin. |
| G2 | `ShengUfs` di bawah arm64e dibangun oleh `build-sheng-source-storage.py` (storage sumber SM8550). Resep UniXNU 3fd6a3c tidak punya saklar `NATIVE_UFS_SM8250` seperti format 1. | Penghalang 1 **ditangani** (`patches/unixnu/0001`); penghalang 2 **ditangani** (lima sumber package pipa, baca-saja; `0003` tanpa root, `0004` probe-only; arsip **di-link dan ter-prelink** dengan `pipa_macos26_ufs_defconfig`, [kernel-integration.md](kernel-integration.md)); penghalang 3 (root) sengaja tidak dikerjakan: `[storage] root = "none"`. Rincian di [Kebutuhan driver](#kebutuhan-driver-g2g6). |
| G3 | Adreno650 (`xVanTuring/Adreno650 01db67e0`) dan AdrenoMetal fork bukan komponen katalog; AdrenoMetal katalog bergantung Adreno740 dan Sm8550Platform. | `Adreno650` **jadi komponen katalog** (`patches/unixnu/0002`) dan dipilih override iPadOS lewat `feeds.toml`; `ShengGmuSource.h` A650 dihasilkan (`scripts/gen_pipa_gmu.py`); kegagalan `write64` ditelusuri, 3 patch fork (0 known-fail setelah patch); **ter-compile, ter-link dan ter-prelink** ke kernel macOS 26.5 lewat `pipa_macos26_gpu_defconfig` (sesi 9: simbol hand-off dan ekspor dari `libPipaGpu.a`); tidak ada pemanggil, GPU tidak diklaim. |
| G4 | Override iPadOS butuh input di luar Git (audit ABI storage dan kunci owner dari UniXNU-tb128fu, firmware GPU/touch dari tablet). | Terbuka. Override hanya di-resolve, tidak di-build oleh repo ini. |
| G5 | Belum ada driver arm64e untuk storage, display, input, dan GPU SM8250 di bawah profil macOS. | Terbuka. Kernel macOS = jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). |
| G6 | XNU memakai satu span memori. macOS: 6 GiB dengan tabel rentang terlarang 64 slot (`window-memory-excluded-ranges.patch`); iPadOS: 5,75 GiB satu run. Seluruh 16 GB butuh beberapa span di pmap/VM. | Tabel **dipasang** untuk macOS; loader (`MemoryWindow.h`) dan sisi kernel (`arm_vm_excluded_init`, dimodelkan) diuji pada model peta; 6 GiB = batas kolam bootstrap 16 halaman di setiap base dan slide (dihitung). Lebih dari 6 GiB terbuka. |
| G7 | Revisi submodul UniXNU 3fd6a3c tidak sama dengan revisi katalog `components.toml` (mis. ArmDTPlatform: submodul `e8bd8d5`, katalog `417ff95`). Build memakai submodul. | Dicatat; `check` menulis keduanya ke JSON (`revision`, `catalog_pin`). |

## Kebutuhan driver G2–G6

Dari pembacaan resep UniXNU 3fd6a3c, fork driver pipa yang dipin `feeds.toml`, dan DT mainline (`docs/hardware-pipa.md`). Label sumber: ML = DT mainline, AN = dibaca dari tablet di Android oleh upstream, UP = dilaporkan upstream jalan di iPadOS, RP = diperiksa repo ini (statis).

### G2 — storage UFS arm64e untuk SM8250

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Host UFS, PHY, regulator, stream SMMU | `0x1d84000` (SPI 265), PHY `0x1d87000`, VCC L17A / VCCQ L6A / VCCQ2 S4A, stream `0xe0`, `0x4e0` | ML, RP (alamat = feed) |
| Driver | `xVanTuring/PipaUfs` `5c64c01` (`ShengUfs` di `feeds.toml`); jalan di iPadOS dari root UFS | UP |
| Penghalang 1 | Di bawah arm64e, `build-arm-driver.py ShengUfs` diteruskan ke `build-sheng-source-storage.py`, yang tidak mendefinisikan `NATIVE_UFS_SM8250` dan tidak punya hook flag. Di `NativeUfs.cpp` pipa, makro itu memilih string compatible `probe()` (dan tata letak GCC/UFS/SMMU di `GccUfs.h`): tanpa makro, driver mencari `qcom,sm8550-ufshc` dan tidak akan cocok dengan node `qcom,sm8250-ufshc` pipa | RP (baca sumber) |
| Migrasi UniXNU (penghalang 1) | **`patches/unixnu/0001-ufs-recipes-board-soc.patch`**: langkah kernel mengekspor `UNIXNU_SOC` dari `[board] soc`; kedua resep UFS (driver arm64 dan storage sumber arm64e) menambah define dari `scripts/ufs_soc.py` (SM8550: tidak ada, sheng tidak berubah; SM8250/SM6225: `-DNATIVE_UFS_<SoC>=1`; SoC lain: ditolak, bukan dibangun diam-diam sebagai SM8550). `pipa_unixnu.py` menerapkannya ke salinan UniXNU (idempoten); patch yang sama adalah usulan upstream. `check --adt` memproses blok `probe()` PipaUfs `5c64c01` dengan define itu: `qcom,sm8250-ufshc` = DTB (tanpa define: `qcom,sm8550-ufshc`) | RP (host: `tests/test_unixnu_patches.py`, CI `check --adt`); **belum di-build** di runner macOS |
| Penghalang 2 | Resep itu juga mengompilasi sumber device `SourceStorage.cpp`, `SourceRootPolicies.cpp`, `SourceRootBinding.cpp`, `BootLog.c`, `BootReset.c`; package pipa tidak punya satu pun (UniXNU-sheng punya) | RP |
| Penghalang 3 | Kebijakan owner yang ditandatangani (`scripts/policies/*25F71`: `trusted-key.bin`, `manifest.bin` untuk OS/SystemOS) dan image root macOS 26.5 di `userdata`. Menulis image itu **menghapus data Android**; alternatif UniXNU (`dual-system-partition.md`) mengubah tabel partisi. Keduanya di luar batasan proyek saat ini dan butuh keputusan pemilik | RP (baca dokumen) |
| Sumber package (sesi 7) | **`SourceStorage.cpp`** (memulai PipaUfs lewat antarmuka IOStorageFamily publik, baca-saja; tanpa disk Data, log UFS, benchmark, restart), **`SourceRootPolicies.cpp`** (tanpa kebijakan), **`SourceRootBinding.cpp`** (tidak ada root UFS yang diotorisasi), **`BootLog.c`** (tanpa penulis), **`BootReset.c`** (menolak; tanpa tulis PMIC/alasan reboot). `PipaStorageGuard.h` menolak setiap mode yang menulis `userdata` atau me-mount root darinya. `patches/unixnu/0003`: langkah kernel mengekspor `UNIXNU_SOURCE_STORAGE_ROOT=none` dan `UNIXNU_KIT`; resep tidak lagi butuh direktori kebijakan dan menemukan package di `kits/<kit>`. Kompatibilitas: seri `0001`–`0003` dinilai utuh (`series_present`), diterapkan idempoten | RP (host: `PipaStorageGuardTests.c`, `tests/test_unixnu_patches.py` sampai langkah header) |
| Build validation | `kernel-build.yml` `[storage-build]` → `scripts/pipa_storage_build.py` di runner macOS: clone IOStorageFamily pada commit pin resep, link input resep yang tidak dipilih profil macOS (PipaUfs dari pin `feeds.toml`, RamBlock/VirtioMmioBlock/VerifiedRoot dari UniXNU), jalankan resep dengan env board, periksa simbol, saklar SoC dari command line, bundle kebijakan kosong. **Berhasil** (run 43132343953): `libShengSourceStorage.a` 1.511.112 byte, tidak di-link. Butuh `patches/shengufs/0001` (antarmuka VM xnu-12377) dan `0002` (`native_ufs_source_create`), keduanya seperti pin katalog ShengUfs `99d8bcd` | **Build** (runner macOS); [kernel-build.md](kernel-build.md) percobaan 13 |
| Langkah berikut | Baca hasil `[storage-build]`; kirim `0001`/`0003` ke UniXNU; mode probe baca-saja (`native-ufs-probe=2`) sebagai uji pertama yang tidak menulis, hanya oleh pemilik | — |

### G3 — GPU Adreno 650

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Alamat, interrupt, stream SMMU, region zap, OPP | `GpuProbe.cpp`, `GpuPowerBoard.h` dan node GPU feed SoC = mainline (18 fakta) | RP |
| Logika daya dan GMU | `GpuPowerBoardTests` (host), `A650GmuTests` (CI arm64, register dimodelkan) | RP |
| Di tablet | GMU cold start, GX, zap, ring, Metal lewat Turnip di iPadOS | UP |
| Penghalang | `Adreno650` / `AdrenoMetal` fork pipa bukan komponen katalog; `AdrenoMetal` katalog bergantung Adreno740 + Sm8550Platform; untuk macOS perlu bundle Metal target macOS dan publikasi akselerator yang dicocokkan WindowServer | RP |
| Host test fork | **`scripts/test_adreno650.py`**: clone `xVanTuring/Adreno650 01db67e0` dan `ArmSmmu4K` pada pin `feeds.toml`, kompilasi sumber fork terhadap double IOKit-nya sendiri (`tests/XnuMemoryFixture.h`) + kit `AdrenoPM4`, jalankan semua `tests/test_*.cpp`. x86: 9 lulus (board, cpinit, gpu, irq, pwrup, ring, sha256, timer, vm_alias), 12 dilewati dengan alasan tertulis (sumber khusus AArch64: `NativeAdrenoMemory`, `NativeAdrenoSubmit`, `ArmSmmu4KMmio`; header `ShengGmu.h` yang dihasilkan per board). Di arm64 (CI): 14 lulus, 5 dilewati (sumber yang butuh `kern/cpu_data.h` atau `ShengGmu.h`), dan **2 gagal** — `test_gmumap` dan `test_vm` berhenti di `write64 … CHECK(0)`: peer register SMMU test itu melarang tulis 64-bit, sedangkan kode yang diuji bersama ArmSmmu4K pada pin `feeds.toml` (`6d4441d`, cabang pipa, berbeda dari kit UniXNU `83969cd`) melakukan satu. Skrip melaporkannya sebagai `known-fail` (terlihat di output dan JSON), bukan disembunyikan; panggilan mana yang menulis belum ditelusuri | RP (host) |
| Parser DT fork pada node pipa | `tests/gpu/A650PipaBoard.cpp`: properti `reg`/`iommus` node `gpu` dan `gmu` DTB mainline pipa lewat `NativeAdrenoBoard` = `GpuPowerBoard.h` (1 + 4 jendela, SID 0 dan 5) | RP (host) |
| Penelusuran `write64` (sesi 7) | gdb pada build host: `NativeAdrenoVm::unmap` → `ArmSmmu4KLiveUpdateContextBatch` → `ArmSmmu4KSyncContextTlbPages` menulis TLBIVAL 64-bit di context bank + `0x620`; peer test fork `CHECK(0)` pada setiap `write64` (upstream Adreno740 sudah memperbaiki peer-nya). `patches/adreno650/0002` mengizinkan TLBIVAL saja; lalu `test_vm` menemukan bug nyata `map(nullptr)` (`0001`, guard upstream); sisa: alias dua BO (fork `1c4065c`) = `known-fail` | RP (host) |
| `ShengGmu` | `ShengGmu.h` = API kit Sm8550Platform (pin katalog); **`scripts/gen_pipa_gmu.py`** menghasilkan `ShengGmuSource.h` A650 dari DTB pipa + `a6xx` xml dan jalur a650 `a6xx_gmu_rpmh_init` Linux, dan memeriksa `A650Gmu.c`: 50/50 konstanta, tabel RSC/PDC 19 tulis | RP (statis, CI) |
| Katalog dan format 2 | `patches/unixnu/0002`: komponen `Adreno650` (deps AdrenoPM4, AdrenoFirmware, ArmSmmu4K; resep `build-adreno650.py`; os_abi iPadOS); `feeds.toml` `[[source]] Adreno650`; override iPadOS memilih dan mengarsipkan `component:Adreno650` | RP (`pipa_unixnu.py check`) |
| Alias BO dan xnu-12377 (sesi 8) | `patches/adreno650/0003`: ekspektasi `test_vm` yang basi diganti blok upstream Adreno740 `d834731` (BO driver eksklusif sejak `1c4065c`); arm64 patched 18 lulus, 0 known-fail. `scripts/pipa_adreno_xnu_check.py` di runner macOS: `build-adreno650.py` dengan record compile kernel → 29 objek; 388 simbol kernel dibutuhkan, 4 tidak ada (`native_gop_handoff_call`, `native_gop_handoff_memory`, `boot_log_export_put` dan stub ptrauth-nya) | **Build** (run 43138111458) |
| Link ke kernel macOS (sesi 9) | `patches/gopframebuffer/0001` + `NativeGOPPresenter.cpp` → `native_gop_handoff_call`/`_memory`; `package/BootLogExport.c` → `boot_log_export_put` (memori, tanpa UFS); `pipa_macos26_gpu_defconfig`: 31 anggota ter-link, 398 simbol, 0 tak ter-resolve, 0 import, prelink berhasil, `__TEXT` tetap `0x188000` | **Build** (run 43150998287) |
| Langkah berikut | Pemanggil macOS untuk driver (probe baca-saja dulu), presenter pada frame buffer, plugin Metal macOS; semuanya diuji hanya oleh pemilik | — |

### G4 — input di luar Git untuk override iPadOS

Tidak berubah: audit ABI storage dan kunci owner dari UniXNU-tb128fu, firmware GPU dan touch dari partisi vendor tablet (disimpan di `.cache/firmware`, tidak di-commit). Firmware tidak boleh masuk repo.

### G5 — display, input, daya di bawah macOS

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Frame buffer boot | splash `0x9c000000`, 1800×2880 `a8r8g8b8`, = mainline | ML, RP |
| Panel penuh | MDSS/DPU/dual DSI/PHY 7 nm ada di `sm8250.dtsi` tetapi **dinonaktifkan** untuk pipa di mainline. Panel dari DT Android Xiaomi (`MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf`): **`package/PanelBoard.h`** — dual DSI D-PHY 4 lane, video, DSC 1.1 (slice 450×20, 8 bpp), 900×2880 per DSI, 120 Hz, porch, reset, rail, ID panel TM/CSOT, GPIO ESD/TE. `PanelBoardTests.c`: timing menghasilkan tepat bit clock `1007032320` pohon itu ((300 + 148) × 3122 × 120 × 24 / 4), DSC menutup frame, porch dfps, ukuran 10,99″ | VND (`pipa_hw.py vendor`, 28 fakta panel), RP (host) |
| GENI I2C | **`package/GeniI2cCore.h`**: GENI SE sebagai I2C mode FIFO, polling: probe baca-saja (protokol firmware, FIFO, idle), cek SCL counter, write/read/repeated start, NACK alamat/data (`M_GP_LENGTH`), bus/arbitrase, cancel lalu abort. Akses register lewat callback. 80 konstanta = `geni-se.h`/`qcom-geni-se.c`/`i2c-qcom-geni.c` Linux (`pipa_hw.py drivers`). Diuji pada simulator register (`GeniI2cTests.c`) | RP (host, statis) |
| Backlight | `package/BacklightBoard.h` (KTZ8866 di I2C11 `0x11`, enable TLMM 139, bias TLMM 130/131, panel-id TLMM 30) + **`package/Ktz8866Driver.h`**: attach baca-saja (engine, clock 400 kHz, `DEVICE_ID`), tulis ditolak sampai diizinkan, init dan brightness dengan read-modify-write. Peta register = `ktz8866.c` Linux (13 fakta); fakta board = mainline (4) dan vendor (3). Belum ada shim MMIO di kernel; belum ditulis ke chip | RP (host, statis) |
| Touch | bus SE4, pin, stream SMMU = mainline; pengontrol `novatek,NVT-ts-spi` di `qupv3_se4_spi`, IRQ TLMM 39, 9,6 MHz, pin 8–10 + CS 11 (qup4, 6 mA), firmware per pembuat panel (0x42 CSOT, 0x36 TM) = DT vendor (7 fakta); pemasangan ke HID macOS belum ada | RP, VND |
| Tombol | ketiganya = mainline | RP |
| Baterai, charger | kapasitas dan USID = mainline; periferal fuel gauge/SMB5 = DT vendor (lihat baris sesi 7) | RP, AN, VND |
| Shim kernel backlight (sesi 7) | **`package/PipaBacklight.c`** di atas panggilan XNU (`ml_io_map_unmappable`, `IODelay`, `PE_parse_boot_argn`): dengan `pipa-backlight=1` memetakan GCC, halaman TLMM lima pin dan I2C11, membaca dan memeriksa vote/branch wrap1, level DFS s3 (harus 19,2 MHz), pin (qup11, 2 mA, tanpa bias; HWEN dan enable bias tinggi) lewat `GeniI2cBoard.h`, lalu `ktz_attach` (baca `DEVICE_ID`). `allow_writes` tetap 0; tidak ada tulis GCC, TLMM, KTZ8866, atau konfigurasi engine; semua di-unmap. Diuji pada tablet simulasi; sintaks mode kernel dicek terhadap `tests/xnu_shim` | RP (host, statis: 95 fakta `pipa_hw.py drivers`) |
| Display/touch (sesi 7) | Reset panel TLMM 75 dari `xiaomi-sm8250-common.dtsi`; dual DSI dari PLL DSI0; DSC 450 byte/chunk, 900 byte/baris, pixel clock 167,84 MHz; catu daya dan urutan; touch NT36532 TDDI (IRQ `0x2001`, tanpa reset GPIO, firmware per pembuat panel); struktur integrasi XNU: [display-touch.md](display-touch.md) | VND (59 fakta), RP (host) |
| Baterai/charger (sesi 7) | PM8150B FG gen4 + SMB5, charge pump bq2597x (SE16 `0x66`, TLMM 68), profil `M82_sunwoda_8840mah`, JEITA; bq27z561 dijelaskan tetapi dinonaktifkan: [power-supply.md](power-supply.md) | VND (22 fakta), RP (host) |
| Langkah berikut | Sambungkan `PipaBacklight.c` ke arsip kernel macOS (tetap baca-saja); uji pertama di tablet hanya oleh pemilik | — |

### G6 — memori

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Bank | 3 bank (unit 16 GB): `0x80000000+0x37700000`, `0xc0000000+0x1c0000000`, `0x800000000+0x200000000` | AN |
| Jendela XNU | **macOS**: 6 GiB (`owned_memory_size = 0x180000000`, batas tabel bootstrap 4 KiB) dengan tabel rentang terlarang 64 slot (`owned_memory_excluded_ranges = 64`), seperti profil macOS UniXNU-sheng. **iPadOS**: tetap 5,75 GiB satu run (`remove` di override; kernelnya tidak membaca tabel) | RP (board.toml, ADT dicek: `darwinboot-memory-excluded` 64 slot) |
| Mekanisme | Rantai 121 patch board berisi `window-memory-excluded-ranges.patch` dan `memwired-booter-size-accounting.patch`: XNU menerima satu span dengan rentang terlarang dari `/chosen/darwinboot-memory-excluded`; DarwinBoot hanya mengalokasikan kepala span dan mengisi tabel dari peta memori UEFI akhir | RP (baca patch, `MemoryWindow.h`, `DarwinBoot.c`) |
| Simulasi | **`scripts/pipa_memory.py`** mengompilasi `MemoryWindow.h` DarwinBoot dari submodul dan menjalankannya pada **model** peta pipa (tiga bank AN, dikurangi 20 region no-map DT mainline). Jendela macOS: `0xc0000000`, 6 GiB dapat dipakai, 0 rentang terlarang. 200 peta dengan 1–24 lubang firmware acak 2 MiB di bank 1 dan 2: tabel menempatkan 200/200 jendela (paling banyak 18 rentang, minimal 5,96 GiB), aturan satu-run hanya 11/200. Hasil `DarwinWindowExclusions` = perhitungan Python independen | RP (host: `tests/hw/test_pipa_memory.py`, CI) |
| Batas | Peta memori firmware uefi-pipa yang sebenarnya tidak diketahui di sini (model, bukan bukti); `owned_memory_size` divalidasi 256 MiB–8 GiB; lebih dari 6 GiB butuh tabel bootstrap yang lebih besar; bank 0 dan bank 2 di luar jendela belum dipakai (patch adopsi memori luar tidak ada di UniXNU yang dipin) | RP |
| Sisi kernel (sesi 7) | `kernel_table` memodelkan `arm_vm_excluded_init` (pangkas ke span, bulatkan keluar ke halaman 4 KiB, gabung, cek rentang pertama ≥ `topOfKernelData + max(span/64, 32 MiB)`); setiap tabel loader (kapasitas 1, 64, 4096; peta acak) diterima tanpa panic dan byte terlarangnya = milik loader (`hw.memsize` = `memSizeActual`). Rumus cadangan kernel = loader (dibaca dari sumber) | RP (host) |
| Tabel bootstrap (sesi 7) | `native-4k-bootstrap-capacity.patch`: kolam 16 halaman = 2 root L1 + 14 L2 (1 GiB per L2). 6 GiB di `0xc0000000`: paling banyak 15 halaman di setiap slide 2 MiB; 6 GiB pada base tak sejajar: tepat 16; 6,25 GiB: 17 (gagal). Batas UniXNU: 256 MiB–8 GiB langkah 2 MiB, 1–4096 slot (dibaca dari `devicetree.py`) | RP (host, statis) |
| Langkah berikut | Uji di tablet hanya oleh pemilik; bandingkan peta UEFI nyata (log `NO WINDOW`/tabel) dengan model | — |

## Yang tidak dibuktikan

- Tidak ada kernel, payload, atau boot image yang dibangun dari board format 2 ini. Kesiapan build kernel: [kernel-build.md](kernel-build.md).
- `ArmCpu` cabang pipa ditulis untuk kernel arm64 iPadOS 17; kompilasinya terhadap header xnu-12377 (arm64e) belum dijalankan.
- Tidak ada yang dijalankan di tablet.
- GENI I2C, KTZ8866 (inti dan shim kernel), panel, touch, daya, jendela memori (loader dan kernel) dan fork Adreno650 diuji di host terhadap simulator, model, atau double; konstantanya dicek terhadap sumber Linux dan DT vendor. Itu bukan bukti perilaku perangkat keras.
- Arsip storage pipa ter-compile di runner macOS tetapi tidak di-link ke kernel apa pun.
