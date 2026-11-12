# Build kernel macOS Tahoe 26.5 untuk pipa

Status: kernel XNU untuk pipa (macOS Tahoe 26.5, xnu-12377.121.6, arm64e) **berhasil di-compile, di-link, dan di-prelink** dengan kext kernelcache resmi 26.5 (J274AP 25F71) di runner macOS, dan build kernel native-nya **reproducible bit demi bit** (percobaan 8–9, 2026-11-11). Kernel collection belum dilewatkan `pacstrip`, belum dimasukkan ke payload, dan **belum di-boot** di perangkat atau emulator. Klaim di halaman ini hanya yang ada buktinya di log run yang ditautkan.

## Apa yang dibangun

`unixnu build kernel` untuk `devices/pipa` dengan profil `macos-26.5-25F71`:

1. Sumber xnu-12377.121.6 (`ac9718fb1af6`) ditambah 121 patch, urut sesuai `board.toml` (arch arm64e UniXNU → SoC SM8250 arm64e → OS macOS 26.5 → device pipa: AMP, null-PAC, FGE, default fitur yang belum ada, teks assert panjang).
2. Konfigurasi: `configs/common.config` (arm64e) + `sm8250.config` + `macos.config` + `pipa_macos26_defconfig`.
3. Arsip yang di-link ke kernel: corecrypto sumber (dua kali, kedua dengan namespace), ArmDTPlatform, ArmCpu cabang pipa, libpthread kernel.
4. Hasil: kernel native `mach.development.bcm2837` (Mach-O `MH_EXECUTE`, arm64e), lalu (tanpa `--skip-prelink`) prelink dengan kext dari kernelcache J274AP 26.5 asli.

Kernel ini sengaja hanya jalur generik: CPU, interrupt, timer, platform expert. Tanpa storage, display, input, dan GPU (celah G2, G3, G5 di [board-migration.md](board-migration.md)), jadi akhir yang diharapkan saat boot adalah panic `Failed to mount root device`, seperti kernel pertama format 1.

## Kesiapan (diperiksa di setiap push oleh CI)

| Syarat | Status | Bukti |
| --- | --- | --- |
| Board format 2 di-resolve UniXNU untuk 26.5 dan override iPadOS | siap | `scripts/pipa-unixnu.sh check` |
| 121/121 patch apply ke xnu-12377.121.6 dalam urutan board | siap | `check --xnu`, `check_patch_chain.py` |
| Patch ARMv8.2 (null-PAC, FGE) sesuai sumber `kernel/` | siap | `gen_tahoe_patches.py --check` |
| Device tree → ADT dengan nilai board | siap | `check --adt` |
| ArmCpu cabang pipa dari pin `feeds.toml` | siap (resolusi) | G1 di board-migration.md |
| Toolchain kernel step (macos-26, Xcode 26.6, SDK iphoneos 26.5) | siap | percobaan 1 |
| Kompilasi XNU arm64e dengan rantai board | **berhasil** | percobaan 1 (119 patch), 2 (120), 8–9 (121) |
| Arsip: corecrypto ×2, ArmDTPlatform, ArmCpu cabang pipa, libpthread | **berhasil dibangun** terhadap header xnu-12377 | percobaan 1 |
| Linking kernel native | **berhasil** di percobaan 2 (percobaan 1 gagal pada 5 simbol) | lihat riwayat |
| Lapisan ARMv8.2 ter-link | **ya**: simbol FGE ada; di kode mesin `sleh_synchronous` memanggil `fge_xnu_handle` dan `ml_addrperm_pacga` berbadan null-PAC | percobaan 2, 8–9 |
| `__TEXT` native muat di `__PRELINK_TEXT` 26.5 | **ya**: `0x188000` (awal `0x19c000`), sisa 42.976 byte | percobaan 8 |
| Tanpa import chained fixup | **ya** (0 import) | percobaan 9 |
| Prelink dengan kernelcache 26.5 | **berhasil** di percobaan 9 (percobaan 3–8 gagal: tata letak, lalu import) | lihat riwayat |
| Build bit-for-bit reproducible | **ya**: kernel native dan kernel collection identik antar-build dan antar-commit dengan input kernel yang sama | percobaan 8, 9, 12 |
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

