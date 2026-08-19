# -*- coding: utf-8 -*-
"""GitHub repository_dispatch 발신.

Supabase 이관 전에는 이 모듈이 blob->tree->commit->ref->PR을 직접 만들었다.
이제 git 커밋은 GitHub Action(.github/workflows/export.yml)이 담당한다 —
그래야 커밋 전에 `npm test`를 돌릴 수 있고, 사용자 대기시간에 GitHub API
왕복이 끼지 않으며, "아티팩트는 발행됐는데 git은 안 됨" 같은 부분 실패 상태가
쓰기 경로 안에 생기지 않는다.

여기 남은 건 "사전이 바뀌었으니 동기화해라"는 신호 하나뿐이다.
실패해도 치명적이지 않다 — 야간 크론이 유실된 신호를 잡아낸다.
"""
import os
from typing import Optional

import requests

API = "https://api.github.com"


class GitHubApiError(Exception):
    def __init__(self, message: str, branch: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.branch = branch


def dispatch(event_type: str = "dict-updated", payload: Optional[dict] = None):
    """export 워크플로를 깨운다. 호출자는 실패를 삼켜도 된다."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        raise GitHubApiError("GITHUB_TOKEN / GITHUB_REPO 환경변수가 설정돼 있지 않습니다.")

    r = requests.post(
        f"{API}/repos/{repo}/dispatches",
        headers={"authorization": f"Bearer {token}",
                  "accept": "application/vnd.github+json",
                  "x-github-api-version": "2022-11-28"},
        json={"event_type": event_type, "client_payload": payload or {}},
        timeout=15)
    if r.status_code >= 300:
        raise GitHubApiError(
            f"repository_dispatch 실패 ({r.status_code}): {r.text[:300]}")
