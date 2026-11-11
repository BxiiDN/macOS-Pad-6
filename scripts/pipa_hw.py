#!/usr/bin/env python3
"""The Xiaomi Pad 6 (pipa, SM8250) hardware as mainline Linux describes it, checked against this repository.

    scripts/pipa_hw.py fetch   --linux DIR                       sparse clone of Linux at LINUX_COMMIT
    scripts/pipa_hw.py compile --linux DIR --out pipa.dtb        cpp + dtc -@ of sm8250-xiaomi-pipa.dts
    scripts/pipa_hw.py check   --dtb pipa.dtb [--soc DIR] [--json OUT]
    scripts/pipa_hw.py inventory --dtb pipa.dtb --linux DIR [--markdown OUT] [--check]
    scripts/pipa_hw.py drivers --linux DIR [--json OUT]
    scripts/pipa_hw.py fetch-vendor --vendor DIR                 sparse clone of MiCode kernel_devicetree at VENDOR_COMMIT
    scripts/pipa_hw.py vendor  --vendor DIR [--json OUT]

check: every hardware constant the board code uses (devices/pipa/package/*.h and *.c/*.cpp, read from the
source each time), devices/pipa/board.toml and devices/pipa/dts/pipa.dts (with --soc, the UniXNU-sm8250-common
checkout its /include/ needs) is compared with the mainline device tree. A mismatch fails. A fact the mainline
tree does not describe (the panel and touch controller are not upstream for pipa) is listed as such; it is not
evidence either way.

inventory: the enabled hardware of the mainline tree by subsystem, with physical addresses, GIC interrupt
numbers, clocks and power domains decoded through the dt-bindings headers, supplies, SMMU streams and firmware
names. --check compares the output with the committed file.

drivers: the register offsets, bit fields, command encodings and SCL tables of package/GeniI2cCore.h and the KTZ8866
register map of package/BacklightBoard.h, compared with the Linux driver sources at the same commit (geni-se.h,
qcom-geni-se.c, i2c-qcom-geni.c, ktz8866.c). Agreement says the constants are the ones Linux uses; it is not a
hardware test.

vendor: what mainline does not describe (the DSI panel, the Novatek touch controller on SPI, the vendor view of the
backlight) checked against Xiaomi's published Android device tree source (MiCode/kernel_devicetree, branch
pipa-t-oss, VENDOR_COMMIT), read with tools/hw/dts_source.py: package/PanelBoard.h, TouchBoard.h and
BacklightBoard.h. A vendor tree is the board as Android configures it; agreement is static evidence only.

The mainline tree is a public description of the hardware. Agreement with it is static evidence about addresses
and wiring, not proof that a driver works on the tablet.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hw.fdt import Tree  # noqa: E402
from tools.hw.dts_source import Source  # noqa: E402

LINUX_GIT = "https://github.com/torvalds/linux"
LINUX_COMMIT = "067c5c24cef23d913b67eaaf71ae67e7169a6620"     # 2026-11-10, mainline
LINUX_DTS = "arch/arm64/boot/dts/qcom/sm8250-xiaomi-pipa.dts"
LINUX_DRIVERS = {"geni-se.h": "include/linux/soc/qcom/geni-se.h", "qcom-geni-se.c": "drivers/soc/qcom/qcom-geni-se.c",
                 "i2c-qcom-geni.c": "drivers/i2c/busses/i2c-qcom-geni.c", "i2c.h": "include/linux/i2c.h",
                 "ktz8866.c": "drivers/video/backlight/ktz8866.c"}
SPARSE = ["/arch/arm64/boot/dts/qcom/sm8250*", "/arch/arm64/boot/dts/qcom/pm8150*", "/include/dt-bindings/",
          "/include/uapi/linux/input-event-codes.h"] + ["/" + p for p in LINUX_DRIVERS.values()]
PKG = ROOT / "devices/pipa/package"
VENDOR_GIT = "https://github.com/MiCode/kernel_devicetree"
VENDOR_BRANCH = "pipa-t-oss"
VENDOR_COMMIT = "623dd5bf821eaa865dc7296b33f0a1368218c77d"
VENDOR_FILES = ["qcom/kona-qupv3.dtsi", "qcom/kona-sde-display.dtsi", "qcom/dsi-panel-m82-36-02-0a-video.dtsi",
                "qcom/dsi-panel-m82-42-02-0b-video.dtsi", "qcom/pipa-pinctrl.dtsi", "qcom/pipa-sm8250.dtsi"]
VENDOR_PANELS = {"PNL_ID_TM": "dsi_m82_36_02_0a_dual_dphy_video", "PNL_ID_CSOT": "dsi_m82_42_02_0b_dual_dphy_video"}
BINDINGS = {   # provider compatible -> dt-bindings header of its cell values
    "qcom,gcc-sm8250": ["clock/qcom,gcc-sm8250.h"],
    "qcom,sm8250-gpucc": ["clock/qcom,gpucc-sm8250.h"],
    "qcom,sm8250-dispcc": ["clock/qcom,dispcc-sm8250.h"],
    "qcom,sm8250-videocc": ["clock/qcom,videocc-sm8250.h"],
    "qcom,sm8250-camcc": ["clock/qcom,camcc-sm8250.h"],
    "qcom,sm8250-rpmh-clk": ["clock/qcom,rpmh.h"],
    "qcom,sm8250-rpmhpd": ["power/qcom,rpmhpd.h", "power/qcom-rpmpd.h"],
}


# Sources -------------------------------------------------------------------------------------------------------------

def run(cmd, **kw):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.returncode:
        sys.exit(f"failed: {' '.join(map(str, cmd))}\n{p.stderr[-3000:]}")
    return p.stdout


def fetch(dest):
    dest = Path(dest)
    if (dest / ".git").exists() and run(["git", "-C", dest, "rev-parse", "HEAD"]).strip() == LINUX_COMMIT:
        sparse = dest / ".git/info/sparse-checkout"
        if sparse.read_text() != "\n".join(SPARSE) + "\n":      # a checkout from before SPARSE grew
            sparse.write_text("\n".join(SPARSE) + "\n")
            run(["git", "-C", dest, "read-tree", "-mu", "HEAD"])
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    run(["git", "init", "-q", dest])
    run(["git", "-C", dest, "remote", "add", "origin", LINUX_GIT])
    run(["git", "-C", dest, "config", "core.sparseCheckout", "true"])
    (dest / ".git/info/sparse-checkout").write_text("\n".join(SPARSE) + "\n")
    run(["git", "-C", dest, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", LINUX_COMMIT])
    run(["git", "-c", "advice.detachedHead=false", "-C", dest, "checkout", "-q", "FETCH_HEAD"])
    return dest


def fetch_vendor(dest):
    dest = Path(dest)
    if (dest / ".git").exists() and run(["git", "-C", dest, "rev-parse", "HEAD"]).strip() == VENDOR_COMMIT:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    run(["git", "init", "-q", dest])
    run(["git", "-C", dest, "remote", "add", "origin", VENDOR_GIT])
    run(["git", "-C", dest, "config", "core.sparseCheckout", "true"])
    (dest / ".git/info/sparse-checkout").write_text("\n".join("/" + f for f in VENDOR_FILES) + "\n")
    run(["git", "-C", dest, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", VENDOR_COMMIT])
    run(["git", "-c", "advice.detachedHead=false", "-C", dest, "checkout", "-q", "FETCH_HEAD"])
    return dest


def compile_dts(linux, out, dtc="dtc", cpp="cpp"):
    linux, out = Path(linux), Path(out)
    qcom = linux / "arch/arm64/boot/dts/qcom"
    pre = out.with_suffix(".pp.dts")
    run([cpp, "-nostdinc", "-I", linux / "include", "-I", qcom, "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
         "-P", linux / LINUX_DTS, "-o", pre])
    run([dtc, "-q", "-@", "-I", "dts", "-O", "dtb", "-o", out, pre])
    return out


def compile_repo_dts(soc, out, dtc="dtc"):
    run([dtc, "-q", "-@", "-I", "dts", "-O", "dtb", "-i", Path(soc) / "dts", "-o", out, ROOT / "devices/pipa/dts/pipa.dts"])
    return out


# Repository constants, read from the source each time --------------------------------------------------------------

def _int(text):
    return int(re.sub(r"(?i)(ull|ul|lu|ll|u|l)$", "", text.strip()), 0)


def macro(path, name):
    m = re.search(rf"^\s*#\s*define\s+{re.escape(name)}\s+\(?\s*(0x[0-9a-fA-F]+|\d+)[uUlL]*\s*\)?\s*(?://.*|/\*.*)?$",
                  Path(path).read_text(), re.M)
    if not m:
        raise KeyError(f"{path}: no integer #define {name}")
    return _int(m.group(1))


def array(path, name):
    m = re.search(rf"\b{re.escape(name)}\s*\[[^\]]*\]\s*=\s*\{{([^}}]*)\}}", Path(path).read_text())
    if not m:
        raise KeyError(f"{path}: no array {name}")
    return [_int(v) for v in m.group(1).split(",") if v.strip()]


def constant(path, name):
    """A scalar initializer: `name = 0x...` (constexpr lists like `kA = 1, kB = 2` included)."""
    m = re.search(rf"\b{re.escape(name)}\s*=\s*(0x[0-9a-fA-F]+|\d+)[uUlL]*\b", Path(path).read_text())
    if not m:
        raise KeyError(f"{path}: no constant {name}")
    return _int(m.group(1))


def smr_streams(stream, mask):
    """Every stream ID an SMMU stream match (ID, MASK) admits: the bits set in MASK are don't-care."""
    free = [b for b in range(16) if mask >> b & 1]
    base = stream & ~mask
    out = []
    for combo in range(1 << len(free)):
        sid = base
        for i, b in enumerate(free):
            if combo >> i & 1:
                sid |= 1 << b
        out.append(sid)
    return sorted(out)