### Percobaan 3 — 2026-11-11, commit `aacff91`, run [42981285641](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42981285641): kernel ter-link lagi, **prelink gagal**

- Compile + link berhasil lagi (rantai dan konfigurasi sama dengan percobaan 2). SHA-256 kernel native kali ini `643b015d2b60778dec1bf0670e4d022800797d7742b35554bfe5d38a73a3bf41`: berbeda dari percobaan 2, jadi build belum reproducible bit-for-bit (stempel waktu/UUID/versi di biner; belum diselidiki).
- `build prelink`: kernelcache resmi `UniversalMac_26.5_25F71_Restore.ipsw` dibaca lewat HTTP range, pin SHA-256 profil cocok, pemasangan simbol `by name: 3384 functions, 292 data of 3764 kext-facing targets; 88 unpaired, 0 conflicts`. Lalu `kits/XnuPrelink/fileset_layout.py` berhenti: **`No room for 0x19c000 bytes in __PRELINK_TEXT`**.
- Arti: XnuPrelink menaruh `__TEXT` kernel native (0x19c000 = 1,61 MiB, kernel DEVELOPMENT) di celah `__PRELINK_TEXT` kernel collection J274AP yang tidak ditempati kext yang dipertahankan (closure dari prelink roots profil). Di KC 26.5 tidak ada celah sebesar itu. Ini batas tata letak, bukan kesalahan kompilasi.
- Diagnostik untuk percobaan berikutnya: `scripts/prelink_layout.py` (dijalankan workflow bila prelink gagal) mencetak celah-celah itu, kext yang membatasinya, dan selisihnya.

Pilihan perbaikan yang dipertimbangkan (diukur di percobaan 4):
1. Kecilkan `__TEXT` native (konfigurasi kernel, atau memindahkan section read-only besar keluar dari `__TEXT`).
2. Kurangi kext yang dipertahankan di sekitar slot kernel.
3. Ubah XnuPrelink agar boleh menaruh `__TEXT` native di luar `__PRELINK_TEXT` (perubahan di UniXNU, perlu dicek terhadap asumsi XNU tentang urutan segmen).

### Percobaan 4 — 2026-11-11, commit `d811bcb`, run [42982647125](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42982647125): pengukuran tata letak prelink

Compile + link berhasil lagi; prelink gagal dengan pesan yang sama; `scripts/prelink_layout.py` mengukur `__PRELINK_TEXT` kernel collection J274AP 26.5 (setelah rebase XnuPrelink, halaman 16 KiB):

| | |
| --- | --- |
| `__PRELINK_TEXT` | `0xfffffe000700c000`, ukuran `0xcc0000` |
| `__TEXT` `com.apple.kernel` asli | `0x120000` (1,13 MiB) di awal segmen |
| `__TEXT` kernel native pipa | `0x19c000` (1,61 MiB) |
| Kext yang dipertahankan (closure roots profil) | 87 |
| Celah 1 (slot kernel): `0xfffffe000700c000` | `0x15d990`: kurang `0x3e670` (255.600 byte) |
| Celah 2: setelah `AppleARMWatchdogTimer`, `0xfffffe000717b8a0` | `0x192f40`, terpakai setelah perataan 16 KiB `0x1927e0`: **kurang `0x9820` (38.944 byte, 2,3 %)** |
| Pembatas celah 1 dan 2 | `com.apple.driver.AppleARMPlatform` (`0x102bb`) dan `com.apple.driver.AppleARMWatchdogTimer` (`0x1c50`), keduanya root profil |

Kesimpulan dari angka ini:
- Pilihan 2 tidak menolong: celah 1 dan 2 dipisahkan `AppleARMPlatform`, yang dibutuhkan jalur platform macOS UniXNU; tanpa `AppleARMWatchdogTimer` pun celah 2 tetap mulai di `0xfffffe000717c000` setelah perataan.
- Pilihan 1 cukup bila `__TEXT` native turun sedikitnya **38.944 byte** (muat di celah 2), atau 255.600 byte untuk slot kernel asli. Laporan kernel (`kernel_report.py`) sekarang mencantumkan ukuran setiap section `__TEXT` untuk memilih apa yang dipangkas.
- Pilihan 3 tetap mungkin, tetapi mengubah UniXNU.

