#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이관 go/no-go 게이트.

Supabase에서 되읽은 데이터가 현재 git 상태를 **바이트 단위로** 재현하는지 본다.
클라이언트를 바꾸기 전에 돌린다. 하나라도 빨간불이면 이관을 진행하지 않는다.

게이트 1이 가장 강하다 — seed CSV 바이트 비교 하나로 행 순서, 컬럼 순서, BOM,
따옴표 처리, 빈값 표현, 별칭 원문 철자 14건이 전부 커버된다. 이게 통과하면
게이트 2(dist)는 결정론적으로 따라온다.

사용법:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python scripts/verify_parity.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))
from _lib import seed_source  # noqa: E402
import audit as audit_mod  # noqa: E402
import build as build_mod  # noqa: E402

SEED = ROOT / "data" / "seed"
DIST = ROOT / "data" / "dist"


def main():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.")

    failures = []
    terms, aliases = seed_source.SupabaseSource(url, key).fetch()
    print(f"Supabase: terms {len(terms)} / aliases {len(aliases)}\n")

    # ── 게이트 1: seed CSV 바이트 동일 ────────────────────────────────
    print("[게이트 1] Supabase -> seed CSV 바이트 동일")
    csvs = seed_source.rows_to_seed_csvs(terms, aliases)
    for fname, data in sorted(csvs.items()):
        orig = (SEED / fname).read_bytes()
        ok = data == orig
        if not ok:
            failures.append(f"seed/{fname}")
        print(f"  {'OK  ' if ok else 'FAIL'} {fname}")

    # ── 게이트 2: 그 seed로 빌드한 dist가 커밋본과 바이트 동일 ────────
    print("\n[게이트 2] build() 산출물 바이트 동일")
    tmp = Path(tempfile.mkdtemp(prefix="parity-"))
    try:
        for fname, data in csvs.items():
            (tmp / fname).write_bytes(data)
        shutil.copy(SEED / "hierarchy.csv", tmp / "hierarchy.csv")
        df = build_mod.build(seed_dir=tmp, dist_dir=None)

        for fname, blob in (("wine_terms.csv", build_mod.serialize_dist_csv(df)),
                             ("wine_terms.json", build_mod.serialize_dist_json(df))):
            ok = blob == (DIST / fname).read_bytes()
            if not ok:
                failures.append(f"dist/{fname}")
            print(f"  {'OK  ' if ok else 'FAIL'} {fname}")
        print(f"       행수 {len(df)} / 캐노니컬 {df.canonical_id.nunique()}")

        # ── 게이트 3: audit 이슈 집합 동일 ────────────────────────────
        print("\n[게이트 3] audit 이슈 집합 동일")
        new = audit_mod.check(df)
        old = audit_mod.check(str(DIST / "wine_terms.csv"))
        n_new = sum(len(v) for v in new.values())
        n_old = sum(len(v) for v in old.values())
        same = {k: sorted(v) for k, v in new.items()} == {k: sorted(v) for k, v in old.items()}
        if not same:
            failures.append("audit")
        print(f"  {'OK  ' if same else 'FAIL'} 이슈 {n_new}건 (기존 {n_old}건)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        sys.exit(f"❌ 실패: {', '.join(failures)}\n이관을 진행하지 마세요. importer를 고쳐야 합니다.")
    print("✅ 전부 초록 — 이관을 진행해도 됩니다.")


if __name__ == "__main__":
    main()
