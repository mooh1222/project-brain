"""벡터 seed 선택: 명시 인자 > config > 같은 Git clone의 다른 checkout."""
from pathlib import Path
import subprocess

from project_brain.config import CONFIG_FILENAME, configured_index_seeds, load_config


def _git(path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ['git', '-C', str(path), *args], capture_output=True, text=True, timeout=10,
        )
        return result.stdout.rstrip('\n') if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def resolve_index_seeds(explicit, *, brain_root: Path, db_path: Path) -> tuple[list[Path], list[dict]]:
    """후보만 찾는다. 호환성·무결성은 rebuild의 이전 색인 reader가 공통 검사한다."""
    configured = configured_index_seeds(explicit)
    if configured is not None:
        return configured, []
    common = _git(brain_root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    current = _git(brain_root, 'rev-parse', '--show-toplevel')
    if not common or not current:
        return [], []
    common_path = Path(common).resolve()
    current_path = Path(current).resolve()
    worktrees = _git(brain_root, 'worktree', 'list', '--porcelain', '-z')
    if worktrees is None:
        return [], [{'path': str(brain_root), 'reason': 'seed_discovery_failed'}]
    # Git은 원본 checkout을 첫 항목으로 반환한다. -z로 공백·개행 경로도 보존한다.
    checkouts = [Path(field[len('worktree '):]) for field in worktrees.split('\0')
                 if field.startswith('worktree ')]
    candidates = []
    failures = []
    for checkout in checkouts:
        if checkout.resolve() == current_path:
            continue
        other_common = _git(checkout, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if not other_common or Path(other_common).resolve() != common_path:
            continue
        try:
            if (checkout / CONFIG_FILENAME).is_file():
                candidate = load_config(start=checkout)['db']
            else:
                # config가 없으면 현재 DB의 checkout 상대 위치만 대응시킨다.
                candidate = checkout / db_path.resolve().relative_to(current_path)
            if candidate.is_file():
                candidates.append(candidate.resolve())
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            failures.append({'path': str(checkout / CONFIG_FILENAME),
                             'reason': 'invalid_seed_config'})
    return candidates, failures
