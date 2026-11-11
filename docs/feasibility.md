# Kelayakan: macOS Tahoe asli di Xiaomi Pad 6

> Diperbarui oleh audit Tahoe 26.x dengan data dari biner Apple asli: [tahoe-26-report.md](tahoe-26-report.md). Bila berbeda, laporan itu yang berlaku.

Ringkas: hambatan inti **bukan** boot, layar, atau GPU. Untuk iPadOS 17 semua itu sudah dikerjakan upstream (lihat [audit.md](audit.md)). Hambatan inti adalah **set instruksi CPU**: seluruh macOS untuk ARM adalah arm64e (ARMv8.3+ dengan Pointer Authentication), sedangkan Snapdragon 870 adalah ARMv8.2.

## 1. Fitur CPU yang hilang

Sumber: definisi CPU di LLVM 18 (`clang -mcpu=X -###`), dicek 2026-11-11.

| CPU | Fitur (ringkas) |
| --- | --- |
| Cortex-A77 (Kryo 585 Gold/Prime) | v8.2a, aes, crc, dotprod, fullfp16, lse, ras, rcpc, rdm, sha2, ssbs |
| Cortex-A55 (Kryo 585 Silver) | sama, **tanpa ssbs** |
| apple-a12 (iOS arm64e pertama) | v8.3a, **pauth, jsconv, complxnum** |
| apple-m1 (Mac pertama) | v8.5a, pauth, jsconv, complxnum, fp16fml, sha3, … |

Selisihnya, dan apa yang terjadi bila instruksi itu dijalankan di SM8250:

| Fitur | Instruksi | Di ARMv8.2 | Penanganan repo ini |
| --- | --- | --- | --- |
| PAuth (bentuk *hint*) | PACIBSP, AUTIBSP, PACIASP, … | NOP, aman | tidak perlu |
| PAuth (bentuk non-hint) | RETAB, BLRAA, BRAA, LDRAA, PACIA, AUTDA, PACGA, MSR APxKey | **UNDEFINED → trap** | `pacstrip` (statis) + FGE (trap) |
| JSCVT | FJCVTZS | trap | FGE |
| FCMA | FCMLA, FCADD | trap | **belum** (diaudit dulu) |
| FlagM / FlagM2 | CFINV, RMIF, SETF8/16, AXFLAG, XAFLAG | trap | FGE |
| SB | SB | trap | FGE |
| LRCPC2 | LDAPUR*, STLUR* | trap | FGE |
| DIT, SSBS (A55) | MSR DIT/SSBS | trap | FGE |
| SHA3/SHA512 | EOR3, BCAX, RAX1, XAR, SHA512* | trap | **belum** |
| FRINTTS | FRINT32/64 | trap | **belum** |

Probe `tests/device/cpu_features_probe` membaca bit `AT_HWCAP` dari kernel Android di tablet untuk memastikan tabel ini di perangkat nyata. **Belum dijalankan** di tablet: tidak ada perangkat di lingkungan build ini.

## 2. Mengapa "null PAC" konsisten

PAC menandatangani pointer dengan kunci rahasia per boot. Profil arm64e UniXNU mencatat bahwa *tidak ada tanda tangan yang dihitung di luar perangkat*: dyld menandatangani saat memuat, XNU menandatangani pointer kernel collection saat boot. Jadi semua tanda tangan dibuat oleh instruksi PAC di perangkat itu sendiri.

Bila **semua** instruksi tanda tangan menjadi identitas dan semua autentikasi juga identitas, setiap pointer "bertanda tangan" sama dengan pointer aslinya, dan setiap autentikasi berhasil. Program berperilaku sama seperti di CPU ber-PAC tanpa serangan. Yang hilang adalah **proteksi keamanan** PAC: serangan ROP/JOP tidak lagi tertahan. Ini harus dinyatakan jujur ke pengguna akhir.

PACGA (MAC generik 32-bit) tidak bisa dibuat identitas; FGE mengembalikan fungsi deterministik per boot, cukup karena nilainya hanya dibandingkan dengan nilai lain hasil PACGA di perangkat yang sama.

## 3. Mengapa penulisan ulang statis (pacstrip) wajib untuk kernel