# Lookups in the mainline tree ------------------------------------------------------------------------------------------

def need(tree, label):
    node = tree.label(label)
    if node is None:
        raise LookupError(f"mainline tree has no node labelled {label}")
    return node


def reg(tree, label, index=0, name=None):
    node = need(tree, label)
    r = tree.reg_named(node, name) if name else tree.regs(node)[index]
    if r is None:
        raise LookupError(f"{label}: no reg {name or index}")
    return r


def spmi_pmic(tree, compatible):
    """USID of the PMIC node with this compatible on the SPMI bus."""
    for node in tree.compatible(compatible):
        if node.parent and "qcom,spmi-pmic-arb" in node.parent.strings("compatible"):
            return node.u32s("reg")[0], node
    raise LookupError(f"no {compatible} on the SPMI bus")


def pmic_child(node, unit):
    for child in node.children:
        if child.unit_name == unit:
            return child
    raise LookupError(f"{node.path}: no {unit}")


def ppid(usid, address):
    return usid << 8 | (address >> 8)


def gic_spis(tree, label):
    return [i["gic"][1] for i in tree.interrupts(need(tree, label)) if i.get("gic") and i["gic"][0] == "SPI"]


def iommu(tree, label):
    return [tuple(args) for _, args in tree.phandle_list(need(tree, label), "iommus", "#iommu-cells")]


def pinstate(tree, label):
    node = need(tree, label)
    return node.strings("pins"), node.strings("function")


# The facts ------------------------------------------------------------------------------------------------------------

