"""raw 원문 청커 + 소스 발견 (스펙 §2.2, P4 raw 본문 색인 — 2026-06-11).

`brain/raw/sources/<context>/*.md`(P1 규약 — 텍스트 원문만 추적)를 헤더 기준으로
청크해 색인 행으로 만든다. hwi_PKM chunker 채택(task 참조 지도 소비 기록):
헤더(#~######) 1차 섹션화 → 목표 토큰 초과 섹션만 문장 경계 2차 분할 + 15% 겹침.
토큰은 정밀 토크나이저가 아니라 보수적 근사(영문 단어수 + 한글 글자수 +
ASCII·한글 이외 비공백 기호 2개당 1토큰)다. 난수·시각 없이 완전 결정론이라
같은 입력이면 항상 같은 청크(재생성 가능 색인의 전제, §4).

청크 행 메타(§2.2): kind="raw_chunk", status="raw", context_id="context.<디렉토리명>"
(실코퍼스 규약 — raw/sources/mina-kayak ↔ context.mina-kayak), id는
"raw.<context디렉토리>.<파일stem>#<순번:03d>" — brain 객체 id와 네임스페이스 분리.
"""

import os
import re
from pathlib import Path

# hwi_PKM chunker와 같은 목표·겹침(참조 지도 채택 — 2026-06-11).
CHUNK_TARGET_TOKENS = 500
CHUNK_OVERLAP_RATIO = 0.15

# §2.2 행 메타 상수 — 색인·recall·채널 배치가 raw 행을 식별하는 단일 출처.
RAW_KIND = "raw_chunk"
RAW_STATUS = "raw"