### Percobaan 5 — 2026-11-11, commit `e1a15dc`, run [42984181369](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42984181369): isi `__TEXT` native

Compile + link berhasil lagi (SHA-256 `e415f1c0105be18e7f5667dbde38c565afa36363acfbfbf38d18cfbe139097fd`, ukuran sama 25.135.384 byte). Section `__TEXT` kernel native:

| Section | Byte |
| --- | --- |
| `__cstring` | 1.116.153 |
| `__os_log` | 281.834 |
| `__const` | 279.432 |
| `__eh_frame` | 1.712 |
| `__copyio_vectors` | 360 |
| `__fips_hmacs` | 32 |
| jumlah | 1.679.523 (`0x19a0a3`), ditambah header Mach-O di awal segmen |

Agar muat di celah 2, `vmsize` `__TEXT` harus turun dari `0x19c000` ke `0x190000` (tiga halaman 16 KiB), jadi isi section harus berkurang sedikitnya sekitar 41 KB ditambah pertumbuhan header. `__cstring` (1,06 MiB) adalah sasaran utama: string diagnostik yang ditambahkan rantai patch (UniXNU dan pipa) dan string build DEVELOPMENT. Belum ada yang dipangkas.

### Percobaan 6 — 2026-11-11, commit `0c4d725`, run [42987653937](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42987653937): audit ukuran dan reproducibility (baseline)

Hanya pengukuran; kode dan data kernel tidak berubah. `pipa_macos26_defconfig` menambahkan link map ld64 (`-Wl,-map`); `scripts/kernel_size_audit.py` memecah setiap section menurut asal (map) dan string menurut patch yang menambahkannya.

Section kernel native (byte):

| Section | Byte | | Section | Byte |
| --- | ---: | --- | --- | ---: |
| `__TEXT_EXEC,__text` | 10.441.504 | | `__TEXT,__os_log` | 281.834 |
| `__TEXT,__cstring` | 1.116.153 | | `__TEXT,__const` | 279.432 |
| `__DATA_CONST,__const` | 865.812 | | `__DATA_CONST,__assert` | 195.648 |
| `__DATA,__common` | 817.976 | | `__TEXT_EXEC,__hib_text` | 4.580 |
| `__BOOTDATA,__init` | 376.472 | | `__TEXT,__eh_frame` | 1.712 |
| `__LINKINFO,__symbolsets` | 286.554 | | `__TEXT_EXEC,__commpage_text` | 816 |

Tidak ada `__stubs` atau `__auth_stubs`: kernel di-link statis, tidak ada pemanggilan lewat stub.

Asal `__TEXT,__cstring` (33.375 string): XNU Apple 1.092.232 byte; arsip corecrypto (namespaced) 17.727; pthread 2.139; ArmCpu 912; ArmDTPlatform 258; firehose 53. **Seluruh string yang ditambahkan 120 patch hanya sekitar 3 KB**: yang terbesar `vfs-union-below-walk` 315, `offline-component-load-probes` 294, `payload-boot-memory-report` 288; **FGE 119 byte, null-PAC 0**. `__TEXT,__os_log` (5.560 string, 281.834 byte) hampir seluruhnya Apple. Jadi memangkas pesan diagnostik dari patch tidak mungkin menghasilkan 45 KB.

Reproducibility: dua build dari nol dengan source dan lokasi sama berbeda SHA-256. **Satu-satunya section yang berbeda adalah `__TEXT,__const`**, berisi string versi kernel yang dicap `date` oleh `config/newvers.pl` (08:38:43 vs 08:44:40 UTC); `LC_UUID` mengikutinya. Tabel simbol, tabel string, fixup, dan semua section lain identik; 1.038 entri debug map (N_OSO) sudah bertimestamp nol (`ZERO_AR_DATE`). Urutan arsip dan compiler tidak menimbulkan perbedaan.

(Catatan: angka "build-path prefix 0 byte" di run ini salah ukur: prefix dioper dengan jalur `.../macOS-Pad-6/../UniXNU-build/...` yang belum dinormalisasi. Diperbaiki di commit `0cd50a2` (`kernel_size_audit.py` menormalkan prefix).)

### Percobaan 7 — 2026-11-11, commit `d5e04a6`, run [42989038338](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42989038338): prefix map dan tanggal build tetap