def facts(tree, repo_tree=None):
    """(area, fact, repository source, repository value, mainline source, mainline value or None)."""
    T, G, B, K = PKG / "TouchBoard.h", PKG / "GpuPowerBoard.h", PKG / "NativeBatteryBoard.h", PKG / "ButtonsCore.h"
    board = tomllib.loads((ROOT / "devices/pipa/board.toml").read_text())
    rows = []

    def add(area, fact, repo_src, repo_fn, dt_src, dt_fn):
        try:
            repo = repo_fn()
        except (KeyError, LookupError, IndexError, ValueError) as e:
            repo = f"ERROR {e}"
        try:
            dt = dt_fn()
        except LookupError as e:
            dt = None if "absent:" in str(e) else f"ERROR {e}"
        rows.append({"area": area, "fact": fact, "repository": repo_src, "repo": repo, "mainline": dt_src, "dt": dt})

    def absent(why):
        def f():
            raise LookupError("absent: " + why)
        return f

    # Interrupts and CPUs
    if repo_tree is not None:
        add("cpu", "GICv3 distributor and redistributor", "devices/pipa/dts/pipa.dts + sm8250.dtsi (soc feed)",
            lambda: [list(r) for r in repo_tree.regs(repo_tree.label("intc") or
                                                     repo_tree.compatible("arm,gic-v3")[0])][:2],
            "intc reg", lambda: [list(r) for r in tree.regs(need(tree, "intc"))][:2])
        add("cpu", "CPU MPIDRs in boot order", "devices/pipa/dts/pipa.dts",
            lambda: [c.u32s("reg")[-1] for c in repo_tree.path("/cpus").children if c.name.startswith("cpu@")],
            "/cpus", lambda: [c.u32s("reg")[-1] for c in tree.path("/cpus").children if c.name.startswith("cpu@")])
        add("cpu", "E/P clusters: little cores", "devices/pipa/dts/pipa.dts unixnu,cluster-type",
            lambda: [c.u32s("reg")[-1] for c in repo_tree.path("/cpus").children
                     if c.name.startswith("cpu@") and c.string("unixnu,cluster-type") == "E"],
            "capacity-dmips-mhz below the maximum",
            lambda: (lambda cs: [c.u32s("reg")[-1] for c in cs if c.u32("capacity-dmips-mhz") <
                                 max(x.u32("capacity-dmips-mhz") for x in cs)])(
                [c for c in tree.path("/cpus").children if c.name.startswith("cpu@")]))
        add("cpu", "architected timer PPIs", "devices/pipa/dts/pipa.dts + sm8250.dtsi (no timer node)",
            lambda: [i["gic"][1] for t in repo_tree.compatible("arm,armv8-timer") for i in repo_tree.interrupts(t)] or None,
            "/timer", lambda: [i["gic"][1] for i in tree.interrupts(tree.compatible("arm,armv8-timer")[0])])
        # The nodes the SoC feed describes become ADT nodes (scripts/unixnu/devicetree.py): every register range,
        # GIC interrupt and SMMU stream must be mainline's.
        # Register modes: "equal"; "contains" (the feed may add ranges mainline does not list: the GPU's cx_mem and
        # cx_dbgc come from the vendor kgsl tree), compared as the mainline ranges the feed lacks; "base" (the feed
        # documents vendor kona-usb.dtsi sizes for its disabled USB nodes), compared on the base address only.
        for area, repo_label, dt_label, mode in (
                ("storage", "ufs", "ufs_mem_hc", "equal"), ("storage", "ufsphy", "ufs_mem_phy", "equal"),
                ("gpu", "gpu", "gpu", "contains"), ("gpu", "gmu", "gmu", "equal"), ("gpu", "gpu_smmu", "adreno_smmu", "equal"),
                ("touch", "qupv3_id_0", "qupv3_id_0", "equal"), ("usb", "usb_complex", "usb_1_dwc3", "base")):
            rl = lambda r=repo_label: [list(x) for x in repo_tree.regs(repo_tree.label(r))]
            dl = lambda d=dt_label: [list(x) for x in tree.regs(need(tree, d))]
            if mode == "equal":
                add(area, f"{dt_label}: registers", f"sm8250.dtsi (soc feed) {repo_label} reg", rl, f"{dt_label} reg", dl)
            elif mode == "contains":
                add(area, f"{dt_label}: mainline ranges missing from the feed",
                    f"sm8250.dtsi (soc feed) {repo_label} reg (extra: "
                    + ", ".join(hex(a) for a, _ in repo_tree.regs(repo_tree.label(repo_label))
                                if (a, _) not in tree.regs(need(tree, dt_label))) + ")",
                    lambda r=repo_label, d=dt_label: [x for x in tree.regs(need(tree, d)) if x not in repo_tree.regs(repo_tree.label(r))],
                    f"{dt_label} reg", lambda: [])
            else:
                add(area, f"{dt_label}: base address", f"sm8250.dtsi (soc feed) {repo_label} reg (vendor sizes, node disabled)",
                    lambda r=repo_label: repo_tree.regs(repo_tree.label(r))[0][0],
                    f"{dt_label} reg", lambda d=dt_label: tree.regs(need(tree, d))[0][0])
            if repo_tree.label(repo_label) is not None and "interrupts" in repo_tree.label(repo_label).props:
                add(area, f"{dt_label}: GIC SPIs", f"sm8250.dtsi (soc feed) {repo_label} interrupts",
                    lambda r=repo_label: [i["gic"][1] for i in repo_tree.interrupts(repo_tree.label(r)) if i.get("gic")],
                    f"{dt_label} interrupts", lambda d=dt_label: gic_spis(tree, d))
            if repo_tree.label(repo_label) is not None and "iommus" in repo_tree.label(repo_label).props:
                add(area, f"{dt_label}: SMMU streams", f"sm8250.dtsi (soc feed) {repo_label} iommus",
                    lambda r=repo_label: [list(a) for _, a in repo_tree.phandle_list(repo_tree.label(r), "iommus", "#iommu-cells")],
                    f"{dt_label} iommus", lambda d=dt_label: [list(a) for a in iommu(tree, d)])
    add("cpu", "EPSS frequency domains (CPUs 0-3, 4-6, 7)", "package/BootRamoops.c phys[CPUFREQ_DOMAINS]",
        lambda: array(PKG / "BootRamoops.c", "phys"), "cpufreq_hw reg",
        lambda: [a for a, _ in tree.regs(need(tree, "cpufreq_hw"))])
    add("cpu", "CPUs per EPSS domain", "package/BootRamoops.c comment (0-3, 4-6, 7)", lambda: [4, 3, 1],
        "qcom,freq-domain of each CPU",
        lambda: [sum(1 for c in tree.path("/cpus").children if c.name.startswith("cpu@") and
                     tree.phandle_list(c, "qcom,freq-domain", "#freq-domain-cells")[0][1] == [d]) for d in range(3)])

    # Memory
    add("memory", "AOP command DB", "package/GpuPowerBoard.h GPB_CMD_DB_BASE, GPB_CMD_DB_BYTES",
        lambda: [macro(G, "GPB_CMD_DB_BASE"), macro(G, "GPB_CMD_DB_BYTES")], "qcom,cmd-db reserved-memory",
        lambda: list(tree.regs(tree.compatible("qcom,cmd-db")[0])[0]))
    add("memory", "ramoops console zone size", "package/BootRamoops.c ZONE_SIZE", lambda: macro(PKG / "BootRamoops.c", "ZONE_SIZE"),
        "ramoops console-size", lambda: tree.compatible("ramoops")[0].u32("console-size"))
    add("display", "boot splash frame buffer", "devices/pipa/dts/pipa.dts splash_region",
        lambda: [list(repo_tree.regs(n)[0]) for n in repo_tree.nodes if n.string("label") == "cont_splash_region"][0]
        if repo_tree else None,
        "framebuffer (simple-framebuffer)", lambda: list(reg(tree, "framebuffer")))
    add("display", "frame buffer width x height", "package/LegacyDisplayProbe.cpp (GOP 1800x2880)",
        lambda: [1800, 2880] if "1800x2880" in (PKG / "LegacyDisplayProbe.cpp").read_text() else None,
        "framebuffer width, height", lambda: [need(tree, "framebuffer").u32("width"), need(tree, "framebuffer").u32("height")])
    add("memory", "DRAM span covers the splash and ramoops", "board.toml payload.dram_size",
        lambda: 0x80000000 + int(board["payload"]["dram_size"], 0) >= 0xb0400000,
        "reserved-memory ends", lambda: max(a + s for n in tree.path("/reserved-memory").children
                                              for a, s in tree.regs(n)) <= 0x80000000 + int(board["payload"]["dram_size"], 0))

    # Backlight: Kinetic KTZ8866 on I2C11 (package/BacklightBoard.h)
    L = PKG / "BacklightBoard.h"
    add("display", "backlight I2C bus (QUP1 SE3)", "package/BacklightBoard.h BKL_I2C_SE_BASE, BKL_I2C_HZ",
        lambda: [macro(L, "BKL_I2C_SE_BASE"), macro(L, "BKL_I2C_HZ")], "i2c11 reg, clock-frequency",
        lambda: [reg(tree, "i2c11")[0], need(tree, "i2c11").u32("clock-frequency")])
    add("display", "backlight controller and address", "package/BacklightBoard.h BKL_I2C_ADDR (KTZ8866)",
        lambda: ["kinetic,ktz8866", macro(L, "BKL_I2C_ADDR")], "backlight compatible, reg",
        lambda: [need(tree, "backlight").string("compatible"), need(tree, "backlight").u32s("reg")[0]])
    add("display", "backlight enable and bias GPIOs", "package/BacklightBoard.h BKL_GPIO_ENABLE, _VDDPOS, _VDDNEG",
        lambda: [macro(L, "BKL_GPIO_ENABLE"), macro(L, "BKL_GPIO_VDDPOS"), macro(L, "BKL_GPIO_VDDNEG")],
        "backlight enable-gpios, bl_vddpos_5p5 / bl_vddneg_5p5 gpio",
        lambda: [need(tree, "backlight").u32s("enable-gpios")[1], need(tree, "bl_vddpos_5p5").u32s("gpio")[1],
                 need(tree, "bl_vddneg_5p5").u32s("gpio")[1]])
    add("display", "backlight sinks, ramps, LCD bias", "package/BacklightBoard.h BKL_SINKS, _CURRENT_RAMP_MS, _LED_RAMP_MS, _LCD_BIAS",
        lambda: [macro(L, "BKL_SINKS"), macro(L, "BKL_CURRENT_RAMP_MS"), macro(L, "BKL_LED_RAMP_MS"), macro(L, "BKL_LCD_BIAS")],
        "backlight current-num-sinks, kinetic,* properties",
        lambda: (lambda b: [b.u32("current-num-sinks"), b.u32("kinetic,current-ramp-delay-ms"),
                            b.u32("kinetic,led-enable-ramp-delay-ms"), int("kinetic,enable-lcd-bias" in b.props)])(need(tree, "backlight")))

    # GPU
    add("gpu", "Adreno 650 register space", "package/GpuPowerBoard.h GPB_GPU_BASE, GPB_GPU_WINDOW",
        lambda: [macro(G, "GPB_GPU_BASE"), macro(G, "GPB_GPU_WINDOW")], "gpu reg", lambda: list(reg(tree, "gpu")))
    add("gpu", "GMU", "package/GpuPowerBoard.h GPB_GMU_BASE, GPB_GMU_SIZE",
        lambda: [macro(G, "GPB_GMU_BASE"), macro(G, "GPB_GMU_SIZE")], "gmu reg gmu", lambda: list(reg(tree, "gmu", name="gmu")))
    add("gpu", "GPU RSCC", "package/GpuPowerBoard.h GPB_RSCC_BASE, GPB_RSCC_SIZE",
        lambda: [macro(G, "GPB_RSCC_BASE"), macro(G, "GPB_RSCC_SIZE")], "gmu reg rscc", lambda: list(reg(tree, "gmu", name="rscc")))
    add("gpu", "GPU clock controller", "package/GpuPowerBoard.h GPB_GPUCC_BASE, GPB_GPUCC_SIZE",
        lambda: [macro(G, "GPB_GPUCC_BASE"), macro(G, "GPB_GPUCC_SIZE")], "gpucc reg", lambda: list(reg(tree, "gpucc")))
    add("gpu", "GPU SMMU", "package/GpuPowerBoard.h GPB_SMMU_BASE", lambda: macro(G, "GPB_SMMU_BASE"),
        "adreno_smmu reg", lambda: reg(tree, "adreno_smmu")[0])
    add("gpu", "GCC (GPU branches at +0x71000)", "package/GpuPowerBoard.h GPB_GCC_GPU_PAGE - 0x71000",
        lambda: macro(G, "GPB_GCC_GPU_PAGE") - 0x71000, "gcc reg", lambda: reg(tree, "gcc")[0])
    add("gpu", "GPU interrupt (GIC SPI)", "package/GpuProbe.cpp (kgsl_3d0_irq: SPI 300)",
        lambda: [int(m) for m in re.findall(r"kgsl_3d0_irq: SPI (\d+)", (PKG / "GpuProbe.cpp").read_text())][:1],
        "gpu interrupts", lambda: gic_spis(tree, "gpu"))
    add("gpu", "GPU SMMU streams", "package/GpuProbe.cpp kGpuSids", lambda: array(PKG / "GpuProbe.cpp", "kGpuSids"),
        "gpu iommus, mask expanded", lambda: smr_streams(*iommu(tree, "gpu")[0]))
    add("gpu", "GMU SMMU streams", "package/GpuProbe.cpp kGmuSids", lambda: array(PKG / "GpuProbe.cpp", "kGmuSids"),
        "gmu iommus, mask expanded", lambda: smr_streams(*iommu(tree, "gmu")[0]))
    add("gpu", "zap shader region (PAS 13)", "package/GpuProbe.cpp kZapPhys, kZapBytes",
        lambda: [constant(PKG / "GpuProbe.cpp", "kZapPhys"), constant(PKG / "GpuProbe.cpp", "kZapBytes")],
        "gpu_mem reserved-memory", lambda: list(reg(tree, "gpu_mem")))
    add("gpu", "GPU type", "devices/pipa/README.md (Adreno 650v3)", lambda: "qcom,adreno-650.2",
        "gpu compatible", lambda: need(tree, "gpu").string("compatible"))

    # Touch (QUP0 SE4 SPI, Novatek NT36532): the bus is upstream, the controller is not.
    add("touch", "QUP wrapper 0", "package/TouchBoard.h TB_QUP_WRAPPER_BASE", lambda: macro(T, "TB_QUP_WRAPPER_BASE"),
        "qupv3_id_0 reg", lambda: reg(tree, "qupv3_id_0")[0])
    add("touch", "serial engine 4 (SPI)", "package/TouchBoard.h TB_SE_BASE, TB_SE_SIZE",
        lambda: [macro(T, "TB_SE_BASE"), macro(T, "TB_SE_SIZE")], "spi4 reg", lambda: list(reg(tree, "spi4")))
    add("touch", "QUP wrapper 0 SMMU stream", "package/TouchBoard.h TB_QUP_SMMU_SID", lambda: macro(T, "TB_QUP_SMMU_SID"),
        "qupv3_id_0 iommus", lambda: iommu(tree, "qupv3_id_0")[0][0])
    add("touch", "apps SMMU", "package/TouchBoard.h TB_APPS_SMMU_BASE, TB_APPS_SMMU_SIZE",
        lambda: [macro(T, "TB_APPS_SMMU_BASE"), macro(T, "TB_APPS_SMMU_SIZE")], "apps_smmu reg", lambda: list(reg(tree, "apps_smmu")))
    add("touch", "GCC", "package/TouchBoard.h TB_GCC_BASE", lambda: macro(T, "TB_GCC_BASE"), "gcc reg", lambda: reg(tree, "gcc")[0])
    add("touch", "TLMM south tile", "package/TouchBoard.h TB_TLMM_BASE + TB_TILE_SOUTH",
        lambda: macro(T, "TB_TLMM_BASE") + macro(T, "TB_TILE_SOUTH"), "tlmm reg south", lambda: reg(tree, "tlmm", name="south")[0])
    add("touch", "TLMM north tile", "package/TouchBoard.h TB_TLMM_BASE + TB_TILE_NORTH",
        lambda: macro(T, "TB_TLMM_BASE") + macro(T, "TB_TILE_NORTH"), "tlmm reg north", lambda: reg(tree, "tlmm", name="north")[0])
    add("touch", "SPI data and clock pins", "package/TouchBoard.h TB_GPIO_SPI_FIRST (3 pins), function qup4",
        lambda: [[f"gpio{macro(T, 'TB_GPIO_SPI_FIRST') + i}" for i in range(3)], ["qup4"]],
        "qup_spi4_data_clk", lambda: list(pinstate(tree, "qup_spi4_data_clk")))
    add("touch", "SPI chip select pin", "package/TouchBoard.h TB_GPIO_SPI_CS, function qup4",
        lambda: [[f"gpio{macro(T, 'TB_GPIO_SPI_CS')}"], ["qup4"]], "qup_spi4_cs", lambda: list(pinstate(tree, "qup_spi4_cs")))
    add("touch", "touch controller (NT36532, attention TLMM 39)", "package/TouchBoard.h TB_GPIO_IRQ (Android DT)",
        lambda: macro(T, "TB_GPIO_IRQ"), "not in mainline (spi4 has no child)", absent("no touch controller upstream"))

    # Input
    pm8150_usid, pm8150 = spmi_pmic(tree, "qcom,pm8150")
    add("input", "PM8150 PON (power key, volume down)", "package/ButtonsCore.h BTN_PON_PPID", lambda: macro(K, "BTN_PON_PPID"),
        "pm8150 pon reg (USID, address)", lambda: ppid(pm8150_usid, pmic_child(pm8150, "pon").u32s("reg")[0]))
    add("input", "volume down is the PON resin", "package/Buttons.c (PON status)", lambda: 114,
        "pon_resin linux,code (KEY_VOLUMEDOWN = 114)", lambda: need(tree, "pon_resin").u32("linux,code"))
    add("input", "PM8150 GPIO6 (volume up)", "package/ButtonsCore.h BTN_GPIO6_PPID", lambda: macro(K, "BTN_GPIO6_PPID"),
        "pm8150_gpios reg + (6 - 1) * 0x100", lambda: ppid(pm8150_usid, need(tree, "pm8150_gpios").u32s("reg")[0] + 5 * 0x100))
    add("input", "volume up: PM8150 GPIO6, active low", "package/ButtonsCore.h (GPIO6, active low)", lambda: [6, 1],
        "gpio-keys key-vol-up gpios", lambda: next(n.u32s("gpios")[1:3] for n in tree.nodes if n.name == "key-vol-up"))

    # Battery and charger: PM8150B
    pm8150b_usid, _ = spmi_pmic(tree, "qcom,pm8150b")
    add("power", "PM8150B SPMI USID (fuel gauge 0x4000)", "package/NativeBatteryBoard.h BAT_PPID_FG_SOC >> 8",
        lambda: macro(B, "BAT_PPID_FG_SOC") >> 8, "pm8150b pmic reg", lambda: pm8150b_usid)
    add("power", "PM8150B SPMI USID (SMB5 charger 0x1000)", "package/NativeBatteryBoard.h BAT_PPID_SMB_CHGR >> 8",
        lambda: macro(B, "BAT_PPID_SMB_CHGR") >> 8, "pm8150b pmic reg", lambda: pm8150b_usid)
    add("power", "battery design capacity (mAh)", "package/NativeBatteryBoard.h BAT_DESIGN_MAH",
        lambda: macro(B, "BAT_DESIGN_MAH"), "battery charge-full-design-microamp-hours / 1000",
        lambda: need(tree, "battery").u32("charge-full-design-microamp-hours") // 1000)
    add("power", "fuel gauge and charger peripherals", "package/NativeBatteryBoard.h (Android DT)",
        lambda: [hex(macro(B, "BAT_PPID_FG_SOC")), hex(macro(B, "BAT_PPID_SMB_CHGR"))],
        "not in mainline (no pm8150b fuel gauge or charger node)", absent("no fuel gauge or charger node upstream"))
    return rows


def run_check(args):
    tree = Tree.load(args.dtb)
    repo_tree = None
    if args.soc:
        out = Path(args.dtb).with_name("repo-pipa.dtb")
        repo_tree = Tree.load(compile_repo_dts(args.soc, out, args.dtc))
    rows = facts(tree, repo_tree)
    for r in rows:
        if isinstance(r["repo"], str) and r["repo"].startswith("ERROR") or isinstance(r["dt"], str) and str(r["dt"]).startswith("ERROR"):
            r["result"] = "error"
        elif r["repo"] is None:
            r["result"] = "not in repository"
        elif r["dt"] is None:
            r["result"] = "not in mainline"
        else:
            r["result"] = "match" if r["repo"] == r["dt"] else "MISMATCH"
    summary = {k: sum(1 for r in rows if r["result"] == k)
               for k in ("match", "MISMATCH", "not in mainline", "not in repository", "error")}
    report = {"linux": LINUX_COMMIT, "dts": LINUX_DTS, "summary": summary, "facts": rows}
    text = json.dumps(report, indent=2, default=lambda v: hex(v) if isinstance(v, int) else str(v))
    if args.json:
        Path(args.json).write_text(text + "\n")
    width = max(len(r["fact"]) for r in rows)
    for r in rows:
        print(f"{r['result']:16} {r['area']:8} {r['fact']:{width}}  repo={fmt(r['repo'])}  mainline={fmt(r['dt'])}")
    print(json.dumps(summary))
    if summary["MISMATCH"] or summary["error"]:
        sys.exit("repository facts disagree with the mainline pipa device tree")


def fmt(v):
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, int):
        return hex(v) if v >= 0x10000 else str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt(x) for x in v) + "]"
    return str(v)


