# Memperoleh firmware dan memory map pipa dengan aman

Status: **prosedur, bukan hasil.** Tidak ada yang dijalankan di tablet oleh repo ini. Setiap langkah di sini hanya membaca; tidak ada yang menulis partisi, menghapus data, atau mengubah Android. Yang menjalankan adalah pemilik, dan hanya setelah prosedur pemulihan di `docs/boot-readiness.md` terverifikasi.

Tujuan: mengganti model host (peta memori, firmware GPU/touch) dengan pengukuran nyata, dan menandai dengan jelas mana yang model dan mana yang terukur. Model **tidak boleh** disebut sebagai hasil pengukuran.

## Aturan

- Baca saja. Tidak ada `fastboot flash`, `fastboot erase`, `dd of=`, penulisan sysfs, atau pemrograman register.
- Simpan keluaran ke `docs/evidence/device/` dengan tanggal dan metode; beri label kelas bukti **DEV** (perangkat nyata), terpisah dari **AN** (dibaca pihak lain di Android), **FS** (sumber firmware), **ML/VND** (DT mainline/vendor), **RP** (repo ini, host/statis).
- Firmware perangkat **tidak** di-commit ke Git (lihat G4 `docs/board-migration.md`); hanya hash dan ukuran yang dicatat. Image biner tetap di `.cache/firmware` lokal.

## 1. Memory map (yang paling penting untuk boot)

Peta yang menentukan adalah peta memori UEFI saat boot (bukan `/proc/iomem` Android, yang menghilangkan rentang no-map). Dua cara membaca, keduanya read-only:

1. **Dari log firmware UniXNU.** Image uji (bila pemilik sudah memverifikasi pemulihan) menulis peta memori UEFI ke zona console ramoops (`RamoopsLogLib`, `0xB0000000`). Setelah `fastboot boot` lalu reboot ke fastboot, `scripts/read-pipa-log.py` membaca log itu. Ini mencetak deskriptor peta nyata (bank DDR, lubang firmware) yang `scripts/pipa_memory.py` dan `pipa_firmware_map.py` saat ini hanya memodelkan.
2. **Dari Android (sebagian, AN→DEV).** `adb shell su -c 'cat /proc/iomem'` dan `/sys/firmware/devicetree/base` memberi System RAM dan reserved-memory, tetapi ABL/kernel Android menyembunyikan sebagian; ini melengkapi, bukan menggantikan, peta UEFI.

Setelah terukur: ganti `BANKS` dan `RESERVED` di `pipa_memory.py` hanya bila sumbernya DEV, dan catat di `docs/evidence/device/`. Sampai itu, keduanya tetap model.

## 2. Firmware GPU (GMU, SQE, zap)

Dibutuhkan untuk `pipa-gpu` mode ≥ 7 (`build-pipa-gpu.py` → `GpuFirmware.c`). Sumber, semua baca saja dari partisi yang sudah ada (tidak menulis apa pun):

- `a650_gmu.bin`, `a650_zap.elf`: partisi vendor `/vendor/firmware` (atau `/firmware`). `adb pull` sebagai read, atau salin dari dump partisi vendor yang sudah dicadangkan.
- `a650_sqe.fw`: linux-firmware (`qcom/a650_sqe.fw`, git.kernel.org), publik.
- Simpan ke `.cache/firmware/gpu` dan `.cache/firmware/linux-firmware`; `build-pipa-gpu.py` mencatat hash dan ukuran di `build-report.json`. Tanpa image, firmware 0 byte dan `GpuProbe` berhenti di "no firmware" sebelum menyentuh GMU.

## 3. Firmware touch (NT36532)

- `novatek_nt36532_m82_fw_tm.bin` / `…_csot.bin`: tabel firmware bawaan kernel stok atau partisi vendor, dipilih per varian panel (`tv_config_for_variant`). Baca saja; simpan di `.cache/firmware/touch` (`PIPA_TOUCH_FIRMWARE`). Tidak di Git.

## 4. Identitas panel (TM vs CSOT)

Byte pembuat `mi,panel-id` tidak ada di tabel publik; ditentukan bootloader. Dua cara aman: baca dari `/sys` panel di Android (AN), atau dari boot-arg yang firmware teruskan ke `pnl_variant_select` saat boot UEFI (DEV, lewat log). Jangan menebak; varian tak dikenal → tidak ada firmware (`tv_config_for_variant` mengembalikan NULL).

## 5. Verifikasi, bukan asumsi

Setiap skrip yang membaca model mencetak kelas buktinya. `scripts/pipa_memory.py` dan `pipa_firmware_map.py` menandai hasilnya sebagai model/FS. Ketika data DEV masuk, skrip harus membandingkannya dengan model dan melaporkan selisih — bukan menimpa diam-diam. Belum ada data DEV: `docs/evidence/device/` kosong.
