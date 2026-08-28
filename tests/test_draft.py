import hashlib
import json
import stat
from unittest import mock

import pytest

from project_brain.draft import DraftError, create, lint, list_drafts, show, update


UPDATED = "2026-08-28T18:30:00+09:00"


def test_create_and_show_round_trip_v1_draft(tmp_path):
    expected = """<!-- project-brain-draft:v1 -->
# 샐리 카누 어휘 감사

Topic ID: sally-canoe-glossary-audit
Updated: 2026-08-28T18:30:00+09:00

## 범위

샐리 카누의 기획 용어와 서버 API 의미를 대조한다.

## 출처

- manifest.sally-canoe.spec-v8
- manifest.sally-canoe.wiki-event-api

## 확인된 이해

## 어휘 관찰

## 가설과 충돌

## 열린 질문
"""

    created = create(
        tmp_path,
        topic_id="sally-canoe-glossary-audit",
        title="샐리 카누 어휘 감사",
        scope="샐리 카누의 기획 용어와 서버 API 의미를 대조한다.",
        sources=(
            "manifest.sally-canoe.spec-v8",
            "manifest.sally-canoe.wiki-event-api",
        ),
        updated_at=UPDATED,
    )

    assert created == show(tmp_path, "sally-canoe-glossary-audit")
    assert created == {
        "topic_id": "sally-canoe-glossary-audit",
        "title": "샐리 카누 어휘 감사",
        "scope": "샐리 카누의 기획 용어와 서버 API 의미를 대조한다.",
        "updated": UPDATED,
        "path": "drafts/sally-canoe-glossary-audit.md",
        "sha256": hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "content": expected,
    }


@pytest.mark.parametrize(
    "topic_id",
    ("../outside", "Upper-Case", "한글-주제", "two--dashes", "-leading", ""),
)
def test_create_rejects_non_ascii_kebab_topic_without_writing(tmp_path, topic_id):
    with pytest.raises(DraftError) as exc:
        create(
            tmp_path,
            topic_id=topic_id,
            title="잘못된 주제",
            scope="범위",
            updated_at=UPDATED,
        )

    assert exc.value.code == "draft_topic_id_invalid"
    assert list(tmp_path.rglob("*.md")) == []


def test_create_never_overwrites_an_existing_draft(tmp_path):
    first = create(
        tmp_path,
        topic_id="existing-topic",
        title="기존 초안",
        scope="기존 범위",
        updated_at=UPDATED,
    )

    with pytest.raises(DraftError) as exc:
        create(
            tmp_path,
            topic_id="existing-topic",
            title="덮어쓸 초안",
            scope="새 범위",
            updated_at="2026-08-28T19:00:00+09:00",
        )

    assert exc.value.code == "draft_exists"
    assert show(tmp_path, "existing-topic") == first


def test_list_returns_only_selection_metadata_sorted_by_topic_id(tmp_path):
    create(
        tmp_path,
        topic_id="zulu-topic",
        title="두 번째 초안",
        scope="두 번째 범위",
        updated_at="2026-08-28T19:00:00+09:00",
    )
    create(
        tmp_path,
        topic_id="alpha-topic",
        title="첫 번째 초안",
        scope="첫 번째 범위",
        updated_at=UPDATED,
    )

    assert list_drafts(tmp_path) == [
        {
            "topic_id": "alpha-topic",
            "title": "첫 번째 초안",
            "scope": "첫 번째 범위",
            "updated": UPDATED,
        },
        {
            "topic_id": "zulu-topic",
            "title": "두 번째 초안",
            "scope": "두 번째 범위",
            "updated": "2026-08-28T19:00:00+09:00",
        },
    ]


