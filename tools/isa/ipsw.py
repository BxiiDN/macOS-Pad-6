#!/usr/bin/env python3
"""Read members of an official IPSW over HTTP range requests, without downloading it.

    python3 -m tools.isa.ipsw list URL
    python3 -m tools.isa.ipsw get URL MEMBER OUT
    python3 -m tools.isa.ipsw kernelcache URL --device-class j274ap OUT_DIR

Only https://updates.cdn-apple.com/ URLs are accepted, so every byte comes
from Apple's own server. ZIP64 is supported (macOS IPSWs are larger than
4 GiB). `kernelcache` reads BuildManifest.plist, picks the kernelcache of the
named board's (DeviceClass) customer erase identity, extracts it, strips the IM4P
wrapper and decompresses LZFSE with `compression_tool` (macOS) or `lzfse`.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path

ALLOWED = "https://updates.cdn-apple.com/"


class Source:
    def size(self):
        raise NotImplementedError

    def read(self, off, n):
        raise NotImplementedError


class FileSource(Source):
    def __init__(self, path):
        self.f = open(path, "rb")

    def size(self):
        self.f.seek(0, 2)
        return self.f.tell()

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


class HttpSource(Source):
    def __init__(self, url, opener=urllib.request.urlopen):
        if not url.startswith(ALLOWED):
            raise ValueError(f"only {ALLOWED} URLs are accepted")
        self.url = url
        self.opener = opener
        self._size = None

    def size(self):
        if self._size is None:
            req = urllib.request.Request(self.url, method="HEAD")
            with self.opener(req) as r:
                self._size = int(r.headers["Content-Length"])
        return self._size

    def read(self, off, n):
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={off}-{off + n - 1}"})
        with self.opener(req) as r:
            data = r.read()
        if len(data) != n:
            raise IOError(f"range {off}+{n}: got {len(data)} bytes")
        return data


def central_directory(src):
    """{name: (local header offset, compressed size, method, uncompressed size, crc32)}."""
    size = src.size()
    tail = src.read(max(0, size - 65558), min(size, 65558))
    k = tail.rfind(b"PK\x05\x06")
    if k < 0:
        raise ValueError("no end of central directory")
    (_d, _dcd, _n_here, n_total, cd_size, cd_off) = struct.unpack_from("<HHHHII", tail, k + 4)
    z = tail.rfind(b"PK\x06\x07", 0, k)
    if z >= 0:                                         # ZIP64 locator
        eocd64_off = struct.unpack_from("<Q", tail, z + 8)[0]
        rec = src.read(eocd64_off, 56)
        if rec[:4] != b"PK\x06\x06":
            raise ValueError("bad ZIP64 end of central directory")
        n_total, cd_size, cd_off = struct.unpack_from("<QQQ", rec, 32)
    cd = src.read(cd_off, cd_size)
    out, p = {}, 0
    for _ in range(n_total):
        if cd[p:p + 4] != b"PK\x01\x02":
            raise ValueError("bad central directory entry")
        (method, _t, _d, crc, csize, usize, nlen, xlen, clen, _dn, _ia, _ea,
         lho) = struct.unpack_from("<HHHIIIHHHHHII", cd, p + 10)
        name = cd[p + 46:p + 46 + nlen].decode("utf-8")
        extra = cd[p + 46 + nlen:p + 46 + nlen + xlen]
        q = 0
        while q + 4 <= len(extra):                     # ZIP64 extended information
            hid, hlen = struct.unpack_from("<HH", extra, q)
            if hid == 1:
                vals = extra[q + 4:q + 4 + hlen]
                v = 0
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack_from("<Q", vals, v)[0]
                    v += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack_from("<Q", vals, v)[0]
                    v += 8
                if lho == 0xFFFFFFFF:
                    lho = struct.unpack_from("<Q", vals, v)[0]
            q += 4 + hlen
        out[name] = (lho, csize, method, usize, crc)
        p += 46 + nlen + xlen + clen
    return out


def read_member(src, entry, sink=None, chunk=32 << 20):
    """Return the member's bytes, or stream them to sink(bytes) when given.
    The CRC-32 and size from the central directory are checked."""
    lho, csize, method, usize, crc = entry
    hdr = src.read(lho, 30)
    if hdr[:4] != b"PK\x03\x04":
        raise ValueError("bad local header")
    nlen, xlen = struct.unpack_from("<HH", hdr, 26)
    start = lho + 30 + nlen + xlen
    parts = [] if sink is None else None
    dec = zlib.decompressobj(-15) if method == 8 else None
    if method not in (0, 8):
        raise ValueError(f"compression method {method} not supported")
    got_crc, got_len = 0, 0
    for off in range(0, csize, chunk):
        data = src.read(start + off, min(chunk, csize - off))
        if dec:
            data = dec.decompress(data)
        got_crc = zlib.crc32(data, got_crc)
        got_len += len(data)
        (parts.append if sink is None else sink)(data)
    if dec:
        rest = dec.flush()
        got_crc = zlib.crc32(rest, got_crc)
        got_len += len(rest)
        (parts.append if sink is None else sink)(rest)
    if got_crc != crc or got_len != usize:
        raise IOError(f"member CRC/size mismatch: {got_crc:#x}/{got_len} != {crc:#x}/{usize}")
    return b"".join(parts) if sink is None else None


def _der(buf, p):
    tag = buf[p]
    n = buf[p + 1]
    p += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[p:p + k], "big")
        p += k
    return tag, p, n


def im4p_payload(buf):
    """(type, payload bytes, compression or None) of an IM4P."""
    tag, p, n = _der(buf, 0)
    if tag != 0x30:
        raise ValueError("IM4P: not a SEQUENCE")
    end = p + n
    items = []
    while p < end:
        tag, q, n = _der(buf, p)
        items.append((tag, buf[q:q + n]))
        p = q + n
    if items[0][1] != b"IM4P":
        raise ValueError("not an IM4P")
    typ = items[1][1].decode()
    payload = next(v for t, v in items if t == 0x04)
    comp = None
    for t, v in items[4:]:
        if t == 0x30:                                   # compression info {algorithm, size}
            _t, a, an = _der(v, 0)
            _t2, b, bn = _der(v, a + an)
            comp = (int.from_bytes(v[a:a + an], "big"), int.from_bytes(v[b:b + bn], "big"))
    return typ, payload, comp


def lzfse_decode(data, out_path):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.lzfse"
        src.write_bytes(data)
        if shutil.which("compression_tool"):
            subprocess.run(["compression_tool", "-decode", "-a", "lzfse", "-i", str(src), "-o",
                            str(out_path)], check=True)
        elif shutil.which("lzfse"):
            subprocess.run(["lzfse", "-decode", "-i", str(src), "-o", str(out_path)], check=True)
        else:
            raise RuntimeError("no LZFSE decoder (compression_tool or lzfse)")


def kernelcache_for(manifest, device_class):
    """(kernelcache path, device class, build, version) of a board's customer erase identity."""
    m = plistlib.loads(manifest)
    for ident in m["BuildIdentities"]:
        info = ident.get("Info", {})
        if info.get("DeviceClass", "").lower() == device_class.lower() and \
                info.get("RestoreBehavior") == "Erase" and "Customer" in info.get("Variant", ""):
            path = ident["Manifest"]["KernelCache"]["Info"]["Path"]
            return path, info.get("DeviceClass"), m.get("ProductBuildVersion"), m.get("ProductVersion")
    raise KeyError(f"no customer erase identity for {device_class}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list")
    a.add_argument("url")
    a = sub.add_parser("get")
    a.add_argument("url")
    a.add_argument("member")
    a.add_argument("out", type=Path)
    a = sub.add_parser("kernelcache")
    a.add_argument("url")
    a.add_argument("--device-class", required=True, help="e.g. j274ap (Mac mini M1)")
    a.add_argument("out_dir", type=Path)
    args = ap.parse_args(argv)
    src = HttpSource(args.url) if args.url.startswith("http") else FileSource(args.url)
    cd = central_directory(src)
    if args.cmd == "list":
        for name, (_o, csize, _m, usize, _crc) in sorted(cd.items()):
            print(f"{usize:>14} {csize:>14} {name}")
        return 0
    if args.cmd == "get":
        with open(args.out, "wb") as f:
            read_member(src, cd[args.member], f.write)
        return 0
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_member(src, cd["BuildManifest.plist"])
    (args.out_dir / "BuildManifest.plist").write_bytes(manifest)
    path, board, build, version = kernelcache_for(manifest, args.device_class)
    im4p = read_member(src, cd[path])
    typ, payload, comp = im4p_payload(im4p)
    out = args.out_dir / Path(path).name
    if payload[:4] == b"bvx2":
        lzfse_decode(payload, out)
    else:
        out.write_bytes(payload)
    info = {"ipsw": args.url, "device_class": board, "version": version,
            "build": build, "member": path, "im4p_type": typ, "im4p_sha256": hashlib.sha256(im4p).hexdigest(),
            "compression": comp, "kernelcache": out.name,
            "kernelcache_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    (args.out_dir / "kernelcache.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