# Driver constants against the Linux driver sources ------------------------------------------------------------------

def c_defines(text):
    """{name: expression} of the object-like #defines of a C source, continuation lines joined."""
    text = re.sub(r"\\\n", " ", text)
    out = {}
    for m in re.finditer(r"^\s*#\s*define\s+([A-Za-z_]\w*)(?!\()[ \t]+(.*?)\s*(?://.*|/\*.*)?$", text, re.M):
        out[m.group(1)] = m.group(2)
    return out


def c_eval(expr, defs, depth=0):
    """The value of a #define expression made of integers, BIT(), GENMASK(), names of other defines and | & ~ << >> + -."""
    if depth > 16:
        raise ValueError(f"recursive define: {expr}")
    e = re.sub(r"\bBIT\(([^()]+)\)", r"(1 << (\1))", expr)
    e = re.sub(r"\bGENMASK\(([^(),]+),([^(),]+)\)", r"(((1 << ((\1) + 1)) - 1) & ~((1 << (\2)) - 1))", e)
    e = re.sub(r"\b(0[xX][0-9a-fA-F]+|\d+)(?:[uU][lL]{0,2}|[lL]{1,2}[uU]?)\b", r"\1", e)
    e = re.sub(r"\b[A-Za-z_]\w*\b", lambda m: f"({c_eval(defs[m.group(0)], defs, depth + 1)})"
               if m.group(0) in defs else m.group(0), e)
    if re.search(r"\b[A-Za-z_]\w*", e) or not re.fullmatch(r"[0-9a-fA-FxX()\s|&~<>+\-]*", e):
        raise ValueError(f"not an integer expression: {expr}")
    return eval(e, {"__builtins__": {}})  # noqa: S307 - digits and operators only, checked above


def c_enum_index(text, enum, member):
    m = re.search(rf"enum\s+{re.escape(enum)}\s*\{{([^}}]*)\}}", text)
    if not m:
        raise KeyError(f"no enum {enum}")
    value = -1
    for item in re.sub(r"/\*.*?\*/|//[^\n]*", "", m.group(1), flags=re.S).split(","):
        if not item.strip():
            continue
        name, _, explicit = item.partition("=")
        value = c_eval(explicit, {}) if explicit.strip() else value + 1
        if name.strip() == member:
            return value
    raise KeyError(f"enum {enum} has no {member}")


def linux_scl_tables(texts, defs):
    out = []
    for hz, name in ((19200000, "geni_i2c_clk_map_19p2mhz"), (32000000, "geni_i2c_clk_map_32mhz")):
        m = re.search(rf"{name}\[\]\s*=\s*\{{(.*?)\n\}};", texts["i2c-qcom-geni.c"], re.S)
        if not m:
            raise KeyError(f"no table {name}")
        for row in re.findall(r"\{\s*([^{}]+?)\s*\}", m.group(1)):
            cells = [c.strip() for c in row.split(",") if c.strip()]
            out.append([hz, c_eval(cells[0], defs)] + [int(c, 0) for c in cells[1:]])
    return out


def repo_scl_table(path):
    m = re.search(r"geni_i2c_scl_table\[\]\s*=\s*\{(.*?)\n\};", Path(path).read_text(), re.S)
    if not m:
        raise KeyError(f"{path}: no geni_i2c_scl_table")
    return [[_int(c) for c in row.split(",")] for row in re.findall(r"\{([^{}]+)\}", m.group(1))]


