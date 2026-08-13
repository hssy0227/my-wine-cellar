#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed CSV -> data/dist/ 전체 재생성.

멱등하다. 몇 번을 돌려도 같은 결과가 나온다.
(이전 구조는 스크립트 9개를 정확한 순서로 돌려야만 올바른 결과가 나왔다.
 docs/MIGRATION.md 참조)
"""
import json
import re
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "matcher"))
from jamo_matcher import to_jamo  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
DIST = ROOT / "data" / "dist"

TYPE_FILE = {"grape": "grapes.csv", "region": "regions.csv",
             "producer": "producers.csv"}

# 생산자 이름 선두의 일반명사. 사람들이 자주 생략하므로 축약형을 자동 생성한다.
# 근거: docs/DECISIONS.md D11
KO_PREFIXES = {"샤토", "샤또", "도멘", "메종", "비냐", "비녜도", "테누타",
               "보데가스", "포데레", "아지엔다", "칸티나", "클로"}
EN_PREFIX_RE = re.compile(
    r"^(chateau|ch\.|domaine|dom\.|tenuta|bodegas?|vina|vinedo|weingut|"
    r"maison|casa|castello|quinta|marchesi|marques\s+de)\s+", re.I)

TIER_RE = re.compile(
    r"\b(DOCG|DOCa|DOC|DOP|IGT|IGP|AOC|AOP|AVA|PGI|PDO|IPR|VR|RDD|VDP|DO)\b",
    re.I)


def search_key_en(s: str) -> str:
    """로마자 검색 키.

    아포스트로피·하이픈은 단어를 가르는 게 아니라 이어붙이는 문장부호다
    (d'Abruzzo, Pontet-Canet). 공백으로 바꾸면 토큰이 갈라져 매칭이 깨진다.
    이 규칙은 src/matcher/matcher.js 의 normEn 과 반드시 일치해야 한다.
    """
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"['\u2019-]", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).lower().strip()
    return re.sub(r"\s+", " ", s)


def load_seed() -> pd.DataFrame:
    rows = []
    for t, fname in TYPE_FILE.items():
        p = SEED / fname
        if not p.exists():
            sys.exit(f"seed 파일이 없습니다: {p}")
        df = pd.read_csv(p).fillna("")
        for _, r in df.iterrows():
            en = str(r.get("name_en", "")).strip()
            ko = str(r.get("name_ko", "")).strip()
            if not en or not ko:
                continue
            rows.append({
                "type": t, "name_ko": ko, "name_en": en,
                "tier": str(r.get("tier", "")).strip(),
                "region_group": str(r.get("region_group", "")).strip(),
                "ko_source": str(r.get("ko_source", "")).strip() or "manual",
                "is_alias": 0,
            })
    return pd.DataFrame(rows)


def load_aliases(entries: pd.DataFrame) -> pd.DataFrame:
    p = SEED / "aliases.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p).fillna("")
    # 대상 항목이 실제로 존재하는지 확인 — 오타로 인한 고아 별칭을 막는다.
    # 발음기호는 무시하고 대조한다. Albarino/Albariño, Carmenere/Carménère 처럼
    # 같은 이름이 악센트 유무로 갈리는 경우가 흔한데, 엄격 비교하면 멀쩡한
    # 별칭이 고아로 잘려나간다.
    known = {}
    for _, r in entries.iterrows():
        known[(r.type, search_key_en(r.name_en))] = r.name_en
    rows, orphans = [], []
    for _, r in df.iterrows():
        t = str(r.get("type", "")).strip()
        raw_en = str(r.get("name_en", "")).strip()
        ko = str(r.get("alias_ko", "")).strip()
        if not ko or not raw_en:
            continue
        target = known.get((t, search_key_en(raw_en)))
        if target is None:
            orphans.append(f"{ko} -> {raw_en} [{t}]")
            continue
        rows.append({"type": t, "name_ko": ko, "name_en": target,
                     "tier": "", "region_group": "", "ko_source": "alias",
                     "is_alias": 1})
    if orphans:
        print(f"[!] 대상을 찾을 수 없는 별칭 {len(orphans)}건 (건너뜀):")
        for o in orphans[:10]:
            print(f"      {o}")
    return pd.DataFrame(rows)


def add_stripped(df: pd.DataFrame) -> pd.DataFrame:
    """생산자 접두어 제거 축약형을 자동 생성한다.

    '샤토 디켐'만 있으면 '디켐'이 자모 길이 차 때문에 fuzzy 가지치기에 걸려
    아예 비교되지 않는다. 근거: docs/DECISIONS.md D11
    """
    out = []
    for _, r in df[df.type == "producer"].iterrows():
        toks = r.name_ko.split(" ", 1)
        if len(toks) == 2 and toks[0] in KO_PREFIXES and len(toks[1]) >= 2:
            out.append({**r.to_dict(), "name_ko": toks[1],
                        "ko_source": "stripped", "is_alias": 1})
    if not out:
        return df
    return pd.concat([df, pd.DataFrame(out)], ignore_index=True)


def build():
    entries = load_seed()
    aliases = load_aliases(entries)
    df = pd.concat([entries, aliases], ignore_index=True) if len(aliases) else entries
    df = add_stripped(df)

    # 캐노니컬 부여: (type, 정규화된 원어명)이 같으면 같은 개념
    canon, nid = OrderedDict(), 0
    ids = []
    for _, r in df.iterrows():
        ken = search_key_en(r.name_en).replace(" ", "")
        if not ken:
            ken = "ko:" + to_jamo(r.name_ko)
        key = (r.type, ken)
        if key not in canon:
            nid += 1
            canon[key] = f"{r.type[:3]}{nid:05d}"
        ids.append(canon[key])
    df["canonical_id"] = ids

    # 대표 표기 선정: 별칭이 아닌 것 우선, 그중 짧은 한글명
    prio = {"manual": 0, "producer": 0, "added": 1, "wikidata": 2,
            "auto": 3, "alias": 4, "stripped": 5}
    df["_p"] = df["ko_source"].map(prio).fillna(3)
    df["_len"] = df["name_ko"].str.len()
    df = df.sort_values(["canonical_id", "is_alias", "_p", "_len"])
    primary = df.groupby("canonical_id")["name_ko"].first()
    df["name_ko_primary"] = df["canonical_id"].map(primary)
    df["is_alias"] = (df["name_ko"] != df["name_ko_primary"]).astype(int)

    # 표시명과 검색 키
    df["name_display"] = df["name_en"].map(
        lambda s: re.sub(r"\s+", " ", TIER_RE.sub(" ", str(s))).strip())
    df["key_ko"] = df["name_ko"].map(to_jamo)
    df["key_en"] = df["name_en"].map(
        lambda s: search_key_en(EN_PREFIX_RE.sub("", str(s)).strip() or str(s)))
    df["key_len"] = df["key_ko"].str.len()
    df["wikidata"] = ""

    df = df.drop_duplicates(subset=["canonical_id", "name_ko"])
    df = df[df.key_ko != ""]

    cols = ["canonical_id", "type", "name_ko", "name_ko_primary", "is_alias",
            "name_en", "name_display", "tier", "key_ko", "key_en", "key_len",
            "region_group", "ko_source", "wikidata"]
    df = df[cols].sort_values(["type", "name_ko_primary", "is_alias"])

    DIST.mkdir(parents=True, exist_ok=True)
    df.to_csv(DIST / "wine_terms.csv", index=False, encoding="utf-8-sig")

    recs = [{"i": r.canonical_id, "t": r.type[0], "ko": r.name_ko,
             "p": r.name_ko_primary, "en": r.name_en, "d": r.name_display,
             "tr": r.tier, "k": r.key_ko, "ke": r.key_en}
            for r in df.itertuples()]
    with open(DIST / "wine_terms.json", "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))

    # 계층 데이터는 가공 없이 통과시킨다
    hp = SEED / "hierarchy.csv"
    if hp.exists():
        pd.read_csv(hp).to_csv(DIST / "wine_hierarchy.csv", index=False,
                               encoding="utf-8-sig")

    print(f"빌드 완료: {len(df)}행 / 캐노니컬 {df.canonical_id.nunique()}개")
    print(df.groupby("type").agg(
        행=("name_ko", "size"), 대표=("canonical_id", "nunique")).to_string())
    return df


if __name__ == "__main__":
    build()
