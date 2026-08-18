# -*- coding: utf-8 -*-
"""사전 관리 패널의 쓰기 엔드포인트 (POST /api/admin-submit).

흐름: 비밀번호 확인 → seed 변경 적용(임시 작업 디렉터리) → build()+audit()로
수정 전/후 비교 → GitHub에 브랜치+커밋+PR 생성.

하드 블록(비밀번호 불일치, 중복 추가, 고아 별칭 등)은 seed_ops.ValidationError로
막고 PR을 만들지 않는다. audit.py가 잡는 나머지 문제는 막지 않고 PR 본문에
"이번 변경으로 새로 유입된 것만" 적어서 사람이 보게 한다.
"""
import hmac
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import audit_adapter, build_adapter, github_client, seed_ops  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
SEED_FILES = ["grapes.csv", "regions.csv", "producers.csv", "aliases.csv"]


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:40] or "edit"


def _pr_title(first_change: dict) -> str:
    label = "추가" if first_change["action"] == "add" else "수정"
    name = first_change["diff"]["after"].get("name_en") or first_change["diff"]["after"].get("alias_ko") or ""
    return f"[사전 편집] {label} · {first_change['file']} · {name}"


def _pr_body(summary: list, audit_diff: dict, reason: str) -> str:
    lines = ["## 변경 내용"]
    for c in summary:
        lines.append(f"- 파일: `data/seed/{c['file']}.csv` · 동작: "
                      f"{'추가' if c['action'] == 'add' else '수정'}")
        before = c["diff"]["before"]
        after = c["diff"]["after"]
        if before:
            for k, v in after.items():
                bv = before.get(k, "")
                if str(bv) != str(v):
                    lines.append(f"  - `{k}`: `{bv}` → `{v}`")
        else:
            lines.append(f"  - {after}")
    if reason:
        lines.append(f"- 편집자 메모: {reason}")

    lines.append("")
    lines.append("## 무결성 점검 (scripts/audit.py 기준, 이번 변경으로 새로 유입된 항목만)")
    if audit_diff["new_issue_count"] == 0:
        lines.append(f"새로 유입된 문제 없음 (기존 {audit_diff['baseline_issue_count']}건은 변동 없음)")
    else:
        for cat, items in audit_diff["new_issues"].items():
            lines.append(f"- **{cat}** {len(items)}건")
            for it in items[:10]:
                lines.append(f"  - {it}")

    lines += [
        "",
        "## 리뷰 체크리스트",
        "- [ ] 원어명/한글명 표기가 정확한가",
        "- [ ] 별칭이 필요한 차이인가, 정규화가 이미 흡수하는 차이인가 (CLAUDE.md 참조)",
        "- [ ] 캐노니컬 병합/분리가 의도한 대로인가",
        "",
        "---",
        "_이 PR은 `/demo` 관리 패널을 통해 자동 생성되었습니다._",
    ]
    return "\n".join(lines)


def handle(payload: dict) -> tuple:
    """반환: (http_status, response_dict)"""
    password = payload.get("password", "")
    expected = os.environ.get("EDIT_PASSWORD", "")
    if not expected or not hmac.compare_digest(str(password), expected):
        return 401, {"ok": False, "error": "unauthorized"}

    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes:
        return 400, {"ok": False, "error": "validation_failed", "message": "changes가 비어 있습니다."}

    reason = str(payload.get("reason") or "").strip()

    with tempfile.TemporaryDirectory(prefix="wine-seed-work-") as tmp:
        work_dir = Path(tmp)
        for fname in SEED_FILES:
            src = SEED_DIR / fname
            if src.exists():
                shutil.copy(src, work_dir / fname)

        summary = []
        try:
            for change in changes:
                path, new_bytes, diff = seed_ops.apply_change(
                    work_dir,
                    change.get("file"),
                    change.get("action"),
                    change.get("row") or {},
                    change.get("match"),
                )
                (work_dir / path.name).write_bytes(new_bytes)
                summary.append({"file": change.get("file"), "action": change.get("action"), "diff": diff})
        except seed_ops.ValidationError as e:
            return 400, {"ok": False, "error": "validation_failed", "message": e.message, "field": e.field}

        baseline_df = build_adapter.build_dir(SEED_DIR)
        after_df = build_adapter.build_dir(work_dir)
        audit_diff = audit_adapter.diff_issues(baseline_df, after_df)

        files_to_commit = {}
        for fname in SEED_FILES:
            p = work_dir / fname
            if p.exists():
                files_to_commit[f"data/seed/{fname}"] = p.read_bytes()
        files_to_commit["data/dist/wine_terms.csv"] = build_adapter.serialize_csv(after_df)
        files_to_commit["data/dist/wine_terms.json"] = build_adapter.serialize_json(after_df)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        first = summary[0]
        name_for_slug = first["diff"]["after"].get("name_en") or first["diff"]["after"].get("alias_ko") or "edit"
        branch = f"edit/{first['file']}-{ts}-{_slug(name_for_slug)}"
        title = _pr_title(first)
        body = _pr_body(summary, audit_diff, reason)

        try:
            pr = github_client.open_pr(files_to_commit, branch, title, body)
        except github_client.GitHubApiError as e:
            err = {"ok": False, "error": "github_api_error", "message": e.message}
            if e.branch:
                err["branch"] = e.branch
            return 502, err

        return 200, {
            "ok": True,
            "pr_url": pr["html_url"],
            "pr_number": pr["number"],
            "branch": branch,
            "audit": audit_diff,
        }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(body or b"{}")
            status, result = handle(payload)
        except json.JSONDecodeError:
            status, result = 400, {"ok": False, "error": "invalid_json"}
        except Exception as e:  # noqa: BLE001 — 항상 JSON으로 응답, 사용자에게 500 HTML을 보이지 않는다
            status, result = 500, {"ok": False, "error": "internal_error", "message": str(e)}

        body_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)
