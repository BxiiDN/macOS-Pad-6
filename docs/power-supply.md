# Fuel gauge dan charger pipa: validasi terhadap DT vendor Xiaomi

Status: **analisis statis dan host test saja.** Tidak ada register PMIC, charger, atau charge pump yang ditulis; macOS pipa tidak punya driver charger, dan `NativeBattery.cpp` (jalur iPadOS UniXNU-pipa) hanya membaca. Tidak ada yang dijalankan di tablet oleh repo ini.

Sumber: `MiCode/kernel_devicetree` `pipa-t-oss` `623dd5bf`: `qcom/pm8150b.dtsi`, `qcom/kona-pmic-overlay.dtsi`, `qcom/pipa-sm8250.dtsi`, `qcom/pipa-pinctrl.dtsi`, `qcom/kona-qupv3.dtsi`, `qcom/fg-gen4-batterydata-pipa-sunwoda-8840mah.dtsi`. Diperiksa otomatis oleh `scripts/pipa_hw.py vendor` (bagian `power`, 22 fakta; seluruh pemeriksaan vendor 81 cocok, 0 berbeda). Kode: `devices/pipa/package/PowerSupplyBoard.h`, `PowerSupplyBoardTests.c`; `NativeBatteryBoard.h` tidak diubah.

## Hasil

| Bagian | Nilai DT vendor | Dicocokkan dengan | Hasil |
| --- | --- | --- | --- |
| PMIC | PM8150B, SPMI USID 2 (`qcom,pm8150b@2`) | `PS_PMIC_USID` | cocok |
| Fuel gauge | FG gen4 (`qcom,fg-gen4`), status ok; periferal `0x4000/0x4100/0x4200/0x4300` | `PS_FG_*`; PPID `0x240..0x243` = `BAT_PPID_FG_*` (NativeBattery) | cocok |
| Charger | SMB5 (`qcom,qpnp-smb5`), status ok; chgr `0x1000`, dcdc `0x1100`, batif `0x1200`, usb `0x1300`, dc `0x1400`, typec `0x1500`, misc `0x1600` | `PS_SMB_*`; PPID `0x210/0x211/0x212/0x213/0x216` = `BAT_PPID_SMB_*` | cocok |
| Batas charger | ICL USB 3 A, FCC 5,9 A, FV 4,47 V (non-FFC 4,44 V), ICL DC 1 A, recharge 99 %, terminasi −400 mA, warm 48,0 °C / cool 15,0 °C | `PS_USB_ICL_UA` … `PS_CHG_*` | cocok |
| VBUS disable | TLMM 74, active high | `PS_GPIO_VBUS_DISABLE` | cocok |
| Regulator | `smb5-vbus`, `smb5-vconn` (SMB5 sebagai sumber VBUS/VCONN) | catatan header | cocok |
| Ambang gauge | cutoff 3400 mV / 200 mA, empty 3100 mV, sys-term −500 mA (FFC −1700 mA) | `PS_FG_*` | cocok |
| Profil baterai | `M82_sunwoda_8840mah`, 8840 mAh, 4,47 V, fast charge 5900 mA, batt-id 100 kΩ, beta 4250 | `PS_BATT_*`; 8840 = `BAT_DESIGN_MAH` | cocok |
| JEITA | tabel FCC dan FV (6 baris masing-masing), too hot 59,0 °C, too cold −10,0 °C | `ps_jeita_fcc`, `ps_jeita_fv` | cocok |
| Charge pump | TI `bq2597x-standalone` di QUP SE16 `0x888000`, alamat `0x66`, status ok | `PS_CP_SE_BASE`, `PS_CP_ADDR` | cocok |
| Interrupt charge pump | TLMM 68, flag `0x2002` (`IRQF_TRIGGER_FALLING \| IRQF_ONESHOT`); pin gpio, 2 mA, pull-up, input | `PS_CP_IRQ_*`, `PS_CP_PIN_MA` | cocok |
| Proteksi charge pump | bat OVP 4550 (alarm 4525) mV, bus OVP 12000 (alarm 11000) mV, bus OCP 3800 (alarm 3500) mA | `PS_CP_*` | cocok |
| Gauge eksternal | `ti,bq27z561_master` (SE13 `0xa94000`, `0x55`) dan `_slave` (SE0 `0x980000`, `0x55`) **dijelaskan tetapi bus-nya `disabled`** | `PS_EXT_FG_*` | cocok |

## Temuan

- Gauge yang dipakai Android adalah FG gen4 PM8150B, bukan bq27z561: kedua bus bq27z561 dinonaktifkan. Itu cocok dengan pilihan `NativeBattery.cpp` (membaca FG gen4 lewat SPMI).
- Pengisian cepat lewat charge pump bq2597x (`mi,use-bq-pump`), dengan SMB5 sebagai charger utama. Driver macOS untuk keduanya belum ada; untuk sekadar melaporkan baterai, keduanya tidak perlu disentuh.
- Tabel FCC JEITA menyebut 48,0 °C di dua baris (`151..480` → 5,9 A dan `480..600` → 4,34 A). Baris mana yang berlaku di batas itu tergantung urutan pencarian driver vendor; `ps_range_value` melaporkan jumlah baris yang cocok (2) dan memakai baris pertama, tanpa mengklaim perilaku driver.
- Node FG menandai `qcom,five-pin-battery`, profil baterai menandai `mi,six-pin-battery`: dua properti untuk konsumen berbeda; dicatat, tidak ditafsirkan.
- Interrupt charger/gauge PM8150B lewat SPMI (USID 2, periferal `0x10…`, `0x40…`) tidak dipakai: jalur baterai yang ada melakukan polling.

## Pengujian

- `PowerSupplyBoardTests.c` (host, x86 dan arm64 di CI): PPID = periferal DT; kapasitas = `BAT_DESIGN_MAH`; FV = tegangan maksimum pack; FCC = fast charge pack; tabel JEITA tanpa celah dari too-cold sampai too-hot, nilai tidak melebihi batas charger; batas gauge konsisten; bus charge pump berbeda dari bus backlight dan touch.
- `scripts/pipa_hw.py vendor` (CI, job `test`): 22 fakta daya di atas dibaca dari sumber setiap kali.

## Yang tidak dibuktikan

- Bahwa tablet nyata memakai profil ini (ID baterai 100 kΩ dibaca driver vendor dari ADC; tidak diukur di sini).
- Perilaku charger atau charge pump: tidak ada yang ditulis ke chip, dan tidak ada pengujian perangkat.