Kode arm64e mengakhiri hampir setiap fungsi dengan `RETAB` (non-hint). Bila hanya mengandalkan trap:

- setiap return fungsi di kext Apple memicu exception (puluhan ribu siklus per trap);
- bila XNU sendiri dikompilasi arm64e, handler trap juga berakhir dengan `RETAB`, sehingga terjadi rekursi tak terbatas.

UniXNU me-*prelink* kernel collection di host, jadi kode kernel dan kext tersedia sebelum boot. `tools/isa/pacstrip` menulis ulang setiap instruksi PAC non-hint ke padanan ARMv8.2 yang **setara persis di bawah null PAC** (RETAB→RET, BLRAA→BLR, LDRAA→LDR/LDUR, PACIA→NOP, …). Tes membandingkan hasil decode LLVM sebelum dan sesudah. Sisanya (PACGA, LDRAA dengan offset negatif di bawah −256) ditangani FGE saat trap. `tools/isa/audit --fail-on PAuth,…` menjadi gerbang build.

## 4. Userland macOS: masalah terbuka

dyld shared cache macOS juga arm64e. Ada dua jalan, keduanya belum dikerjakan:

1. **Hanya trap (FGE di EL0).** Benar secara fungsi, tetapi setiap return fungsi di framework sistem memicu trap. Perkiraan kasar: ratusan ribu sampai jutaan trap per detik saat UI aktif. Hampir pasti terlalu lambat untuk desktop. Angka sebenarnya harus **diukur**: jalankan `tools/isa/audit` pada dyld shared cache IPSW 26C5035r untuk hitungan statis, lalu ukur counter FGE di perangkat.
2. **pacstrip pada dyld shared cache.** Cepat, tetapi halaman kode cache diverifikasi dengan hash code signature dan cryptex. Perlu dipelajari apakah jalur owner trust UniXNU bisa menerima cache yang dimodifikasi. Ini pertanyaan terbuka nomor 1.

Selain PAC, frekuensi FCMA/SHA3/FRINTTS di userland belum diketahui. Audit IPSW akan menentukan apakah FGE perlu menanganinya.

## 5. Tahoe 26.x vs profil 27.3

Profil macOS UniXNU menargetkan macOS 27.3. Untuk Tahoe, distribution-macOS `macos-265` menunjukkan bahwa **26.5 = xnu-12377.121.6**, revisi yang sama dengan yang dipakai UniXNU. Profil `macos-26.5-25F71` dibuat dari IPSW resmi dan hanya membuang 4 patch Darwin 26 (rinciannya di [tahoe-26-report.md](tahoe-26-report.md) §2). Hambatan PAC sama, karena macOS untuk ARM selalu arm64e.

## 6. Komponen proprietary Apple (tidak bisa dibuat ulang, tidak boleh didistribusikan)

Kernelcache dan semua kext, dyld shared cache dan semua framework (WindowServer, AppKit, Metal, CoreAnimation), Finder, Dock, Safari, System Settings, trust cache, dan konten cryptex. Semuanya berasal dari IPSW yang diunduh pengguna dari server Apple oleh `unixnu fetch`. Repo ini tidak mengunggah binary Apple apa pun.

EULA macOS hanya mengizinkan instalasi pada hardware bermerek Apple. Ini masalah lisensi pengguna, bukan teknis. README menyatakannya.

## 7. Kesimpulan

| Pertanyaan | Jawaban saat ini |
| --- | --- |
| Bisakah XNU berjalan di SM8250? | Ya. Upstream sudah menjalankannya dengan iPadOS 17 (arm64). |
| Bisakah kernel macOS (arm64e) berjalan di SM8250? | Mungkin, dengan pacstrip pada kernel collection + FGE. **Belum diuji** di perangkat. |
| Bisakah userland macOS berjalan? | Belum diketahui. Bergantung pada pertanyaan terbuka §4. |
| Apakah ada yang lebih dekat ke "macOS asli di tablet Xiaomi"? | Ya: Xiaomi Pad 6S Pro (SM8550, punya PAC) sudah menjalankan macOS 27.3 sampai WindowServer di UniXNU-sheng. |
