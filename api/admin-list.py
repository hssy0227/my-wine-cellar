# -*- coding: utf-8 -*-
"""관리 패널의 목록 조회 (POST /api/admin-list).

pandas를 import하지 않는다 — 이 경로는 사람이 스크롤할 때마다 불리므로
쓰기 경로(콜드 ~5.8s, pandas import가 지배)와 같은 비용을 물면 안 된다.

브라우저가 Supabase를 직접 읽지 않는 이유: 그러려면 anon 키를 페이지에
심어야 하는데, RLS 정책을 하나도 두지 않는 설계(service_role만 통과)와
맞지 않는다. 비밀번호 게이트 뒤에서 서버가 대신 읽어 넘긴다.
"""
import hmac
import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import supabase_client  # noqa: E402

TYPE_BY_FILE = {"grapes": "grape", "regions": "region", "producers": "producer"}


def handle(payload: dict):
    expected = os.environ.get("EDIT_PASSWORD", "")
    if not expected or not hmac.compare_digest(str(payload.get("password", "")), expected):
        return 401, {"ok": False, "error": "unauthorized"}

    file = payload.get("file", "grapes")
    try:
        sb = supabase_client.Supabase()
        if file in TYPE_BY_FILE:
            rows = sb.select_all("terms", {
                "select": "id,seq,name_en,name_ko,tier,region_group,ko_source,note",
                "type": f"eq.{TYPE_BY_FILE[file]}",
                "deleted_at": "is.null", "order": "seq",
            })
        elif file == "aliases":
            raw = sb.select_all("term_aliases", {
                "select": "id,seq,alias_ko,name_en_raw,note,terms(type)",
                "deleted_at": "is.null", "order": "seq",
            })
            rows = [{"id": a["id"], "seq": a["seq"], "alias_ko": a["alias_ko"],
                      "name_en": a["name_en_raw"], "note": a.get("note") or "",
                      "type": (a.get("terms") or {}).get("type")} for a in raw]
        else:
            return 400, {"ok": False, "error": "validation_failed",
                          "message": f"알 수 없는 파일입니다: {file}"}
        return 200, {"ok": True, "file": file, "rows": rows}
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
        except Exception as e:  # noqa: BLE001
            status, result = 500, {"ok": False, "error": "internal_error", "message": str(e)}

        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
