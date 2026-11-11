# Perangkat keras Xiaomi Pad 6 (pipa, SM8250)

Riset perangkat keras untuk migrasi board pipa. **Tidak ada yang dijalankan di tablet oleh repo ini.** Setiap fakta di bawah diberi label sumbernya:

| Label | Sumber | Artinya |
| --- | --- | --- |
| **ML** | DT mainline Linux `sm8250-xiaomi-pipa.dts` (+ `sm8250.dtsi`, `pm8150*.dtsi`), commit `067c5c24cef2` | deskripsi publik yang di-review; bukan hasil uji |
| **AN** | dibaca upstream (UniXNU-pipa) dari tablet di bawah Android: `android-devinfo`, DT vendor, sysfs | pengamatan pihak lain |
| **UP** | dilaporkan upstream xVanTuring/UniXNU-pipa berjalan di tablet (iPadOS 17, 2026-10-23/24) | klaim pihak lain, tidak diulang di sini |
| **RP** | diperiksa oleh repo ini | statis saja (build, perbandingan, host test) |

Alat: `scripts/pipa_hw.py` (ambil, kompilasi, periksa, inventaris). Inventaris lengkap yang dihasilkan: [evidence/hardware/pipa-mainline-inventory.md](evidence/hardware/pipa-mainline-inventory.md).

## 1. Device tree: konstanta repo vs mainline

`scripts/pipa_hw.py check` membaca setiap konstanta perangkat keras **langsung dari kode board** (`#define` di `package/*.h`, array dan `constexpr` di `*.c`/`*.cpp`, `board.toml`, dan `dts/pipa.dts` dengan `sm8250.dtsi` feed SoC), lalu membandingkannya dengan DTB mainline. CI menjalankannya di setiap push.

Hasil (RP, 2026-11-11): **52 cocok, 0 berbeda**, 2 tidak ada di mainline, 1 tidak ada di repo.

| Area | Yang dicocokkan |
| --- | --- |
| CPU | 8 MPIDR (`0x000..0x700`), klaster E = core kapasitas rendah (0–3), GICv3 dist `0x17a00000` / redist `0x17a60000`, 3 domain EPSS (`0x18591000/2000/3000`, CPU 0–3, 4–6, 7) |
| Backlight | KTZ8866 di I2C11 `0xa8c000` 400 kHz alamat `0x11`, enable TLMM 139, bias TLMM 130/131, 5 sink, ramp 128/1 ms, bias LCD (`BacklightBoard.h`) |
| Memori | command DB AOP `0x80860000+0x20000`, zona console ramoops `0x200000`, splash `0x9c000000+0x2300000`, 1800×2880 |
| GPU | Adreno 650 `0x3d00000+0x40000` (`qcom,adreno-650.2`), GMU `0x3d6a000`, RSCC `0x3de0000`, GPUCC `0x3d90000`, SMMU GPU `0x3da0000`, GCC, SPI 300, stream GPU `{0,1,0x400,0x401}` dari `<0 0x401>`, stream GMU `{5,0x405}` dari `<5 0x400>`, region zap `0x8681a000+0x2000` |
| Touch (bus) | QUP0 `0x9c0000`, SE4 SPI `0x990000+0x4000`, stream SMMU QUP0 `0x5a3`, apps SMMU `0x15000000`, ubin TLMM selatan `0xf500000`/utara `0xf900000`, pin SPI GPIO 8–10 + CS 11 fungsi `qup4` |
| Input | PON PM8150 PPID `0x008`, volume turun = PON RESIN (`KEY_VOLUMEDOWN`), volume naik = GPIO6 PM8150 (PPID `0x0c5`) active-low |
| Daya | PM8150B di USID 2 (fuel gauge `0x4000`, charger SMB5 `0x1000`), kapasitas desain 8840 mAh |
| Feed SoC | register, SPI GIC, dan stream SMMU node `ufs`, `ufsphy`, `gpu`, `gmu`, `gpu_smmu`, `qupv3_id_0` = mainline |

Dua aturan pembandingan yang disengaja:

- Node GPU feed menambahkan `cx_mem` (`0x3d9e000`) dan `cx_dbgc` (`0x3d61000`) dari tree kgsl vendor. Yang diperiksa: semua range mainline ada di feed.
- Node USB feed memakai ukuran `kona-usb.dtsi` vendor dan dinonaktifkan. Yang diperiksa: alamat dasar (`0xa600000`).

Tidak tercakup mainline (bukan bukti salah atau benar):

