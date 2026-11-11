"""AArch64 encodings that need a feature the SM8250 cores lack.

Cortex-A77 and Cortex-A55 implement ARMv8.2-A plus RCpc and DotProd (LLVM's
CPU definitions: +v8.2a +rcpc +dotprod +fullfp16 +ssbs on the A77 only).
Apple's arm64e code targets ARMv8.3-A and later. Each rule is (name, mask,
value, needs, fge): `needs` is the missing feature, `fge` says whether
kernel/fge emulates it. The masks are cross-checked against LLVM by
tests/isa/test_features.py.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""

RULES = [
    # FEAT_PAuth, non-hint forms: UNDEFINED on ARMv8.2, so they trap.
    ("pac-dp1", 0xFFFF0000, 0xDAC10000, "PAuth", True),
    ("pacga", 0xFFE0FC00, 0x9AC03000, "PAuth", True),
    ("pac-branch", 0xFE1FF800, 0xD61F0800, "PAuth", True),
    ("pac-eret", 0xFFFFFBFF, 0xD69F0BFF, "PAuth", False),
    ("pac-load", 0xFF200400, 0xF8200400, "PAuth", True),
    ("pac-keyreg", 0xFFDFF000, 0xD5182000, "PAuth", True),
    # FEAT_JSCVT, FEAT_FCMA (v8.3)
    ("jscvt", 0xFFFFFC00, 0x1E7E0000, "JSCVT", True),
    ("fcadd", 0xBF20EC00, 0x2E00E400, "FCMA", False),
    ("fcmla", 0xBF20E400, 0x2E00C400, "FCMA", False),
    ("fcmla-elem", 0xBF009400, 0x2F001000, "FCMA", False),
    # FEAT_FlagM (v8.4), FEAT_FlagM2 and FEAT_SB (v8.5)
    ("cfinv", 0xFFFFFFFF, 0xD500401F, "FlagM", True),
    ("rmif", 0xFFE07C10, 0xBA000400, "FlagM", True),
    ("setf", 0xFFFFBC1F, 0x3A00080D, "FlagM", True),
    ("axflag", 0xFFFFFFFF, 0xD500405F, "FlagM2", True),
    ("xaflag", 0xFFFFFFFF, 0xD500403F, "FlagM2", True),
    ("sb", 0xFFFFFFFF, 0xD50330FF, "SB", True),
    # FEAT_LRCPC2 (v8.4)
    ("rcpc2", 0x3F200C00, 0x19000000, "LRCPC2", True),
    # FEAT_DIT (v8.4) and SSBS (absent on the A55 only)
    ("msr-dit", 0xFFFFF0FF, 0xD503405F, "DIT", True),
    ("dit-reg", 0xFFDFFFE0, 0xD51B42A0, "DIT", True),
    ("msr-ssbs", 0xFFFFF0FF, 0xD503403F, "SSBS(A55)", True),
    # FEAT_SHA3 / FEAT_SHA512 (v8.2 optional, not on these cores)
    ("eor3-bcax", 0xFFC08000, 0xCE000000, "SHA3", False),
    ("sha512-rax1", 0xFFE0F000, 0xCE608000, "SHA512/SHA3", False),
    ("xar", 0xFFE00000, 0xCE800000, "SHA3", False),
    ("sha512su0", 0xFFFFFC00, 0xCEC08000, "SHA512", False),
    # FEAT_FRINTTS (v8.5)
    ("frint-scalar", 0xFFBE7C00, 0x1E284000, "FRINTTS", False),
    ("frint-vector", 0x9FBFEC00, 0x0E21E800, "FRINTTS", False),
]

# Hint-space instructions: NOPs on cores without the feature (counted, harmless).
HINT_PAC = {0xD503211F: "pacia1716", 0xD503215F: "pacib1716", 0xD503219F: "autia1716",
            0xD50321DF: "autib1716", 0xD503231F: "paciaz", 0xD503233F: "paciasp",
            0xD503235F: "pacibz", 0xD503237F: "pacibsp", 0xD503239F: "autiaz",
            0xD50323BF: "autiasp", 0xD50323DF: "autibz", 0xD50323FF: "autibsp",
            0xD50320FF: "xpaclri"}
HINT_BTI = {0xD503241F: "bti", 0xD503245F: "bti c", 0xD503249F: "bti j", 0xD50324DF: "bti jc"}


def _valid(name, w):
    """Reject the unallocated encodings that share a rule's fixed bits."""
    if name == "pac-dp1":
        op = (w >> 10) & 0x3F
        rn = (w >> 5) & 0x1F
        return op <= 7 or (op <= 17 and rn == 31)
    if name == "pac-branch":
        opc = (w >> 21) & 0xF
        rn, op4 = (w >> 5) & 0x1F, w & 0x1F
        if opc in (0, 1):
            return op4 == 31
        if opc == 2:
            return rn == 31 and op4 == 31
        return opc in (8, 9)
    if name == "pac-keyreg":
        crm, op2 = (w >> 8) & 0xF, (w >> 5) & 7
        return (crm in (1, 2) and op2 <= 3) or (crm == 3 and op2 <= 1)
    if name == "rcpc2":
        size, opc = w >> 30, (w >> 22) & 3
        return not ((size == 2 and opc == 3) or (size == 3 and opc >= 2))
    if name in ("fcadd", "fcmla"):
        size = (w >> 22) & 3
        q = (w >> 30) & 1
        return size != 0 and not (size == 3 and q == 0)
    if name == "frint-vector":
        return not ((w >> 22) & 1 and not (w >> 30) & 1)      # .1d is reserved
    if name == "fcmla-elem":
        size, q = (w >> 22) & 3, (w >> 30) & 1
        lbit, hbit = (w >> 21) & 1, (w >> 11) & 1
        if size == 2:
            return q == 1 and lbit == 0
        if size == 1:
            return not (hbit == 1 and q == 0)
        return False
    return True


def classify(w):
    """Return (rule name, needed feature, emulated by FGE) or None for words the cores run."""
    for name, mask, value, needs, fge in RULES:
        if (w & mask) == value and _valid(name, w):
            return name, needs, fge
    return None


def hint_name(w):
    return HINT_PAC.get(w) or HINT_BTI.get(w)
