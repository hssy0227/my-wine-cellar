# -*- coding: utf-8 -*-
"""audit 결과 비교 — 이번 편집으로 **새로 생긴** 이슈만 뽑는다.

그대로 보여주면 기존 이슈(현재 73건)에 파묻혀 리뷰어가 뭘 봐야 할지 알 수 없다.
PR 리뷰 단계를 없앤 만큼, 이 신호가 유일한 사후 방어선이라 정확해야 한다.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import audit as audit_mod  # noqa: E402

# 제출을 멈추고 사람 확인을 받아야 하는 audit 항목.
# audit.py가 붙이는 카테고리 이름과 문자열이 정확히 같아야 한다.
CONFIRM_REQUIRED = ("원어명 유실 의심",)


def all_issues(df) -> dict:
    """전체 이슈 집합. artifacts.audit_summary에 저장해 다음 편집의 기준선이 된다."""
    return {k: list(v) for k, v in audit_mod.check(df).items()}


def _diff(before: dict, after: dict) -> dict:
    new_issues = {}
    for category, lines in after.items():
        before_set = set(before.get(category, []))
        added = [line for line in lines if line not in before_set]
        if added:
            new_issues[category] = added
    return {
        "new_issues": new_issues,
        "new_issue_count": sum(len(v) for v in new_issues.values()),
        "baseline_issue_count": sum(len(v) for v in before.values()),
    }


def diff_issues(before_df, after_df) -> dict:
    """두 빌드 결과를 비교한다 (CLI·테스트용)."""
    return _diff(all_issues(before_df), all_issues(after_df))


def diff_issues_from_stored(stored_issues: dict, after_df) -> dict:
    """저장된 기준선과 비교한다 (쓰기 경로용).

    "수정 전" 빌드를 한 번 더 돌리지 않아 빠르고, 재-파생한 값이 아니라
    실제로 발행돼 있는 아티팩트와 비교하므로 더 정확하다.
    """
    return _diff(stored_issues or {}, all_issues(after_df))