# (repository header, repository name, Linux file, Linux name)
GENI_PAIRS = [(f"GeniI2cCore.h", ours, src, theirs) for ours, src, theirs in [
    ("GENI_STATUS", "geni-se.h", "SE_GENI_STATUS"), ("GENI_SER_M_CLK_CFG", "geni-se.h", "GENI_SER_M_CLK_CFG"),
    ("GENI_IF_DISABLE_RO", "geni-se.h", "GENI_IF_DISABLE_RO"), ("GENI_FW_REVISION_RO", "geni-se.h", "GENI_FW_REVISION_RO"),
    ("GENI_CLK_SEL", "geni-se.h", "SE_GENI_CLK_SEL"), ("GENI_BYTE_GRAN", "qcom-geni-se.c", "SE_GENI_BYTE_GRAN"),
    ("GENI_DMA_MODE_EN", "geni-se.h", "SE_GENI_DMA_MODE_EN"),
    ("GENI_TX_PACKING_CFG0", "qcom-geni-se.c", "SE_GENI_TX_PACKING_CFG0"),
    ("GENI_TX_PACKING_CFG1", "qcom-geni-se.c", "SE_GENI_TX_PACKING_CFG1"),
    ("GENI_RX_PACKING_CFG0", "qcom-geni-se.c", "SE_GENI_RX_PACKING_CFG0"),
    ("GENI_RX_PACKING_CFG1", "qcom-geni-se.c", "SE_GENI_RX_PACKING_CFG1"),
    ("GENI_I2C_TX_TRANS_LEN", "i2c-qcom-geni.c", "SE_I2C_TX_TRANS_LEN"),
    ("GENI_I2C_RX_TRANS_LEN", "i2c-qcom-geni.c", "SE_I2C_RX_TRANS_LEN"),
    ("GENI_I2C_SCL_COUNTERS", "i2c-qcom-geni.c", "SE_I2C_SCL_COUNTERS"),
    ("GENI_M_CMD0", "geni-se.h", "SE_GENI_M_CMD0"), ("GENI_M_CMD_CTRL", "geni-se.h", "SE_GENI_M_CMD_CTRL_REG"),
    ("GENI_M_IRQ_STATUS", "geni-se.h", "SE_GENI_M_IRQ_STATUS"), ("GENI_M_IRQ_EN", "geni-se.h", "SE_GENI_M_IRQ_EN"),
    ("GENI_M_IRQ_CLEAR", "geni-se.h", "SE_GENI_M_IRQ_CLEAR"), ("GENI_TX_FIFO", "geni-se.h", "SE_GENI_TX_FIFOn"),
    ("GENI_RX_FIFO", "geni-se.h", "SE_GENI_RX_FIFOn"), ("GENI_TX_FIFO_STATUS", "geni-se.h", "SE_GENI_TX_FIFO_STATUS"),
    ("GENI_RX_FIFO_STATUS", "geni-se.h", "SE_GENI_RX_FIFO_STATUS"),
    ("GENI_TX_WATERMARK", "geni-se.h", "SE_GENI_TX_WATERMARK_REG"), ("GENI_M_GP_LENGTH", "geni-se.h", "SE_GENI_M_GP_LENGTH"),
    ("GENI_HW_PARAM_0", "geni-se.h", "SE_HW_PARAM_0"),
    ("GENI_M_CMD_ACTIVE", "geni-se.h", "M_GENI_CMD_ACTIVE"), ("GENI_FIFO_IF_DISABLE", "geni-se.h", "FIFO_IF_DISABLE"),
    ("GENI_FW_PROTOCOL_MASK", "geni-se.h", "FW_REV_PROTOCOL_MSK"),
    ("GENI_FW_PROTOCOL_SHIFT", "geni-se.h", "FW_REV_PROTOCOL_SHFT"), ("GENI_SER_CLK_EN", "geni-se.h", "SER_CLK_EN"),
    ("GENI_CLK_DIV_MASK", "geni-se.h", "CLK_DIV_MSK"), ("GENI_CLK_DIV_SHIFT", "geni-se.h", "CLK_DIV_SHFT"),
    ("GENI_SCL_HIGH_MASK", "i2c-qcom-geni.c", "HIGH_COUNTER_MSK"),
    ("GENI_SCL_HIGH_SHIFT", "i2c-qcom-geni.c", "HIGH_COUNTER_SHFT"),
    ("GENI_SCL_LOW_MASK", "i2c-qcom-geni.c", "LOW_COUNTER_MSK"), ("GENI_SCL_LOW_SHIFT", "i2c-qcom-geni.c", "LOW_COUNTER_SHFT"),
    ("GENI_SCL_CYCLE_MASK", "i2c-qcom-geni.c", "CYCLE_COUNTER_MSK"),
    ("GENI_TX_FIFO_DEPTH_MASK", "geni-se.h", "TX_FIFO_DEPTH_MSK"),
    ("GENI_TX_FIFO_DEPTH_SHIFT", "geni-se.h", "TX_FIFO_DEPTH_SHFT"), ("GENI_RX_FIFO_WC_MASK", "geni-se.h", "RX_FIFO_WC_MSK"),
    ("GENI_RX_LAST", "geni-se.h", "RX_LAST"), ("GENI_M_CMD_ABORT", "geni-se.h", "M_GENI_CMD_ABORT"),
    ("GENI_M_CMD_CANCEL", "geni-se.h", "M_GENI_CMD_CANCEL"),
    ("GENI_M_CMD_DONE", "geni-se.h", "M_CMD_DONE_EN"), ("GENI_M_CMD_OVERRUN", "geni-se.h", "M_CMD_OVERRUN_EN"),
    ("GENI_M_ILLEGAL_CMD", "geni-se.h", "M_ILLEGAL_CMD_EN"), ("GENI_M_CMD_FAILURE", "geni-se.h", "M_CMD_FAILURE_EN"),
    ("GENI_M_CMD_CANCEL_IRQ", "geni-se.h", "M_CMD_CANCEL_EN"), ("GENI_M_CMD_ABORT_IRQ", "geni-se.h", "M_CMD_ABORT_EN"),
    ("GENI_M_GP_IRQ_0", "geni-se.h", "M_GP_IRQ_0_EN"), ("GENI_M_GP_IRQ_1", "geni-se.h", "M_GP_IRQ_1_EN"),
    ("GENI_M_GP_IRQ_3", "geni-se.h", "M_GP_IRQ_3_EN"), ("GENI_M_GP_IRQ_4", "geni-se.h", "M_GP_IRQ_4_EN"),
    ("GENI_M_RX_FIFO_WATERMARK", "geni-se.h", "M_RX_FIFO_WATERMARK_EN"),
    ("GENI_M_RX_FIFO_LAST", "geni-se.h", "M_RX_FIFO_LAST_EN"),
    ("GENI_M_TX_FIFO_WATERMARK", "geni-se.h", "M_TX_FIFO_WATERMARK_EN"),
    ("GENI_I2C_ERR_BITS", "i2c-qcom-geni.c", "SE_I2C_ERR"),
    ("GENI_I2C_WRITE", "i2c-qcom-geni.c", "I2C_WRITE"), ("GENI_I2C_READ", "i2c-qcom-geni.c", "I2C_READ"),
    ("GENI_I2C_STOP_STRETCH", "i2c-qcom-geni.c", "STOP_STRETCH"), ("GENI_I2C_ADDR_MASK", "i2c-qcom-geni.c", "SLV_ADDR_MSK"),
    ("GENI_I2C_ADDR_SHIFT", "i2c-qcom-geni.c", "SLV_ADDR_SHFT"),
    ("GENI_M_OPCODE_SHIFT", "geni-se.h", "M_OPCODE_SHFT"), ("GENI_M_PARAMS_MASK", "geni-se.h", "M_PARAMS_MSK"),
]]
KTZ_PAIRS = [("BacklightBoard.h", ours, "ktz8866.c", theirs) for ours, theirs in [
    ("BKL_REG_DEVICE_ID", "DEVICE_ID"), ("BKL_REG_CFG2", "BL_CFG2"), ("BKL_REG_BRT_LSB", "BL_BRT_LSB"),
    ("BKL_REG_BRT_MSB", "BL_BRT_MSB"), ("BKL_REG_EN", "BL_EN"), ("BKL_REG_LCD_BIAS_CFG1", "LCD_BIAS_CFG1"),
    ("BKL_REG_DIMMING", "BL_DIMMING"), ("BKL_REG_MAX", "REG_MAX"), ("BKL_EN_BIT", "BL_EN_BIT"),
    ("BKL_LCD_BIAS_EN", "LCD_BIAS_EN"), ("BKL_PWM_HYST", "PWM_HYST"), ("BKL_MAX_LEVEL", "MAX_BRIGHTNESS"),
    ("BKL_DEFAULT_LEVEL", "DEFAULT_BRIGHTNESS"),
]]


def driver_facts(linux):
    texts = {k: (Path(linux) / v).read_text() for k, v in LINUX_DRIVERS.items()}
    linux_defs = {k: c_defines(t) for k, t in texts.items()}
    merged = {}
    for k in ("i2c.h", "geni-se.h", "qcom-geni-se.c", "i2c-qcom-geni.c", "ktz8866.c"):
        merged.update(linux_defs[k])
    repo_defs = {h: c_defines((PKG / h).read_text()) for h in ("GeniI2cCore.h", "BacklightBoard.h")}
    rows = []

    def add(fact, repo_src, repo_fn, linux_src, linux_fn):
        try:
            repo = repo_fn()
        except (KeyError, ValueError, SyntaxError) as e:
            repo = f"ERROR {e}"
        try:
            lx = linux_fn()
        except (KeyError, ValueError, SyntaxError) as e:
            lx = f"ERROR {e}"
        rows.append({"fact": fact, "repository": repo_src, "repo": repo, "linux_source": linux_src, "linux": lx})

    for header, ours, src, theirs in GENI_PAIRS + KTZ_PAIRS:
        add(ours, f"package/{header} {ours}", lambda h=header, o=ours: c_eval(repo_defs[h][o], repo_defs[h]),
            f"{LINUX_DRIVERS[src]} {theirs}",
            lambda s=src, t=theirs: c_eval(linux_defs[s][t], {**merged, **linux_defs[s]}))
    add("GENI_PROTOCOL_I2C", "package/GeniI2cCore.h GENI_PROTOCOL_I2C",
        lambda: c_eval(repo_defs["GeniI2cCore.h"]["GENI_PROTOCOL_I2C"], {}),
        f"{LINUX_DRIVERS['geni-se.h']} enum geni_se_protocol_type GENI_SE_I2C",
        lambda: c_enum_index(texts["geni-se.h"], "geni_se_protocol_type", "GENI_SE_I2C"))
    add("SCL tables (19.2 and 32 MHz)", "package/GeniI2cCore.h geni_i2c_scl_table",
        lambda: repo_scl_table(PKG / "GeniI2cCore.h"),
        f"{LINUX_DRIVERS['i2c-qcom-geni.c']} geni_i2c_clk_map_19p2mhz, _32mhz", lambda: linux_scl_tables(texts, merged))
    for r in rows:
        bad = any(isinstance(r[k], str) and r[k].startswith("ERROR") for k in ("repo", "linux"))
        r["result"] = "error" if bad else ("match" if r["repo"] == r["linux"] else "MISMATCH")
    return rows


def struct_array(path, name):
    """The rows of `name[] = {{a, b}, {c, d}}` as lists of integers."""
    m = re.search(rf"\b{re.escape(name)}\s*\[[^\]]*\]\s*=\s*\{{(.*?)\}};", Path(path).read_text(), re.S)
    if not m:
        raise KeyError(f"{path}: no array {name}")
    return [[_int(c) for c in row.split(",")] for row in re.findall(r"\{([^{}]+)\}", m.group(1))]


