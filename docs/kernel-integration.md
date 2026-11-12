# Kesiapan integrasi kernel pipa (macOS Tahoe 26.5, xnu-12377.121.6)

Diperbarui: 2026-11-12 (sesi 8). Baseline sesi: `92bd286`. Semua angka di bawah berasal dari log run yang ditautkan atau dari perintah yang bisa diulang; tidak ada yang dijalankan di tablet.

**Ringkasan.** Kernel pipa dengan storage UFS (probe-only) **ter-compile, ter-link, dan ter-prelink** dengan kernelcache 26.5 di runner macOS ([run 43138111458](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43138111458)): 0 import chained fixup, 0 target hilang/stub, sisa `__PRELINK_TEXT` 10.208 byte. Fork Adreno650 ter-compile terhadap header xnu-12377, tetapi butuh 4 simbol yang tidak ada di kernel ini (display handoff dan ekspor log), jadi **belum siap di-link**. Display dan touch belum punya driver macOS; strukturnya ada sebagai kode murni yang diuji di host. Siap di-link bukan berarti berfungsi: tidak ada bukti perangkat keras.

## Konfigurasi

| | `pipa_macos26_defconfig` (generik) | `pipa_macos26_ufs_defconfig` (integrasi) |
| --- | --- | --- |
| Pemilih di workflow | `[kernel-build]`, `[kernel-prelink]` | `[kernel-ufs]` (+ `[kernel-prelink]`) |
| Arsip storage | dibangun tiap kernel step (`component:ShengUfs`), **tidak di-link** | dibangun dan di-`force_load` |
| `native_source_storage_start()` | tidak di-compile (`XNU_PIPA_SOURCE_STORAGE` tidak ada) | dipanggil setelah `vfsinit` |
| Hasil terakhir | [run 43139267130](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43139267130): 0 anggota arsip ter-link, `__TEXT` `0x188000`, sisa 42.976 byte, prelink berhasil | [run 43138111458](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43138111458): 12 anggota ter-link, `__TEXT` `0x190000`, sisa 10.208 byte, prelink berhasil |
| Perangkat lain | — | file hanya di `devices/pipa`; profil board lain tidak berubah |

Rantai patch: 122/122 apply ke xnu-12377.121.6 (patch baru `zzzzc-pipa-source-storage-start.patch`). Karena patch itu menggeser nomor baris `bsd_init.c`, kernel generik pun punya hash baru, walau kodenya tidak berubah.

## 1. UFS SM8250 (G2)

| Pemeriksaan | Hasil | Bukti |
| --- | --- | --- |
| Arsip `libShengSourceStorage.a` | 1.359.384 byte, arm64e; dibuat oleh kernel step lewat resep UniXNU dengan `patches/unixnu` 0001 (SM8250), 0003 (tanpa root), **0004 (probe-only)** dan `patches/shengufs` 0001–0002 | run 43138111458, langkah "Source storage archive" |
| Saklar compile `NativeUfs.cpp` | `-DNATIVE_UFS_SOURCE_API=1 -DNATIVE_UFS_SM8250=1 -DNATIVE_UFS_PROBE_ONLY=1` (dari command line yang direkam) | `storage-build.json` |
| Simbol pipa (13) | semua terdefinisi | idem |
| Simbol yang harus disediakan kernel | 385, **semua ter-resolve** (link berhasil); a.l. IOKit, `kmem_alloc_guard`/`kmem_free_guard`, SHA-256/384, `rsa_verify_pkcs1v15`, `gPhysBase`, `g_kernel_kmod_info` | idem |
| Anggota yang ter-link (link map) | 12: `IOBlockStorageDevice.late.o`, `NativeUfs.late.o`, `NativeRamBlock.late.o`, `SourceStorage.o`, `SourceRootPolicies.o`, `SourceRootBinding.o`, `BootLog.o`, `BootLogDefaults.o`, `BootReset.o`, `verified_root.o`, `xnu_crypto.o`, `RootAnchor.o` | idem |
| Import chained fixup | 0 (`boot_progress_poll` hidden, default hidden untuk `native_ufs_store_write_cached`) | `kernel-report.json` |
| Konflik linker | tidak ada (tidak ada duplicate symbol; `.late.o` tanpa `__mod_init_func`, inisialisasi dipanggil `SourceStorage`) | log link |
| Root dari `userdata` | **tidak mungkin dari kode yang di-link**: tanpa kebijakan (bundle 32 byte, 0 kebijakan), anchor nol, `SourceRootBinding` selalu 0, dan dengan probe-only `NativeUfsBlock`/`startRoot`/uji blok userdata tidak di-compile | `PipaStorageGuardTests.c`, patch 0004 |
| Kapan berjalan | hanya dengan `native-source-storage=1` **dan** `native-ufs-probe` ∈ {2, 6, 7, 8} (baca register saja); semua mode root/store/log/publikasi ditolak; tidak ada di `kernel_args` board | `PipaStorageGuard.h` |

