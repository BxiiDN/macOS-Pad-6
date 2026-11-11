# Laporan teknis: macOS Tahoe 26.x di Xiaomi Pad 6 (SM8250)

Tanggal: 2026-11-11. Target tetap: **macOS Tahoe 26.x asli** (XNU + userland Apple) di Xiaomi Pad 6.

**Tahoe belum boot di Pad 6.** Laporan ini memisahkan tiga jenis status:

- apa yang diukur dari perangkat lunak Apple asli;
- apa yang sudah diuji, tetapi hanya di host;
- apa yang masih terbuka.

## 0. Sumber bukti

| Bukti | Asal | File |
| --- | --- | --- |
| Pemetaan versi Tahoe ↔ XNU/dyld | tag `macos-260`…`macos-265` di apple-oss-distributions/distribution-macOS | §2 |
| Sistem Tahoe 26.7.2 (25G332) terpasang | runner GitHub `macos-26-arm64` (Apple M1 virtual), workflow `tahoe-audit.yml` run 42945525130 | [evidence/tahoe-26.5/host.json](evidence/tahoe-26.5/host.json), [host.md](evidence/tahoe-26.5/host.md) |
| Kernelcache Tahoe 26.5 (25F71) untuk J274AP (Mac mini M1) | IPSW resmi `UniversalMac_26.5_25F71_Restore.ipsw` dari updates.cdn-apple.com, dibaca dengan HTTP range + CRC-32 | [kernelcache-j274ap-25F71.json](evidence/tahoe-26.5/kernelcache-j274ap-25F71.json) |
| Image OS / SystemOS / AppOS 26.5 | IPSW yang sama; AEA didekripsi dengan kunci yang dipublikasikan Apple; SHA-256 + UUID volume APFS | [images-26.5.json](evidence/tahoe-26.5/images-26.5.json) |
| Profil 26.5 dimuat oleh UniXNU | `unixnu status` (UniXNU `3fd6a3cf0e6f`, board UniXNU-sheng `f3e60cab`, SoC sm8550 `97665e28`) | [unixnu-status.json](evidence/tahoe-26.5/unixnu-status.json) |

Hanya angka, nama, versi, dan hash yang dipublikasikan. Tidak ada kode Apple yang keluar dari runner.

## 1. Persyaratan CPU

### 1.1 Yang dipakai Tahoe, diukur

Instruksi di luar ARMv8.2+RCpc+DotProd (yaitu yang tidak dimiliki Cortex-A77/A55), dihitung secara statis di section instruksi:

| Kelas | dyld shared cache 26.7.2 (3.648 image, 2,95 GB kode) | Kernelcache 26.5 J274AP (346 kext) | Di SM8250 | Penanganan |
| --- | ---: | ---: | --- | --- |
| PAC non-hint (RETAB, BLRAA, PACIA, AUTDA, …) | 26.929.850 | 778.238 | trap | pacstrip (statis) + FGE |
| PAC MSR/MRS kunci | 0 | 102 | trap | pacstrip / FGE / patch null-PAC |
| PACGA | 724 | 42 | trap | FGE (tidak bisa ditulis ulang) |
| LDRAA/LDRAB | 22 | 0 | trap | pacstrip; sisanya FGE |
| ERETAA/ERETAB | 0 di kode | 0 | trap | pacstrip saja (tidak bisa diemulasi) |
| JSCVT (FJCVTZS) | 1.009 (JavaScriptCore, WebCore) | 0 | trap | FGE |
| SHA3 (EOR3, BCAX, XAR) | 14.766 (AuthKit, AppleAccount, AOSKit, Osprey, corecrypto, …) | 257 | trap | **FGE** (baru, dicek terhadap QEMU) |
| SHA512 + RAX1 | 1.197 (corecrypto, **dyld**, libMobileGestalt, …) | 154 | trap | **FGE** (baru) |
| DIT, SB, LRCPC2 | 192 / 7 / 15 | 27 / 4 / 4 | trap | FGE |
| FCMA (FCADD, FCMLA) | 25.274 (libBLAS, libSparseBLAS, VectorKit, ShazamKit, libsystem_m 1) | 0 | trap | **belum** |
| FHM (FMLAL/FMLSL) | 128 (hanya libBNNS) | 0 | trap | **belum** |
| FRINTTS, FlagM, FlagM2 | 0 di kode | 0 | trap | FGE (FlagM) / belum (FRINTTS) |
| BTI, SSBS | — | — | tidak dibutuhkan | runner M1 melaporkan `FEAT_BTI 0`, `FEAT_SSBS 0` dan Tahoe tetap berjalan |

