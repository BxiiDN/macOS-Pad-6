# Display dan touchscreen pipa: temuan DT vendor dan struktur integrasi XNU

Status: **analisis statis dan host test saja.** Tidak ada yang di sini diprogram ke MDSS/DSI, panel, atau pengontrol touch, dan tidak ada yang dijalankan di tablet oleh repo ini. Layar di macOS pipa tetap frame buffer firmware (GOP, 1800×2880).

Sumber: `MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf` (publik), dicek otomatis oleh `scripts/pipa_hw.py vendor` (bagian display dan touch: 59 fakta; seluruhnya 81 cocok, 0 berbeda). Kode: `devices/pipa/package/PanelBoard.h`, `TouchVendor.h`, host test `PanelBoardTests.c`, `TouchVendorTests.c`.

## Reset GPIO panel

| | Nilai | Sumber |
| --- | --- | --- |
| Reset panel | **TLMM 75**, `qcom,platform-reset-gpio = <&tlmm 75 0>` | `xiaomi-sm8250-common.dtsi` `&dsi_m82_36_02_0a_dual_dphy_video` dan `&dsi_m82_42_02_0b_dual_dphy_video` |
| Pin state aktif | gpio, 8 mA, tanpa pull | `pipa-pinctrl.dtsi` `sde_dsi_active` (dipakai `sde_dsi` `pinctrl-0`) |
| Pin state suspend | gpio, 2 mA, pull-down | `sde_dsi_suspend` (`pinctrl-1`) |
| Tile TLMM | SOUTH (`PINGROUP(75, SOUTH, …)`), offset kontrol `0x54b000` | `pinctrl-sm8250.c` Linux |
| Urutan reset | 0 (10 ms), 1 (3), 0 (3), 1 (15) = 31 ms | `qcom,mdss-dsi-reset-sequence` kedua panel |
| TE | TLMM 66 | `qcom,platform-te-gpio` (board dan `sde_dsi`) |

Koreksi atas handoff sesi 6: reset GPIO **ada**. Berkas panel `dsi-panel-m82-*.dtsi` sendiri tidak menyebut GPIO reset; board file `xiaomi-sm8250-common.dtsi` (di-include `pipa-sm8250.dtsi`, dan memang ada di cabang `pipa-t-oss`) menambahkannya. Sesi 6 tidak mem-fetch berkas itu. `VENDOR_FILES` sekarang memuatnya dalam urutan include.

Catatan: `pipa-sm8250.dtsi` men-set `qcom,dsi-default-panel = <&dsi_k81_42_02_0a_dual_cphy_video>` (panel lain); panel yang dipakai dipilih bootloader lewat command line, jadi tidak dianggap fakta pipa.

## Catu daya panel

`dsi_panel_pwr_supply_m82` (pipa-sm8250.dtsi), urutan nyala: vddio 1,8 V (+2 ms), dvddbuck 1,3 V, dvddldo 1,3 V (+2 ms), enp +5,5 V (+2 ms), enn −5,5 V; total 6 ms lalu urutan reset 31 ms. Entri 3 dan 4 memakai `reg = <2>` yang sama dengan entri 2 (kekeliruan vendor); driver Qualcomm mengikuti urutan node, jadi urutan itulah yang dicatat. enp/enn adalah output bias KTZ8866 (TLMM 130/131, `BacklightBoard.h`).

## Jalur dual DSI dan DSC

| Besaran | Nilai | Asal |
| --- | --- | --- |
| Antarmuka | DSI0 + DSI1, PHY 0 + 1, D-PHY 4 lane masing-masing | `qcom,dsi-ctrl-num`, `-phy-num`, lane state |
| Clock | keduanya dari PLL DSI0 (`mux_byte_clk0`, `mux_pixel_clk0`); DSI1 slave | `qcom,dsi-select-clocks` |
| Topologi | 2 LM, 2 encoder DSC, 2 INTF (`<2 2 2>`); setiap antarmuka membawa separuh 900 px | `qcom,display-topology` |
| Timing per antarmuka | 900×2880, H 2/46/100, V 2/214/26, 120 Hz | timing@0 |
| DSC | 1.1, slice 450×20, 8 bpc, 8 bpp (rasio 3:1), 2 slice per paket | `qcom,mdss-dsc-*` |
| Lebar aktif terkompresi | 900 × 8 / 24 = 300 clock piksel | turunan |
| Pixel clock (DSC) | (300 + 148) × 3122 × 120 = **167.838.720 Hz** | turunan |
| Lane bit clock | pixel clock × 24 / 4 = **1.007.032.320** = `qcom,mdss-dsi-panel-clockrate` | turunan = DT |
| Byte clock | 125.879.040 Hz | turunan |
| Paket per baris | chunk 450 byte × 2 slice = 900 byte, 1 paket; 225 siklus byte clock di 4 lane | turunan |
| Tanpa DSC | 2,36 Gb/s per lane (di atas nilai DT): laju DT hanya tercapai terkompresi | turunan |
| dfps | 120/90/60/50/48/30 lewat porch vertikal; 144 Hz terdaftar tetapi butuh clock lain | `qcom,dsi-supported-dfps-list` |

