# -*- coding: utf-8 -*-
"""사전 manifest 조회 (GET /api/dict-manifest) — 인증 불필요.

페이지가 사전을 찾아가는 유일한 진입점이다. Supabase Storage의 공개 URL은
프로젝트 ref를 포함하는데, vercel.json의 rewrite는 환경변수 치환을 지원하지
않아 git에 하드코딩할 수 없다. 그래서 환경변수에서 읽어 절대 URL을 돌려준다.

payload(556KB) 자체는 프록시하지 않는다 — 브라우저가 Supabase Storage에서
직접 받아야 CDN 이점을 얻고 함수 호출 비용도 안 든다. 버킷이 public이라
CORS 헤더가 붙어 있어 Service Worker가 정상 캐싱할 수 있다.

이 응답 자체는 캐시하지 않는다. 새 버전을 알리는 통로가 이것뿐이기 때문이다.
"""
import json
import os
from http.server import BaseHTTPRequestHandler

import requests

BUCKET = "dict"


def handle():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return 503, {"ok": False, "error": "not_configured",
                      "message": "SUPABASE_URL이 설정되지 않았습니다."}
    base = f"{url}/storage/v1/object/public/{BUCKET}"
    try:
        r = requests.get(f"{base}/manifest.json", timeout=10)
        if r.status_code >= 300:
            return 502, {"ok": False, "error": "manifest_unavailable",
                          "message": f"manifest를 읽을 수 없습니다 ({r.status_code})."}
        m = r.json()
    except Exception as e:  # noqa: BLE001 — 페이지는 git 폴백으로 넘어가면 된다
        return 502, {"ok": False, "error": "manifest_unavailable", "message": str(e)}

    m["url"] = f"{base}/{m['path']}"
    return 200, {"ok": True, **m}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, result = handle()
        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
