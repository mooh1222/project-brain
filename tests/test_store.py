"""BrainStore.load — 객체 디렉토리(_KIND_DIR)만 스캔한다.

2-레포 분리로 brain root 직속에 비객체 JSON(eval_scenarios.json 등)이 같이 살게
됐다 — 전체 rglob이면 그 파일을 객체로 읽다 KeyError로 죽는다. 객체는 항상
save_object가 _KIND_DIR 아래에 쓰므로 스캔도 같은 경계를 따른다.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.store import BrainStore, StoreLoadError

from tests.test_ingest import context


class LoadScanBoundaryTest(unittest.TestCase):
    def test_duplicate_payload_id_from_distinct_files_is_rejected_with_paths(self):
        for same_payload in (True, False):
            with self.subTest(same_payload=same_payload), TemporaryDirectory() as td:
                brain = Path(td) / "brain"
                first = context()
                second = dict(first)
                if not same_payload:
                    second["title"] = "different"
                first_path = brain / "objects" / "domain" / "first.json"
                second_path = brain / "objects" / "domain" / "second.json"
                first_path.parent.mkdir(parents=True)
                first_path.write_bytes(BrainStore.object_bytes(first))
                second_path.write_bytes(BrainStore.object_bytes(second))

                with self.assertRaises(StoreLoadError) as caught:
                    BrainStore.load(brain)

                self.assertEqual(
                    caught.exception.code,
                    "duplicate_existing_object_id",
                )
                self.assertEqual(
                    caught.exception.paths,
                    (first_path, second_path),
                )

    def test_corrupt_tracked_object_json_is_structured_error(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            path = brain / "objects" / "domain" / "broken.json"
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")

            with self.assertRaises(StoreLoadError) as caught:
                BrainStore.load(brain)

            self.assertEqual(caught.exception.code, "object_json_invalid")
            self.assertEqual(caught.exception.paths, (path,))

    def test_excessively_nested_tracked_json_is_structured_error(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            path = brain / "objects" / "domain" / "nested.json"
            path.parent.mkdir(parents=True)
            path.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")

            with self.assertRaises(StoreLoadError) as caught:
                BrainStore.load(brain)

            self.assertEqual(caught.exception.code, "object_payload_invalid")
            self.assertEqual(caught.exception.paths, (path,))

    def test_non_object_tracked_json_is_structured_error(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            path = brain / "objects" / "domain" / "array.json"
            path.parent.mkdir(parents=True)
            path.write_text("[]", encoding="utf-8")

            with self.assertRaises(StoreLoadError) as caught:
                BrainStore.load(brain)

            self.assertEqual(caught.exception.code, "object_payload_invalid")
            self.assertEqual(caught.exception.paths, (path,))

    def test_object_path_is_kind_routed_under_brain_root(self):
        brain = Path("/tmp/example-brain")
        obj = context()

        self.assertEqual(
            BrainStore.object_path(brain, obj),
            brain / "objects" / "domain" / "context.neutral.json",
        )

    def test_object_bytes_are_utf8_deterministic_with_one_trailing_newline(self):
        obj = context()

        encoded = BrainStore.object_bytes(obj)

        self.assertEqual(encoded, BrainStore.object_bytes(obj))
        self.assertEqual(encoded.decode("utf-8"), json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
        ) + "\n")
        self.assertFalse(encoded.endswith(b"\n\n"))

    def test_save_object_uses_canonical_object_bytes(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            obj = context()

            path = BrainStore.save_object(brain, obj)

            self.assertEqual(path.read_bytes(), BrainStore.object_bytes(obj))

    def test_load_retains_raw_source_receipt_from_tracked_scan(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            obj = context()
            path = BrainStore.object_path(brain, obj)
            path.parent.mkdir(parents=True)
            raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            path.write_bytes(raw)

            store = BrainStore.load(brain)

            self.assertEqual(
                store.source_sha256(obj["id"]),
                hashlib.sha256(raw).hexdigest(),
            )
            self.assertNotEqual(
                store.source_sha256(obj["id"]),
                hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest(),
            )

    def test_non_object_json_at_root_is_ignored(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            BrainStore.save_object(brain, context())
            # 골든셋·메타 파일이 brain root 직속에 있어도 객체 로드는 안 깨진다.
            (brain / "eval_scenarios.json").write_text(
                json.dumps({"scenarios": []}), encoding="utf-8")
            store = BrainStore.load(brain)
            self.assertTrue(store.has("context.neutral"))
            self.assertEqual(len(list(store.all())), 1)

    def test_non_object_json_under_raw_sources_is_ignored(self):
        with TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            BrainStore.save_object(brain, context())
            src = brain / "raw" / "sources" / "feature-x"
            src.mkdir(parents=True)
            (src / "design-data.json").write_text("{\"slides\": []}", encoding="utf-8")
            store = BrainStore.load(brain)
            self.assertEqual(len(list(store.all())), 1)


if __name__ == "__main__":
    unittest.main()
