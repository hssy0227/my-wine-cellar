# -*- coding: utf-8 -*-
"""GitHub REST(Git Data API)로 브랜치+원자적 멀티파일 커밋+PR을 생성한다.

Vercel 함수는 별도 인프라에서 돌아 이 세션의 GitHub MCP 도구를 못 쓴다 —
직접 REST 호출한다. blob/tree/commit을 먼저 만들고 그 커밋 위치에 브랜치를
마지막에 만든다 — 중간에 실패해도 불완전한 브랜치가 안 남는다.
"""
import base64
import os
from typing import Dict, Optional

import requests

API = "https://api.github.com"


class GitHubApiError(Exception):
    def __init__(self, message: str, branch: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.branch = branch  # 커밋까지는 됐는데 PR 생성만 실패한 경우에 채워짐


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubApiError("GITHUB_TOKEN 환경변수가 설정돼 있지 않습니다.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPO")
    if not repo:
        raise GitHubApiError("GITHUB_REPO 환경변수가 설정돼 있지 않습니다.")
    return repo


def _req(method: str, path: str, **kwargs) -> dict:
    resp = requests.request(method, f"{API}/repos/{_repo()}{path}",
                             headers=_headers(), timeout=20, **kwargs)
    if resp.status_code >= 300:
        raise GitHubApiError(
            f"GitHub API {method} {path} 실패 ({resp.status_code}): {resp.text[:500]}")
    return resp.json() if resp.text else {}


def open_pr(files: Dict[str, bytes], branch: str, title: str, body: str) -> dict:
    """files: {"data/seed/producers.csv": b"...", ...} — 저장소 루트 기준 상대경로.

    반환: {"html_url": ..., "number": ...}
    """
    repo_info = _req("GET", "")
    default_branch = repo_info["default_branch"]

    base_ref = _req("GET", f"/git/ref/heads/{default_branch}")
    base_sha = base_ref["object"]["sha"]

    base_commit = _req("GET", f"/git/commits/{base_sha}")
    base_tree_sha = base_commit["tree"]["sha"]

    tree_entries = []
    for path, content in files.items():
        blob = _req("POST", "/git/blobs", json={
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
        tree_entries.append(
            {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    new_tree = _req("POST", "/git/trees", json={
        "base_tree": base_tree_sha,
        "tree": tree_entries,
    })

    new_commit = _req("POST", "/git/commits", json={
        "message": title,
        "tree": new_tree["sha"],
        "parents": [base_sha],
    })

    _req("POST", "/git/refs", json={
        "ref": f"refs/heads/{branch}",
        "sha": new_commit["sha"],
    })

    try:
        pr = _req("POST", "/pulls", json={
            "title": title,
            "head": branch,
            "base": default_branch,
            "body": body,
        })
    except GitHubApiError as e:
        # 커밋+브랜치는 이미 생겼는데 PR만 실패 — 브랜치명을 실어 올려서
        # 호출자가 사용자에게 "직접 PR 열거나 브랜치를 정리하라"고 안내할 수 있게.
        raise GitHubApiError(e.message, branch=branch) from e

    return {"html_url": pr["html_url"], "number": pr["number"]}
