"""raw 원문 청커 + 소스 발견 (스펙 §2.2, P4 raw 본문 색인 — 2026-06-11).

`brain/raw/sources/<context>/*.md`(P1 규약 — 텍스트 원문만 추적)를 헤더 기준으로
청크해 색인 행으로 만든다. hwi_PKM chunker 채택(task 참조 지도 소비 기록):
헤더(#~######) 1차 섹션화 → 목표 토큰 초과 섹션만 문장 경계 2차 분할 + 15% 겹침.
토큰은 정밀 토크나이저가 아니라 근사(영문 단어수 + 한글 글자수/2) — 난수·시각
없이 완전 결정론이라 같은 입력이면 항상 같은 청크(재생성 가능 색인의 전제, §4).

청크 행 메타(§2.2): kind="raw_chunk", status="raw", context_id="context.<디렉토리명>"
(실코퍼스 규약 — raw/sources/mina-kayak ↔ context.mina-kayak), id는
"raw.<context디렉토리>.<파일stem>#<순번:03d>" — brain 객체 id와 네임스페이스 분리.
"""

import re
from pathlib import Path

# hwi_PKM chunker와 같은 목표·겹침(참조 지도 채택 — 2026-06-11).
CHUNK_TARGET_TOKENS = 500
CHUNK_OVERLAP_RATIO = 0.15

# §2.2 행 메타 상수 — 색인·recall·게이트가 raw 행을 식별하는 단일 출처.
RAW_KIND = "raw_chunk"
RAW_STATUS = "raw"

_HEADING_RE = re.compile(r"^#{1,6}\s")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_HANGUL_RE = re.compile(r"[가-힣]")
# 문장 경계: 종결 부호 뒤 공백. 마크다운 표·목록처럼 부호 없는 줄은 줄 자체가 유닛.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def approx_tokens(text: str) -> int:
    """토큰 수 근사 — 영문 단어수 + 한글 글자수/2 (hwi_PKM 동일 근사)."""
    ascii_words = len(_ASCII_WORD_RE.findall(text))
    hangul_chars = len(_HANGUL_RE.findall(text))
    return ascii_words + hangul_chars // 2


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


def _windows(units: list[str], target: int, overlap_ratio: float) -> list[str]:
    """유닛을 토큰 예산 창으로 묶는다. 다음 창은 직전 창 꼬리 ~15% 토큰 분량을
    다시 포함(겹침). i가 항상 전진하므로 무한 루프 없음 — 결정론."""
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


def iter_raw_sources(brain_root) -> list[dict]:
    """brain/raw/sources/<context>/*.md를 청크 행으로 펼친다(정렬 순회 — 결정론).

    반환 원소: {chunk_id, context_id, text}. 디렉토리가 없으면 빈 리스트.
    .md만 본다 — P1 규약이 텍스트 원문만 추적하고 현 코퍼스 전부 md.
    """
    root = Path(brain_root) / "raw" / "sources"
    if not root.exists():
        return []
    out: list[dict] = []
    for ctx_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for md in sorted(ctx_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            for i, chunk in enumerate(split_markdown(text)):
                out.append({
                    "chunk_id": f"raw.{ctx_dir.name}.{md.stem}#{i:03d}",
                    "context_id": f"context.{ctx_dir.name}",
                    "text": chunk,
                })
    return out