- `-fmacro-prefix-map` untuk pohon build dan salinan XNU-nya: `__FILE__` di `VERIFY()` (`bsd/sys/mcache.h`), `AssertMacros.h` IOKit, dan `cc_macros.h` corecrypto sebelumnya memuat ±104 karakter direktori runner.
- `KERNEL_BUILD_DATE` (override `newvers.pl` untuk build reproducible) dari waktu commit HEAD, lewat `scripts/pipa_unixnu.py`.
- Hasil: `__TEXT,__cstring` 1.116.153 → **1.090.601** (−25.552 byte, jumlah string sama 33.375), `__text` tetap 10.441.504 byte. `__TEXT` hanya turun satu halaman (`0x19c000` → `0x198000`); prelink gagal lagi, `No room for 0x198000 bytes in __PRELINK_TEXT`.
- Perhitungan ulang: celah terbesar terpakai `0x1927e0` setelah perataan 16 KiB, jadi `__TEXT` harus `≤ 0x190000`; isinya harus turun sekitar 45 KB dari awal (bukan 38.944 byte seperti tertulis di percobaan 4, yang belum menghitung header Mach-O dan pembulatan halaman).

### Percobaan 8 — 2026-11-11, commit `d51558b`, run [42991705340](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42991705340): teks assert panjang, **`__TEXT` muat**, build reproducible

- Patch device `zzzzb-pipa-long-assert-text.patch`: `assert()` biasa tetap memeriksa, tetap trap, dan deskriptornya tetap menyimpan `__FILE_NAME__` dan `__LINE__`; untuk ekspresi lebih dari 48 byte deskriptor menunjuk satu catatan bersama `(long expression omitted: see file:line)` alih-alih teks ekspresinya. Diuji dengan clang (C dan C++, `-O0`, `-Os`, `-O2`): instruksi identik, literal panjang tidak dihasilkan. `release_assert`, `assertf`, `assert3u/3s/3p` tidak berubah. Rantai 121/121.
- Hasil:

| | Awal (percobaan 6) | Percobaan 8 | Selisih |
| --- | ---: | ---: | ---: |
| `__TEXT` vmsize | `0x19c000` | **`0x188000`** | −80 KiB (5 halaman) |
| `__TEXT,__cstring` | 1.116.153 | 1.033.274 | **−82.879** |
| `__TEXT,__os_log` | 281.834 | 281.834 | 0 |
| `__TEXT,__const` | 279.432 | 279.432 | 0 |
| `__TEXT_EXEC,__text` | 10.441.504 | 10.441.504 | 0 |
| Ukuran file kernel | 25.135.384 | 25.048.600 | −86.784 |

- `scripts/prelink_layout.py`: `__TEXT` native `0x188000` **muat** di celah setelah `AppleARMWatchdogTimer` (`0x1927e0`), **sisa 42.976 byte**.
- Integrasi tetap: `sleh_synchronous` memanggil `fge_xnu_handle` (1 call site), `ml_addrperm_pacga` diawali badan null-PAC (`orr x0, x0, #1; ret`), sensus ISA sama (57.243 word PAuth, 0 di luar FGE).
- **Reproducibility**: build kedua dari nol di tempat yang sama menghasilkan kernel identik bit demi bit: SHA-256 `7db1659a583282e1835af9b5ef47aa918eb05996e04ee2234352887781768e00` dan `LC_UUID` sama, tidak ada section atau blob link-edit yang berbeda.
- Prelink berhenti pada penyebab berikutnya: **`Chained fixup imports are not supported`** (`kc_image.py`). Penyebabnya patch `zzzz` saya sendiri: `native_exit_trace` didefinisikan `weak`, dan definisi weak di executable Mach-O di-bind lewat weak lookup, yang ditulis linker sebagai import chained fixup (lib ordinal −3; direproduksi dengan lld: weak → 1 import, strong → 0). Diperbaiki di commit `50736cd`: definisi biasa (strong).

### Percobaan 9 — 2026-11-11, commit `50736cd`, run [42994058285](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42994058285): **prelink berhasil**

