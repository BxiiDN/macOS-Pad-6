"""ctypes front end of tools/isa/scan.c (built on first use with the host C compiler).

scan(buf, ranges, record=set()) -> (Counter of rule name -> count, {rule: [file offsets]})

buf is any object supporting the buffer protocol (bytes, bytearray, mmap).
ranges are macho.CodeRange; their exclusions (data in code) are skipped.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import ctypes
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from tools.isa import features

HERE = Path(__file__).resolve().parent
_LIB = None
CHUNK_WORDS = 1 << 24          # 64 MiB per call


def _build():
    out_dir = Path(os.environ.get("ISA_BUILD_DIR", HERE.parents[1] / "build" / "host"))
    out_dir.mkdir(parents=True, exist_ok=True)
    lib = out_dir / "libisascan.so"
    srcs = [HERE / "scan.c", HERE / "rules.h"]
    if not lib.exists() or lib.stat().st_mtime < max(s.stat().st_mtime for s in srcs):
        cc = os.environ.get("CC", "cc")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_lib = Path(tmp) / lib.name
            subprocess.run([cc, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
                            "-o", str(tmp_lib), str(HERE / "scan.c")], check=True)
            os.replace(tmp_lib, lib)
    return lib


def lib():
    global _LIB
    if _LIB is None:
        _LIB = ctypes.CDLL(str(_build()))
        _LIB.isa_classify.restype = ctypes.c_int
        _LIB.isa_classify.argtypes = [ctypes.c_uint32]
        _LIB.isa_nrules.restype = ctypes.c_int
        _LIB.isa_scan.restype = None
        _LIB.isa_scan.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64),
                                  ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t), ctypes.c_uint64]
        if _LIB.isa_nrules() != len(features.RULES):
            raise RuntimeError("scan.c rules out of date: run python3 -m tools.isa.gen_rules")
    return _LIB


NAMES = [r[0] for r in features.RULES]


def classify(word):
    r = lib().isa_classify(word)
    return NAMES[r] if r >= 0 else None


def _pieces(rng, size):
    """[start, end) file intervals of a code range minus its exclusions, 4-byte aligned."""
    start = rng.offset + (-rng.offset % 4)
    end = min(rng.offset + rng.size, size)
    cuts = []
    for o, n in sorted(rng.exclude):
        lo = o - (o % 4)
        hi = o + n + (-(o + n) % 4)
        cuts.append((lo, hi))
    pos = start
    for lo, hi in cuts:
        if lo > pos:
            yield pos, min(lo, end)
        pos = max(pos, hi)
    if pos < end:
        yield pos, end - ((end - pos) % 4)


def scan(buf, ranges, record=()):
    lb = lib()
    n = len(NAMES)
    counts = (ctypes.c_uint64 * n)()
    mask = 0
    for name in record:
        mask |= 1 << NAMES.index(name)
    view = memoryview(buf)
    if view.readonly:
        # ctypes needs a writable buffer to take an address; copy-free for mmap(ACCESS_COPY)/bytearray.
        raise TypeError("scan needs a writable buffer (bytearray or mmap with ACCESS_COPY/ACCESS_WRITE)")
    base = ctypes.addressof(ctypes.c_char.from_buffer(view))
    hits_by_rule = {name: [] for name in record}
    for rng in ranges:
        for lo, hi in _pieces(rng, len(view)):
            for clo in range(lo, hi, 4 * CHUNK_WORDS):
                chi = min(hi, clo + 4 * CHUNK_WORDS)
                nwords = (chi - clo) // 4
                if not nwords:
                    continue
                total = ctypes.c_size_t(0)
                cap = min(nwords, 1 << 20) if record else 0
                hits = (ctypes.c_uint64 * max(cap, 1))()
                snapshot = list(counts)
                lb.isa_scan(base + clo, nwords, counts, mask, hits, cap, ctypes.byref(total), 0)
                if total.value > cap:                 # more hits than room: rescan this chunk
                    for k in range(n):
                        counts[k] = snapshot[k]
                    cap = total.value
                    total = ctypes.c_size_t(0)
                    hits = (ctypes.c_uint64 * cap)()
                    lb.isa_scan(base + clo, nwords, counts, mask, hits, cap, ctypes.byref(total), 0)
                for k in range(min(total.value, cap)):
                    off = clo + 4 * hits[k]
                    w = int.from_bytes(view[off:off + 4], "little")
                    hits_by_rule[NAMES[lb.isa_classify(w)]].append(off)
    return Counter({NAMES[k]: counts[k] for k in range(n) if counts[k]}), hits_by_rule
