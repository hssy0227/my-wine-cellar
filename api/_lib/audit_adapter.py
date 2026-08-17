# -*- coding: utf-8 -*-
"""audit.check()를 수정 전/후 두 번 돌려서, 이번 편집으로 새로 생긴 이슈만 뽑는다.

그대로 보여주면 기존 이슈(현재 73건)에 매번 파묻혀서 리뷰어가 뭘 봐야 할지
알 수 없다 — 차집합만 남긴다.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import audit as audit_mod  # noqa: E402


def diff_issues(before_df, after_df) -> dict:
    before = audit_mod.check(before_df)
    after = audit_mod.check(after_df)
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