- Kernel native: SHA-256 `ce13aea1586d2e425b10f48170d884f2b0f4af1348ab32ae459f3074e7e5ddec`, 25.048.584 byte, `MH_EXECUTE` arm64e, `__TEXT` `0x188000`, **0 import chained fixup**. `sleh_synchronous` memanggil `fge_xnu_handle`; `ml_addrperm_pacga` berbadan null-PAC.
- `build prelink`: kernelcache dari `UniversalMac_26.5_25F71_Restore.ipsw` (HTTP range, pin SHA-256 profil). `scripts/prelink_layout.py`: `__TEXT` native muat (sisa 42.976 byte).
- Hasil: `kernel/kernel.macho`, **kernel collection `MH_FILESET` arm64e**, 135.036.928 byte, SHA-256 `840488d5d4b6ea38df85bbe210b24e170bbe012f28c47ff53936697a5dc66e3c`, `LC_UUID` `29f1b7a9e6a8f673fb8297457a4ba754`, 93 load command, 0 import. Segmen: `__TEXT` @ `0xfffffff007004000`, `__PRELINK_TEXT` (`0xcc0000`), `__DATA_CONST`, `__TEXT_EXEC` (`0x360c000`), `__PRELINK_INFO`, `__DATA`, `__LINKEDIT`, `__KLDDATA`, `__BOOTDATA`.
- Catatan XnuPrelink (`kernel.json`): `format` `MH_FILESET`; input `kernelcache_sha256` `19ae26f4…` (= pin profil) dan `native_sha256` `ce13aea1…` (= kernel native run ini); entry `com.apple.kernel`; `matcher_version` 8; pemasangan simbol `symbol-names`; closure kext yang dipertahankan dicantumkan (AppleARMPlatform, AppleMobileFileIntegrity, apfs, IOHIDFamily, IOGPUFamily, …). Pemeriksaan regresi prelink UniXNU lolos (langkah berhasil). Isi lengkap catatan: percobaan 10.
- Sensus ISA kernel collection (statis): 6.526.890 word kode di 80 image arm64e; yang tidak dimiliki SM8250: PAuth 290.710 (`pac-branch` 154.421, `pac-dp1` 136.278, `pacga` 7, `pac-keyreg` 4), SHA3 122, SHA512 32, DIT 21, LRCPC2 4, SB 1. **Semuanya di kelas yang ditangani FGE; 0 di luar FGE.** Tanpa `pacstrip`, setiap instruksi PAC non-hint itu akan trap ke FGE saat dieksekusi; `pacstrip` adalah langkah berikutnya.
- Reproducibility: build kedua dari nol menghasilkan kernel native `ce13aea1…` lagi (SHA-256 dan `LC_UUID` sama, tidak ada section yang berbeda).

Yang tidak dibuktikan: kernel collection ini belum di-`pacstrip`, belum masuk payload/boot image, dan belum dijalankan. Prelink yang lolos adalah syarat perlu, bukan bukti boot.

### Percobaan 10 — 2026-11-11, commit `c521ea5`, run [42997283204](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42997283204): catatan XnuPrelink lengkap

Prelink berhasil lagi. Catatan `kernel/kernel.json` XnuPrelink (`scripts/prelink_record.py`):

| Kunci | Nilai |
| --- | --- |
| `format` | `MH_FILESET` |
| `inputs.kernelcache_sha256` | `19ae26f46899…` (= pin profil `macos-26.5-25F71`) |
| `inputs.entry` | `com.apple.kernel` |
| `closure` | 87 kext dipertahankan |
| `collection_base` / `native_link_address` | `0xfffffff007004000` / `0xfffffff007004000` |
| `collection_slide` | `0x1f000000000` |
| pemasangan simbol (`kernel.map.json`) | `symbol-names`: 3.384 fungsi, 292 data, semuanya lewat nama simbol |
| **`missing`** | **kosong**: tidak ada target kext yang tidak terpasang |
| **`stubbed`** | **kosong**: tidak ada target yang di-stub (`allow_missing` false) |
| `mapping_complete` | **true** |
| `native_original_branches` | kosong |
| `personalities_dropped` | 7: hfs.encodings, IOAccessoryManager, IOPCIFamily, IOSerialFamily, IOSkywalkFamily, AppleUSBHostMergeProperties, AppleUSBHostPlatformProperties |
| `early_security_init` | `com.apple.driver.AppleMobileFileIntegrity` @ `0xfffffe00096f17cc` (= profil) |
| `runtime_qualified`, `loadable` | **false**: XnuPrelink selalu menulis false; tidak ada yang menguji kernel collection ini saat berjalan |
| `candidate_bytes` | 135.036.928 |

