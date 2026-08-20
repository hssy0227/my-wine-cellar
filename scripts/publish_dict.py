#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supabase의 현재 seed로 사전을 빌드해 Storage에 발행한다.

두 곳에서 쓴다:
  · 이관 직후 — 최초 발행. 이걸 안 하면 Storage에 manifest.json이 없어서
    페이지가 사전을 찾지 못한다(이관만으로는 시스템이 동작하지 않는다).
  · 복구 — 아티팩트가 꼬였을 때 현재 DB 상태로 다시 찍어낸다.

멱등하다. 내용이 같으면 같은 버전 해시가 나오므로 클라이언트도 다시 받지 않는다.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))
from _lib import audit_adapter, publish, seed_source, supabase_client  # noqa: E402
import build as build_mod  # noqa: E402


def main():
    sb = supabase_client.Supabase()
    terms, aliases = seed_source.SupabaseSource(client=sb).fetch()
    if not terms:
        sys.exit("terms가 비어 있습니다 — 빈 사전을 발행하지 않도록 중단합니다.")

    tmp = Path(tempfile.mkdtemp(prefix="publish-"))
    try:
        for fname, data in seed_source.rows_to_seed_csvs(terms, aliases).items():
            (tmp / fname).write_bytes(data)
        df = build_mod.build(seed_dir=tmp, dist_dir=None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    manifest = publish.publish(sb, df)
    publish.record_artifact(sb, manifest, sb.revision(), audit_adapter.all_issues(df))
    print(f"발행 완료: v{manifest['version']} / {manifest['rows']}행 / "
          f"캐노니컬 {manifest['canonical']}")
    print(f"  경로: {manifest['path']}")


if __name__ == "__main__":
    main()