- **Pengontrol touch** NT36532 (attention TLMM 39): mainline pipa tidak punya node touch; `spi4` dinonaktifkan.
- **Fuel gauge dan charger PM8150B**: mainline tidak punya node-nya; PPID di `NativeBatteryBoard.h` dari DT Android.
- **Timer arsitektur**: `pipa.dts` dan `sm8250.dtsi` feed tidak punya node timer. Mainline: PPI 13, 14, 11, 10 (INTID 29, 30, 27, 26); timer virtual INTID 27 sesuai yang dipakai ArmCpu. Komentar di board format 1 menulis PPI ke-4 = 12; mainline 10 (timer hypervisor), tidak berpengaruh.

Uji negatif: mengubah `TB_SE_BASE` ke `0x994000` membuat pemeriksaan gagal (`MISMATCH`, exit 1).

## 2. Inventaris perangkat keras

| Komponen | Fakta | Sumber |
| --- | --- | --- |
| SoC | SM8250 v2.1 (`qcom,msm-id <SM8250 0x20001>`, `board-id <0x34 0>`) | ML |
| CPU | 4× Kryo 585 Silver (Cortex-A55, kapasitas 448), 3× Gold + 1× Gold Prime (Cortex-A77, 1024); 3 domain frekuensi EPSS | ML |
| RAM | 3 bank: `0x80000000+0x37700000`, `0xc0000000+0x1c0000000`, `0x800000000+0x200000000` (unit referensi 16 GB) | AN |
| Storage | UFS 3.1 SK hynix HN8T05DEHKX073, host `0x1d84000` (SPI 265), stream SMMU `0xe0`, `0x4e0`; regulator VCC L17A 3,0 V, VCCQ L6A 1,2 V, VCCQ2 S4A 1,8 V | ML (host), AN (chip) |
| Panel | `mdss_dsi_m82_36_02_0a_dual_dphy_video`: dual DSI, mode video, 1800×2880, 120 Hz | AN |
| Display | MDSS `0xae00000` (SPI 83), DPU `0xae01000`, DSI0 `0xae94000`, DSI1 `0xae96000`, PHY DSI 7 nm, DISPCC `0xaf00000`; **dinonaktifkan di mainline pipa** | ML |
| Backlight | Kinetic **KTZ8866** di I2C11 (`0xa8c000`) alamat `0x11`, enable TLMM 139, bias ±5,5 V lewat TLMM 130/131, 5 sink | ML |
| Frame buffer boot | `0x9c000000`, 1800×2880, stride 7200, `a8r8g8b8` | ML |
| GPU | Adreno 650 v3 (chip ID `0x06050002`), OPP 305–670 MHz, GMU 200 MHz, firmware zap `a650_zap.mbn` (mainline) / `a650_zap.elf` (partisi vendor) | ML, AN |
| Touch | Novatek NT36532, GENI SPI QUP0 SE4 9,6 MHz, attention TLMM 39, firmware `novatek_nt36532_m82_fw_tm.bin`, rentang 0..17999 × 0..28799 | AN |
| Tombol | power = PON KPDPWR, volume turun = PON RESIN, volume naik = GPIO6 PM8150 | ML |
| PMIC | PM8150 (USID 0/1), PM8150B (2/3: charger, fuel gauge, Type-C), PM8150L (4/5: BOB, LPG, flash) | ML |
| Baterai | 8840 mAh, 34,3 Wh, 3,4–4,37 V | ML |
| USB | DWC3 `0xa600000` mode **peripheral**, PHY HS + QMP | ML |
| PCIe | PCIe0 aktif; perangkat di belakangnya (kemungkinan Wi-Fi) **tidak dideskripsikan** | ML |
| Prosesor jarak jauh | ADSP (audio), CDSP, SLPI (sensor), Venus (video), firmware `qcom/sm8250/xiaomi/pipa/*.mbn` | ML |
| Belum teridentifikasi dari sumber publik | chip Wi-Fi/Bluetooth, codec dan amplifier audio, kamera, sensor | — |

## 3. GPU Adreno 650

