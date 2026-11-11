# macOS-Pad-6

Riset dan implementasi untuk menjalankan **macOS asli (XNU + userland Apple)** di **Xiaomi Pad 6** (pipa, Snapdragon 870 / SM8250, Adreno 650), di atas [UniXNU](https://github.com/UniXNU/UniXNU) dan port pipa milik [xVanTuring](https://github.com/xVanTuring/UniXNU-pipa).

> **Status: Tahoe belum boot di Pad 6.** Target: **macOS Tahoe 26.5 (25F71)**, rilis Tahoe terbaru yang source kernelnya (xnu-12377.121.6) dipublikasikan Apple. Yang sudah ada:
>
> - audit biner Tahoe asli (IPSW resmi 26.5 dan sistem 26.7.2 di runner Apple Silicon);
> - profil UniXNU `macos-26.5-25F71` yang dibuat dari IPSW itu;
> - rantai patch XNU untuk pipa (118/118 apply);
> - lapisan yang menangani hambatan utama: CPU Pad 6 (ARMv8.2) tidak punya Pointer Authentication, sedangkan seluruh macOS untuk ARM adalah arm64e.
>
> Laporan lengkap ada di [docs/tahoe-26-report.md](docs/tahoe-26-report.md); status per fitur di [docs/compatibility.md](docs/compatibility.md).

Ini bukan launcher, tema, simulator, atau skin.

## Kenapa sulit

| | iPadOS 17 | macOS (Tahoe 26 / 27.x) |
| --- | --- | --- |
| ABI | arm64 (tanpa PAC) | **arm64e** (ARMv8.3+, PAC) |
| Di Pad 6 (upstream) | sampai home screen, Metal lewat Turnip | belum |
| Hambatan | — | instruksi PAC dan beberapa instruksi v8.3–8.5 **trap** di Cortex-A77/A55 |

Penjelasan lengkap: [docs/feasibility.md](docs/feasibility.md). Audit proyek upstream: [docs/audit.md](docs/audit.md).

## Isi repo

| Path | Isi |
| --- | --- |
| `kernel/fge/` | **FGE**: emulator C tanpa libc untuk instruksi ARMv8.3–8.5 yang tidak dimiliki SM8250: PAuth sebagai *null PAC*, FJCVTZS, FlagM/FlagM2, SB, LDAPUR/STLUR, DIT/SSBS, SHA3, SHA512, register kunci PAC |
| `kernel/xnu/`, `kernel/patches/xnu-12377/` | Integrasi ke handler exception XNU; patch untuk xnu-12377.121.6 (revisi yang dipin UniXNU) |
| `tools/isa/pacstrip.py` | Menulis ulang instruksi PAC di kernel collection ke padanan ARMv8.2 yang setara persis, sebelum boot |
| `tools/isa/audit.py` | Sensus instruksi bermasalah di Mach-O / kernel collection / dyld shared cache; juga gerbang build |
| `tests/device/cpu_features_probe.c` | Probe read-only untuk tablet (Android, tanpa root) |
| `profiles/macos-26.5/` | Profil OS UniXNU Tahoe 26.5 (`unixnu/`), seri SoC SM8250, patch null-PAC + FGE untuk pipa |
| `tools/isa/ipsw.py`, `tools/isa/tahoe_audit.py` | Pembaca IPSW resmi via HTTP range, dan audit Tahoe (dijalankan di `.github/workflows/tahoe-audit.yml`) |
| `docs/evidence/tahoe-26.5/` | Bukti audit: angka, versi, dan hash (tanpa kode Apple) |
| `third_party/` | UniXNU, UniXNU-pipa, uefi-pipa sebagai submodul yang dipin |
| `docs/` | laporan Tahoe 26.x, audit, kelayakan, arsitektur, kompatibilitas, boot, driver, pengujian, roadmap |

## Mencoba

```sh
git clone https://github.com/BxiiDN/macOS-Pad-6 && cd macOS-Pad-6
scripts/test.sh                     # tes host, cross-build, cek patch (XNU=... opsional)
```

Di tablet (aman, hanya membaca):

```sh
scripts/build-probe.sh
adb push build/device/cpu_features_probe /data/local/tmp/
adb shell /data/local/tmp/cpu_features_probe
```

Probe juga tersedia sebagai artefak di setiap run CI.

## Batasan yang tidak berubah

- **Lisensi Apple.** Repo ini tidak berisi dan tidak akan berisi binary, firmware, atau IPSW Apple. Semuanya diunduh pengguna sendiri lewat `unixnu fetch`. EULA macOS hanya mengizinkan instalasi pada hardware Apple; itu tanggung jawab pengguna.
- **Keamanan.** *Null PAC* membuat kode arm64e berjalan tanpa proteksi PAC.
- **Data.** Repo ini tidak melakukan flashing. Menulis root image UniXNU ke `userdata` menghapus data Android.

## Kredit

UniXNU contributors, xVanTuring (UniXNU-pipa, uefi-pipa, driver pipa), Mu-Silicium / DuoWoA, dan Apple (XNU, APSL 2.0). Daftar lengkap: [THIRD_PARTY.md](THIRD_PARTY.md).

Lisensi: BSD-2-Clause-Patent ([LICENSE](LICENSE)), sama dengan UniXNU.
