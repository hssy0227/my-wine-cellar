# -*- coding: utf-8 -*-
"""seed 행 검증·변경 — Supabase 스냅샷 위에서 동작한다.

CSV 파일이 아니라 seed_source가 읽어온 행 목록(list[dict])을 받는다.
클라이언트가 준 행 인덱스는 절대 신뢰하지 않는다 — 요청이 오가는 사이 다른
편집이 들어왔을 수 있어서, 매 요청마다 DB에서 새로 읽은 스냅샷 위에서 매칭한다.

검증은 두 층이다:
  · 하드 블록(ValidationError) — 요청을 거부한다. 되돌리기 어려운 사고를 막는 것만 넣는다.
  · 경고(warnings) — 막지 않고 응답에 실어 보낸다. 정당한 예외가 존재하는 규칙은 여기로.

파생(canonical_id, key_ko, 대표 표기)은 여기서 하지 않는다. build.py 몫이다.
여기서 계산하는 key_en_norm은 파생이 아니라 **DB 유니크 인덱스를 위한 저장 컬럼**이며,
반드시 build.search_key_en()을 그대로 호출해서 두 구현이 갈리지 않게 한다.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import audit as audit_mod  # noqa: E402
import build as build_mod  # noqa: E402

TYPE_BY_FILE = {"grapes": "grape", "regions": "region", "producers": "producer"}
TERM_FIELDS = ["name_en", "name_ko", "tier", "region_group", "ko_source", "note"]
ALIAS_FIELDS = ["alias_ko", "name_en", "type", "note"]
KO_SOURCES = ("manual", "added", "wikidata", "auto", "alias", "producer")


class ValidationError(Exception):
    """하드 블록 사유. 그대로 사용자에게 보여준다."""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field


class DbOp:
    """수행할 DB 변경 하나. 빌드가 성공한 뒤에야 실제로 실행된다."""

    def __init__(self, table: str, action: str, payload: dict, row_id: Optional[str] = None):
        self.table = table      # terms | term_aliases
        self.action = action    # insert | update | delete
        self.payload = payload
        self.row_id = row_id


def _clean(row: Dict, fields) -> Dict[str, str]:
    return {f: str(row.get(f, "") or "").strip() for f in fields}


def _require_no_hangul(value: str, field: str):
    if audit_mod.HAN.search(value or ""):
        raise ValidationError(f"{field}에 한글이 섞여 있습니다.", field)


def _next_seq(rows: List[dict]) -> int:
    """CSV 끝에 덧붙이는 것과 같은 의미. build()의 canonical_id 부여 순서가
    행 순서에 의존하므로, 기존 행 사이에 끼워넣지 않는다."""
    return max((int(r["seq"]) for r in rows), default=0) + 1


def _find_term(terms: List[dict], type_: str, name_en: str) -> dict:
    key = build_mod.search_key_en(name_en)
    hits = [t for t in terms
            if t["type"] == type_ and build_mod.search_key_en(t["name_en"]) == key]
    if not hits:
        raise ValidationError(
            "수정할 대상을 찾을 수 없습니다 (그 사이 바뀌었을 수 있습니다. 새로고침 후 다시 시도하세요).",
            "match")
    if len(hits) > 1:
        raise ValidationError("수정 대상이 여러 개 일치합니다 — 직접 확인이 필요합니다.", "match")
    return hits[0]


def apply_change(terms: List[dict], aliases: List[dict], file: str, action: str,
                  row: Dict, match: Optional[Dict]) -> Tuple[List[dict], List[dict], DbOp, dict, list]:
    """스냅샷에 변경 하나를 적용한다.

    반환: (새 terms, 새 aliases, 수행할 DbOp, {"before","after"} diff, 경고 목록)
    """
    warnings: List[str] = []
    terms = [dict(t) for t in terms]
    aliases = [dict(a) for a in aliases]

    if file in TYPE_BY_FILE:
        return _apply_term(terms, aliases, TYPE_BY_FILE[file], action, row, match, warnings)
    if file == "aliases":
        return _apply_alias(terms, aliases, action, row, match, warnings)
    raise ValidationError(f"알 수 없는 파일입니다: {file}", "file")


def _apply_term(terms, aliases, type_, action, row, match, warnings):
    if action == "delete":
        if not match:
            raise ValidationError("삭제할 대상을 지정해야 합니다.", "match")
        target = _find_term(terms, type_, str(match.get("name_en", "")))
        # 별칭이 붙어 있으면 막는다. 조용히 함께 지우면 사용자가 인지하지 못한 채
        # 검색 경로가 사라진다 — PR 리뷰가 잡아주던 종류의 사고다.
        attached = [a["alias_ko"] for a in aliases if a.get("target_id") == target.get("id")]
        if attached:
            raise ValidationError(
                f"이 항목에 별칭 {len(attached)}건이 붙어 있어 삭제할 수 없습니다: "
                f"{', '.join(attached[:5])}{' 외' if len(attached) > 5 else ''}. "
                "별칭을 먼저 삭제하세요.", "match")
        terms = [t for t in terms if t is not target]
        op = DbOp("terms", "delete", {}, target.get("id"))
        return terms, aliases, op, {"before": target, "after": None}, warnings

    clean = _clean(row, TERM_FIELDS)
    if not clean["name_en"]:
        raise ValidationError("name_en은 비어 있을 수 없습니다.", "name_en")
    if not clean["name_ko"]:
        raise ValidationError("name_ko는 비어 있을 수 없습니다.", "name_ko")
    _require_no_hangul(clean["name_en"], "name_en")
    # 한글 없는 한글명은 막지 않는다 — '1865'(칠레 브랜드)처럼 정당한 예외가 실재한다
    # (audit.py의 기존 이슈에 포함). 오타 가능성이 높으니 경고만 띄운다.
    if not audit_mod.HAN.search(clean["name_ko"]):
        warnings.append(f"한글명 '{clean['name_ko']}'에 한글이 없습니다. 의도한 표기가 맞는지 확인하세요.")
    if clean["ko_source"] and clean["ko_source"] not in KO_SOURCES:
        raise ValidationError(f"ko_source는 {'/'.join(KO_SOURCES)} 중 하나여야 합니다.", "ko_source")
    clean["ko_source"] = clean["ko_source"] or "manual"
    key = build_mod.search_key_en(clean["name_en"])

    if action == "add":
        if any(t["type"] == type_ and build_mod.search_key_en(t["name_en"]) == key for t in terms):
            raise ValidationError(
                "이미 같은 원어명의 항목이 있습니다. 추가 대신 편집을 사용하세요.", "name_en")
        new = {"seq": _next_seq(terms), "type": type_, "key_en_norm": key, **clean}
        terms.append(new)
        payload = {k: v for k, v in new.items()}
        return terms, aliases, DbOp("terms", "insert", payload), {"before": None, "after": clean}, warnings

    if action == "edit":
        if not match:
            raise ValidationError("편집할 대상을 지정해야 합니다.", "match")
        target = _find_term(terms, type_, str(match.get("name_en", "")))
        # 원어명을 바꾸는 편집이 기존 항목과 충돌하는지 본다.
        if key != build_mod.search_key_en(target["name_en"]):
            if any(t is not target and t["type"] == type_
                    and build_mod.search_key_en(t["name_en"]) == key for t in terms):
                raise ValidationError(
                    "바꾸려는 원어명이 이미 다른 항목에 있습니다.", "name_en")
        before = dict(target)
        target.update(clean)
        target["key_en_norm"] = key
        payload = {**clean, "key_en_norm": key}
        return terms, aliases, DbOp("terms", "update", payload, target.get("id")), \
            {"before": before, "after": clean}, warnings

    raise ValidationError(f"알 수 없는 action입니다: {action}", "action")


def _apply_alias(terms, aliases, action, row, match, warnings):
    def find_alias(m):
        ko = str(m.get("alias_ko", "")).strip()
        en = str(m.get("name_en", "")).strip()
        ty = str(m.get("type", "")).strip()
        hits = [a for a in aliases
                if a["alias_ko"] == ko and a["name_en_raw"] == en and a.get("type") == ty]
        if not hits:
            raise ValidationError(
                "수정할 별칭을 찾을 수 없습니다 (그 사이 바뀌었을 수 있습니다. 새로고침 후 다시 시도하세요).",
                "match")
        if len(hits) > 1:
            raise ValidationError("수정 대상이 여러 개 일치합니다 — 직접 확인이 필요합니다.", "match")
        return hits[0]

    if action == "delete":
        if not match:
            raise ValidationError("삭제할 대상을 지정해야 합니다.", "match")
        target = find_alias(match)
        aliases = [a for a in aliases if a is not target]
        return terms, aliases, DbOp("term_aliases", "delete", {}, target.get("id")), \
            {"before": target, "after": None}, warnings

    clean = _clean(row, ALIAS_FIELDS)
    if not audit_mod.HAN.search(clean["alias_ko"]):
        raise ValidationError("별칭에 한글이 없습니다.", "alias_ko")
    _require_no_hangul(clean["name_en"], "name_en")
    if clean["type"] not in ("grape", "region", "producer"):
        raise ValidationError("type은 grape/region/producer 중 하나여야 합니다.", "type")

    # 대상이 실재하는지 — build.load_aliases()의 고아 판정과 같은 키로 본다.
    key = build_mod.search_key_en(clean["name_en"])
    target_terms = [t for t in terms
                    if t["type"] == clean["type"] and build_mod.search_key_en(t["name_en"]) == key]
    if not target_terms:
        raise ValidationError(
            f"별칭 대상 '{clean['name_en']}'({clean['type']})이 사전에 없습니다. "
            "먼저 원본 항목을 추가하세요.", "name_en")
    target_id = target_terms[0].get("id")

    if action == "add":
        if any(a["alias_ko"] == clean["alias_ko"] and a.get("target_id") == target_id
                for a in aliases):
            raise ValidationError("이미 존재하는 별칭입니다.", "alias_ko")
        new = {"seq": _next_seq(aliases), "alias_ko": clean["alias_ko"],
               "target_id": target_id, "name_en_raw": clean["name_en"],
               "note": clean["note"], "type": clean["type"]}
        aliases.append(new)
        payload = {k: v for k, v in new.items() if k != "type"}  # type은 target이 결정한다
        return terms, aliases, DbOp("term_aliases", "insert", payload), \
            {"before": None, "after": clean}, warnings

    if action == "edit":
        if not match:
            raise ValidationError("편집할 대상을 지정해야 합니다.", "match")
        target = find_alias(match)
        before = dict(target)
        target.update({"alias_ko": clean["alias_ko"], "target_id": target_id,
                        "name_en_raw": clean["name_en"], "note": clean["note"],
                        "type": clean["type"]})
        payload = {"alias_ko": clean["alias_ko"], "target_id": target_id,
                   "name_en_raw": clean["name_en"], "note": clean["note"]}
        return terms, aliases, DbOp("term_aliases", "update", payload, target.get("id")), \
            {"before": before, "after": clean}, warnings

    raise ValidationError(f"알 수 없는 action입니다: {action}", "action")