def vendor_facts(vendor):
    src = Source.load(*[Path(vendor) / f for f in VENDOR_FILES])
    P, T, L = PKG / "PanelBoard.h", PKG / "TouchBoard.h", PKG / "BacklightBoard.h"
    rows = []

    def add(area, fact, repo_src, repo_fn, vendor_src, vendor_fn):
        try:
            repo = repo_fn()
        except (KeyError, LookupError, ValueError) as e:
            repo = f"ERROR {e}"
        try:
            v = vendor_fn()
        except (KeyError, LookupError, ValueError) as e:
            v = f"ERROR {e}"
        rows.append({"area": area, "fact": fact, "repository": repo_src, "repo": repo, "vendor_source": vendor_src,
                     "vendor": v})

    def gpio(node, prop):
        cells = node.cells(prop)
        if cells[0] != "&tlmm":
            raise LookupError(f"{node.path} {prop}: not a TLMM GPIO: {cells}")
        return cells[1]

    def pins(node):
        return [int(p[4:]) for p in node.child("mux").strings("pins")]

    for id_macro, label in VENDOR_PANELS.items():
        panel = lambda lb=label: src.label(lb)
        timing = lambda lb=label: src.label(lb).child("qcom,mdss-dsi-display-timings").child("timing")
        tag = f"panel {id_macro[7:]}"
        where = f"{label} (dsi-panel-m82-*.dtsi, kona-sde-display.dtsi)"
        add("display", f"{tag}: identity", f"package/PanelBoard.h PNL_ID_MODEL, {id_macro}",
            lambda m=id_macro: [macro(P, "PNL_ID_MODEL"), macro(P, m)], f"{where} mi,panel-id",
            lambda p=panel: p().u32s("mi,panel-id"))
        add("display", f"{tag}: DSI interfaces, lanes, bpp", "package/PanelBoard.h PNL_DSI_COUNT, PNL_LANES, PNL_BPP",
            lambda: [macro(P, "PNL_DSI_COUNT"), macro(P, "PNL_LANES"), macro(P, "PNL_BPP")],
            f"{where} qcom,dsi-ctrl-num, lane-N-state, mdss-dsi-bpp",
            lambda p=panel: [len(p().u32s("qcom,dsi-ctrl-num")),
                             sum(p().flag(f"qcom,mdss-dsi-lane-{i}-state") for i in range(4)), p().u32("qcom,mdss-dsi-bpp")])
        add("display", f"{tag}: video mode, traffic", "package/PanelBoard.h (video mode, non-burst sync events)",
            lambda: ["dsi_video_mode", "non_burst_sync_event"], f"{where} panel-type, traffic-mode",
            lambda p=panel: [p().string("qcom,mdss-dsi-panel-type"), p().string("qcom,mdss-dsi-traffic-mode")])
        add("display", f"{tag}: refresh and lane bit clock", "package/PanelBoard.h PNL_FPS, PNL_BITCLK_HZ",
            lambda: [macro(P, "PNL_FPS"), macro(P, "PNL_BITCLK_HZ")], f"{where} timing@0 framerate, clockrate",
            lambda t=timing: [t().u32("qcom,mdss-dsi-panel-framerate"), t().u32("qcom,mdss-dsi-panel-clockrate")])
        add("display", f"{tag}: active area per DSI", "package/PanelBoard.h PNL_H_ACTIVE, PNL_V_ACTIVE",
            lambda: [macro(P, "PNL_H_ACTIVE"), macro(P, "PNL_V_ACTIVE")], f"{where} timing@0 panel-width, -height",
            lambda t=timing: [t().u32("qcom,mdss-dsi-panel-width"), t().u32("qcom,mdss-dsi-panel-height")])
        add("display", f"{tag}: porches and pulses", "package/PanelBoard.h PNL_HPW, _HBP, _HFP, _VPW, _VBP, _VFP",
            lambda: [macro(P, n) for n in ("PNL_HPW", "PNL_HBP", "PNL_HFP", "PNL_VPW", "PNL_VBP", "PNL_VFP")],
            f"{where} timing@0 h/v pulse width, back porch, front porch",
            lambda t=timing: [t().u32(f"qcom,mdss-dsi-{n}") for n in ("h-pulse-width", "h-back-porch", "h-front-porch",
                                                                      "v-pulse-width", "v-back-porch", "v-front-porch")])
        add("display", f"{tag}: DSC", "package/PanelBoard.h PNL_DSC_*",
            lambda: [macro(P, n) for n in ("PNL_DSC_VERSION", "PNL_DSC_SLICE_WIDTH", "PNL_DSC_SLICE_HEIGHT",
                                           "PNL_DSC_SLICE_PER_PKT", "PNL_DSC_BPC", "PNL_DSC_BPP")] + ["dsc"],
            f"{where} timing@0 qcom,mdss-dsc-*, compression-mode",
            lambda t=timing: [t().u32(f"qcom,mdss-dsc-{n}") for n in ("version", "slice-width", "slice-height",
                                                                      "slice-per-pkt", "bit-per-component", "bit-per-pixel")]
            + [t().string("qcom,compression-mode")])
        add("display", f"{tag}: topology", "package/PanelBoard.h PNL_TOPOLOGY_LM, _DSC, _INTF",
            lambda: [macro(P, "PNL_TOPOLOGY_LM"), macro(P, "PNL_TOPOLOGY_DSC"), macro(P, "PNL_TOPOLOGY_INTF")],
            f"{where} timing@0 qcom,display-topology", lambda t=timing: t().u32s("qcom,display-topology"))
        add("display", f"{tag}: PHY timings", "package/PanelBoard.h pnl_phy_timings", lambda: array(P, "pnl_phy_timings"),
            f"{where} timing@0 qcom,mdss-dsi-panel-phy-timings",
            lambda t=timing: list(t().bytes("qcom,mdss-dsi-panel-phy-timings")))
        add("display", f"{tag}: physical size (0.1 mm)", "package/PanelBoard.h PNL_WIDTH_DMM, PNL_HEIGHT_DMM",
            lambda: [macro(P, "PNL_WIDTH_DMM"), macro(P, "PNL_HEIGHT_DMM")], f"{where} mdss-pan-physical-*-dimension",
            lambda p=panel: [p().u32("qcom,mdss-pan-physical-width-dimension"),
                             p().u32("qcom,mdss-pan-physical-height-dimension")])
        add("display", f"{tag}: reset sequence", "package/PanelBoard.h pnl_reset_sequence",
            lambda: struct_array(P, "pnl_reset_sequence"), f"{where} qcom,mdss-dsi-reset-sequence",
            lambda p=panel: p().groups("qcom,mdss-dsi-reset-sequence"))
        add("display", f"{tag}: dynamic fps list", "package/PanelBoard.h pnl_dfps", lambda: array(P, "pnl_dfps"),
            f"{where} qcom,dsi-supported-dfps-list", lambda p=panel: p().u32s("qcom,dsi-supported-dfps-list"))
        add("display", f"{tag}: status check", "package/PanelBoard.h PNL_STATUS_DCS, PNL_STATUS_VALUE",
            lambda: [macro(P, "PNL_STATUS_DCS"), macro(P, "PNL_STATUS_VALUE")],
            f"{where} panel-status-command (last byte), -status-value",
            lambda p=panel: [p().bytes("qcom,mdss-dsi-panel-status-command")[-1],
                             p().u32("qcom,mdss-dsi-panel-status-value")])
        add("display", f"{tag}: ESD interrupt GPIOs", "package/PanelBoard.h PNL_GPIO_ESD, PNL_GPIO_ESD_SEC",
            lambda: [macro(P, "PNL_GPIO_ESD"), macro(P, "PNL_GPIO_ESD_SEC")], f"{where} mi,esd-err-irq-gpio(-sec)",
            lambda p=panel: [gpio(p(), "mi,esd-err-irq-gpio"), gpio(p(), "mi,esd-err-irq-gpio-sec")])
    add("display", "panel TE GPIO", "package/PanelBoard.h PNL_GPIO_TE", lambda: macro(P, "PNL_GPIO_TE"),
        "sde_dsi qcom,platform-te-gpio (kona-sde-display.dtsi)",
        lambda: gpio(src.label("sde_dsi"), "qcom,platform-te-gpio"))
    add("display", "panel DVDD rails (GPIO, uV)", "package/PanelBoard.h PNL_GPIO_DVDD_BUCK, _LDO, PNL_DVDD_UV",
        lambda: [macro(P, "PNL_GPIO_DVDD_BUCK"), macro(P, "PNL_GPIO_DVDD_LDO"), [macro(P, "PNL_DVDD_UV")]],
        "display_panel_dvdd_buck / _ldo gpio, regulator-min-microvolt (pipa-sm8250.dtsi)",
        lambda: [gpio(src.label("display_panel_dvdd_buck"), "gpio"), gpio(src.label("display_panel_dvdd_ldo"), "gpio"),
                 sorted({src.label(n).u32("regulator-min-microvolt")
                         for n in ("display_panel_dvdd_buck", "display_panel_dvdd_ldo")})])
    add("display", "panel bias rails (GPIO, uV, ramp)", "package/PanelBoard.h PNL_GPIO_ENP, _ENN, PNL_BIAS_UV, _RAMP_US",
        lambda: [macro(P, "PNL_GPIO_ENP"), macro(P, "PNL_GPIO_ENN"), macro(P, "PNL_BIAS_UV"), macro(P, "PNL_BIAS_RAMP_US")],
        "display_panel_enp / _enn (pipa-sm8250.dtsi)",
        lambda: [gpio(src.label("display_panel_enp"), "gpio"), gpio(src.label("display_panel_enn"), "gpio"),
                 src.label("display_panel_enp").u32("regulator-min-microvolt"),
                 src.label("display_panel_enp").u32("regulator-enable-ramp-delay")])

    # Touch: Novatek NT36532 on SPI (QUP0 SE4)
    spi = lambda: src.label("qupv3_se4_spi")
    nvt = lambda: spi().child("novatek")
    add("touch", "touch SPI serial engine", "package/TouchBoard.h TB_SE_BASE, TB_SE_SIZE",
        lambda: [macro(T, "TB_SE_BASE"), macro(T, "TB_SE_SIZE")], "qupv3_se4_spi reg (kona-qupv3.dtsi)",
        lambda: spi().u32s("reg"))
    add("touch", "touch controller enabled on it", "package/TouchProbe.cpp (Novatek NT36532 on SPI)",
        lambda: ["novatek,NVT-ts-spi", True], "qupv3_se4_spi/novatek@0 compatible, status (pipa-sm8250.dtsi)",
        lambda: [nvt().string("compatible"), spi().enabled() and nvt().enabled()])
    add("touch", "touch interrupt GPIO", "package/TouchBoard.h TB_GPIO_IRQ", lambda: macro(T, "TB_GPIO_IRQ"),
        "novatek@0 novatek,irq-gpio", lambda: gpio(nvt(), "novatek,irq-gpio"))
    add("touch", "touch SPI clock", "package/TouchBoard.h TB_SPI_DEFAULT_HZ", lambda: macro(T, "TB_SPI_DEFAULT_HZ"),
        "novatek@0 spi-max-frequency", lambda: nvt().u32("spi-max-frequency"))
    add("touch", "touch SPI pins (data/clock, CS)", "package/TouchBoard.h TB_GPIO_SPI_FIRST.., TB_GPIO_SPI_CS",
        lambda: [list(range(macro(T, "TB_GPIO_SPI_FIRST"), macro(T, "TB_GPIO_SPI_FIRST") + 3)), [macro(T, "TB_GPIO_SPI_CS")]],
        "qupv3_se4_spi_active, ts_cs_active mux pins",
        lambda: [pins(src.label("qupv3_se4_spi_active")), pins(src.label("ts_cs_active"))])
    add("touch", "touch pin function and drive", "package/TouchBoard.h TB_FUNC_QUP4 (qup4), TB_DRIVE_6MA (mA/2-1)",
        lambda: ["qup4", "qup4", (macro(T, "TB_DRIVE_6MA") + 1) * 2, (macro(T, "TB_DRIVE_6MA") + 1) * 2],
        "qupv3_se4_spi_active / ts_cs_active function, drive-strength",
        lambda: [src.label("qupv3_se4_spi_active").child("mux").string("function"),
                 src.label("ts_cs_active").child("mux").string("function"),
                 src.label("qupv3_se4_spi_active").child("config").u32("drive-strength"),
                 src.label("ts_cs_active").child("config").u32("drive-strength")])
    add("touch", "touch firmware by panel maker", "package/PanelBoard.h PNL_MAKER_CSOT, PNL_MAKER_TM",
        lambda: [macro(P, "PNL_MAKER_CSOT"), macro(P, "PNL_MAKER_TM")], "novatek@0 cfg_N novatek,display-maker",
        lambda: [c.u32("novatek,display-maker") for n, c in sorted(nvt().children.items()) if n.startswith("novatek,cfg_")])

    # Backlight, the vendor view (compatible differs from mainline's kinetic,ktz8866)
    i2c = lambda: src.label("qupv3_se11_i2c")
    ktz = lambda: i2c().child("ktz8866")
    add("display", "backlight I2C serial engine (vendor)", "package/BacklightBoard.h BKL_I2C_SE_BASE",
        lambda: macro(L, "BKL_I2C_SE_BASE"), "qupv3_se11_i2c reg (kona-qupv3.dtsi)", lambda: i2c().u32s("reg")[0])
    add("display", "backlight controller (vendor)", "package/BacklightBoard.h BKL_I2C_ADDR",
        lambda: ["ktz,ktz8866", macro(L, "BKL_I2C_ADDR"), True], "ktz8866@11 compatible, reg, status",
        lambda: [ktz().string("compatible"), ktz().u32("reg"), i2c().enabled() and ktz().enabled()])
    add("display", "backlight GPIOs (vendor)", "package/BacklightBoard.h BKL_GPIO_ENABLE, _VDDPOS, _VDDNEG, _PANELID",
        lambda: [macro(L, n) for n in ("BKL_GPIO_ENABLE", "BKL_GPIO_VDDPOS", "BKL_GPIO_VDDNEG", "BKL_GPIO_PANELID")],
        "ktz8866@11 ktz8866,hwen/enp/enn/panelid-gpio",
        lambda: [gpio(ktz(), f"ktz8866,{n}-gpio") for n in ("hwen", "enp", "enn", "panelid")])
    for r in rows:
        bad = any(isinstance(r[k], str) and r[k].startswith("ERROR") for k in ("repo", "vendor"))
        r["result"] = "error" if bad else ("match" if r["repo"] == r["vendor"] else "MISMATCH")
    return rows


