"""Tests of tools/isa/ipsw.py: ZIP64 central directory, member extraction, IM4P, URL policy.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import io
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.isa import ipsw


def der(tag, body):
    n = len(body)
    if n < 0x80:
        return bytes([tag, n]) + body
    nb = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(nb)]) + nb + body


class Zip(unittest.TestCase):
    def test_zip64_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.ipsw"
            big = bytes(range(256)) * 4000
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("stored.bin", b"hello", compress_type=zipfile.ZIP_STORED)
                with z.open("deflated.bin", "w", force_zip64=True) as f:
                    f.write(big)
            src = ipsw.FileSource(path)
            self.addCleanup(src.f.close)
            cd = ipsw.central_directory(src)
            self.assertEqual(set(cd), {"stored.bin", "deflated.bin"})
            self.assertEqual(ipsw.read_member(src, cd["stored.bin"]), b"hello")
            self.assertEqual(ipsw.read_member(src, cd["deflated.bin"]), big)
            parts = []
            ipsw.read_member(src, cd["deflated.bin"], parts.append, chunk=1000)
            self.assertEqual(b"".join(parts), big)
            lho, csize, method, usize, crc = cd["stored.bin"]
            with self.assertRaises(IOError):
                ipsw.read_member(src, (lho, csize, method, usize, crc ^ 1))


class Im4p(unittest.TestCase):
    def test_payload_and_compression(self):
        payload = b"bvx2" + b"\x00" * 300
        comp = der(0x30, der(0x02, b"\x01") + der(0x02, (123456).to_bytes(3, "big")))
        blob = der(0x30, der(0x16, b"IM4P") + der(0x16, b"krnl") + der(0x16, b"KernelCacheBuilder")
                   + der(0x04, payload) + comp)
        typ, got, c = ipsw.im4p_payload(blob)
        self.assertEqual((typ, got, c), ("krnl", payload, (1, 123456)))

    def test_not_im4p(self):
        with self.assertRaises(ValueError):
            ipsw.im4p_payload(der(0x30, der(0x16, b"IMG4")))


class Manifest(unittest.TestCase):
    def test_customer_erase_identity(self):
        m = {"ProductBuildVersion": "25F71", "ProductVersion": "26.5",
             "SupportedProductTypes": ["Macmini9,1", "Mac16,1"],
             "BuildIdentities": [
                 {"ApProductType": "Mac16,1", "Info": {"DeviceClass": "j604ap", "RestoreBehavior": "Erase",
                                                      "Variant": "macOS Customer"},
                  "Manifest": {"KernelCache": {"Info": {"Path": "kernelcache.release.mac16"}}}},
                 {"ApProductType": "Macmini9,1", "Info": {"DeviceClass": "j274ap", "RestoreBehavior": "Update",
                                                         "Variant": "macOS Customer"},
                  "Manifest": {"KernelCache": {"Info": {"Path": "wrong"}}}},
                 {"ApProductType": "Macmini9,1", "Info": {"DeviceClass": "j274ap", "RestoreBehavior": "Erase",
                                                         "Variant": "macOS Customer"},
                  "Manifest": {"KernelCache": {"Info": {"Path": "kernelcache.release.mac13g"}}}}]}
        self.assertEqual(ipsw.kernelcache_for(plistlib.dumps(m), "J274AP"),
                         ("kernelcache.release.mac13g", "j274ap", "25F71", "26.5"))


class Http(unittest.TestCase):
    def test_only_apple_cdn(self):
        with self.assertRaises(ValueError):
            ipsw.HttpSource("https://example.com/x.ipsw")

    def test_range_header(self):
        seen = []

        class Resp(io.BytesIO):
            headers = {"Content-Length": "10"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req):
            seen.append((req.get_method(), req.headers.get("Range")))
            return Resp(b"abc")

        src = ipsw.HttpSource("https://updates.cdn-apple.com/x.ipsw", opener=opener)
        self.assertEqual(src.read(5, 3), b"abc")
        self.assertEqual(src.size(), 10)
        self.assertEqual(seen, [("GET", "bytes=5-7"), ("HEAD", None)])


if __name__ == "__main__":
    unittest.main()
