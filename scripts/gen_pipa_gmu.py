#!/usr/bin/env python3
"""Generate the board GMU inputs of pipa's Adreno 650 (build/pipa-gmu/ShengGmuSource.h) from the board's device tree and
pinned Linux sources, and check the hand-written A650 cold start (devices/pipa/package/A650Gmu.c) against them (G3).

    scripts/gen_pipa_gmu.py --linux DIR --dtb pipa-mainline.dtb [--out build/pipa-gmu] [--check]

UniXNU's A740 board (sheng) generates ShengGmuSource.h with prepare-sheng-gmu.py: register offsets from Linux's
a6xx.xml / a6xx_gmu.xml, the RSC/PDC setup of a6xx_gmu_rpmh_init, the chip ID from a6xx_catalog.c and the register
windows from the board DTB. ShengGmu.h itself is the API of UniXNU-sm8550-common's Sm8550Platform kit, not generated.
This is the same generation for the A650 (chip 0x06050002, "a650 family"):
  - windows from the DTB: gmu node reg-names gmu, rscc, gmu_pdc; gpu node kgsl_3d0_reg_memory;
  - GMU register dword offsets relative to the GMU window: the xml offset minus mmio_offset / 4, mmio_offset being
    the GMU window's distance from the GPU's (a6xx_gmu.c: gmu->mmio_offset = start - res->start);
  - the RSC/PDC writes of a6xx_gmu_rpmh_init evaluated for the a650 family (not a7xx, a740, a722, a8xx; pdc_in_aop),
    with structural checks on the source so a change upstream is an error, not a silent new sequence;
  - the AO and CM3 fatal masks from the xml bitfields (A6XX_GMU_IRQ_MASK, A6XX_HFI_IRQ_MASK of a6xx_gmu.c).
No firmware is read or pinned here (the GMU image is the tablet's, read by the board probe). --check compares every
offset, mask, chip ID, window size and the RSC/PDC table of A650Gmu.c with the generated values and fails on a
difference. Source analysis only; nothing touches hardware.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "devices/pipa/package"
SOURCES = {"a6xx_gmu.c": "drivers/gpu/drm/msm/adreno/a6xx_gmu.c", "a6xx_gmu.h": "drivers/gpu/drm/msm/adreno/a6xx_gmu.h",
           "a6xx_catalog.c": "drivers/gpu/drm/msm/adreno/a6xx_catalog.c",
           "a6xx.xml": "drivers/gpu/drm/msm/registers/adreno/a6xx.xml",
           "a6xx_gmu.xml": "drivers/gpu/drm/msm/registers/adreno/a6xx_gmu.xml"}
NS = {"r": "http://nouveau.freedesktop.org/"}
CHIP = 0x06050002
# The a650 family, as a6xx_gmu.c's predicates answer for chip 0x06050002 (adreno_gpu.h: a650_family covers a650, a660,
# a690; a7xx/a740/a722/a8xx/a618/a619/a640 do not).
PREDICATES = {"adreno_is_a650_family": True, "adreno_is_a7xx": False, "adreno_is_a740_family": False,
              "adreno_is_a722": False, "adreno_is_a8xx": False, "adreno_is_a618": False, "adreno_is_a619": False,
              "adreno_is_a640_family": False}
WINDOWS = ["gmu", "rscc", "gmu_pdc", "kgsl_3d0_reg_memory"]          # A650GmuCore, A650GmuRscc, A650GmuPdc, the GPU
CORE, RSCC, PDC = 0, 1, 2


class GenError(SystemExit):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Registers -----------------------------------------------------------------------------------------------------------

def load_registers(linux):
    """{(domain, name): [(dword offset, variants or None, element)]} of a6xx.xml and a6xx_gmu.xml."""
    regs = {}
    for name in ("a6xx.xml", "a6xx_gmu.xml"):
        root = ET.parse(Path(linux) / SOURCES[name]).getroot()
        for domain in root.findall("r:domain", NS):
            for reg in domain.findall("r:reg32", NS):
                regs.setdefault((domain.attrib["name"], reg.attrib["name"]), []).append(
                    (int(reg.attrib["offset"], 0), reg.attrib.get("variants"), reg))
    return regs


def applies(variants, gen="A6XX"):
    """An xml variants attribute ("A6XX", "A7XX-", "A6XX-A7XX", None) applies to the a6xx generation."""
    if variants is None:
        return True
    order = ["A2XX", "A3XX", "A4XX", "A5XX", "A6XX", "A7XX", "A8XX"]
    for part in variants.split(","):
        part = part.strip()
        if "-" in part:
            lo, _, hi = part.partition("-")
            lo_i = order.index(lo) if lo else 0
            hi_i = order.index(hi) if hi else len(order) - 1
            if lo_i <= order.index(gen) <= hi_i:
                return True
        elif part == gen:
            return True
    return False


def register(regs, domain, name):
    hits = [(o, v, e) for o, v, e in regs.get((domain, name), []) if applies(v)]
    if len(hits) != 1:
        raise GenError(f"{domain}.{name}: {len(hits)} a6xx definitions in the xml")
    return hits[0]


def bit(regs, domain, name, field):
    _, _, reg = register(regs, domain, name)
    for f in reg.findall("r:bitfield", NS):
        if f.attrib.get("name") == field:
            return 1 << int(f.attrib["pos"])
    raise GenError(f"{domain}.{name}: no bitfield {field}")


# The RSC/PDC sequence -----------------------------------------------------------------------------------------------

def c_value(expr, symbols):
    """Evaluate a value or offset expression of a6xx_gmu_rpmh_init for the a650: REG_* names, BIT(n), + and the
    ternaries on adreno_is_*() predicates."""
    e = " ".join(expr.split())
    e = re.sub(r"\badreno_is_(\w+)\(adreno_gpu\)", lambda m: str(PREDICATES[f"adreno_is_{m.group(1)}"])
               if f"adreno_is_{m.group(1)}" in PREDICATES else m.group(0), e)
    e = re.sub(r"\bBIT\((\d+)\)", lambda m: str(1 << int(m.group(1))), e)
    e = e.replace("||", " or ").replace("&&", " and ")
    while "?" in e:                                       # cond ? a : b, innermost first (one level is all there is)
        m = re.search(r"\(?\s*([^?():]+?)\s*\)?\s*\?\s*([^?:()]+?)\s*:\s*([^?:()]+)", e)
        if not m:
            raise GenError(f"unsupported ternary: {expr}")
        e = e[:m.start()] + f"(({m.group(2)}) if ({m.group(1)}) else ({m.group(3)}))" + e[m.end():]
    e = re.sub(r"\b(REG_A[67]XX_\w+|seqmem0_drv0_reg)\b", lambda m: str(symbols[m.group(1)]), e)
    if re.search(r"[A-Za-z_]\w*", re.sub(r"\b(True|False|or|and|if|else|0x[0-9a-fA-F]+)\b", "", e)):
        raise GenError(f"unknown name in {expr!r} -> {e!r}")
    return int(eval(e, {"__builtins__": {}}))  # noqa: S307 - digits, operators and booleans only, checked above


def need(text, snippet, what):
    if " ".join(snippet.split()) not in " ".join(text.split()):
        raise GenError(f"a6xx_gmu.c: {what} changed (expected {snippet!r})")


def rpmh_sequence(linux, regs, expected=19):
    """[(window, dword, value)] that a6xx_gmu_rpmh_init writes for the a650 family, in order."""
    src = (Path(linux) / SOURCES["a6xx_gmu.c"]).read_text()
    start = src.index("static void a6xx_gmu_rpmh_init(")
    body = src[start:src.index("\n}\n", start)]
    need(body, "if (adreno_is_a650_family(adreno_gpu) || adreno_is_a7xx(adreno_gpu)) pdc_in_aop = true;",
         "the a650 family's pdc_in_aop")
    need(body, "if (pdc_in_aop) goto setup_pdc;", "the jump over the PDC sequencer for pdc_in_aop")
    need(body, "if (adreno_is_a740_family(adreno_gpu) || adreno_is_a722(adreno_gpu)) "
               "seqmem0_drv0_reg = REG_A7XX_RSCC_SEQ_MEM_0_DRV0_A740;", "the RSC sequencer address selection")
    class Symbols(dict):
        """REG_* names resolved from the xml when a reached statement uses them (the a650 path never evaluates the
        other branches' registers, e.g. the PDC sequencer memory, which lives in A6XX_PDC_GPU_SEQ)."""
        def __missing__(self, full):
            m = re.fullmatch(r"REG_(A[67]XX)_(\w+)", full)
            if not m:
                raise GenError(f"unknown symbol {full}")
            name = m.group(2)
            domain, xml_name = ("A6XX_PDC", name[4:]) if name.startswith("PDC_") else ("A6XX", name)
            self[full] = register(regs, domain, xml_name)[0]
            return self[full]

    symbols = Symbols()
    seqmem = symbols["REG_A6XX_RSCC_SEQ_MEM_0_DRV0"]
    if PREDICATES["adreno_is_a740_family"] or PREDICATES["adreno_is_a722"]:
        raise GenError("not an a650")
    symbols["seqmem0_drv0_reg"] = seqmem
    writes = []

    def take(segment, fn, window, pointer=None):
        pat = r"gmu_write_rscc\(gmu,\s*([^,]+),\s*([\s\S]*?)\);" if fn == "rscc" else \
            rf"pdc_write\({pointer},\s*([^,]+),\s*([\s\S]*?)\);"
        for reg, value in re.findall(pat, segment):
            writes.append((window, c_value(reg, symbols), c_value(value, symbols)))

    prefix = body[body.index("/* Disable SDE clock gating */"):body.index("/* The second spin")]
    take(prefix, "rscc", RSCC)
    ucode = body.index("/* Load RSC sequencer uCode for sleep and wakeup */")
    branch = body[ucode:body.index("} else {", ucode)]
    need(branch, "if (adreno_is_a650_family(adreno_gpu) || adreno_is_a7xx(adreno_gpu)) {", "the a650 sequencer branch")
    take(branch, "rscc", RSCC)
    tail = body[body.index("setup_pdc:"):]
    take(tail, "pdc", PDC, "pdcptr")
    if len(writes) != expected:
        raise GenError(f"the a650 RSC/PDC sequence has {len(writes)} writes, expected {expected} (12 RSC, 5 sequencer, 2 PDC)")
    return writes


# The board ------------------------------------------------------------------------------------------------------------

def dt_windows(dtb):
    from tools.hw.fdt import Tree
    tree = Tree.load(dtb)
    out = {}
    for label in ("gmu", "gpu"):
        node = tree.label(label)
        if node is None:
            raise GenError(f"{dtb}: no {label} node")
        names = node.strings("reg-names")
        for name, (base, size) in zip(names, tree.regs(node)):
            out[name] = (base, size)
    missing = [w for w in WINDOWS if w not in out]
    if missing:
        raise GenError(f"{dtb}: no register window {', '.join(missing)}")
    return out


def catalog_chip(linux):
    text = (Path(linux) / SOURCES["a6xx_catalog.c"]).read_text()
    m = re.search(rf"\.chip_ids = ADRENO_CHIP_IDS\({CHIP:#010x}\)([\s\S]*?)\}}, \{{", text)
    if not m:
        raise GenError("a6xx_catalog.c: no 0x06050002 entry")
    fw = re.search(r'\[ADRENO_FW_GMU\] = "([^"]+)"', m.group(1))
    if not fw or "a6xx_gmu" not in m.group(1) and "gmu" not in fw.group(1):
        raise GenError("a6xx_catalog.c: the A650 entry names no GMU firmware")
    return {"chip_id": CHIP, "gmu_firmware": fw.group(1)}


# Generation --------------------------------------------------------------------------------------------------------

GMU_NAMES = {   # A650Gmu.c enum name -> (xml domain, xml name)
    **{n: ("A6XX", n) for n in (
        "GMU_CM3_ITCM_START", "GMU_CM3_DTCM_START", "GMU_ICACHE_CONFIG", "GMU_DCACHE_CONFIG", "GMU_SYS_BUS_CONFIG",
        "GMU_CM3_SYSRESET", "GMU_CM3_BOOT_CONFIG", "GMU_CM3_FW_INIT_RESULT", "GMU_CM3_CFG", "GMU_PWR_COL_INTER_FRAME_CTRL",
        "GMU_RPMH_CTRL", "GMU_HFI_CTRL_STATUS", "GMU_HFI_SFR_ADDR", "GMU_HFI_QTBL_INFO", "GMU_HFI_QTBL_ADDR",
        "GMU_HFI_CTRL_INIT", "GMU_GMU2HOST_INTR_CLR", "GMU_GMU2HOST_INTR_INFO", "GMU_GMU2HOST_INTR_MASK",
        "GMU_HOST2GMU_INTR_SET", "GMU_GENERAL_7", "GMU_AO_HOST_INTERRUPT_CLR", "GMU_AO_HOST_INTERRUPT_STATUS",
        "GMU_AO_HOST_INTERRUPT_MASK", "GMU_RSCC_CONTROL_REQ", "GMU_RSCC_CONTROL_ACK", "GMU_AHB_FENCE_RANGE_0")},
    "GMU_CX_FAL_INTF": ("A6XX", "GPU_GMU_CX_GMU_CX_FAL_INTF"),
    "GMU_CX_FALNEXT_INTF": ("A6XX", "GPU_GMU_CX_GMU_CX_FALNEXT_INTF"),
    "GMU_PWR_COL_CP_MSG": ("A6XX", "GPU_GMU_CX_GMU_PWR_COL_CP_MSG"),
    "GMU_PWR_COL_CP_RESP": ("A6XX", "GPU_GMU_CX_GMU_PWR_COL_CP_RESP"),
}
RSCC_NAMES = {"RSCC_RSC_STATUS0_DRV0": "GPU_RSCC_RSC_STATUS0_DRV0", **{n: n for n in (
    "RSCC_PDC_SEQ_START_ADDR", "RSCC_PDC_MATCH_VALUE_LO", "RSCC_PDC_MATCH_VALUE_HI", "RSCC_PDC_SLAVE_ID_DRV0",
    "RSCC_HIDDEN_TCS_CMD0_ADDR", "RSCC_HIDDEN_TCS_CMD0_DATA", "RSCC_OVERRIDE_START_ADDR", "RSCC_SEQ_BUSY_DRV0",
    "RSCC_SEQ_MEM_0_DRV0")}}
PDC_NAMES = {"PDC_GPU_ENABLE_PDC": "GPU_ENABLE_PDC", "PDC_GPU_SEQ_START_ADDR": "GPU_SEQ_START_ADDR"}


def generate(linux, dtb):
    linux = Path(linux)
    regs = load_registers(linux)
    windows = dt_windows(dtb)
    gmu_base, gpu_base = windows["gmu"][0], windows["kgsl_3d0_reg_memory"][0]
    mmio_offset = gmu_base - gpu_base
    if mmio_offset % 4 or mmio_offset <= 0:
        raise GenError("the GMU window does not lie above the GPU window")
    values = {}
    for name, (domain, xml_name) in GMU_NAMES.items():
        off = register(regs, domain, xml_name)[0] - mmio_offset // 4
        if off < 0 or off * 4 >= windows["gmu"][1]:
            raise GenError(f"{name}: dword {off:#x} outside the gmu window")
        values[name] = off
    for name, xml_name in RSCC_NAMES.items():
        values[name] = register(regs, "A6XX", xml_name)[0]
    for name, xml_name in PDC_NAMES.items():
        values[name] = register(regs, "A6XX_PDC", xml_name)[0]
    ao = sum(bit(regs, "A6XX", "GMU_AO_HOST_INTERRUPT_STATUS", f) for f in ("WDOG_BITE", "FENCE_ERR", "HOST_AHB_BUS_ERROR"))
    gmu_h = (linux / SOURCES["a6xx_gmu.c"]).read_text()      # the IRQ masks are defined in a6xx_gmu.c
    need(gmu_h, "#define A6XX_GMU_IRQ_MASK \\\n\t(A6XX_GMU_AO_HOST_INTERRUPT_STATUS_WDOG_BITE | \\\n"
                "\t A6XX_GMU_AO_HOST_INTERRUPT_STATUS_HOST_AHB_BUS_ERROR | \\\n"
                "\t A6XX_GMU_AO_HOST_INTERRUPT_STATUS_FENCE_ERR)", "A6XX_GMU_IRQ_MASK (a6xx_gmu.c)")
    cm3 = bit(regs, "A6XX", "GMU_GMU2HOST_INTR_INFO", "CM3_FAULT")
    need(gmu_h, "#define A6XX_HFI_IRQ_MASK \\\n\t(A6XX_GMU_GMU2HOST_INTR_INFO_CM3_FAULT)", "A6XX_HFI_IRQ_MASK (a6xx_gmu.c)")
    setup = rpmh_sequence(linux, regs)
    for window, dword, value in setup:
        if dword * 4 + 4 > windows[WINDOWS[window]][1] or not 0 <= value <= 0xffffffff:
            raise GenError(f"setup write {window}:{dword:#x} outside its window")
    chip = catalog_chip(linux)
    return {"windows": {w: windows[w] for w in WINDOWS}, "mmio_offset": mmio_offset, "registers": values,
            "ao_fatal": ao, "cm3_fatal": cm3, "rsc_setup": setup, **chip,
            "sources": {n: sha(linux / p) for n, p in SOURCES.items()}}


def header(g):
    lines = ["/* Generated by scripts/gen_pipa_gmu.py from the pipa DTB and pinned Linux sources. Do not commit. */",
             "/* SPDX-License-Identifier: BSD-2-Clause-Patent */", "#ifndef PIPA_SHENG_GMU_SOURCE_H",
             "#define PIPA_SHENG_GMU_SOURCE_H", "#include <stdint.h>", "#include <stddef.h>",
             "/* GMU dword offsets relative to the GMU window; RSCC and PDC ones relative to theirs. */"]
    lines += [f"#define REG_{n} UINT32_C({v:#x})" for n, v in g["registers"].items()]
    w = g["windows"]
    lines += [f"#define SHENG_GMU_CHIP_ID UINT32_C({g['chip_id']:#010x})",
              f"#define SHENG_GMU_FIRMWARE_NAME \"{g['gmu_firmware']}\"",
              f"#define SHENG_GMU_CORE_GPU_DELTA {g['mmio_offset']:#x}u",
              f"#define SHENG_GMU_AO_FATAL_MASK {g['ao_fatal']:#x}u", f"#define SHENG_GMU_CM3_FATAL_MASK {g['cm3_fatal']:#x}u",
              f"static const uint64_t sheng_gmu_window_physical[{len(w)}]={{{','.join(hex(w[n][0]) for n in WINDOWS)}}};",
              f"static const size_t sheng_gmu_window_bytes[{len(w)}]={{{','.join(hex(w[n][1]) for n in WINDOWS)}}};",
              "typedef struct {unsigned window;size_t byte_offset;uint32_t value;} ShengGmuSetupWrite;",
              f"#define SHENG_GMU_RSC_SETUP_COUNT {len(g['rsc_setup'])}u",
              f"static const ShengGmuSetupWrite sheng_gmu_rsc_setup[{len(g['rsc_setup'])}]={{"]
    lines += [f"    {{{win},{4 * dw:#x},{val:#x}}}," for win, dw, val in g["rsc_setup"]]
    lines += ["};", "#endif", ""]
    return "\n".join(lines)


# Check against A650Gmu.c -------------------------------------------------------------------------------------------

def a650gmu_constants(path=PKG / "A650Gmu.c", hdr=PKG / "A650Gmu.h"):
    text = Path(path).read_text()
    enums = {}
    for block in re.findall(r"enum\s*\{([^}]*)\}", text):
        for name, value in re.findall(r"\b([A-Z][A-Z0-9_]+)\s*=\s*(0x[0-9a-fA-F]+|\d+)", re.sub(r"/\*.*?\*/", "", block, flags=re.S)):
            enums[name] = int(value, 0)
    defines = {n: int(v.rstrip("uU"), 0) for n, v in re.findall(r"#define\s+(\w+)\s+(0x[0-9a-fA-F]+u?|\d+u?)\b",
                                                               text + Path(hdr).read_text())}
    m = re.search(r"rsc\[\]\s*=\s*\{(.*?)\n\s*\};", text, re.S)
    if not m:
        raise GenError("A650Gmu.c: no rsc[] table")
    window = {"A650GmuCore": CORE, "A650GmuRscc": RSCC, "A650GmuPdc": PDC}
    rsc = []
    for win, reg, val in re.findall(r"\{(A650Gmu\w+),\s*([A-Z_0-9]+(?:\s*\+\s*\d+)?),\s*([^}]+)\}",
                                    re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)):
        base, _, add = reg.partition("+")
        v = val.strip().rstrip("uU")
        v = 1 << int(re.match(r"1u?\s*<<\s*(\d+)", val.strip()).group(1)) if "<<" in val else int(v, 0)
        rsc.append((window[win], enums[base.strip()] + int(add or 0), v))
    return enums, defines, rsc


