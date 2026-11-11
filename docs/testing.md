# Pengujian

```sh
scripts/test.sh          # semua tes host, cross-compile, probe, cek patch (bila XNU tersedia)
```

Butuh: Python ≥ 3.11, clang dengan target AArch64, `llvm-mc`, `ld.lld`. Encoding instruksi di tes **dihasilkan oleh llvm-mc saat tes berjalan**, bukan diketik tangan.

| Tes | Yang dibuktikan | Yang tidak dibuktikan |
| --- | --- | --- |
| `tests/fge/test_fge.py` | Semantik setiap instruksi FGE terhadap model Python independen: FJCVTZS (model rasional dari pseudocode Arm, 40.000+ vektor), flag (tabel kebenaran lengkap), LRCPC2 semua ukuran/sign-extension, LDRAA offset/writeback, state tidak berubah saat fault | Perilaku di CPU nyata |
| `tests/fge/test_fge_fuzz.py` | Decoder FGE dan disassembler LLVM sepakat pada 28.000 encoding acak di sekitar setiap kelas | Encoding di luar sampel |
| `tests/isa/test_isa.py` | Mask fitur sepakat dengan LLVM; setiap rewrite pacstrip setara (decode LLVM sebelum/sesudah); data-in-code utuh; parsing fat, MH_FILESET, dyld cache | Kernel collection Apple asli |
| `tests/xnu_shim/check.sh` | Glue XNU lolos compile dengan deklarasi yang disalin dari xnu-12377.121.6 | Build kernel XNU sebenarnya |
| `scripts/gen_xnu_patch.py --check` | Patch yang di-commit sesuai sumber dan apply bersih ke xnu `ac9718fb1af6` | — |
| `build/device/cpu_features_probe` | Dibangun sebagai ELF static-PIE AArch64 tanpa relokasi | Hasil di tablet (belum dijalankan) |

## Uji di perangkat (non-destruktif)

Hanya probe yang aman dijalankan sekarang:

```sh
adb push build/device/cpu_features_probe /data/local/tmp/
adb shell /data/local/tmp/cpu_features_probe
```

Probe hanya membaca `/proc/self/auxv` dan sysfs. Simpan output ke `docs/evidence/`.

Repo ini tidak melakukan flashing otomatis. `fastboot boot` tidak menulis apa pun ke tablet. `fastboot flash userdata` (dibutuhkan root image UniXNU) **menghapus data Android**: cadangkan dulu.