- **UP**: UniXNU-pipa menjalankan Adreno 650 di iPadOS 17: GMU cold start, GX, zap shader lewat PAS 13, ring 0, interrupt SPI 300, Metal lewat Turnip (40–54 fps), dengan cacat sudut membulat pada pass GMEM.
- **RP**: alamat, interrupt, stream SMMU, dan region zap yang dipakai `GpuProbe.cpp` dan `GpuPowerBoard.h` sama dengan mainline (bagian 1). Host test `GpuPowerBoardTests` lolos; `A650GmuTests` (urutan GMU a650 Linux v6.6 terhadap register yang dimodelkan) dijalankan CI di runner arm64, karena kit `AdrenoFirmware` hanya dibangun untuk AArch64.
- Kebutuhan dari DT untuk driver: clock GMU `GPU_CC_AHB_CLK`, `GPU_CC_CX_GMU_CLK`, `GPU_CC_CXO_CLK`, `GCC_DDRSS_GPU_AXI_CLK`, `GCC_GPU_MEMNOC_GFX_CLK`; domain `GPU_CX_GDSC`, `GPU_GX_GDSC`; OPP GPU 305, 400, 441, 490, 525, 587, 670 MHz (vote GX repo 305 MHz = OPP terendah).
- **Celah macOS (G3)**: `Adreno650` dan `AdrenoMetal` fork pipa bukan komponen katalog UniXNU; `AdrenoMetal` katalog bergantung pada Adreno740/Sm8550Platform. Kernel macOS pipa belum memilih GPU.

## 4. Display dan frame buffer

- **ML**: mainline pipa tidak mengaktifkan MDSS/DSI; Linux pipa hanya memakai `simple-framebuffer` dari splash bootloader.
- **UP**: iPadOS di pipa menggambar ke frame buffer firmware (GOP uefi-pipa) dengan salinan CPU (tanpa vsync, tearing), atau salinan GPU. `MdssProbe.cpp` hanya membaca.
- **Temuan baru (ML)**: kecerahan dikendalikan **KTZ8866** di I2C11, alamat `0x11`. Repo kini punya model board-nya (`package/BacklightBoard.h`: fakta + urutan register init dan kecerahan 11-bit, host test `BacklightBoardTests.c`), tetapi belum ada driver GENI I2C atau backlight di kernel, dan belum ada yang ditulis ke chip.
- **Kebutuhan macOS (G5)**: frame buffer bootloader cukup untuk tahap awal (UniXNU `GopFramebuffer`); kecerahan butuh driver GENI I2C (QUP1 SE3) + KTZ8866; display penuh butuh DPU + dual DSI + PHY 7 nm, yang belum ada di Linux mainline untuk panel ini.

## 5. Touchscreen dan input

- **AN/UP**: NT36532 di SE4 dengan `QcomGeniSpi` dan `PipaNovatekTouch`; laporan titik ±120/s; rentang yang dilaporkan firmware 18000×28800 (sepersepuluh piksel).
- **RP**: alamat SE4, pin SPI, stream SMMU QUP0, ubin TLMM sama dengan mainline; host test `TouchBoardTests`, `GesturesTests`, `ButtonsTests` lolos.
- Tombol: ketiganya terdeskripsi di mainline dan cocok dengan `ButtonsCore.h`.
- **Celah macOS (G5)**: pemasangan ke input HID macOS (WindowServer, multitouch) belum dikerjakan; driver touch iPadOS dari upstream belum dibangun untuk arm64e.

## 6. Interrupt, clock, regulator, daya

- **Interrupt**: GICv3 (dist + redist, 4 sel interrupt di feed, 3 di mainline); PDC `0xb220000` untuk interrupt wakeup (ADSP, SPMI); ringkasan TLMM SPI 208; arbiter SPMI dengan interrupt per periferal PMIC `<usid ppid irq type>`; MDSS punya pengontrol interrupt sendiri untuk DSI.
- **Clock**: `rpmhcc` (CXO), `gcc` `0x100000`, `gpucc`, `dispcc` (masukan dari PHY DSI dan USB), `videocc`, `camcc`.
- **Regulator**: RPMh lewat `apps_rsc` (`0x18200000`, 3 DRV): PM8150 (`a`) dan PM8150L (`c`), daftar lengkap di inventaris; regulator tetap `vph_pwr` 3,7 V dan bias backlight.
- **Domain daya**: `rpmhpd` (CX, MX, MMCX, LCX, LMX) dan GDSC (GPU CX/GX, MDSS, UFS, video).
- **Frekuensi CPU**: EPSS (`pipa-cpufreq=1` UniXNU-pipa meminta level tertinggi; **UP**).
- Board menulis `sleep-disabled = 1`: suspend/resume belum ada.

## 7. Kebutuhan driver G2–G6

Rinciannya ada di [board-migration.md](board-migration.md#kebutuhan-driver-g2g6).