def check(g):
    enums, defines, rsc = a650gmu_constants()
    rows = []
    for name, value in g["registers"].items():
        rows.append((name, enums.get(name), value))
    rows += [("AO_FATAL", defines.get("AO_FATAL"), g["ao_fatal"]), ("CM3_FATAL", defines.get("CM3_FATAL"), g["cm3_fatal"]),
             ("A650_GMU_CHIP_ID", defines.get("A650_GMU_CHIP_ID"), g["chip_id"]),
             ("A650_GMU_CORE_BYTES", defines.get("A650_GMU_CORE_BYTES"), g["windows"]["gmu"][1]),
             ("A650_GMU_RSCC_BYTES", defines.get("A650_GMU_RSCC_BYTES"), g["windows"]["rscc"][1]),
             ("A650_GMU_PDC_BYTES", defines.get("A650_GMU_PDC_BYTES"), g["windows"]["gmu_pdc"][1]),
             ("rsc[] (window, dword, value)", rsc, g["rsc_setup"])]
    return [{"fact": n, "A650Gmu.c": a, "generated": b, "result": "match" if a == b else "MISMATCH"} for n, a, b in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--linux", type=Path, required=True)
    ap.add_argument("--dtb", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "build/pipa-gmu")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    g = generate(args.linux, args.dtb)
    args.out.mkdir(parents=True, exist_ok=True)
    text = header(g)
    (args.out / "ShengGmuSource.h").write_text(text)
    report = {**g, "generated_header_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_analysis_only": True,
              "hardware_registers_observed": False}
    rows = check(g)
    report["check"] = rows
    (args.out / "source-report.json").write_text(json.dumps(report, indent=2, default=lambda v: hex(v) if isinstance(v, int) else str(v)) + "\n")
    bad = [r for r in rows if r["result"] != "match"]
    for r in rows:
        print(f"{r['result']:8} {r['fact']:32} A650Gmu.c={r['A650Gmu.c']!s:.60}  generated={r['generated']!s:.60}")
    print(json.dumps({"match": len(rows) - len(bad), "MISMATCH": len(bad), "header": str(args.out / "ShengGmuSource.h")}))
    if args.check and bad:
        sys.exit("A650Gmu.c differs from the generated GMU inputs")


if __name__ == "__main__":
    main()