Jadi pemetaan statisnya lengkap (setiap referensi kext ke kernel terpasang ke simbol kernel native, tanpa stub). Itu belum bukti bahwa kernel collection ini berjalan.

**Reproducibility antar-commit**: kernel native run ini (`4f0e748c…`) berbeda dari percobaan 9 (`ce13aea1…`) meski source kernelnya sama. Satu-satunya perbedaan adalah `__TEXT,__const`, string versi: tanggal dipin dari waktu commit HEAD, dan HEAD berganti karena commit yang hanya mengubah alat dan dokumen. Mulai commit berikutnya tanggal diambil dari commit terakhir yang mengubah input kernel (`devices/pipa`, `profiles`, `kernel`, `third_party`, `.gitmodules`), sehingga commit dokumen atau CI menghasilkan kernel yang identik. Diverifikasi di percobaan 11 dan 12.

### Percobaan 11 — 2026-11-11, commit `984c8f5`, run [42998883741](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/42998883741): semua langkah hijau; pin tanggal antar-commit belum berlaku

- Compile + link: kernel native `226b3dba8eef8dc9e6cb394b0941efb10d015340f21dba466318a60658a7d26b`, 25.048.584 byte, `__TEXT` `0x188000`, 0 import; FGE (`sleh_synchronous` → `fge_xnu_handle`) dan null-PAC (`ml_addrperm_pacga`) terverifikasi di kode mesin; sensus 57.243 word PAuth, 0 di luar FGE.
- Tata letak: muat, sisa 42.976 byte.
- Prelink: `MH_FILESET` arm64e 135.036.928 byte, SHA-256 `79d228cc9953dc7c5b1c9a08386e597c172b139180147d0249cf2b669adf7b09`, 0 import, 0 di luar FGE; catatan XnuPrelink: `missing` {}, `stubbed` {}, `mapping_complete` true, 87 kext, 3.384 fungsi + 292 data terpasang lewat nama simbol, input native = kernel run ini.
- Build kedua dari nol di run yang sama: identik (SHA-256, `LC_UUID`, semua section, link-edit, string versi).
- Tetapi tanggal versi adalah 09:52:50 UTC (waktu `984c8f5` sendiri), bukan 09:18:20 (`50736cd`, commit input kernel terakhir). Penyebab: `actions/checkout` mengambil 1 commit; di clone dangkal commit itu tampak mengubah setiap path, jadi `git log -1 -- <input>` mengembalikan HEAD. Diperbaiki: `fetch-depth: 0` di `kernel-build.yml`, dan `pipa_unixnu.py` memberi peringatan bila clone dangkal.

### Percobaan 12 — 2026-11-11, commit `4250b45`, run [43011657003](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43011657003): **reproducible antar-commit**

Tidak ada input kernel yang berubah sejak `50736cd`; dengan checkout penuh tanggal build menjadi 09:18:20 UTC, sama dengan percobaan 9 (tanpa peringatan clone dangkal). Hasilnya, dari commit lain dan sekitar empat jam kemudian:

| | Percobaan 9 (`50736cd`) | Percobaan 12 (`4250b45`) |
| --- | --- | --- |
| Kernel native (SHA-256) | `ce13aea1586d2e425b10f48170d884f2b0f4af1348ab32ae459f3074e7e5ddec` | **sama** |
| Kernel collection hasil prelink (SHA-256) | `840488d5d4b6ea38df85bbe210b24e170bbe012f28c47ff53936697a5dc66e3c` | **sama** |

- Build kedua dari nol di run yang sama: identik juga (SHA-256, `LC_UUID`, semua section, link-edit, string versi).
- Prelink deterministik: input yang sama menghasilkan kernel collection yang sama bit demi bit. Catatan XnuPrelink lagi-lagi `missing` {}, `stubbed` {}, `mapping_complete` true, input native = `ce13aea1…`.
- FGE dan null-PAC tetap terverifikasi di kode mesin; 0 import chained fixup; tata letak muat dengan sisa 42.976 byte.