Cuplikan disassembly di sekitar setiap temuan (di file bukti) memastikan semua ini kode sungguhan. Run pertama sempat menghitung string `__TEXT` (misalnya FCMLA "palsu" dari byte `o` dan `/`). Kesalahan itu sudah diperbaiki dan dibahas di §7.

### 1.2 Pilihan kernel M1 (t8103)

Kernel per-SoC di runner menunjukkan bahwa kernel untuk M2 dan yang lebih baru memakai **LRCPC2 (592–606×)**, sedangkan kernel M1 (`t8103`) tidak memakainya sama sekali. Karena itu profil memakai identitas **Mac mini M1 (J274AP, kernelcache `mac13g`)**: CPU tertua yang didukung Tahoe dan selisih ISA terkecil terhadap SM8250.

### 1.3 Jalur kompatibilitas yang sudah ada di Tahoe

dyld-1378 (dyld milik 26.5) memilih **function variants** berdasarkan `hw.optional.arm.caps` untuk flagm, flagm2, fhm, dotprod, sha3, sha512, sb, frintts, lrcpc2, fcma, dan jscvt. XNU 26.5 mengisi caps itu dari register ID CPU (`commpage_init_arm_optional_features_isar1`). Akibatnya, di SM8250 caps itu akan kosong untuk fitur-fitur tersebut, dan dyld memilih varian default bila fungsi itu punya varian.

Kalimat "bila fungsi itu punya varian" belum diukur. Tabel di atas adalah batas atas: belum dipisahkan kode yang dilindungi pemeriksaan runtime dari kode yang tidak. **PAuth tidak termasuk daftar varian**, jadi tidak ada jalur kompatibilitas bawaan untuk PAC.

## 2. Persyaratan kernel

| Rilis | XNU | dyld |
| --- | --- | --- |
| 26.0 | xnu-12377.1.9 | dyld-1323.3 |
| 26.1 | xnu-12377.41.6 | dyld-1330 |
| 26.2 | xnu-12377.61.12 | dyld-1335 |
| 26.3 | xnu-12377.81.4 | dyld-1340 |
| 26.4 | xnu-12377.101.15 | dyld-1376.6 |
| **26.5** | **xnu-12377.121.6** (`ac9718fb1af6`) | **dyld-1378** |
| 26.6 / 26.7 | belum dipublikasikan (runner 26.7.2: xnu-12377.161.15) | — |

Konsekuensinya:

- **Target: Tahoe 26.5**, satu-satunya rilis Tahoe terbaru yang source kernelnya cocok persis. Ini juga revisi yang dipakai UniXNU.
- **Perbedaan 26.5 vs 27.3:** profil 27.3 UniXNU menjalankan kernel 26.5 dengan **4 patch Darwin 26** (syscall, KPI, shared region, KPI macOS) agar userland 27.3 jalan. Untuk 26.5 keempatnya tidak boleh dipasang. Patch macOS lain (firmlink, cryptex, union root, timebase 24 MHz, dan seterusnya) tetap diperlukan.
- **Bukti apply** (`scripts/check_patch_chain.py`): rantai 27.3 asli apply 120/120 (validasi alat). Rantai pipa Tahoe 26.5 apply **120/120** (urutan `devices/pipa/board.toml`), terdiri dari seri arm64e UniXNU, lapisan SoC SM8250 arm64e, seri OS tanpa 4 patch Darwin 26, patch AMP pipa, patch null-PAC, patch FGE, dan default fitur board yang belum ada (owner root, exit trace).
- **Kernel harus arm64e dengan `HAS_APPLE_PAC`.** Tanpanya `ml_grade_binary` menolak biner arm64e (`cpu_subtype` hanya ARM64E bila `HAS_APPLE_PAC`), padahal semua biner sistem Tahoe adalah `x86_64 arm64e` saja (§3).
- **Mode null-PAC** (`devices/pipa/patches/xnu-12377/null-pac-armv82.patch`):
  - tidak ada pemrograman register kunci;
  - bit EnIA/EnIB/EnDA/EnDB tidak diset (RES0 di v8.2);
  - hash thread state konstan, karena `COMPUTE_THREAD_STATE_HASH` memakai 5 PACGA di **setiap exception**, sehingga emulasi trap akan rekursif;
  - `ml_addrperm_pacga` dan `ptrauth_utils_sign_blob_generic` tanpa PACGA.
- **pacstrip pada seluruh kernel collection wajib.** Locore XNU sendiri memakai `pacia`, `autia`, dan `braa` di jalur exception (15 instruksi tulisan tangan), dan kompiler arm64e memakai `retab` di setiap fungsi.
- **Hasil di kernelcache 26.5 nyata:** 778.340 instruksi PAC ditulis ulang, hanya 42 PACGA tersisa. Format fixup KC `64_KERNEL_CACHE`. Semua 67 root prelink profil 27.3 ada di KC 26.5.

## 3. Persyaratan userland

- **Tidak ada jalur arm64 (non-e).** `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/` hanya berisi `dyld_shared_cache_arm64e` (+ `x86_64` untuk Rosetta). dyld, launchd, WindowServer, Finder, Dock, loginwindow, System Settings, Terminal, Safari, dan amfid semuanya `x86_64 arm64e`.
- **Chained fixups:** executable memakai `ARM64E_USERLAND24` (beberapa `ARM64E`); shared cache memakai slide info **v5** (pointer auth arm64e). Di bawah null PAC, pointer bertanda tangan yang dibuat dyld atau pager kernel sama dengan pointer aslinya, karena penandatanganan menjadi identitas.
- **Bukti bahwa ABI ini tahan null PAC:** UniXNU (patch `native-pac-arm64-user-jop`) sudah menjalankan library sistem arm64e di dalam proses arm64 **dengan semua kunci PAC dimatikan** (semantik arsitektur kunci-mati = identitas), di perangkat SM8550 nyata. Apple sendiri berbeda: XNU 26.5 mempertahankan kunci dan memakai diversifier lain (`ml_non_arm64e_user_jop_pid`).
- **Masalah performa** (belum diukur di perangkat): 26,9 juta instruksi PAC non-hint di shared cache. Tanpa penulisan ulang, setiap `retab` di framework memicu trap.

## 4. Persyaratan GPU

- WindowServer dan Core Animation membutuhkan Metal. Di pipa, upstream sudah menjalankan Metal → Vulkan (Turnip) di iPadOS 17 (40–54 fps). Untuk macOS, UniXNU-sheng sudah membangun bundle `NativeAdrenoMetal.bundle` target macos27.
- Untuk Tahoe 26.5 di pipa: bundle itu harus dibangun untuk macOS 26 / Adreno 650, lalu ditaruh di `/Library/GPUBundles` (`gpu-addon=1`). **Belum dikerjakan.**
- Identitas dari DeviceTree J274AP: `graphics-featureset-class = APPLE7`. Profil memakai nilai Apple apa adanya; kecocokan dengan fitur Turnip/A650 belum dievaluasi.

## 5. Hambatan PAC: ringkasan