def run_vendor(args):
    rows = vendor_facts(args.vendor)
    summary = {k: sum(1 for r in rows if r["result"] == k) for k in ("match", "MISMATCH", "error")}
    if args.json:
        Path(args.json).write_text(json.dumps({"vendor": VENDOR_GIT, "branch": VENDOR_BRANCH, "commit": VENDOR_COMMIT,
                                               "summary": summary, "facts": rows}, indent=2, default=str) + "\n")
    width = max(len(r["fact"]) for r in rows)
    for r in rows:
        print(f"{r['result']:8} {r['area']:8} {r['fact']:{width}}  repo={fmt(r['repo'])}  vendor={fmt(r['vendor'])}")
    print(json.dumps(summary))
    if summary["MISMATCH"] or summary["error"]:
        sys.exit("board facts disagree with the vendor pipa device tree")


def run_drivers(args):
    rows = driver_facts(args.linux)
    summary = {k: sum(1 for r in rows if r["result"] == k) for k in ("match", "MISMATCH", "error")}
    if args.json:
        Path(args.json).write_text(json.dumps({"linux": LINUX_COMMIT, "summary": summary, "facts": rows}, indent=2,
                                              default=str) + "\n")
    width = max(len(r["fact"]) for r in rows)
    for r in rows:
        print(f"{r['result']:8} {r['fact']:{width}}  repo={fmt(r['repo'])}  linux={fmt(r['linux'])}")
    print(json.dumps(summary))
    if summary["MISMATCH"] or summary["error"]:
        sys.exit("driver constants disagree with the Linux driver sources")


# Inventory ------------------------------------------------------------------------------------------------------------

def binding_names(linux):
    """{header: {value: [names]}} of the dt-bindings headers in BINDINGS."""
    out = {}
    for headers in BINDINGS.values():
        for h in headers:
            path = Path(linux) / "include/dt-bindings" / h
            table = {}
            if path.is_file():
                for name, value in re.findall(r"^#define\s+(\w+)\s+(\d+)\s*$", path.read_text(), re.M):
                    table.setdefault(int(value), []).append(name)
            out[h] = table
    return out


def decode(names, provider, args, kind):
    headers = next((BINDINGS[c] for c in provider.strings("compatible") if c in BINDINGS), [])
    if not args:
        return None
    for h in headers:
        cands = names.get(h, {}).get(args[0], [])
        if kind == "power":
            cands = [c for c in cands if c.endswith("_GDSC") or c.startswith(("RPMHPD_", "SM8250_"))]
        else:
            cands = [c for c in cands if not c.endswith(("_GDSC", "_BCR", "_RESET")) and not c.startswith("RPMHPD_")]
        if cands:
            return cands[0]
    return None   # no dt-bindings name (a PHY's clock output, a raw index): the caller names the provider


SUBSYSTEMS = [
    ("CPU and interrupts", ["intc", "pdc", "tlmm", "cpufreq_hw", "spmi_bus"]),
    ("Clocks", ["rpmhcc", "gcc", "gpucc", "dispcc", "videocc", "camcc"]),
    ("Power domains and RPMh", ["rpmhpd", "apps_rsc"]),
    ("GPU", ["gpu", "gmu", "adreno_smmu"]),
    ("Display", ["mdss", "mdss_mdp", "mdss_dsi0", "mdss_dsi0_phy", "mdss_dsi1", "mdss_dsi1_phy", "i2c11", "backlight"]),
    ("Touch and input", ["qupv3_id_0", "spi4", "pon", "pon_pwrkey", "pon_resin", "pm8150_gpios", "gpio_keys"]),
    ("Storage, USB, PCIe", ["ufs_mem_hc", "ufs_mem_phy", "usb_1", "usb_1_dwc3", "usb_1_hsphy", "usb_1_qmpphy", "pcie0", "pcie0_phy"]),
    ("Remote processors and media", ["adsp", "cdsp", "slpi", "venus", "gpu_zap_shader"]),
    ("SMMU", ["apps_smmu"]),
]


def supplies(tree, node):
    out = []
    for key in sorted(node.props):
        if key.endswith("-supply"):
            reg_node = tree.phandle(node.u32(key))
            if reg_node is not None:
                lo, hi = reg_node.u32("regulator-min-microvolt"), reg_node.u32("regulator-max-microvolt")
                volts = f" {lo / 1e6:g}-{hi / 1e6:g} V" if lo is not None else ""
                out.append(f"{key[:-7]}={reg_node.string('regulator-name', tree.name_of(reg_node))}{volts}")
    return out


