# -*- coding: utf-8 -*-
"""커밋된 dist가 커밋된 seed로부터 재현되는지 검증한다.

Supabase 이관 이후 이 테스트의 역할이 커졌다. 사전의 원천은 Supabase지만
회귀 테스트(test_sync.py, matcher.test.js)의 골든 데이터는 여전히 git의
data/dist/다. export가 조용히 실패하면 CI는 낡은 데이터로 통과하는데
실제 서비스는 최신 데이터를 쓰는 괴리가 생긴다 — 그 상태를 여기서 잡는다.

잡아내는 것:
  · 손으로 편집한 dist (CLAUDE.md 규칙 3 위반)
  · export가 멈춰 낡아버린 dist
  · build.py 변경으로 산출물이 달라졌는데 dist를 재생성하지 않은 커밋
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

import build as build_mod  # noqa: E402
from _lib import seed_source  # noqa: E402

SEED = ROOT / "data" / "seed"
DIST = ROOT / "data" / "dist"


@pytest.fixture(scope="module")
def built():
    return build_mod.build(seed_dir=SEED, dist_dir=None)


def test_dist_csv가_seed로부터_재현된다(built):
    assert build_mod.serialize_dist_csv(built) == (DIST / "wine_terms.csv").read_bytes(), (
        "data/dist/wine_terms.csv가 seed와 어긋납니다. "
        "`python scripts/build.py`로 재생성하세요."
    )


def test_dist_json이_seed로부터_재현된다(built):
    assert build_mod.serialize_dist_json(built) == (DIST / "wine_terms.json").read_bytes(), (
        "data/dist/wine_terms.json이 seed와 어긋납니다. "
        "`python scripts/build.py`로 재생성하세요."
    )


def test_export_직렬화가_커밋된_seed와_바이트_동일하다():
    """CsvSource -> rows_to_seed_csvs 왕복이 원본 바이트를 그대로 낸다.

    이 경로는 Supabase export가 쓰는 것과 **같은 직렬화 코드**다.
    여기가 깨지면 export 커밋에 의미 없는 diff가 쏟아진다(BOM/줄바꿈/따옴표/컬럼순서).
    """
    terms, aliases = seed_source.CsvSource(SEED).fetch()
    for fname, data in seed_source.rows_to_seed_csvs(terms, aliases).items():
        assert data == (SEED / fname).read_bytes(), f"{fname} 직렬화가 원본과 다릅니다"


def test_key_en_norm에_타입내_중복이_없다():
    """(type, key_en_norm) 유니크 — DB 인덱스와 같은 불변식.

    대시보드에서 손으로 넣은 행이 key_en_norm을 틀리게 채우면 유니크 인덱스는
    통과하지만 별칭 해석이 조용히 달라진다. export된 seed에서 재계산해 대조한다.
    """
    terms, _ = seed_source.CsvSource(SEED).fetch()
    seen = {}
    dups = []
    for t in terms:
        k = (t["type"], t["key_en_norm"])
        if k in seen:
            dups.append(f"{k}: {seen[k]} vs {t['name_en']}")
        seen[k] = t["name_en"]
    assert not dups, "(type, key_en_norm) 중복:\n  " + "\n  ".join(dups[:10])
