"""BrainStore.load — 객체 디렉토리(_KIND_DIR)만 스캔한다.

2-레포 분리로 brain root 직속에 비객체 JSON(eval_scenarios.json 등)이 같이 살게
됐다 — 전체 rglob이면 그 파일을 객체로 읽다 KeyError로 죽는다. 객체는 항상
save_object가 _KIND_DIR 아래에 쓰므로 스캔도 같은 경계를 따른다.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.store import BrainStore

from tests.test_ingest import context


class LoadScanBoundaryTest(unittest.TestCase):
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