Jalan ke prelink: putaran pertama ([run 43136731212](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43136731212)) ter-link (25.251.496 byte, 0 import) tetapi `__TEXT` `0x194000` melebihi celah `__PRELINK_TEXT` `0x192f40` sebanyak 6.176 byte. Probe-only (0004) membuang kode publikasi blok/root: `__TEXT` `0x190000`, sisa 10.208 byte.

## 2. Adreno 650 (G3)

| Pemeriksaan | Hasil | Bukti |
| --- | --- | --- |
| Known-fail alias BO (`test_vm` patched) | **selesai**: test basi. Fork `1c4065c` memetakan BO milik driver lewat batch eksklusif (`exclusivePages` true untuk BO non-impor); test masih mengharapkan penolakan. Upstream Adreno740 mengganti ekspektasi itu di `d834731`; `patches/adreno650/0003` mengambil blok upstream. Bukan perubahan driver | CI arm64: patched 18 lulus, 3 dilewati, **0 known-fail**, 0 FAILED |
| Pin tanpa patch | tetap 2 known-fail (`test_gmumap`, `test_vm`: peer SMMU basi, TLBIVAL 64-bit), tercatat | CI arm64 |
| Katalog | komponen `Adreno650` (patch `0002`) di-resolve untuk override iPadOS dari pin `feeds.toml`, deps AdrenoPM4, AdrenoFirmware, ArmSmmu4K (pin pipa `6d4441d`) | `pipa_unixnu.py check` |
| GMU | `ShengGmuSource.h` A650 dihasilkan dari DT + Linux, 50/50 konstanta `A650Gmu.c` | `gen_pipa_gmu.py --check` |
| Compile terhadap xnu-12377 | **berhasil**: 29 objek (`build-adreno650.py` dengan record compile kernel ini), arsip 1.228.856 byte; tidak ada simbol NativeAdreno/kit yang hilang | run 43138111458, langkah "Adreno650 against xnu-12377" |
| Simbol kernel | 388 dibutuhkan; **4 tidak ada di kernel ini**: `native_gop_handoff_call`, `native_gop_handoff_memory` (dari GopFramebuffer, display handoff), `boot_log_export_put` (weak import; ekspor log sheng) dan stub ptrauth-nya | idem — langkah ditandai gagal (`continue-on-error`), tidak disembunyikan |
| Di-link ke kernel macOS | **tidak**; profil macOS tidak memilih GPU | — |

Akselerasi GPU tidak diklaim: tidak ada driver yang di-link, tidak ada uji perangkat.

## 3. Display dan touchscreen