Semua besaran turunan diuji di `PanelBoardTests.c` dan saling mengunci: bila satu nilai DT salah dibaca, bit clock tidak lagi sama dengan nilai DT.

## Kebutuhan driver touchscreen (DT vendor)

| Kebutuhan | Nilai | Keadaan di repo |
| --- | --- | --- |
| Pengontrol | Novatek NT36532, `novatek,NVT-ts-spi`, mode TDDI (`mi,is-tddi-flag` di kedua panel) | `TouchVendor.h` |
| Bus | QUP0 SE4 SPI, pin 8–10 + CS 11 (qup4, 6 mA), mode 0, 9,6 MHz (pilihan di komentar DT: 4,8/9,6/15/19,2 MHz) | `TouchBoard.h` (mainline + vendor) |
| Interrupt | TLMM 39, flag `0x2001` = `IRQF_TRIGGER_RISING \| IRQF_ONESHOT` | `TouchVendor.h` |
| Reset | tidak ada GPIO reset touch (`novatek,reset-gpio` dikomentari); TDDI: reset panel TLMM 75 ikut me-reset bagian touch; bootloader touch di-reset lewat perintah SPI | `TouchVendor.h`, `PanelBoard.h` |
| Firmware | dipilih byte pembuat `mi,panel-id`: `0x42` → `novatek_nt36532_m82_fw_csot.bin`, `0x36` → `…_fw_tm.bin` (+ image MP) | `tv_config_for_panel()`; image tetap di partisi vendor tablet, tidak di repo |
| Matriks sensor | 38 × 60 (kedua kriteria MP), pen aktif, resolusi stylus ganda | `TouchVendor.h` |

**Temuan**: `build-gop-legacy-display.py` UniXNU-pipa hanya membangun firmware TM ke dalam kernel iPadOS ("panelnya yang 36"). Tablet dengan panel CSOT (`0x42`) akan menerima firmware pembuat lain. Pemilihan yang benar mengikuti ID panel (`tv_config_for_panel`), belum disambungkan.

## Struktur integrasi XNU (belum dibangun untuk macOS)

| Lapisan | Komponen | os_abi katalog | Celah untuk macOS 26.5 arm64e |
| --- | --- | --- | --- |
| Frame buffer | `GopFramebuffer` (`NativeMobileDisplay`, `NativeLegacyDisplay`) | iPadOS 17.7.11, 27.0.1 | Tidak ada ABI macOS; WindowServer macOS butuh framebuffer IOKit lain |
| Backlight | `PipaBacklight.c` (repo ini, baca-saja, di belakang `pipa-backlight=1`) | — | Belum masuk arsip kernel; tulis ke KTZ8866 dikunci |
| Bus SPI | `QcomGeniSpi` (`GeniSpi.c`) | iPadOS | Belum dikompilasi arm64e |
| Protokol touch | `ShengNovatekTouch` (`NvtTouchCore.c`, sensor sheng) + `TouchProbe.cpp` pipa | iPadOS | Konfigurasi sensor pipa (38×60) dan pemilihan firmware per panel |
| HID | `ShengHidInput` (`NativeHidInput`) | iPadOS | Penerbitan IOHIDDevice untuk macOS belum ada |
| Panel penuh | tidak ada (MDSS/DPU/DSI tidak didukung driver mana pun) | — | `MdssProbe.cpp` sengaja tidak membaca register MDSS: SError fatal tanpa clock/GDSC yang di-vote kernel |

Urutan yang aman bila dilanjutkan: (1) kompilasi `QcomGeniSpi` + `ShengNovatekTouch` terhadap header xnu-12377 di runner macOS; (2) sambungkan `tv_config_for_panel` ke pemuatan firmware; (3) HID untuk macOS; (4) panel penuh hanya setelah ada driver clock/GDSC MDSS. Setiap uji di tablet hanya oleh pemilik.

## Yang tidak dibuktikan

- Bahwa TLMM 75 benar-benar me-reset panel atau touch pipa: dibaca dari DT vendor, tidak diukur.
- Bahwa nilai DSC/clock turunan dipakai firmware pipa: perhitungan, bukan pembacaan register (membaca MDSS dari XNU bisa menyebabkan SError).
- Perilaku touch di macOS: tidak ada driver macOS. Klaim upstream bahwa touch berjalan di iPadOS 17 tidak diulang di sini.