Sumber ketidak-reproducible-an yang diaudit:
- **Timestamp**: string versi dari `newvers.pl`. Satu-satunya sumber; kini dipin.
- **Debug map (N_OSO)**: sudah nol karena `ZERO_AR_DATE`.
- **Build path**: tidak lagi di `__cstring` karena prefix map, dan tidak ada di string versi (`runner:ios-obj/...`).
- **Urutan arsip dan nondeterminisme compiler**: tidak ditemukan; tidak ada section lain yang berbeda.
- **Metadata build**: `LC_UUID` diturunkan dari isi, jadi ikut sama.

### Percobaan 13 — 2026-11-12, commit `3b3e1be`, run [43132343953](https://github.com/BxiiDN/macOS-Pad-6/actions/runs/43132343953): **arsip storage pipa ter-compile** (G2)

`[storage-build]`: setelah langkah kernel, `scripts/pipa_storage_build.py` menjalankan resep UniXNU `build-sheng-source-storage.py` (dengan `patches/unixnu` 0001 + 0003) di tree yang sama, dengan env board (`UNIXNU_SOC=SM8250`, `UNIXNU_SOURCE_STORAGE_ROOT=none`, `UNIXNU_KIT=pipa`, target `macosx` 26.5 25F71) dan IOStorageFamily `7edb88fb` (pin resep, sumber publik). Kernel native juga ter-compile dan ter-link di run ini (`227cbe63…`; tanggal build pindah karena input kernel berubah, keputusan 6).

| | |
| --- | --- |
| Arsip | `libShengSourceStorage.a`, 1.511.112 byte; **tidak di-link** ke kernel (profil macOS tidak memilih ShengUfs) |
| Simbol pipa | semua 13 terdefinisi (`native_source_storage_start`, `native_source_root_policies_load`, `native_verified_block_root_authorized`, `native_ufs_source_create`, `boot_log_tick`, `boot_reset_bootloader`, `pipa_storage_decision`, …) |
| Saklar SoC | perintah compile `NativeUfs.cpp` memuat `-DNATIVE_UFS_SOURCE_API=1 -DNATIVE_UFS_SM8250=1`; tidak ada `qcom,sm8550-ufshc` di objek |
| Kebijakan root | bundle 32 byte, 0 kebijakan (tidak ada root dari `userdata`) |

Jalan ke sana (setiap kegagalan nyata, diperbaiki di kode, bukan disembunyikan):

| Run | Commit | Berhenti di | Perbaikan |
| --- | --- | --- | --- |
| 43100104425 | `930893d` | Board check: seri patch dilaporkan hilang pada checkout `--in-place` | `series_present` membaca file asli dari `git show HEAD:` (`901576d`) |
| 43100577481 | `901576d` | resep: `tree/drivers/ShengUfs/NativeUfs.cpp` tidak ada (profil macOS tidak memilih ShengUfs/RamBlock/VerifiedRoot) | `ensure_inputs` me-link dari pin `feeds.toml` dan checkout UniXNU (`71a4597`) |
| 43102116643, 43103297025 | `71a4597`, `ccab691` | 5 error compile `NativeUfs.cpp`, tidak terlihat di log job | error dicetak dari log per sumber resep (`ccab691`, `b01bb09`) |
| 43105063854 | `b01bb09` | `kma_flags_t`, `KMA_KOBJECT`, `KMA_DATA`, `kmem_free`, `vm_map_protect`: PipaUfs `5c64c01` memakai antarmuka VM kernel iPadOS 17 | `patches/shengufs/0001`: `vm/vm_kern_xnu.h` + `mach_vm_protect`, seperti pin katalog ShengUfs `99d8bcd` (`8234313`) |
| 43106623934 | `8234313` | arsip jadi; `native_ufs_source_create` tidak terdefinisi; string compatible tidak ada di objek | `patches/shengufs/0002` (factory pin katalog); saklar SoC dicek dari command line (`3b3e1be`) |

Yang dibuktikan: lima sumber package pipa dan PipaUfs (dengan dua patch) ter-compile terhadap header xnu-12377.121.6 yang di-prepare kernel step, sebagai arm64e. Yang tidak: link ke kernel, perilakunya, apa pun di tablet.
