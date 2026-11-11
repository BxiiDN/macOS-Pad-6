"""patches/unixnu (applied by scripts/pipa_unixnu.py to its UniXNU copy): the patches apply to the pinned submodule,
also when the copy sits inside another Git repository and twice in a row; the UFS SoC switch they add gives the
right define for each SoC and the kernel step exports the board's SoC; and the probe-compatible extraction that
`pipa_unixnu.py check --adt` runs on the PipaUfs source.

SPDX-License-Identifier: BSD-2-Clause-Patent
"""
import importlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipa_unixnu as pu  # noqa: E402

UNIXNU = ROOT / "third_party/UniXNU"
HAVE_UNIXNU = (UNIXNU / "scripts/unixnu/kernel.py").is_file()
HAVE_CC = bool(shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"))

PROBE = """
static int f(void) {
#if defined(NATIVE_UFS_SM6225)
  const char *compatible = "qcom,ufshc";
#elif defined(NATIVE_UFS_SM8250)
  const char *compatible = "qcom,sm8250-ufshc";
#else
  const char *compatible = "qcom,sm8550-ufshc";
#endif
  return compatible[0];
}
#if defined(NATIVE_UFS_SM8250)
#define GCC_BASE 0x100000
#endif
"""


class Series(unittest.TestCase):
    def test_series_names_files(self):
        patches = pu.unixnu_patches()
        self.assertTrue(patches)
        for p in patches:
            self.assertTrue(p.is_file(), p)
            self.assertIn("SPDX-License-Identifier", p.read_text())


@unittest.skipUnless(HAVE_UNIXNU, "needs the UniXNU submodule")
class Applied(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # The copy inside a Git repository of its own, as build/pipa-unixnu/UniXNU sits inside this repository.
        outer = Path(cls.tmp.name) / "outer"
        outer.mkdir()
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        cls.ux = outer / "UniXNU"
        shutil.copytree(UNIXNU / "scripts", cls.ux / "scripts")
        shutil.copy(UNIXNU / "components.toml", cls.ux / "components.toml")
        cls.first = pu.apply_unixnu_patches(cls.ux)
        cls.second = pu.apply_unixnu_patches(cls.ux)
        sys.path.insert(0, str(cls.ux / "scripts"))
        cls.ufs_soc = importlib.import_module("ufs_soc")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(cls.ux / "scripts"))
        sys.modules.pop("ufs_soc", None)
        for name in [m for m in sys.modules if m == "unixnu" or m.startswith("unixnu.")]:
            sys.modules.pop(name)
        cls.tmp.cleanup()

    def test_applies_once_then_present(self):
        self.assertEqual(set(self.first.values()), {"applied"})
        self.assertEqual(set(self.second.values()), {"present"})
        self.assertTrue((self.ux / "scripts/ufs_soc.py").is_file())

    def test_defines(self):
        d = self.ufs_soc.defines
        self.assertEqual(d("SM8250"), ["-DNATIVE_UFS_SM8250=1"])
        self.assertEqual(d("sm8250"), ["-DNATIVE_UFS_SM8250=1"])
        self.assertEqual(d("SM6225"), ["-DNATIVE_UFS_SM6225=1"])
        self.assertEqual(d("SM8550"), [])                  # sheng: unchanged
        self.assertEqual(d(""), [])
        self.assertEqual(d(None), [])
        with self.assertRaises(SystemExit):
            d("SM8650")                                    # no block in the driver: refuse, do not build SM8550
        with self.assertRaises(SystemExit):
            d("SM8250; rm -rf /")

    def test_recipes_use_it(self):
        for name in ("build-arm-driver.py", "build-sheng-source-storage.py"):
            text = (self.ux / "scripts" / name).read_text()
            self.assertIn("ufs_soc.defines(os.environ.get('UNIXNU_SOC'))", text, name)
            compile(text, name, "exec")

    def test_adreno650_catalog_entry(self):
        import tomllib
        entries = {e["id"]: e for e in tomllib.loads((self.ux / "components.toml").read_text())["component"]}
        a650 = entries["Adreno650"]
        self.assertEqual(a650["repository"], "https://github.com/xVanTuring/Adreno650.git")
        self.assertEqual(a650["revision"], "01db67e0620fe0e70ab8cbce533cbdb1369f5922")
        self.assertEqual(a650["build"], ["build-adreno650.py"])
        self.assertTrue((ROOT / "devices/pipa/scripts/build-adreno650.py").is_file())   # the device recipe it names
        self.assertNotIn("Sm8550Platform", a650["dependencies"])
        for dep in a650["dependencies"]:
            self.assertIn(dep, entries)
        # The same pin as feeds.toml's [[source]] Adreno650.
        feeds = {x["name"]: x for x in tomllib.loads((ROOT / "devices/pipa/feeds.toml").read_text())["source"]}
        self.assertEqual(feeds["Adreno650"]["commit"], a650["revision"])
        # The catalog's selection logic resolves it with its dependencies first.
        components = importlib.import_module("unixnu.components")
        ctx = types.SimpleNamespace(root=self.ux, board={"components": {"include": ["Adreno650"]}})
        order = [e["id"] for e in components.selected(ctx)]
        self.assertEqual(order[-1], "Adreno650")
        self.assertEqual(set(order[:-1]), {"AdrenoPM4", "AdrenoFirmware", "ArmSmmu4K"})

    def test_kernel_step_exports_soc(self):
        kernel = importlib.import_module("unixnu.kernel")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "profile.toml").write_text('[arch]\nname = "arm64e"\n')
            ctx = types.SimpleNamespace(schema_version=2, profile_roots={"arch": Path(d)},
                                        board={"board": {"soc": "SM8250"}, "os": {}, "root": {}, "ipsw": {"build": "25F71"}})
            env = kernel.version_env({}, ctx)
        self.assertEqual(env["UNIXNU_SOC"], "SM8250")
        self.assertEqual(env["UNIXNU_XNU_ARCH"], "arm64e")


@unittest.skipUnless(HAVE_CC, "needs a C preprocessor")
class ProbeCompatible(unittest.TestCase):
    def test_switch(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "NativeUfs.cpp"
            src.write_text(PROBE)
            self.assertEqual(pu.ufs_probe_compatible(src, ["-DNATIVE_UFS_SM8250=1"]), "qcom,sm8250-ufshc")
            self.assertEqual(pu.ufs_probe_compatible(src, []), "qcom,sm8550-ufshc")   # what format 2 built for pipa
            self.assertEqual(pu.ufs_probe_compatible(src, ["-DNATIVE_UFS_SM6225=1"]), "qcom,ufshc")
            src.write_text("int x;\n")
            with self.assertRaises(LookupError):
                pu.ufs_probe_compatible(src, [])

    def test_pinned_pipa_fork(self):
        """The PipaUfs feed as pipa_unixnu.py fetches it, when a previous prepare left it in build/."""
        feeds = sorted((ROOT / "build/pipa-unixnu/feeds").glob("ShengUfs-*/NativeUfs.cpp"))
        if not feeds:
            self.skipTest("no fetched PipaUfs (scripts/pipa_unixnu.py prepare)")
        self.assertEqual(pu.ufs_probe_compatible(feeds[-1], ["-DNATIVE_UFS_SM8250=1"]), "qcom,sm8250-ufshc")
        self.assertEqual(pu.ufs_probe_compatible(feeds[-1], []), "qcom,sm8550-ufshc")


if __name__ == "__main__":
    unittest.main()
