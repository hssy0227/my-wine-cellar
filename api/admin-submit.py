# -*- coding: utf-8 -*-
"""사전 편집 엔드포인트 (POST /api/admin-submit).

흐름:
  비밀번호 → Supabase 스냅샷 fetch → 메모리에서 검증·적용 → build() 1회 →
  audit 차집합(라이브 아티팩트 기준) → DB 반영 → Storage 발행 → 동기화 신호 → 응답

빌드가 성공한 뒤에야 DB를 건드린다. 순서를 뒤집으면 빌드 실패 시 DB만
바뀌어 라이브 사전과 어긋난 채로 남는다.
"""
import hmac
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _lib import (audit_adapter, github_client, publish, seed_ops,  # noqa: E402
                   seed_source, supabase_client)
import build as build_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _build(terms, aliases):
    """스냅샷 -> build(). build.py는 손대지 않는다 — seed CSV 형태로 직렬화해서 넘긴다.

    이 우회가 오히려 낫다. build()의 파생 로직이 한 줄도 안 바뀌므로
    "dist가 seed로부터 바이트 재현된다"는 회귀 테스트가 그대로 유효하다.
    """
    # hierarchy.csv는 넣지 않는다 — build()가 그 파일을 읽는 건 dist를 파일로 쓸 때뿐이고,
    # 여기선 dist_dir=None이라 그 경로를 타지 않는다. 덕분에 함수 번들에서 data/를 통째로 뺄 수 있다.
    tmp = Path(tempfile.mkdtemp(prefix="wine-build-"))
    try:
        for fname, data in seed_source.rows_to_seed_csvs(terms, aliases).items():
            (tmp / fname).write_bytes(data)
        return build_mod.build(seed_dir=tmp, dist_dir=None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _apply_all(terms, aliases, changes):
    ops, diffs, warnings = [], [], []
    for ch in changes:
        terms, aliases, op, diff, warns = seed_ops.apply_change(
            terms, aliases,
            file=ch.get("file"), action=ch.get("action"),
            row=ch.get("row") or {}, match=ch.get("match"))
        ops.append(op)
        diffs.append({"file": ch.get("file"), "action": ch.get("action"), **diff})
        warnings.extend(warns)
    return terms, aliases, ops, diffs, warnings


def handle(payload: dict):
    expected = os.environ.get("EDIT_PASSWORD", "")
    if not expected or not hmac.compare_digest(str(payload.get("password", "")), expected):
        return 401, {"ok": False, "error": "unauthorized"}

    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes:
        return 400, {"ok": False, "error": "validation_failed", "message": "changes가 비어 있습니다."}
    reason = str(payload.get("reason") or "").strip()

    try:
        sb = supabase_client.Supabase()
        source = seed_source.SupabaseSource(client=sb)

        revision = sb.revision()
        orig_terms, orig_aliases = source.fetch()
        try:
            terms, aliases, ops, diffs, warnings = _apply_all(orig_terms, orig_aliases, changes)
        except seed_ops.ValidationError as e:
            return 400, {"ok": False, "error": "validation_failed",
                          "message": e.message, "field": e.field}

        df = _build(terms, aliases)

        # 다른 편집이 끼어들었으면 새 스냅샷으로 한 번만 다시 시도한다.
        if sb.revision() != revision:
            revision = sb.revision()
            orig_terms, orig_aliases = source.fetch()
            try:
                terms, aliases, ops, diffs, warnings = _apply_all(orig_terms, orig_aliases, changes)
            except seed_ops.ValidationError as e:
                return 409, {"ok": False, "error": "conflict", "message": e.message}
            df = _build(terms, aliases)

        # audit은 재-파생한 값이 아니라 **실제로 라이브인** 아티팩트와 비교한다.
        prev = sb.latest_artifact()
        baseline = (prev or {}).get("audit_summary")
        if not baseline:
            # 기준선이 아직 없다(최초 편집 등). 비어 있는 걸 기준선으로 쓰면 기존 73건이
            # 전부 "신규"로 잡혀 겁나는 오보가 된다 — 변경 전 스냅샷을 한 번 더 빌드한다.
            baseline = audit_adapter.all_issues(_build(orig_terms, orig_aliases))
        audit_diff = audit_adapter.diff_issues_from_stored(baseline, df)

        # 한 종류만 확인을 강제한다. PR 리뷰가 사라진 지금, audit 경고는 "피곤하면
        # 넘길 수 있는 배너"가 됐다. 그런데 원어명 유실은 이 프로젝트의 역사적 실패
        # 유형이다 — 모스카토 다스티가 Moscato로, 소노마 코스트가 Sonoma로 저장된
        # 사고가 실제로 있었고, 검색은 되는데 결과만 틀려서 아무도 눈치채지 못했다.
        # 나머지 경고는 사후 표시로 충분하지만 이것만은 손을 멈추게 한다.
        gated = {k: v for k, v in audit_diff["new_issues"].items()
                 if k in audit_adapter.CONFIRM_REQUIRED}
        if gated and not payload.get("confirm_audit"):
            return 409, {"ok": False, "error": "confirm_required",
                          "message": "원어명 일부가 빠졌을 수 있습니다. 확인 후 진행하세요.",
                          "issues": gated, "audit": audit_diff}

        # 빌드가 성공한 뒤에야 DB를 건드린다.
        for op in ops:
            if op.action == "insert":
                sb.insert(op.table, op.payload)
            elif op.action == "update":
                sb.update(op.table, op.row_id, op.payload)
            elif op.action == "delete":
                sb.soft_delete(op.table, op.row_id)

        manifest = publish.publish(sb, df)
        publish.record_artifact(sb, manifest, sb.revision(), audit_adapter.all_issues(df))

        for d in diffs:
            sb.log_edit({"action": d["action"], "table_name": d["file"],
                          "row_before": d.get("before"), "row_after": d.get("after"),
                          "reason": reason, "artifact_version": manifest["version"]})

        dispatched = True
        try:
            github_client.dispatch("dict-updated", {"version": manifest["version"]})
        except github_client.GitHubApiError:
            dispatched = False  # 야간 크론이 잡는다 — 편집 자체를 실패시키지 않는다

        return 200, {"ok": True, "version": manifest["version"],
                      "rows": manifest["rows"], "canonical": manifest["canonical"],
                      "audit": audit_diff, "warnings": warnings,
                      "git_sync_requested": dispatched}

    except supabase_client.SupabaseError as e:
        return 502, {"ok": False, "error": "supabase_error", "message": str(e)}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            status, result = handle(json.loads(body or b"{}"))
        except json.JSONDecodeError:
            status, result = 400, {"ok": False, "error": "invalid_json"}
        except Exception as e:  # noqa: BLE001 — 사용자에게 500 HTML을 보이지 않는다
            status, result = 500, {"ok": False, "error": "internal_error", "message": str(e)}

        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
