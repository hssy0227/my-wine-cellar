# -*- coding: utf-8 -*-
"""seed CSV 행 매칭·검증·직렬화.

편집 요청은 항상 name_en(별칭은 alias_ko+name_en+type 복합키)으로 매칭한다.
클라이언트가 준 행 인덱스는 신뢰하지 않는다 — 요청이 오가는 사이 다른 PR이
머지돼 파일이 바뀌었을 수 있어서, 매 요청마다 파일을 새로 읽는다.
"""
import io
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import build as build_mod  # noqa: E402
import audit as audit_mod  # noqa: E402

MAIN_FILES = {"grapes": "grape", "regions": "region", "producers": "producer"}
MAIN_COLUMNS = ["name_en", "name_ko", "tier", "region_group", "ko_source", "note"]
ALIAS_COLUMNS = ["alias_ko", "name_en", "type", "note"]


class ValidationError(Exception):
    """하드 블록 사유. PR을 만들지 않고 그대로 사용자에게 보여준다."""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field


def _read_csv(path: Path, columns) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    # dtype=str가 없으면 pandas가 "1865" 같은 name_en을 정수로 추론해버린다.
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    return df[columns]


def _write_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")  # 기존 seed 파일과 같은 BOM 유지
    return buf.getvalue()


def _require_hangul(value: str, field: str):
    if not audit_mod.HAN.search(value or ""):
        raise ValidationError(f"{field}에 한글이 없습니다.", field)


def _require_no_hangul(value: str, field: str):
    if audit_mod.HAN.search(value or ""):
        raise ValidationError(f"{field}에 한글이 섞여 있습니다.", field)


def _existing_type_keys(seed_dir: Path) -> set:
    """(type, search_key_en(name_en)) 집합.

    별칭 추가 시 대상이 실제로 존재하는지 확인하는 데 쓴다 —
    build.load_aliases()의 고아 별칭 판정과 동일한 키로 비교해야
    빌드 시점 판정과 어긋나지 않는다.
    """
    entries = build_mod.load_seed(seed_dir)
    return {(r.type, build_mod.search_key_en(r.name_en)) for r in entries.itertuples()}


def apply_change(seed_dir: Path, file: str, action: str, row: Dict[str, str],
                  match: Optional[Dict[str, str]]) -> Tuple[Path, bytes, dict]:
    """seed CSV 한 파일에 add/edit를 적용한다.

    반환: (수정 대상 seed 파일 경로, 새 CSV 바이트, {"before":.., "after":..} diff).
    실패하면 ValidationError를 던진다 (호출자가 하드 블록으로 처리).
    """
    if file in MAIN_FILES:
        path = seed_dir / f"{file}.csv"
        columns = MAIN_COLUMNS
    elif file == "aliases":
        path = seed_dir / "aliases.csv"
        columns = ALIAS_COLUMNS
    else:
        raise ValidationError(f"알 수 없는 파일입니다: {file}", "file")

    df = _read_csv(path, columns)
    row = {c: str(row.get(c, "") or "").strip() for c in columns}

    if file == "aliases":
        _require_hangul(row["alias_ko"], "alias_ko")
        _require_no_hangul(row["name_en"], "name_en")
        if row["type"] not in ("grape", "region", "producer"):
            raise ValidationError("type은 grape/region/producer 중 하나여야 합니다.", "type")
        target_key = (row["type"], build_mod.search_key_en(row["name_en"]))
        if target_key not in _existing_type_keys(seed_dir):
            raise ValidationError(
                f"별칭 대상 '{row['name_en']}'({row['type']})이 사전에 없습니다. "
                "먼저 원본 항목을 추가하세요.", "name_en")
    else:
        _require_hangul(row["name_ko"], "name_ko")
        _require_no_hangul(row["name_en"], "name_en")
        if not row["name_en"]:
            raise ValidationError("name_en은 비어 있을 수 없습니다.", "name_en")

    if action == "add":
        if file == "aliases":
            dup = df[(df.alias_ko == row["alias_ko"]) & (df.name_en == row["name_en"])
                     & (df.type == row["type"])]
            if len(dup):
                raise ValidationError("이미 존재하는 별칭입니다.", "alias_ko")
        else:
            new_key = build_mod.search_key_en(row["name_en"])
            existing_keys = {build_mod.search_key_en(v) for v in df["name_en"]}
            if new_key in existing_keys:
                raise ValidationError(
                    "이미 같은 원어명의 항목이 있습니다. 추가 대신 편집을 사용하세요.",
                    "name_en")
        new_df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        before = None

    elif action == "edit":
        if not match:
            raise ValidationError("편집할 대상을 지정해야 합니다.", "match")
        if file == "aliases":
            mask = ((df.alias_ko == str(match.get("alias_ko", "")).strip())
                     & (df.name_en == str(match.get("name_en", "")).strip())
                     & (df.type == str(match.get("type", "")).strip()))
        else:
            mask = df.name_en == str(match.get("name_en", "")).strip()
        hits = df[mask]
        if len(hits) == 0:
            raise ValidationError(
                "수정할 대상을 찾을 수 없습니다 (그 사이 바뀌었을 수 있습니다. 새로고침 후 다시 시도하세요).",
                "match")
        if len(hits) > 1:
            raise ValidationError("수정 대상이 여러 개 일치합니다 — 직접 확인이 필요합니다.", "match")
        before = hits.iloc[0].to_dict()
        new_df = df.copy()
        new_df.loc[hits.index[0]] = row

    else:
        raise ValidationError(f"알 수 없는 action입니다: {action}", "action")

    diff = {"before": before, "after": row}
    return path, _write_csv_bytes(new_df), diff
