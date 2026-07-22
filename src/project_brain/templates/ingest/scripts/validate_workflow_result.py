#!/usr/bin/env python3
"""동적 workflow 결과가 적재 가능한 완료 상태인지 판정한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_result(payload: dict) -> list[str]:
    """빈 리스트면 완료, 아니면 적재를 막을 오류 목록."""
    if not isinstance(payload, dict):
        return ["결과 JSON은 객체여야 합니다"]

    errors: list[str] = []
    expected = payload.get("expected")
    items = payload.get("items")
    failures = payload.get("failures")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        errors.append("expected는 0 이상의 정수여야 합니다")
    if not isinstance(items, list):
        errors.append("items는 배열이어야 합니다")
        items = []
    if not isinstance(failures, list):
        errors.append("failures는 배열이어야 합니다")
        failures = [object()]

    if isinstance(expected, int) and not isinstance(expected, bool) and len(items) != expected:
        errors.append(f"items 개수({len(items)})가 expected({expected})와 다릅니다")
    if failures:
        errors.append("failures가 비어 있지 않습니다")

    keys: list[Any] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{index}]는 객체여야 합니다")
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            errors.append(f"items[{index}].key가 없습니다")
        else:
            keys.append(key)
        if item.get("extract_status") != "ok":
            errors.append(f"items[{index}].extract_status가 ok가 아닙니다")
        if item.get("verify_status") != "ok":
            errors.append(f"items[{index}].verify_status가 ok가 아닙니다")
        if item.get("verdict") not in {"pass", "fixed"}:
            errors.append(f"items[{index}].verdict가 pass 또는 fixed가 아닙니다")
    if len(keys) != len(set(keys)):
        errors.append("items key가 중복됩니다")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="workflow 결과의 적재 가능 완료 상태를 검사합니다")
    parser.add_argument("result_json", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.result_json.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 1

    errors = validate_result(payload)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "completed": len(payload["items"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
