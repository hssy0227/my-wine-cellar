# -*- coding: utf-8 -*-
"""seed 데이터 공급원 추상화 — CSV(git) 또는 Supabase.

핵심 불변식: 어느 공급원에서 오든 build()에 들어가는 프레임과, 다시 CSV로
내보낸 바이트가 **동일**해야 한다. 그래야 이관 검증을 "바이트 동일"이라는
가장 강한 기준으로 걸 수 있고, git export가 낡았는지도 diff로 즉시 드러난다.

CSV 형식 세부는 실측으로 확정했다(BOM=utf-8-sig, 줄바꿈=LF, 따옴표 없음):
pandas to_csv(index=False, encoding='utf-8-sig', lineterminator='\\n')가
현재 커밋된 4개 파일과 바이트 동일하다.
"""
import io
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import build as build_mod  # noqa: E402

TERM_COLUMNS = ["name_en", "name_ko", "tier", "region_group", "ko_source", "note"]
ALIAS_COLUMNS = ["alias_ko", "name_en", "type", "note"]
TYPE_FILE = build_mod.TYPE_FILE  # {"grape": "grapes.csv", ...} — 순서가 seq 순서다


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig", lineterminator="\n")
    return buf.getvalue()


def rows_to_seed_csvs(term_rows, alias_rows) -> dict:
    """DB 행 -> {파일명: CSV 바이트}. git export와 패리티 검증이 공유한다."""
    out = {}
    terms = sorted(term_rows, key=lambda r: r["seq"])
    for t, fname in TYPE_FILE.items():
        sub = [{c: (r.get(c) or "") for c in TERM_COLUMNS}
               for r in terms if r["type"] == t]
        out[fname] = _to_csv_bytes(pd.DataFrame(sub, columns=TERM_COLUMNS))

    aliases = sorted(alias_rows, key=lambda r: r["seq"])
    sub = [{
        "alias_ko": r["alias_ko"],
        # CSV 원문 철자를 되살린다. target의 철자를 쓰면 14건이 달라져 diff가 난다.
        "name_en": r["name_en_raw"],
        "type": r["type"],
        "note": r.get("note") or "",
    } for r in aliases]
    out["aliases.csv"] = _to_csv_bytes(pd.DataFrame(sub, columns=ALIAS_COLUMNS))
    return out


def write_seed_dir(term_rows, alias_rows, seed_dir: Path):
    """seed_dir에 4개 CSV를 쓴다.

    hierarchy.csv는 건드리지 않는다 — Supabase 스코프 밖이고, build()가 같은
    디렉터리에서 그대로 통과시켜 wine_hierarchy.csv를 만들기 때문에 그대로 둬야 한다.
    """
    for fname, data in rows_to_seed_csvs(term_rows, alias_rows).items():
        (seed_dir / fname).write_bytes(data)


class CsvSource:
    """git의 seed CSV를 SupabaseSource.fetch()와 **같은 모양**으로 읽는다.

    존재 이유는 패리티 테스트다. 두 공급원이 같은 행 구조를 내놓아야
    rows_to_seed_csvs()가 어느 쪽에서 왔든 같은 바이트를 만든다는 걸
    DB 없이 CI에서 검증할 수 있다.
    """

    def __init__(self, seed_dir: Path):
        self.seed_dir = Path(seed_dir)

    def fetch(self):
        terms, seq = [], 0
        for t, fname in TYPE_FILE.items():
            df = pd.read_csv(self.seed_dir / fname, dtype=str, keep_default_na=False)
            for _, r in df.iterrows():
                en, ko = str(r["name_en"]).strip(), str(r["name_ko"]).strip()
                if not en or not ko:
                    continue
                seq += 1
                terms.append({
                    "seq": seq, "type": t, "name_en": en, "name_ko": ko,
                    "key_en_norm": build_mod.search_key_en(en),
                    "tier": str(r.get("tier", "")).strip(),
                    "region_group": str(r.get("region_group", "")).strip(),
                    "ko_source": str(r.get("ko_source", "")).strip() or "manual",
                    "note": str(r.get("note", "")).strip(),
                })

        known = {(t["type"], t["key_en_norm"]) for t in terms}
        adf = pd.read_csv(self.seed_dir / "aliases.csv", dtype=str, keep_default_na=False)
        aliases, aseq = [], 0
        for _, r in adf.iterrows():
            ko, raw = str(r["alias_ko"]).strip(), str(r["name_en"]).strip()
            ty = str(r["type"]).strip()
            if not ko or not raw:
                continue
            if (ty, build_mod.search_key_en(raw)) not in known:
                continue  # 고아 별칭 — load_aliases와 같은 판정
            aseq += 1
            aliases.append({
                "seq": aseq, "alias_ko": ko, "name_en_raw": raw, "type": ty,
                "note": str(r.get("note", "")).strip(),
            })
        return terms, aliases


class SupabaseSource:
    """PostgREST로 seed 전체를 읽는다. 행수 상한을 가정하지 않고 페이지네이션한다."""

    PAGE = 1000

    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def _get(self, path: str, params: dict) -> list:
        import requests
        rows, offset = [], 0
        while True:
            p = dict(params, limit=self.PAGE, offset=offset)
            r = requests.get(f"{self.url}/rest/v1/{path}", params=p, timeout=30,
                              headers={"apikey": self.key,
                                       "authorization": f"Bearer {self.key}"})
            if r.status_code >= 300:
                raise RuntimeError(f"PostgREST {path} 실패 ({r.status_code}): {r.text[:300]}")
            page = r.json()
            rows.extend(page)
            if len(page) < self.PAGE:
                return rows
            offset += self.PAGE

    def fetch(self):
        terms = self._get("terms", {
            "select": "id,seq,type,name_en,name_ko,key_en_norm,tier,region_group,ko_source,note",
            "deleted_at": "is.null", "order": "seq",
        })
        raw = self._get("term_aliases", {
            "select": "id,seq,alias_ko,target_id,name_en_raw,note,terms(type)",
            "deleted_at": "is.null", "order": "seq",
        })
        # 별칭의 type은 target이 결정한다 — 별칭 자체는 type을 저장하지 않는다.
        aliases = [{
            "id": a["id"], "seq": a["seq"], "alias_ko": a["alias_ko"],
            "target_id": a["target_id"], "name_en_raw": a["name_en_raw"],
            "note": a.get("note") or "",
            "type": (a.get("terms") or {}).get("type"),
        } for a in raw]
        return terms, aliases
