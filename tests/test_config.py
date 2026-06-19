"""config(.project-brain.json) 해석 테스트.

엔진이 글로벌 도구로 분리되면서 기본 경로의 기준이 '엔진 파일 위치'에서
'데이터를 가진 프로젝트'로 바뀌었다 — cwd 상향 탐색으로 config를 찾고,
경로 필드는 config 파일 위치 기준으로 절대화한다. 명시 인자 > config > 에러.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.config import (
    CONFIG_FILENAME,
    ConfigError,
    find_config,
    load_config,
    resolve_brain_root,
    resolve_db_path,
    resolve_scenarios_path,
)


def write_config(root: Path, payload: dict) -> Path:
    path = root / CONFIG_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class FindConfigTest(unittest.TestCase):
    def test_found_in_start_dir(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            cfg = write_config(root, {})
            self.assertEqual(find_config(start=root), cfg)

    def test_found_walking_up_from_child(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            cfg = write_config(root, {})
            child = root / "a" / "b"
            child.mkdir(parents=True)
            self.assertEqual(find_config(start=child), cfg)

    def test_missing_returns_none(self):
        with TemporaryDirectory() as td:
            self.assertIsNone(find_config(start=Path(td)))


class LoadConfigTest(unittest.TestCase):
    def test_minimal_config_derives_defaults_from_brain_root(self):
        # 빈 config여도 brain_root 기본 "brain"에서 db·scenarios가 파생된다.
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            write_config(root, {})
            cfg = load_config(start=root)
            self.assertEqual(cfg["brain_root"], root / "brain")
            self.assertEqual(cfg["db"], root / "brain" / ".brain-local" / "index.db")
            self.assertEqual(cfg["scenarios"], root / "brain" / "eval_scenarios.json")

    def test_explicit_relative_paths_resolved_against_config_dir(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            write_config(root, {
                "brain_root": "data/brain",
                "db": "data/index.db",
                "scenarios": "data/golden.json",
                "project": "demo",
            })
            cfg = load_config(start=root)
            self.assertEqual(cfg["brain_root"], root / "data" / "brain")
            self.assertEqual(cfg["db"], root / "data" / "index.db")
            self.assertEqual(cfg["scenarios"], root / "data" / "golden.json")
            self.assertEqual(cfg["project"], "demo")

    def test_db_default_follows_explicit_brain_root(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            write_config(root, {"brain_root": "knowledge"})
            cfg = load_config(start=root)
            self.assertEqual(cfg["db"], root / "knowledge" / ".brain-local" / "index.db")
            self.assertEqual(cfg["scenarios"], root / "knowledge" / "eval_scenarios.json")

    def test_missing_config_returns_none(self):
        with TemporaryDirectory() as td:
            self.assertIsNone(load_config(start=Path(td)))


class ResolveTest(unittest.TestCase):
    def test_explicit_wins_over_config(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            write_config(root, {"brain_root": "from-config"})
            self.assertEqual(
                resolve_brain_root("/explicit/brain", start=root),
                Path("/explicit/brain"),
            )
            self.assertEqual(
                resolve_db_path("/explicit/index.db", start=root),
                Path("/explicit/index.db"),
            )
            self.assertEqual(
                resolve_scenarios_path("/explicit/golden.json", start=root),
                Path("/explicit/golden.json"),
            )

    def test_falls_back_to_config(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            write_config(root, {})
            self.assertEqual(resolve_brain_root(None, start=root), root / "brain")
            self.assertEqual(
                resolve_db_path(None, start=root),
                root / "brain" / ".brain-local" / "index.db",
            )
            self.assertEqual(
                resolve_scenarios_path(None, start=root),
                root / "brain" / "eval_scenarios.json",
            )

    def test_no_explicit_no_config_raises_with_guidance(self):
        with TemporaryDirectory() as td:
            for fn in (resolve_brain_root, resolve_db_path, resolve_scenarios_path):
                with self.assertRaises(ConfigError) as ctx:
                    fn(None, start=Path(td))
                self.assertIn(CONFIG_FILENAME, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