| Bagian | Keadaan | Bukti |
| --- | --- | --- |
| Struktur dual DSI + DSC | `PanelLink.h`: dua host DSI (DSI0 master clock, DSI1 slave, separuh 900 px), konfigurasi DSC 1.1 per encoder dengan parameter rate-control menurut `drm_dsc_compute_rc_parameters` Linux untuk DSI msm. Nilai dihitung tangan di test (mis. `final_offset` 4336, `nfl_bpg_offset` 1294, `slice_bpg_offset` 1562, `rc_bits` 7944). Konstanta dan tabel pre-SCR 8 bpp/8 bpc = sumber Linux (12 fakta) | `PanelLinkTests.c`, `pipa_hw.py drivers` |
| Reset TLMM 75 | di DT vendor setiap pengguna TLMM 75 adalah reset panel DSI atau pin state `sde_dsi`; pipa (dua node m82) termasuk. `pnl_reset_check()` memeriksa pin state dari pembacaan register (gpio, output, 8 mA, tanpa pull, tinggi), tanpa menulis | `pipa_hw.py vendor` (82 cocok), `PanelLinkTests.c` |
| Varian TM/CSOT | dipisah: nama node/panel (bentuk bootloader) dan byte pembuat harus cocok; selain itu `PNL_UNKNOWN`. Dua panel berbeda di urutan perintah on (DT vendor) | `pnl_variant_select` |
| Firmware NT36532 | `tv_config_for_variant()`: TM → `…_fw_tm.bin`, CSOT → `…_fw_csot.bin`, panel tak dikenal → **tidak ada firmware** | `PanelLinkTests.c` |
| Integrasi XNU | belum ada driver macOS; panel penuh butuh driver clock/GDSC MDSS (baca MDSS tanpa itu = SError) | `docs/display-touch.md` |

## 4. GENI I2C dan KTZ8866

Audit statis (`tests/hw/test_backlight_audit.py`) membuktikan dari kode:

- `PipaBacklight.c` hanya menulis lewat callback engine (`se_write`); jendela GCC dan TLMM hanya dibaca.
- `GeniI2cCore.h` hanya menulis register transfer: command, IRQ clear, panjang transfer, TX FIFO dan watermark-nya. Register konfigurasi (`DMA_MODE_EN`, `SER_M_CLK_CFG`, `CLK_SEL`, `SCL_COUNTERS`, packing) tidak pernah ditulis.
- Satu-satunya penulisan register KTZ8866 ada di `ktz_write`, yang menolak selama `allow_writes` = 0. Nilai itu tidak pernah diubah.

Simulasi `PipaBacklightTests.c` menghitung nol tulis untuk semua jalur. Shim ini belum di-link ke kernel.

## 5. Memori

| Pemeriksaan | Hasil |
| --- | --- |
| Batas bootstrap 4 KiB | kolam 16 halaman: 6 GiB di `0xc0000000` paling banyak 15 halaman di setiap slide; 6 GiB adalah maksimum di setiap base dan slide (6,25 GiB butuh 17) |
| Alamat | memori DTS = rentang dram board (`0x80000000+0x980000000`); jendela `0xc0000000..0x240000000` di dalamnya dan di satu bank; sejajar 2 MiB; estimasi image (192 MiB) ≥ kernel collection (135.102.464 byte dengan UFS); head (image + cadangan 96 MiB) di dalam jendela |
| Excluded ranges | tabel loader (kapasitas 1, 64, 4096; peta acak) diterima kernel tanpa panic, byte sama (`hw.memsize`); setiap rentang sejajar halaman, terurut, di dalam jendela, setelah head; salinan kernel muat satu halaman |

Bukti: `scripts/pipa_memory.py --check`, `tests/hw/test_pipa_memory.py` (22 test). Peta memori adalah model; peta firmware nyata belum diketahui.

## 6. Hambatan yang tersisa

1. **Adreno650**: 4 simbol kernel yang tidak ada (GopFramebuffer handoff, ekspor log). Dibutuhkan komponen GopFramebuffer untuk macOS, atau stub yang disetujui, sebelum link. Profil macOS tidak memilih GPU.
2. **Display/touch**: belum ada driver macOS; `QcomGeniSpi`, `ShengNovatekTouch`, `ShengHidInput` dan `GopFramebuffer` hanya ABI iPadOS. Identitas panel saat boot harus datang dari firmware atau boot-arg.
3. **Backlight**: shim belum di-link (keputusan berikut, tetap baca-saja).
4. **UFS**: hanya inspeksi register yang diizinkan; perilakunya di tablet belum diuji. Ruang `__PRELINK_TEXT` tinggal 10.208 byte untuk komponen berikutnya.
5. Ditunda atas instruksi: `pacstrip`, gerbang ISA, payload, boot.