def test_lint_accepts_engine_generated_v1_draft(tmp_path):
    create(
        tmp_path,
        topic_id="valid-topic",
        title="유효한 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )

    assert lint(tmp_path) == []
    assert lint(tmp_path, topic_id="valid-topic") == []


def test_lint_reports_missing_v1_marker_as_a_structured_problem(tmp_path):
    created = create(
        tmp_path,
        topic_id="edited-topic",
        title="수정된 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    path.write_text(
        created["content"].replace("<!-- project-brain-draft:v1 -->\n", ""),
        encoding="utf-8",
    )

    problems = lint(tmp_path, topic_id="edited-topic")

    assert [problem["code"] for problem in problems] == ["draft_marker_invalid"]
    assert problems[0]["path"] == "drafts/edited-topic.md"


def test_lint_reports_missing_h1_title(tmp_path):
    created = create(
        tmp_path,
        topic_id="edited-topic",
        title="수정된 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    path.write_text(
        created["content"].replace("# 수정된 초안\n", "수정된 초안\n"),
        encoding="utf-8",
    )

    assert [problem["code"] for problem in lint(tmp_path)] == [
        "draft_title_invalid"
    ]


def test_lint_reports_topic_id_that_does_not_match_the_filename(tmp_path):
    created = create(
        tmp_path,
        topic_id="edited-topic",
        title="수정된 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    path.write_text(
        created["content"].replace(
            "Topic ID: edited-topic",
            "Topic ID: another-topic",
        ),
        encoding="utf-8",
    )

    assert [problem["code"] for problem in lint(tmp_path)] == [
        "draft_topic_id_mismatch"
    ]


def test_lint_reports_updated_timestamp_without_timezone(tmp_path):
    created = create(
        tmp_path,
        topic_id="edited-topic",
        title="수정된 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    path.write_text(
        created["content"].replace(UPDATED, "2026-08-28T18:30:00"),
        encoding="utf-8",
    )

    assert [problem["code"] for problem in lint(tmp_path)] == [
        "draft_updated_invalid"
    ]


def test_lint_reports_required_h2_sections_out_of_order(tmp_path):
    created = create(
        tmp_path,
        topic_id="edited-topic",
        title="수정된 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    edited = created["content"].replace("## 범위", "## 임시")
    edited = edited.replace("## 출처", "## 범위").replace("## 임시", "## 출처")
    path.write_text(edited, encoding="utf-8")

    assert [problem["code"] for problem in lint(tmp_path)] == [
        "draft_sections_invalid"
    ]


def test_lint_rejects_a_draft_file_symlink_without_reading_its_target(tmp_path):
    outside_root = tmp_path / "outside-brain"
    outside = create(
        outside_root,
        topic_id="linked-topic",
        title="바깥 초안",
        scope="drafts 밖의 파일",
        updated_at=UPDATED,
    )
    drafts_root = tmp_path / "brain" / "drafts"
    drafts_root.mkdir(parents=True)
    (drafts_root / "linked-topic.md").symlink_to(outside_root / outside["path"])

    problems = lint(tmp_path / "brain")

    assert [problem["code"] for problem in problems] == ["draft_path_invalid"]
    assert problems[0]["path"] == "drafts/linked-topic.md"


def test_lint_rejects_a_symlinked_drafts_root(tmp_path):
    outside_root = tmp_path / "outside-brain"
    create(
        outside_root,
        topic_id="outside-topic",
        title="바깥 초안",
        scope="바깥 범위",
        updated_at=UPDATED,
    )
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    (brain_root / "drafts").symlink_to(outside_root / "drafts", target_is_directory=True)

    assert lint(brain_root) == [{
        "path": "drafts",
        "code": "draft_path_invalid",
        "detail": "drafts 루트는 symlink가 아닌 실제 디렉터리여야 합니다",
    }]


def test_lint_reports_non_utf8_regular_file_without_raising(tmp_path):
    drafts_root = tmp_path / "drafts"
    drafts_root.mkdir()
    (drafts_root / "invalid-encoding.md").write_bytes(b"\xff\xfe")

    problems = lint(tmp_path)

    assert [problem["code"] for problem in problems] == ["draft_utf8_invalid"]


def test_lint_rejects_markdown_outside_the_topic_filename_grammar(tmp_path):
    valid = create(
        tmp_path,
        topic_id="valid-topic",
        title="유효한 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    valid_path = tmp_path / valid["path"]
    valid_path.rename(valid_path.with_name("Not-Kebab.md"))

    problems = lint(tmp_path)

    assert [problem["code"] for problem in problems] == ["draft_path_invalid"]


def test_show_and_list_never_follow_a_draft_symlink(tmp_path):
    outside_root = tmp_path / "outside-brain"
    outside = create(
        outside_root,
        topic_id="linked-topic",
        title="바깥 초안",
        scope="drafts 밖의 파일",
        updated_at=UPDATED,
    )
    brain_root = tmp_path / "brain"
    (brain_root / "drafts").mkdir(parents=True)
    (brain_root / "drafts" / "linked-topic.md").symlink_to(
        outside_root / outside["path"]
    )

    for read in (lambda: show(brain_root, "linked-topic"), lambda: list_drafts(brain_root)):
        with pytest.raises(DraftError) as exc:
            read()
        assert exc.value.code == "draft_path_invalid"


def test_create_rejects_invalid_updated_before_any_write(tmp_path):
    with pytest.raises(DraftError) as exc:
        create(
            tmp_path,
            topic_id="invalid-updated",
            title="잘못된 갱신 시각",
            scope="검사할 범위",
            updated_at="2026-08-28T18:30:00",
        )

    assert exc.value.code == "draft_updated_invalid"
    assert list(tmp_path.rglob("*.md")) == []


def test_create_rejects_an_empty_or_multiline_title_before_any_write(tmp_path):
    for title in ("", "첫 줄\n둘째 줄"):
        with pytest.raises(DraftError) as exc:
            create(
                tmp_path,
                topic_id="invalid-title",
                title=title,
                scope="검사할 범위",
                updated_at=UPDATED,
            )
        assert exc.value.code == "draft_title_invalid"

    assert list(tmp_path.rglob("*.md")) == []


def test_create_uses_the_engine_clock_when_updated_is_omitted(tmp_path):
    with mock.patch("project_brain.draft.now_kst", return_value=UPDATED):
        created = create(
            tmp_path,
            topic_id="clocked-topic",
            title="엔진 시각 초안",
            scope="검사할 범위",
        )

    assert created["updated"] == UPDATED


def test_update_replaces_a_valid_draft_at_the_expected_sha(tmp_path):
    created = create(
        tmp_path,
        topic_id="updated-topic",
        title="갱신할 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    content = created["content"].replace(
        f"Updated: {UPDATED}",
        "Updated: 2026-08-28T19:30:00+09:00",
    ).replace(
        "## 확인된 이해\n\n## 어휘 관찰",
        "## 확인된 이해\n\n- 이벤트 의미를 확인했다.\n\n## 어휘 관찰",
    )

    updated = update(
        tmp_path,
        "updated-topic",
        expected_sha=created["sha256"],
        content=content,
    )

    assert updated == show(tmp_path, "updated-topic")
    assert updated["content"] == content
    assert updated["sha256"] != created["sha256"]


def test_update_with_stale_sha_is_structured_and_writes_nothing(tmp_path):
    created = create(
        tmp_path,
        topic_id="contended-topic",
        title="경합 초안",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    winner_content = created["content"].replace(
        f"Updated: {UPDATED}",
        "Updated: 2026-08-28T19:00:00+09:00",
    )
    winner = update(
        tmp_path,
        "contended-topic",
        expected_sha=created["sha256"],
        content=winner_content,
    )
    stale_content = created["content"].replace(
        f"Updated: {UPDATED}",
        "Updated: 2026-08-28T20:00:00+09:00",
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "contended-topic",
            expected_sha=created["sha256"],
            content=stale_content,
        )

    assert exc.value.code == "draft_stale_sha"
    assert exc.value.actual_sha == winner["sha256"]
    assert show(tmp_path, "contended-topic") == winner


def test_update_rejects_invalid_v1_content_before_replacing_the_file(tmp_path):
    created = create(
        tmp_path,
        topic_id="validated-update",
        title="검증할 갱신",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    invalid = created["content"].replace(
        "<!-- project-brain-draft:v1 -->\n",
        "",
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "validated-update",
            expected_sha=created["sha256"],
            content=invalid,
        )

    assert exc.value.code == "draft_marker_invalid"
    assert show(tmp_path, "validated-update") == created
    assert list((tmp_path / "drafts").glob(".*.tmp")) == []


def test_update_replace_failure_preserves_original_and_cleans_temporary_file(tmp_path):
    created = create(
        tmp_path,
        topic_id="atomic-update",
        title="원자 갱신",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    content = created["content"].replace(
        f"Updated: {UPDATED}",
        "Updated: 2026-08-28T19:30:00+09:00",
    )

    with mock.patch("project_brain.draft.os.replace", side_effect=OSError("교체 실패")):
        with pytest.raises(OSError, match="교체 실패"):
            update(
                tmp_path,
                "atomic-update",
                expected_sha=created["sha256"],
                content=content,
            )

    assert show(tmp_path, "atomic-update") == created
    assert list((tmp_path / "drafts").glob(".*.tmp")) == []


def test_update_preserves_the_existing_draft_file_mode(tmp_path):
    created = create(
        tmp_path,
        topic_id="mode-update",
        title="권한 보존 갱신",
        scope="검사할 범위",
        updated_at=UPDATED,
    )
    path = tmp_path / created["path"]
    path.chmod(0o640)
    content = created["content"].replace(
        f"Updated: {UPDATED}",
        "Updated: 2026-08-28T19:30:00+09:00",
    )

    update(
        tmp_path,
        "mode-update",
        expected_sha=created["sha256"],
        content=content,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_create_never_writes_through_a_symlinked_drafts_root(tmp_path):
    outside_drafts = tmp_path / "outside" / "drafts"
    outside_drafts.mkdir(parents=True)
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    (brain_root / "drafts").symlink_to(outside_drafts, target_is_directory=True)

    with pytest.raises(DraftError) as exc:
        create(
            brain_root,
            topic_id="escaped-topic",
            title="이탈 초안",
            scope="검사할 범위",
            updated_at=UPDATED,
        )

    assert exc.value.code == "draft_path_invalid"
    assert list(outside_drafts.iterdir()) == []


def test_create_validates_rendered_sections_before_writing(tmp_path):
    with pytest.raises(DraftError) as exc:
        create(
            tmp_path,
            topic_id="injected-section",
            title="절이 추가된 초안",
            scope="기본 범위\n\n## 추가 절\n\n허용되지 않은 H2",
            updated_at=UPDATED,
        )

    assert exc.value.code == "draft_sections_invalid"
    assert list(tmp_path.rglob("*.md")) == []


def test_drafts_are_outside_store_raw_index_query_and_graph_inputs(tmp_path):
    from project_brain.graph import find_isolated
    from project_brain.graph_viz import build_payload
    from project_brain.raw_chunks import iter_raw_sources
    from project_brain.router import QueryRouter
    from project_brain.search_index import compute_corpus_fingerprint, rebuild
    from project_brain.store import BrainStore

    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = BrainStore.load(brain_root)
    fingerprint_before = compute_corpus_fingerprint(before, brain_root)

    create(
        brain_root,
        topic_id="excluded-topic",
        title="DRAFT_ONLY_TITLE_8F6A",
        scope="DRAFT_ONLY_SCOPE_7C1B",
        updated_at=UPDATED,
    )

    after = BrainStore.load(brain_root)
    fingerprint_after = compute_corpus_fingerprint(after, brain_root)
    stats = rebuild(
        brain_root=brain_root,
        db_path=brain_root / ".brain-local" / "index.db",
        embedder=None,
    )
    answer = QueryRouter(after).answer("이 값은 무엇인가")

    assert after.all() == before.all() == []
    assert fingerprint_after == fingerprint_before
    assert list(iter_raw_sources(brain_root)) == []
    assert stats["indexed"] == stats["raw_chunks"] == stats["total_objects"] == 0
    assert find_isolated(after) == []
    assert build_payload(after)["nodes"] == []
    assert "DRAFT_ONLY" not in json.dumps(answer, ensure_ascii=False)


def test_interfaces_reject_a_symlinked_brain_root_without_following_it(tmp_path):
    actual_root = tmp_path / "actual-brain"
    create(
        actual_root,
        topic_id="existing-topic",
        title="기존 초안",
        scope="기존 범위",
        updated_at=UPDATED,
    )
    linked_root = tmp_path / "linked-brain"
    linked_root.symlink_to(actual_root, target_is_directory=True)

    assert [problem["code"] for problem in lint(linked_root)] == [
        "draft_path_invalid"
    ]
    for read in (
        lambda: show(linked_root, "existing-topic"),
        lambda: list_drafts(linked_root),
        lambda: create(
            linked_root,
            topic_id="escaped-topic",
            title="이탈 초안",
            scope="이탈 범위",
            updated_at=UPDATED,
        ),
    ):
        with pytest.raises(DraftError) as exc:
            read()
        assert exc.value.code == "draft_path_invalid"

    assert not (actual_root / "drafts" / "escaped-topic.md").exists()


def test_update_rejects_a_malformed_expected_sha_without_writing(tmp_path):
    created = create(
        tmp_path,
        topic_id="sha-topic",
        title="SHA 초안",
        scope="검사 범위",
        updated_at=UPDATED,
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "sha-topic",
            expected_sha="not-a-sha",
            content=created["content"],
        )

    assert exc.value.code == "draft_expected_sha_invalid"
    assert show(tmp_path, "sha-topic") == created


def test_update_rejects_metadata_shifted_out_of_the_fixed_v1_header(tmp_path):
    created = create(
        tmp_path,
        topic_id="shifted-header",
        title="고정 헤더 초안",
        scope="검사 범위",
        updated_at=UPDATED,
    )
    shifted = created["content"].replace(
        "<!-- project-brain-draft:v1 -->\n",
        "<!-- project-brain-draft:v1 -->\n고정 구조 밖 텍스트\n",
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "shifted-header",
            expected_sha=created["sha256"],
            content=shifted,
        )

    assert exc.value.code == "draft_title_invalid"
    assert show(tmp_path, "shifted-header") == created


def test_update_rejects_unscoped_text_between_header_and_first_section(tmp_path):
    created = create(
        tmp_path,
        topic_id="unscoped-header",
        title="고정 헤더 초안",
        scope="검사 범위",
        updated_at=UPDATED,
    )
    invalid = created["content"].replace(
        f"Updated: {UPDATED}\n\n## 범위",
        f"Updated: {UPDATED}\n\nUnexpected: value\n\n## 범위",
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "unscoped-header",
            expected_sha=created["sha256"],
            content=invalid,
        )

    assert exc.value.code == "draft_sections_invalid"
    assert show(tmp_path, "unscoped-header") == created


def test_lint_ignores_heading_like_lines_inside_fenced_code(tmp_path):
    created = create(
        tmp_path,
        topic_id="fenced-content",
        title="코드 예시 초안",
        scope="검사 범위",
        updated_at=UPDATED,
    )
    content = created["content"].replace(
        "## 확인된 이해\n\n## 어휘 관찰",
        """## 확인된 이해

```bash
# shell comment
## 문서 절이 아닌 출력 예시
Topic ID: not-metadata
Updated: not-a-time
<!-- project-brain-draft:v1 -->
```

## 어휘 관찰""",
    )

    updated = update(
        tmp_path,
        "fenced-content",
        expected_sha=created["sha256"],
        content=content,
    )

    assert lint(tmp_path, topic_id="fenced-content") == []
    assert updated["topic_id"] == "fenced-content"
    assert updated["title"] == "코드 예시 초안"


@pytest.mark.parametrize("indent", (" ", "  ", "   "))
def test_lint_counts_indented_commonmark_h1_and_h2_as_real_headings(
    tmp_path,
    indent,
):
    created = create(
        tmp_path,
        topic_id="indented-heading",
        title="들여쓴 제목 검사",
        scope="검사 범위",
        updated_at=UPDATED,
    )
    content = created["content"].replace(
        "## 확인된 이해\n\n## 어휘 관찰",
        (
            "## 확인된 이해\n\n"
            f"{indent}# 추가 H1\n"
            f"{indent}## 추가 H2\n\n"
            "## 어휘 관찰"
        ),
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "indented-heading",
            expected_sha=created["sha256"],
            content=content,
        )

    assert exc.value.code == "draft_title_invalid"
    assert show(tmp_path, "indented-heading") == created


def test_lint_counts_setext_h1_and_h2_as_real_headings(tmp_path):
    created = create(
        tmp_path,
        topic_id="setext-heading",
        title="Setext 제목 검사",
        scope="검사 범위",
        updated_at=UPDATED,
    )
    content = created["content"].replace(
        "## 확인된 이해\n\n## 어휘 관찰",
        """## 확인된 이해

추가 H1
===

추가 H2
---

## 어휘 관찰""",
    )

    with pytest.raises(DraftError) as exc:
        update(
            tmp_path,
            "setext-heading",
            expected_sha=created["sha256"],
            content=content,
        )

    assert exc.value.code == "draft_title_invalid"
    assert show(tmp_path, "setext-heading") == created


def test_create_rejects_an_atx_title_that_commonmark_parses_as_empty(tmp_path):
    with pytest.raises(DraftError) as exc:
        create(
            tmp_path,
            topic_id="empty-atx-title",
            title="#",
            scope="검사 범위",
            updated_at=UPDATED,
        )

    assert exc.value.code == "draft_title_invalid"
    assert list(tmp_path.rglob("*.md")) == []