_HEADING_RE = re.compile(r"^#{1,6}\s")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_HANGUL_RE = re.compile(r"[가-힣]")
_OTHER_NONSPACE_RE = re.compile(r"[^\sA-Za-z0-9_가-힣]")
# 문장 경계: 종결 부호 뒤 공백. 마크다운 표·목록처럼 부호 없는 줄은 줄 자체가 유닛.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def approx_tokens(text: str) -> int:
    """토큰 수의 보수적 근사 — 영문 단어, 한글 글자, 나머지 기호를 센다."""
    ascii_words = len(_ASCII_WORD_RE.findall(text))
    hangul_chars = len(_HANGUL_RE.findall(text))
    other_chars = len(_OTHER_NONSPACE_RE.findall(text))
    return ascii_words + hangul_chars + ((other_chars + 1) // 2)


def _split_sections(text: str) -> list[str]:
    """헤더 줄에서 섹션을 가른다. 본문 없는 헤더(제목 연쇄)는 다음 섹션에 붙여
    제목만 있는 거의 빈 청크를 만들지 않는다. 첫 헤더 앞 서문도 한 섹션."""
    sections: list[str] = []
    cur: list[str] = []

    def has_body(lines) -> bool:
        return any(l.strip() and not _HEADING_RE.match(l) for l in lines)

    for line in text.splitlines():
        if _HEADING_RE.match(line) and has_body(cur):
            sections.append("\n".join(cur).strip("\n"))
            cur = []
        cur.append(line)
    if any(l.strip() for l in cur):
        sections.append("\n".join(cur).strip("\n"))
    return [s for s in sections if s.strip()]


def _units(section_text: str) -> list[str]:
    """과대 섹션의 분할 유닛 — 줄 단위로 받고, 종결 부호가 있는 줄은 문장으로 더
    가른다(스펙 §2.2 "문장 경계 분할"). 빈 줄은 검색용 청크라 버린다."""
    units: list[str] = []
    for line in section_text.splitlines():
        if not line.strip():
            continue
        units.extend(p for p in _SENTENCE_SPLIT_RE.split(line) if p.strip())
    return units


def _split_oversized_unit(unit: str, target: int) -> list[str]:
    """목표를 넘는 단일 유닛을 문자 경계에서 보수적으로 나눈다."""
    out, buf = [], []
    for ch in unit:
        candidate = "".join(buf) + ch
        if buf and approx_tokens(candidate) > target:
            out.append("".join(buf))
            buf = [ch]
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _windows(units: list[str], target: int, overlap_ratio: float) -> list[str]:
    """유닛을 토큰 예산 창으로 묶는다. 다음 창은 직전 창 꼬리 ~15% 토큰 분량을
    다시 포함(겹침). i가 항상 전진하므로 무한 루프 없음 — 결정론."""
    units = [
        piece
        for unit in units
        for piece in (_split_oversized_unit(unit, target)
                      if approx_tokens(unit) > target else [unit])
        if piece
    ]
    out: list[str] = []
    i, n = 0, len(units)
    overlap_budget = int(target * overlap_ratio)
    while i < n:
        tokens, j = 0, i
        while j < n and (tokens == 0 or tokens + approx_tokens(units[j]) <= target):
            tokens += approx_tokens(units[j])
            j += 1
        out.append("\n".join(units[i:j]))
        if j >= n:
            break
        k, back = j, 0
        while k > i + 1 and back < overlap_budget:
            k -= 1
            back += approx_tokens(units[k])
        i = max(k, i + 1)
    return out


def split_markdown(text: str, target_tokens: int = CHUNK_TARGET_TOKENS,
                   overlap_ratio: float = CHUNK_OVERLAP_RATIO) -> list[str]:
    """마크다운 원문을 청크 텍스트 리스트로 나눈다(완전 결정론).

    헤더 기준 섹션이 목표 토큰 이하면 섹션 그대로 한 청크, 넘으면 문장 경계
    유닛을 토큰 예산 창으로 묶고 15% 겹침을 둔다.
    """
    chunks: list[str] = []
    for section in _split_sections(text):
        if approx_tokens(section) <= target_tokens:
            chunks.append(section)
        else:
            chunks.extend(_windows(_units(section), target_tokens, overlap_ratio))
    return chunks


def raw_source_paths(brain_root) -> list[Path]:
    """색인이 발견하는 원문 파일. 순서·깊이·확장자는 기존 색인 규약 그대로다."""
    root = Path(brain_root) / "raw" / "sources"
    if not root.exists():
        return []
    return [
        md
        for ctx_dir in sorted(p for p in root.iterdir() if p.is_dir())
        for md in sorted(ctx_dir.glob("*.md"))
    ]


def _source_chunks(md: Path) -> list[dict]:
    text = md.read_text(encoding="utf-8")
    return [
        {"chunk_id": f"raw.{md.parent.name}.{md.stem}#{i:03d}",
         "context_id": f"context.{md.parent.name}", "text": chunk}
        for i, chunk in enumerate(split_markdown(text))
    ]


def indexable_raw_chunks(chunks, *, tokenize_fn=None):
    """rebuild와 preview가 공유하는 검색 토큰 공백 제외 관문."""
    if tokenize_fn is None:
        from project_brain.tokenize_ko import tokenize
        tokenize_fn = tokenize
    for chunk in chunks:
        tokens = tokenize_fn(chunk["text"])
        if tokens:
            yield chunk, tokens


def preview_raw_chunks(brain_root, paths=None) -> dict:
    """기존 DB·임베더 없이 원문별 실제 raw 색인 예상 행 수를 계산한다."""
    from project_brain.tokenize_ko import tokenizer_signature

    brain_root = Path(brain_root)
    if not brain_root.is_dir():
        raise ValueError(f"brain 코퍼스 디렉터리가 없음: {brain_root}")
    discovered = raw_source_paths(brain_root)
    if paths:
        requested = {Path(os.path.abspath(path)) for path in paths}
        available = {Path(os.path.abspath(path)): path for path in discovered}
        invalid = requested - available.keys()
        if invalid:
            raise ValueError(
                "색인 탐색 범위 raw/sources/<context>/*.md에 없는 원문: "
                + ", ".join(str(path) for path in sorted(invalid))
            )
        discovered = [md for md in discovered if Path(os.path.abspath(md)) in requested]
    sources = [
        {"path": md.relative_to(brain_root).as_posix(),
         "context_id": f"context.{md.parent.name}",
         "raw_chunks": sum(1 for _ in indexable_raw_chunks(_source_chunks(md)))}
        for md in discovered
    ]
    return {"brain_root": str(brain_root), "tokenizer": tokenizer_signature(),
            "raw_chunks": sum(source["raw_chunks"] for source in sources),
            "sources": sources}


def iter_raw_sources(brain_root) -> list[dict]:
    """brain/raw/sources/<context>/*.md를 청크 행으로 펼친다(정렬 순회 — 결정론).

    반환 원소: {chunk_id, context_id, text}. 디렉토리가 없으면 빈 리스트.
    .md만 본다 — P1 규약이 텍스트 원문만 추적하고 현 코퍼스 전부 md.
    """
    return [chunk for md in raw_source_paths(brain_root) for chunk in _source_chunks(md)]
