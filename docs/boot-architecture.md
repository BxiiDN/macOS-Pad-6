# Arsitektur boot Xiaomi Pad 6 (pipa) dan jalur macOS

Status: **riset dari sumber publik dan dari sumber `third_party/uefi-pipa`.** Tidak ada yang diukur di tablet. pipa **bukan** perangkat UEFI standar: UEFI muncul hanya karena image yang di-`fastboot boot` membawanya; firmware flash tablet adalah rantai Qualcomm. Dicek otomatis oleh `scripts/pipa_firmware_map.py` (kelas bukti FS = sumber firmware).

## 1. Rantai boot Qualcomm SM8250 (flash tablet, tidak diubah)

Urutan Qualcomm (sumber: [Qualcomm APSS cold boot flow](https://dragonwingdocs.qualcomm.com/System/Boot/apss-cold-boot-flow.md), [LineageOS: Qualcomm's Chain of Trust](https://lineageos.org/engineering/Qualcomm-Firmware), [worthdoingbadly: Qualcomm XBL](https://worthdoingbadly.com/qcomxbl/)):

1. **PBL** di ROM SoC: bawa clock/MMU minimal, pilih device boot, verifikasi dan muat XBL.
2. **XBL** (EL3, Secure): init DDR, PMIC, device; muat dan verifikasi TZ, hypervisor, dan inti UEFI. XBL Qualcomm berbasis UEFI.
3. **TZ** (TrustZone/QTEE) lalu **hypervisor**.
4. **ABL** (Android Bootloader Xiaomi, aplikasi UEFI `LinuxLoader`): mode fastboot dan pemuat image boot. Memverifikasi tanda tangan image boot (nonaktif bila `vbmeta` di-disable), lalu memuat kernel + ramdisk + DTB dan menyerahkan ke kernel di **EL1 non-secure** (hypervisor memegang EL2).

Repo ini **tidak menyentuh** PBL, XBL, TZ, hypervisor, maupun ABL. Satu-satunya titik masuk kita adalah image boot yang diberikan ke ABL.

## 2. Jalur macOS: ABL → BootShim → UEFI → UniXNU → DarwinBoot → XNU

Rantai yang sama dengan UniXNU-pipa (sumber: `third_party/UniXNU/docs/concepts/boot-chain.md`, `third_party/uefi-pipa`). Tidak ada partisi yang ditulis.

1. **ABL → BootShim.** Image boot (header v1 mkbootimg; `base=0x10000000`, `kernel_offset=0x8000`, `tags_offset=0x100`, `pagesize=2048`, dari `Resources/Configs/pipa.toml`) berisi field "kernel" berupa stream gzip: BootShim lalu firmware volume Mu-Silicium, dengan DTB di belakang stream (`append_dtb=true`). BootShim (`BootShim/BootShim.S`) membawa header Linux arm64 Image (`text_offset = FD_BASE`, magic `ARM\x64`), jadi ABL memperlakukannya sebagai kernel Linux: ABL menaruh pasangan itu di alamat yang diminta, menyalin DTB, dan melompat dengan DTB di `x0`. BootShim merelokasi firmware volume ke `FD_BASE` (`0x9FC00000`) dan masuk UEFI.
2. **UEFI → UniXNU.** `ShengBootMemoryDxe` membaca DTB yang diserahkan di `x0` (disimpan SEC dalam HOB), dan menerbitkan ramdisk image boot (volume payload UniXNU) sebagai block device read-only. `UniXNUDxe` mendaftarkan `UniXNU.efi`; boot manager memindai `\EFI\UniXNU\unixnu.toml`.
3. **UniXNU → DarwinBoot.** Entry tipe `xnu` diserahkan dengan DTB (disalin + 64 KiB slack, patch global/kit/entry, dipasang sebagai `EFI_DTB_TABLE`), ramdisk, boot args, dan kext. `/chosen` membawa `linux,initrd-start/end` untuk ramdisk.
4. **DarwinBoot → XNU.** DarwinBoot membaca `kernel.macho` (+ `.adt`, + `.trustcache` bila ada), memeriksa header Mach-O (`MH_MAGIC_64`, `CPU_TYPE_ARM64`, `MH_EXECUTE`, satu `LC_MAIN`), setiap segmen page-aligned dan di dalam jendela 256 MiB, baca info framebuffer dari GOP, alokasikan jendela fisik kontigu, salin segmen/ADT/trustcache/ramdisk, bangun `DARWIN_BOOT_ARGS`, exit boot services, lalu lompat ke XNU.

## 3. Format image boot dan handoff

| Besaran | Nilai (FS) | Catatan |
| --- | --- | --- |
| Header image boot | v1 (mkbootimg) | sumber: `pipa.toml`; bukan header v3/v4 GKI. ABL pipa menerima v1 dengan DTB di-append |
| Kompresi kernel | gzip | BootShim + FD di dalam gzip |
| DTB | di belakang stream gzip (`append_dtb`) | ABL meneruskannya di `x0`; `ShengBootMemoryDxe` menyimpannya |
| `FD_BASE` / `FD_SIZE` | `0x9FC00000` / `0x300000` | = deskriptor "UEFI FD" di `MemoryMapLib.c` |
| Ramdisk | payload UniXNU, block device read-only | ABL menaruhnya di area "Kernel" `0xA0000000+0x10000000` (deskriptor reserved) |
| Framebuffer | `0x9c000000+0x2300000`, 1800×2880 `a8r8g8b8` | DT `cont_splash_region`, di dalam "Display Reserved"; DarwinBoot baca ukurannya dari GOP |
| Exception level | kernel di EL1 non-secure | hypervisor Qualcomm di EL2; XNU tidak diberi EL2 |
| Register handoff | DTB di `x0` (protokol boot Linux arm64) | ABL mengikuti protokol kernel Linux |

`fastboot boot <image>` memuat image ke RAM saja; ABL tidak menulis partisi. Ini jalur uji; tidak ada langkah flashing di repo.

## 4. Memory map

Sumber kebenaran saat boot adalah **peta memori UEFI** yang dibangun firmware dari tabel partisi RAM yang ditinggalkan XBL (`RamManagerDxe` menambah DDR yang belum diketahui GCD). `MemoryMapLib.c` (`third_party/uefi-pipa`) menetapkan reservasi statis; DarwinBoot memilih basis jendela dari peta itu saat boot, bukan dari model.

- Reservasi DDR (sumber firmware) meliputi semua rentang no-map DT mainline yang dipakai model G6, **plus** enam yang tidak ada di model: `0x80880000` (GPU PRR), `0x80890000` (XBL UEFI log), `0x92700000` (ADSP RPC), **`0xA0000000+0x10000000` (area muat kernel/ramdisk ABL)**, `0xB0400000` (display ramdump), **`0xFFC00000` (Bank 1 Hole)**. `scripts/pipa_firmware_map.py` mencantumkannya sebagai titik buta model.
- Jendela macOS 6 GiB (`owned_memory_size=0x180000000`, 64 slot tabel rentang terlarang): pada peta model mainline basisnya `0xc0000000`; pada peta sumber firmware `0xffe00000` (bank 1 hole menggeser first-fit). Keduanya hanya model; basis nyata datang dari peta UEFI tablet.
- MMIO: `MemoryMapLib.c` mendaftar ±30 region register (GPU_CC, SMMU, TLMM, QUPV3, APSS_HM). pipa_memory.py memverifikasi sisi jendela/tabel.

**ARM64:** SM8250 = 4× Cortex-A55 (E) + 4× Cortex-A77 (P), tanpa PAC/ARMv8.3 (lihat `docs/feasibility.md`), GICv3 `0x17a00000/0x17a60000`, timebase 19,2 MHz. Kernel macOS arm64e berjalan di CPU ini hanya dengan lapisan ARMv8.2 (null-PAC + emulator FGE) dan, untuk kext Apple di kernel collection, gerbang ISA — yang belum dikerjakan (ditunda).

## 5. Yang tidak diketahui tanpa tablet

- Peta memori UEFI nyata (bank DDR, lubang firmware): hanya dari tablet, lihat `docs/firmware-acquisition.md`.
- Apakah ABL menaruh ramdisk 192 MiB dari image header v1 dan melaporkannya di `/chosen` (tercatat "unverified" di `PORTING.md`).
- Apakah panel tetap menyala lewat driver clock/power vendor saat menu UniXNU jalan.
- Apakah FD 3 MiB masih memuat UniXNU (input vendor 4,8 MiB sebelum kompresi).
