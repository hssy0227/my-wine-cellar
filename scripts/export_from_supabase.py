#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supabase -> data/seed/*.csv 내보내기.

GitHub Action이 이걸 돌린 뒤 build.py를 실행해 dist까지 재생성하고 커밋한다.
git은 폐기된 게 아니라 강등된 것이다 — 회귀 테스트의 골든 데이터이자,
Supabase가 정지·삭제돼도 사전을 복구할 수 있는 완전한 사본으로 남는다.

hierarchy.csv는 건드리지 않는다(Supabase 스코프 밖).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from _lib import seed_source  # noqa: E402

SEED = ROOT / "data" / "seed"


def main():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.")

    terms, aliases = seed_source.SupabaseSource(url, key).fetch()
    if not terms:
        sys.exit("terms가 비어 있습니다 — 빈 seed를 커밋해 데이터를 날리지 않도록 중단합니다.")

    seed_source.write_seed_dir(terms, aliases, SEED)
    print(f"export 완료: terms {len(terms)} / aliases {len(aliases)} -> {SEED}")


if __name__ == "__main__":
    main()
