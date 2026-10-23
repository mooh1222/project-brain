"""Release content identity: synthetic packages, never the developer installation."""

import json
import tempfile
import unittest
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import asdict

from project_brain.engine_identity import (
    read_release_identity,
    write_release_identity,
)


class ReleaseIdentityTest(unittest.TestCase):
    def test_memory_code_is_checked_when_cache_is_deleted_or_replaced(self):
        import project_brain

        for cache in ("deleted", "replaced"):
            with self.subTest(cache=cache), tempfile.TemporaryDirectory() as tmp:
                site = Path(tmp)
                package = site / "project_brain"
                package.mkdir()
                original = Path(project_brain.__file__).parent
                for name in ("__init__.py", "engine_identity.py"):
                    shutil.copyfile(original / name, package / name)
                (package / "loaded.py").write_text("def value(): return 'NEW'\n")
                metadata = site / "project_brain-0.2.0.dist-info"
                metadata.mkdir()
                (metadata / "METADATA").write_text("Name: project-brain\nVersion: 0.2.0\n")
                write_release_identity(package, "a" * 40, "0.2.0")
                source = (
                    "import sys,pathlib,py_compile\n"
                    f"sys.path.insert(0,{str(site)!r})\n"
                    "import project_brain.loaded as loaded\n"
                    "exec(compile(\"def value(): return 'OLD'\\n\", loaded.__file__, 'exec'), loaded.__dict__)\n"
                    "print(loaded.value(), flush=True)\n"
                    + ("pathlib.Path(loaded.__cached__).unlink(missing_ok=True)\n" if cache == "deleted"
                       else "py_compile.compile(loaded.__file__, doraise=True)\n")
                    + "from project_brain.engine_identity import capture_release_engine\n"
                    "capture_release_engine()\n"
                )
                result = subprocess.run([sys.executable, "-I", "-c", source],
                                        text=True, capture_output=True)
                self.assertEqual(result.stdout.strip(), "OLD")
                self.assertNotEqual(result.returncode, 0, "loaded OLD code accepted with NEW source")
                self.assertIn("executed code/source mismatch", result.stderr)

    def test_release_binding_preserves_content_identity_without_upgrading_legacy(self):
        from project_brain.transaction_receipt import (
            BatchBinding, ReleaseBatchBinding, batch_binding_dict, normalize_batch_binding,
        )
        old = BatchBinding(**dict(
            batch_manifest_sha256="a" * 64, item_key="one",
            item_input_fingerprint="b" * 64, verify_json_sha256="c" * 64,
            domain_spec_py_sha256="d" * 64, coverage_sha256="e" * 64,
            repo_root="/consumer", brain_root="/consumer/brain",
            brain_root_device=1, brain_root_inode=2, expected_repo_id="demo",
            expected_revision_ref="HEAD", target_revision_sha="a" * 40,
            engine_root="/engine", engine_sha="b" * 40,
        ))
        identity = dict(scheme="release-v1", version="0.2.0",
                        source_commit="b" * 40, content_sha256="f" * 64)
        release = ReleaseBatchBinding(**asdict(old), engine_identity=identity,
                                      engine_root_device=1, engine_root_inode=3)
        self.assertEqual(normalize_batch_binding(batch_binding_dict(release)), release)
        self.assertNotIn("engine_identity", batch_binding_dict(old))
        identity["source_commit"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "engine_sha"):
            normalize_batch_binding(release)

    def test_content_and_modes_are_bound_even_when_version_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package / "__init__.py").write_text("")
            code = package / "cli.py"
            code.write_text("VALUE = 1\n")
            expected = write_release_identity(package, "a" * 40, "0.2.0")
            self.assertEqual(read_release_identity(package), expected)
            code.write_text("VALUE = 2\n")
            with self.assertRaisesRegex(ValueError, "content mismatch"):
                read_release_identity(package)
            code.write_text("VALUE = 1\n")
            code.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "mode mismatch"):
                read_release_identity(package)

    def test_extra_code_and_rewritten_identity_digest_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package / "__init__.py").write_text("")
            write_release_identity(package, "a" * 40, "0.2.0")
            extra = package / "extra.py"
            extra.write_text("VALUE = 2\n")
            with self.assertRaisesRegex(ValueError, "file set"):
                read_release_identity(package)
            extra.unlink()
            manifest = package / "_release_identity.json"
            payload = json.loads(manifest.read_text())
            payload["source_commit"] = "b" * 40
            manifest.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                read_release_identity(package)