def row(tree, names, label):
    node = tree.label(label)
    if node is None:
        return None
    cpu_regs, bus_regs = tree.regs(node), tree.regs(node, translate=False)
    parts = []
    for (a, s), (b, _), n in zip(cpu_regs, bus_regs, node.strings("reg-names") + [""] * len(cpu_regs)):
        if a is not None:
            parts.append(f"{a:#x}+{s:#x}" + (f" {n}" if n else ""))
        else:   # a device on a bus without ranges (I2C, SPI, SPMI): its address on that bus
            parts.append(f"{node.parent.unit_name} address {b:#x}")
    regs = ", ".join(parts)
    irqs = ", ".join(f"{i['gic'][0]} {i['gic'][1]} (INTID {i['gic'][2]})" if i.get("gic") else
                     f"{i['controller']} {' '.join(map(str, i['cells']))}" for i in tree.interrupts(node))
    clocks = [decode(names, p, a, "clock") or f"{tree.name_of(p)} {' '.join(map(str, a))}".strip()
              for p, a in tree.phandle_list(node, "clocks", "#clock-cells")] \
        if "clocks" in node.props else []
    domains = [decode(names, p, a, "power") or f"{tree.name_of(p)} {' '.join(map(str, a))}".strip()
               for p, a in tree.phandle_list(node, "power-domains", "#power-domain-cells")] \
        if "power-domains" in node.props else []
    streams = [f"{tree.name_of(p)} {' '.join(hex(x) for x in a)}" for p, a in tree.phandle_list(node, "iommus", "#iommu-cells")] \
        if "iommus" in node.props else []
    extra = []
    if node.string("firmware-name"):
        extra.append("firmware " + node.string("firmware-name"))
    if "operating-points-v2" in node.props:
        table = tree.phandle(node.u32("operating-points-v2"))
        hz = sorted(struct.unpack(">Q", c.props["opp-hz"][:8])[0] for c in table.children if "opp-hz" in c.props)
        if hz:
            extra.append("OPP " + ", ".join(f"{h // 1000000}" for h in hz) + " MHz")
    for key in sorted(k for k in node.props if k.endswith("gpios") or k == "gpio"):
        cells, i, pins = node.u32s(key), 0, []
        while i < len(cells):
            ctrl = tree.phandle(cells[i])
            n = ctrl.u32("#gpio-cells", 2) if ctrl is not None else 2
            if ctrl is not None:
                pins.append(f"{tree.name_of(ctrl)} {cells[i + 1]}" + (" active-low" if n > 1 and cells[i + 2] & 1 else ""))
            i += 1 + n
        extra.append(f"{key} " + ", ".join(pins))
    for key in ("clock-frequency", "dr_mode"):
        if key in node.props:
            extra.append(f"{key} {node.string(key) if key == 'dr_mode' else node.u32(key)}")
    return {"label": label, "enabled": tree.effectively_enabled(node), "compatible": node.string("compatible", ""),
            "reg": regs, "interrupts": irqs, "clocks": clocks, "power_domains": domains, "iommus": streams,
            "supplies": supplies(tree, node), "notes": extra}


def regulators(tree):
    out = []
    for node in tree.compatible("qcom,pm8150-rpmh-regulators", "qcom,pm8150l-rpmh-regulators"):
        for child in node.children:
            if "regulator-name" in child.props:
                flags = [k[10:] for k in ("regulator-always-on", "regulator-boot-on") if k in child.props]
                out.append((node.string("qcom,pmic-id"), child.name, child.string("regulator-name"),
                            child.u32("regulator-min-microvolt"), child.u32("regulator-max-microvolt"), flags))
    return out


def markdown_inventory(tree, names):
    lines = [f"<!-- Generated by scripts/pipa_hw.py inventory from Linux {LINUX_COMMIT[:12]} {LINUX_DTS}; do not edit. -->",
             "<!-- SPDX-License-Identifier: BSD-2-Clause-Patent -->", "",
             "# Xiaomi Pad 6 (pipa): mainline device tree inventory", "",
             f"Source: Linux `{LINUX_COMMIT[:12]}`, `{LINUX_DTS}` (+ `sm8250.dtsi`, `pm8150*.dtsi`). "
             "Addresses are CPU physical; interrupts are GIC numbers; clocks and power domains are the dt-bindings "
             "names. This is the public hardware description, not a test result.", ""]
    cpus = [c for c in tree.path("/cpus").children if c.name.startswith("cpu@")]
    lines += ["## CPUs", "", "| CPU | MPIDR | compatible | capacity | EPSS domain |", "| --- | --- | --- | ---: | ---: |"]
    for c in cpus:
        dom = tree.phandle_list(c, "qcom,freq-domain", "#freq-domain-cells")[0][1][0]
        lines.append(f"| {c.name} | {c.u32s('reg')[-1]:#x} | {c.string('compatible')} | {c.u32('capacity-dmips-mhz')} | {dom} |")
    for title, labels in SUBSYSTEMS:
        lines += ["", f"## {title}", "", "| Node | Status | Compatible | Registers | Interrupts | Clocks | Power domains | SMMU | Supplies | Notes |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for label in labels:
            r = row(tree, names, label)
            if r is None:
                lines.append(f"| `{label}` | absent | | | | | | | | |")
                continue
            cell = lambda v: "<br>".join(v) if isinstance(v, list) else v
            lines.append("| `{label}` | {st} | `{compatible}` | {reg} | {irq} | {clk} | {pd} | {mmu} | {sup} | {notes} |".format(
                label=label, st="enabled" if r["enabled"] else "disabled", compatible=r["compatible"], reg=r["reg"],
                irq=r["interrupts"], clk=cell(r["clocks"]), pd=cell(r["power_domains"]), mmu=cell(r["iommus"]),
                sup=cell(r["supplies"]), notes=cell(r["notes"])))
    lines += ["", "## PMICs on SPMI", "", "| USID | Compatible | Enabled peripherals |", "| ---: | --- | --- |"]
    for node in tree.nodes:
        if node.parent and "qcom,spmi-pmic-arb" in node.parent.strings("compatible"):
            per = [f"{c.unit_name}@{c.u32s('reg')[0]:#x}" for c in node.children if c.u32s("reg") and tree.effectively_enabled(c)]
            lines.append(f"| {node.u32s('reg')[0]} | `{node.string('compatible')}` | {', '.join(per)} |")
    lines += ["", "## RPMh regulators", "", "| PMIC | Node | Name | Min V | Max V | Flags |", "| --- | --- | --- | ---: | ---: | --- |"]
    for pmic, nm, name, lo, hi, flags in regulators(tree):
        lines.append(f"| {pmic} | {nm} | {name} | {lo / 1e6:g} | {hi / 1e6:g} | {', '.join(flags)} |")
    lines += ["", "## Reserved memory", "", "| Label | Node | Base | Size | no-map |", "| --- | --- | --- | --- | --- |"]
    for node in sorted(tree.path("/reserved-memory").children, key=lambda n: (tree.regs(n) or [(0, 0)])[0][0] or 0):
        for a, s in tree.regs(node):
            label = tree.label_of.get(node.path, "")
            lines.append(f"| {label} | {node.name} | {a:#x} | {s:#x} | {'yes' if 'no-map' in node.props else ''} |")
    return "\n".join(lines) + "\n"


def run_inventory(args):
    tree = Tree.load(args.dtb)
    text = markdown_inventory(tree, binding_names(args.linux))
    if args.check:
        current = Path(args.markdown).read_text() if Path(args.markdown).is_file() else ""
        if current != text:
            sys.exit(f"{args.markdown} is not current; run scripts/pipa_hw.py inventory without --check")
        print(f"{args.markdown} is current")
        return
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(text)
        print(f"wrote {args.markdown}")
    else:
        print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--linux", type=Path, required=True)
    p = sub.add_parser("compile")
    p.add_argument("--linux", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dtc", default="dtc")
    p.add_argument("--cpp", default="cpp")
    p = sub.add_parser("check")
    p.add_argument("--dtb", type=Path, required=True)
    p.add_argument("--soc", type=Path, help="UniXNU-sm8250-common checkout: also compile and check devices/pipa/dts/pipa.dts")
    p.add_argument("--dtc", default="dtc")
    p.add_argument("--json", type=Path)
    p = sub.add_parser("inventory")
    p.add_argument("--dtb", type=Path, required=True)
    p.add_argument("--linux", type=Path, required=True)
    p.add_argument("--markdown", type=Path)
    p.add_argument("--check", action="store_true")
    p = sub.add_parser("fetch-vendor")
    p.add_argument("--vendor", type=Path, required=True)
    p = sub.add_parser("vendor")
    p.add_argument("--vendor", type=Path, required=True)
    p.add_argument("--json", type=Path)
    p = sub.add_parser("drivers")
    p.add_argument("--linux", type=Path, required=True)
    p.add_argument("--json", type=Path)
    args = ap.parse_args()
    if args.cmd == "fetch":
        print(fetch(args.linux))
    elif args.cmd == "compile":
        head = run(["git", "-C", args.linux, "rev-parse", "HEAD"]).strip() if (args.linux / ".git").exists() else None
        if head and head != LINUX_COMMIT:
            sys.exit(f"{args.linux} is at {head}, expected {LINUX_COMMIT}")
        print(compile_dts(args.linux, args.out, args.dtc, args.cpp))
    elif args.cmd == "check":
        run_check(args)
    elif args.cmd == "drivers":
        run_drivers(args)
    elif args.cmd == "fetch-vendor":
        print(fetch_vendor(args.vendor))
    elif args.cmd == "vendor":
        run_vendor(args)
    else:
        run_inventory(args)


if __name__ == "__main__":
    main()
