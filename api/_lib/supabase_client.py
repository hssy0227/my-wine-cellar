# -*- coding: utf-8 -*-
"""Supabase PostgREST + Storage 최소 클라이언트.

supabase-py를 쓰지 않는다. httpx/gotrue/storage3/realtime을 끌고 들어와
함수 번들과 콜드 스타트를 키우는데, 여기서 필요한 건 GET/POST/PATCH/DELETE와
파일 업로드가 전부다. requests는 이미 의존성에 있다.

service_role 키만 쓴다 — RLS를 전 테이블에 켜고 정책을 두지 않았으므로
anon 키로는 아무것도 못 읽는다. 이 키는 절대 브라우저로 가지 않는다.
"""
import json
import os
from typing import Optional

import requests

TIMEOUT = 30
PAGE = 1000


class SupabaseError(Exception):
    pass


class Supabase:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.url or not self.key:
            raise SupabaseError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.")

    # ── 공통 ────────────────────────────────────────────────────────
    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {"apikey": self.key, "authorization": f"Bearer {self.key}"}
        if extra:
            h.update(extra)
        return h

    def _rest(self, method: str, table: str, **kw):
        r = requests.request(method, f"{self.url}/rest/v1/{table}",
                              headers=self._headers(kw.pop("headers", None)),
                              timeout=TIMEOUT, **kw)
        if r.status_code == 503 or "project is paused" in r.text.lower():
            raise SupabaseError(
                "Supabase 프로젝트가 일시정지 상태입니다 — 대시보드에서 Resume 후 다시 시도하세요.")
        if r.status_code >= 300:
            raise SupabaseError(f"{method} {table} 실패 ({r.status_code}): {r.text[:400]}")
        return r.json() if r.text.strip() else None

    # ── 테이블 ──────────────────────────────────────────────────────
    def select_all(self, table: str, params: dict) -> list:
        """행수 상한을 가정하지 않고 전부 읽는다. PostgREST는 기본 상한이 있다."""
        rows, offset = [], 0
        while True:
            page = self._rest("GET", table,
                               params=dict(params, limit=PAGE, offset=offset)) or []
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            offset += PAGE

    def insert(self, table: str, payload) -> list:
        return self._rest("POST", table, json=payload,
                           headers={"content-type": "application/json",
                                    "prefer": "return=representation"}) or []

    def update(self, table: str, row_id: str, payload: dict) -> list:
        return self._rest("PATCH", table, params={"id": f"eq.{row_id}"}, json=payload,
                           headers={"content-type": "application/json",
                                    "prefer": "return=representation"}) or []

    def soft_delete(self, table: str, row_id: str) -> list:
        """물리 삭제하지 않는다 — deleted_at만 채운다.

        되돌리려면 deleted_at을 null로 되돌리면 되고, edit_log와 함께
        "실수로 지웠다"를 복구 가능하게 만든다. 읽기는 전부 deleted_at is null로 건다.
        """
        return self._rest("PATCH", table, params={"id": f"eq.{row_id}"},
                           json={"deleted_at": "now()"},
                           headers={"content-type": "application/json",
                                    "prefer": "return=representation"}) or []

    def revision(self) -> int:
        rows = self._rest("GET", "seed_state", params={"select": "revision", "id": "eq.1"}) or []
        return int(rows[0]["revision"]) if rows else 0

    def latest_artifact(self) -> Optional[dict]:
        rows = self._rest("GET", "artifacts", params={
            "select": "version,seed_revision,audit_summary,built_at",
            "order": "built_at.desc", "limit": 1}) or []
        return rows[0] if rows else None

    # ── 스토리지 ────────────────────────────────────────────────────
    def upload(self, bucket: str, path: str, data: bytes,
               content_type: str = "application/json", cache_control: str = "3600"):
        r = requests.post(
            f"{self.url}/storage/v1/object/{bucket}/{path}",
            headers=self._headers({"content-type": content_type,
                                    "cache-control": cache_control,
                                    "x-upsert": "true"}),
            data=data, timeout=TIMEOUT)
        if r.status_code >= 300:
            raise SupabaseError(f"업로드 실패 {bucket}/{path} ({r.status_code}): {r.text[:300]}")

    def log_edit(self, entry: dict):
        """편집 이력은 실패해도 본 작업을 막지 않는다 — 감사 로그가 사전 편집을 인질로 잡으면 안 된다."""
        try:
            self.insert("edit_log", entry)
        except SupabaseError:
            pass
