# -*- coding: utf-8 -*-
"""빌드 결과를 Storage에 발행한다.

사전 payload는 **내용주소(content-addressed) 불변 객체**다. 파일명에 내용 해시가
들어가므로 같은 URL이 다른 내용을 가리키는 일이 없고, 그래서 Service Worker가
조건부 요청 없이 cache-first로 쓸 수 있다 — 이게 진짜 오프라인의 핵심이다.
빌드 결과가 이전과 같으면 버전도 같아서 클라이언트가 헛되이 다시 받지 않는다.

업로드 순서가 중요하다: payload 먼저, manifest 마지막.
반대로 하면 manifest가 아직 없는 객체를 가리키는 순간이 생긴다.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import build as build_mod  # noqa: E402

BUCKET = "dict"
IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


def publish(sb, df) -> dict:
    """df(빌드 결과)를 Storage에 올리고 manifest를 갱신한다. 반환: manifest dict."""
    payload = build_mod.serialize_dist_json(df)
    csv_bytes = build_mod.serialize_dist_csv(df)
    version = hashlib.sha256(payload).hexdigest()[:12]

    json_path = f"wine_terms.{version}.json"
    sb.upload(BUCKET, json_path, payload, "application/json", IMMUTABLE)
    sb.upload(BUCKET, f"wine_terms.{version}.csv", csv_bytes, "text/csv", IMMUTABLE)

    manifest = {
        "version": version,
        "path": json_path,
        "rows": int(len(df)),
        "canonical": int(df.canonical_id.nunique()),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    # manifest는 항상 마지막. 그리고 캐시하지 않는다 — 이것만이 버전 변화를 알리는 통로다.
    sb.upload(BUCKET, "manifest.json",
              json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
              "application/json", NO_CACHE)
    return manifest


def record_artifact(sb, manifest: dict, seed_revision: int, audit_issues: dict):
    """발행 기록. audit_issues는 다음 편집의 비교 기준선이 되므로 전체를 넣는다."""
    sb.insert("artifacts", {
        "version": manifest["version"],
        "storage_path": manifest["path"],
        "row_count": manifest["rows"],
        "canonical_count": manifest["canonical"],
        "seed_revision": seed_revision,
        "audit_summary": audit_issues,
    })