| Hambatan | Status |
| --- | --- |
| Instruksi PAC di kernel dan kext | **teratasi di host**: pacstrip pada KC 26.5 nyata, sisa 42 PACGA → FGE |
| PACGA di jalur exception (thread state) | **teratasi di source**: patch null-PAC, apply di rantai 120/120 |
| Register kunci PAC tidak ada di v8.2 | **teratasi di source** (null-PAC) + pacstrip (102 MSR di KC) |
| Kernel harus arm64e agar biner arm64e diterima | dipertahankan (`HAS_APPLE_PAC`) |
| ERETAA/ERETAB | hanya pacstrip (FGE tidak bisa: ELR ditimpa trap) |
| 26,9 juta PAC di dyld shared cache | **belum teratasi**: trap-only kemungkinan terlalu lambat; pacstrip cache terbentur verifikasi halaman kode |
| Keamanan | null PAC menghapus proteksi ROP/JOP. Dinyatakan, bukan disembunyikan |

## 6. Status solusi

### Sudah diuji (host)

- FGE: PAuth (null PAC), JSCVT, FlagM/FlagM2, SB, LRCPC2, DIT/SSBS, register kunci. **Baru:** SHA3 dan SHA512.
  - Diuji terhadap model Python, fuzz encoding terhadap LLVM, dan **oracle QEMU** (helper `crypto_helper.c` dikompilasi saat tes, tidak di-commit).
- Glue XNU:
  - akses memori single-copy atomic (perbaikan audit);
  - mode null-PAC dan penolakan mode thread-state bertanda tangan;
  - tes host glue (17 cek).
- pacstrip dan audit: scanner C dengan paritas Python; parsing fat, MH_FILESET, dyld cache multi-file, chained fixups, dan simbol.
- Rantai patch Tahoe 26.5 pipa 120/120, beserta pemeriksaan bahwa patch yang di-commit masih sesuai sumber.
- Board pipa format 2 (`devices/pipa`) dengan profil 26.5 sebagai default, di-resolve `unixnu status` (lihat [board-migration.md](board-migration.md)).
- Profil `macos-26.5-25F71` dimuat dan di-resolve oleh `unixnu status` (135 patch, nol patch Darwin 26).

### Eksperimental (ditulis, belum di-build sebagai kernel atau dijalankan di perangkat)

- Patch null-PAC dan FGE di dalam XNU.
- Profil 26.5: diisi dari IPSW resmi (pin kernelcache, AMFI `0xfffffe00096f17cc`, identitas J274AP, UUID volume dan hash image), tetapi belum pernah di-build menjadi payload.
- Seri SoC SM8250: dua patch generik dari SM8550, belum diuji di pipa.

### Belum terselesaikan

1. ~~Board UniXNU-pipa masih format 1~~: dimigrasi ke `devices/pipa` (format 2). Kernel dari board ini belum di-build ([kernel-build.md](kernel-build.md)).
2. FCMA dan FHM tidak diemulasi. Butuh FMA berpembulatan benar dalam integer, atau bukti bahwa libBLAS, libBNNS, dan libsystem_m memeriksa CPU dulu.
3. Performa PAC di userland (§3); pacstrip untuk dyld shared cache belum ada.
4. FRINTTS tidak diemulasi (0 di kode yang diukur).
5. Driver macOS untuk pipa (display IOMFB, HID, GPU bundle macOS, audio, Wi-Fi, Bluetooth).
6. Build kernel dan boot di perangkat: belum ada. **Tahoe belum boot.**

## 7. Koreksi dan batasan audit

- Run audit pertama (42944808472) menghitung data di `__TEXT` dyld cache sebagai kode, dan menghitung header fileset dua kali. Angka di atas berasal dari run 42945525130 yang memindai section instruksi per image. Cuplikan disassembly di bukti menunjukkan temuan berada di kode.
- Sensus bersifat statis: menghitung instruksi, bukan eksekusi, dan belum membedakan kode yang dilindungi function variants.
- Data userland berasal dari Tahoe 26.7.2 yang terpasang di runner, bukan dari image 26.5. Image 26.5 baru di-hash, belum disensus isinya.
