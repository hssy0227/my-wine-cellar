# -*- coding: utf-8 -*-
"""build()를 임의의 seed 디렉터리에 대해 돌려서 파일을 쓰지 않고 결과만 얻는다.

admin-submit.py가 실제 data/seed/를 임시 작업 디렉터리에 복사한 뒤 변경사항을
그 위에 적용하고, 이 모듈로 수정 전/후 두 번 빌드해서 비교한다.
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import build as build_mod  # noqa: E402


def build_dir(seed_dir: Path) -> pd.DataFrame:
    """seed_dir의 seed CSV들로 build()를 돌린 결과. 파일은 쓰지 않는다(dist_dir=None)."""
    return build_mod.build(seed_dir=seed_dir, dist_dir=None)


def serialize_csv(df: pd.DataFrame) -> bytes:
    return build_mod.serialize_dist_csv(df)


def serialize_json(df: pd.DataFrame) -> bytes:
    return build_mod.serialize_dist_json(df)
