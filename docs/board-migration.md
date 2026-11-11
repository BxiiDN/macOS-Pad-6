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
| G2 | `ShengUfs` di bawah arm64e dibangun oleh `build-sheng-source-storage.py` (storage sumber SM8550). Resep UniXNU 3fd6a3c tidak punya saklar `NATIVE_UFS_SM8250` seperti format 1. | Penghalang 1 **ditangani** oleh `patches/unixnu/0001` (diuji di host); penghalang 2 dan 3 terbuka. Rincian di [Kebutuhan driver](#kebutuhan-driver-g2g6). |
| G3 | Adreno650 (`xVanTuring/Adreno650 01db67e0`) dan AdrenoMetal fork bukan komponen katalog; AdrenoMetal katalog bergantung Adreno740 dan Sm8550Platform. | Terbuka untuk build; logika fork diuji di host (`scripts/test_adreno650.py`). Tidak ada GPU di kernel macOS. |
| G4 | Override iPadOS butuh input di luar Git (audit ABI storage dan kunci owner dari UniXNU-tb128fu, firmware GPU/touch dari tablet). | Terbuka. Override hanya di-resolve, tidak di-build oleh repo ini. |
| G5 | Belum ada driver arm64e untuk storage, display, input, dan GPU SM8250 di bawah profil macOS. | Terbuka. Kernel macOS = jalur generik (ArmDTPlatform, ArmCpu, corecrypto, pthread). |
| G6 | XNU memakai satu span memori. macOS: 6 GiB dengan tabel rentang terlarang 64 slot (`window-memory-excluded-ranges.patch`); iPadOS: 5,75 GiB satu run. Seluruh 16 GB butuh beberapa span di pmap/VM. | Tabel **dipasang** untuk macOS (diuji dengan `MemoryWindow.h` di host); lebih dari 6 GiB terbuka (tabel bootstrap 4 KiB). |
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
| Langkah berikut | Kirim patch 0001 ke UniXNU; porting kelima sumber package dari UniXNU-sheng (butuh build tree xnu di runner macOS untuk dikompilasi; tidak dikerjakan tanpa itu); mode probe baca-saja (`native-ufs-probe=2`) sebagai uji pertama yang tidak menulis, hanya oleh pemilik | — |

### G3 — GPU Adreno 650

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Alamat, interrupt, stream SMMU, region zap, OPP | `GpuProbe.cpp`, `GpuPowerBoard.h` dan node GPU feed SoC = mainline (18 fakta) | RP |
| Logika daya dan GMU | `GpuPowerBoardTests` (host), `A650GmuTests` (CI arm64, register dimodelkan) | RP |
| Di tablet | GMU cold start, GX, zap, ring, Metal lewat Turnip di iPadOS | UP |
| Penghalang | `Adreno650` / `AdrenoMetal` fork pipa bukan komponen katalog; `AdrenoMetal` katalog bergantung Adreno740 + Sm8550Platform; untuk macOS perlu bundle Metal target macOS dan publikasi akselerator yang dicocokkan WindowServer | RP |
| Host test fork | **`scripts/test_adreno650.py`**: clone `xVanTuring/Adreno650 01db67e0` dan `ArmSmmu4K` pada pin `feeds.toml`, kompilasi sumber fork terhadap double IOKit-nya sendiri (`tests/XnuMemoryFixture.h`) + kit `AdrenoPM4`, jalankan semua `tests/test_*.cpp`. x86: 9 lulus (board, cpinit, gpu, irq, pwrup, ring, sha256, timer, vm_alias), 12 dilewati dengan alasan tertulis (sumber khusus AArch64: `NativeAdrenoMemory`, `NativeAdrenoSubmit`, `ArmSmmu4KMmio`; header `ShengGmu.h` yang dihasilkan per board). CI juga menjalankannya di arm64 | RP (host) |
| Parser DT fork pada node pipa | `tests/gpu/A650PipaBoard.cpp`: properti `reg`/`iommus` node `gpu` dan `gmu` DTB mainline pipa lewat `NativeAdrenoBoard` = `GpuPowerBoard.h` (1 + 4 jendela, SID 0 dan 5) | RP (host) |
| Langkah berikut | Komponen katalog `Adreno650` (resep build dari `scripts/build-adreno650.py` pipa, header `ShengGmu.h` dari tabel GMU A650), lalu build arm64e terhadap header xnu-12377 | — |

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
| Baterai, charger | kapasitas dan USID = mainline; register fuel gauge/SMB5 hanya dari DT Android | RP, AN |
| Langkah berikut | Shim kernel arm64e (pemetaan MMIO SE `0xa8c000`, delay) di sekitar `GeniI2cCore.h`/`Ktz8866Driver.h`, dikompilasi di runner macOS; uji pertama di tablet oleh pemilik: `ktz_attach` saja (baca `DEVICE_ID`, tanpa tulis) | — |

### G6 — memori

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Bank | 3 bank (unit 16 GB): `0x80000000+0x37700000`, `0xc0000000+0x1c0000000`, `0x800000000+0x200000000` | AN |
| Jendela XNU | **macOS**: 6 GiB (`owned_memory_size = 0x180000000`, batas tabel bootstrap 4 KiB) dengan tabel rentang terlarang 64 slot (`owned_memory_excluded_ranges = 64`), seperti profil macOS UniXNU-sheng. **iPadOS**: tetap 5,75 GiB satu run (`remove` di override; kernelnya tidak membaca tabel) | RP (board.toml, ADT dicek: `darwinboot-memory-excluded` 64 slot) |
| Mekanisme | Rantai 121 patch board berisi `window-memory-excluded-ranges.patch` dan `memwired-booter-size-accounting.patch`: XNU menerima satu span dengan rentang terlarang dari `/chosen/darwinboot-memory-excluded`; DarwinBoot hanya mengalokasikan kepala span dan mengisi tabel dari peta memori UEFI akhir | RP (baca patch, `MemoryWindow.h`, `DarwinBoot.c`) |
| Simulasi | **`scripts/pipa_memory.py`** mengompilasi `MemoryWindow.h` DarwinBoot dari submodul dan menjalankannya pada **model** peta pipa (tiga bank AN, dikurangi 20 region no-map DT mainline). Jendela macOS: `0xc0000000`, 6 GiB dapat dipakai, 0 rentang terlarang. 200 peta dengan 1–24 lubang firmware acak 2 MiB di bank 1 dan 2: tabel menempatkan 200/200 jendela (paling banyak 18 rentang, minimal 5,96 GiB), aturan satu-run hanya 11/200. Hasil `DarwinWindowExclusions` = perhitungan Python independen | RP (host: `tests/hw/test_pipa_memory.py`, CI) |
| Batas | Peta memori firmware uefi-pipa yang sebenarnya tidak diketahui di sini (model, bukan bukti); `owned_memory_size` divalidasi 256 MiB–8 GiB; lebih dari 6 GiB butuh tabel bootstrap yang lebih besar; bank 0 dan bank 2 di luar jendela belum dipakai (patch adopsi memori luar tidak ada di UniXNU yang dipin) | RP |
| Langkah berikut | Uji di tablet hanya oleh pemilik; bandingkan peta UEFI nyata (log `NO WINDOW`/tabel) dengan model | — |

## Yang tidak dibuktikan

- Tidak ada kernel, payload, atau boot image yang dibangun dari board format 2 ini. Kesiapan build kernel: [kernel-build.md](kernel-build.md).
- `ArmCpu` cabang pipa ditulis untuk kernel arm64 iPadOS 17; kompilasinya terhadap header xnu-12377 (arm64e) belum dijalankan.
- Tidak ada yang dijalankan di tablet.
- GENI I2C, KTZ8866, panel, jendela memori dan fork Adreno650 diuji di host terhadap simulator, model, atau double; konstantanya dicek terhadap sumber Linux dan DT vendor. Itu bukan bukti perilaku perangkat keras.
