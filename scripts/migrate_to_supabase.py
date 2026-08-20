#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed CSV -> Supabase 최초 이관 (1회성).

행 순서가 생명이다. build()의 canonical_id 부여가 seed 행 순서에 의존하므로,
여기서 넣는 seq가 CSV 순서와 어긋나면 2,328개 캐노니컬이 전부 재번호되어
dist가 통째로 바뀐다. load_seed()와 **같은 순서·같은 건너뛰기 규칙**으로 읽는다.

사용법:
    python scripts/migrate_to_supabase.py --dry-run          # 검사만
    python scripts/migrate_to_supabase.py --emit-sql out.sql # SQL 파일 생성
    python scripts/migrate_to_supabase.py                    # PostgREST로 직접 삽입
                                                             # (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 필요)
"""
import argparse
import os
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build as build_mod  # noqa: E402

SEED = ROOT / "data" / "seed"
MAIN_COLUMNS = ["name_en", "name_ko", "tier", "region_group", "ko_source", "note"]


def read_terms():
    """load_seed()와 동일한 순서·건너뛰기 규칙으로 읽되, note까지 보존한다.

    load_seed()는 note를 버리므로 그대로 쓸 수 없다. 대신 순회 순서
    (build.TYPE_FILE의 삽입 순서: grape -> region -> producer)와
    "name_en이나 name_ko가 비면 건너뜀" 규칙을 그대로 복제한다.
    """
    rows, seq = [], 0
    for t, fname in build_mod.TYPE_FILE.items():
        df = pd.read_csv(SEED / fname, dtype=str, keep_default_na=False)
        for _, r in df.iterrows():
            en = str(r.get("name_en", "")).strip()
            ko = str(r.get("name_ko", "")).strip()
            if not en or not ko:
                continue
            seq += 1
            rows.append({
                "id": str(uuid.uuid4()),
                "seq": seq,
                "type": t,
                "name_en": en,
                "name_ko": ko,
                "key_en_norm": build_mod.search_key_en(en),
                "tier": str(r.get("tier", "")).strip(),
                "region_group": str(r.get("region_group", "")).strip(),
                "ko_source": str(r.get("ko_source", "")).strip() or "manual",
                "note": str(r.get("note", "")).strip(),
            })
    return rows


def read_aliases(terms):
    """별칭을 target_id로 해석한다.

    대조 키는 load_aliases()와 같은 (type, search_key_en(name_en))이다.
    발음기호 유무로 갈리는 표기(Albarino / Albariño)를 흡수하기 위한 것이고,
    CSV 원문 철자는 name_en_raw에 따로 보존해 export가 바이트 동일이 되게 한다.
    """
    known = {(t["type"], t["key_en_norm"]): t["id"] for t in terms}
    df = pd.read_csv(SEED / "aliases.csv", dtype=str, keep_default_na=False)
    rows, orphans, seq = [], [], 0
    for _, r in df.iterrows():
        t = str(r.get("type", "")).strip()
        raw_en = str(r.get("name_en", "")).strip()
        ko = str(r.get("alias_ko", "")).strip()
        if not ko or not raw_en:
            continue
        target = known.get((t, build_mod.search_key_en(raw_en)))
        if target is None:
            orphans.append(f"{ko} -> {raw_en} [{t}]")
            continue
        seq += 1
        rows.append({
            "id": str(uuid.uuid4()),
            "seq": seq,
            "alias_ko": ko,
            "target_id": target,
            "name_en_raw": raw_en,
            "note": str(r.get("note", "")).strip(),
        })
    return rows, orphans


def check(terms, aliases, orphans):
    """스키마 제약을 미리 검사한다. DB가 거부할 것을 여기서 먼저 잡는다."""
    problems = []
    if orphans:
        problems.append(f"고아 별칭 {len(orphans)}건: {orphans[:5]}")

    seen = {}
    for t in terms:
        k = (t["type"], t["key_en_norm"])
        if k in seen:
            problems.append(f"(type,key_en_norm) 중복: {k} — {seen[k]} vs {t['name_en']}")
        seen[k] = t["name_en"]

    import re
    for t in terms:
        if not re.fullmatch(r"[a-z0-9 ]*", t["key_en_norm"]):
            problems.append(f"key_en_norm 모양 위반: {t['name_en']} -> {t['key_en_norm']}")
        if re.search(r"[가-힣]", t["name_en"]):
            problems.append(f"name_en에 한글: {t['name_en']}")
        if t["ko_source"] not in ("manual", "added", "wikidata", "auto", "alias", "producer"):
            problems.append(f"ko_source 미지원 값: {t['ko_source']} ({t['name_en']})")

    pairs = set()
    for a in aliases:
        k = (a["alias_ko"], a["target_id"])
        if k in pairs:
            problems.append(f"별칭 중복: {a['alias_ko']} -> {a['name_en_raw']}")
        pairs.add(k)
    return problems


def q(v):
    """SQL 문자열 리터럴. 작은따옴표만 이스케이프하면 충분하다(E'' 미사용)."""
    return "'" + str(v).replace("'", "''") + "'"


def emit_sql(terms, aliases, path: Path):
    parts = ["begin;"]
    for t in terms:
        parts.append(
            "insert into terms (id,seq,type,name_en,name_ko,key_en_norm,tier,region_group,ko_source,note) values ("
            f"{q(t['id'])}::uuid,{t['seq']},{q(t['type'])}::term_type,{q(t['name_en'])},{q(t['name_ko'])},"
            f"{q(t['key_en_norm'])},{q(t['tier'])},{q(t['region_group'])},{q(t['ko_source'])},{q(t['note'])});"
        )
    for a in aliases:
        parts.append(
            "insert into term_aliases (id,seq,alias_ko,target_id,name_en_raw,note) values ("
            f"{q(a['id'])}::uuid,{a['seq']},{q(a['alias_ko'])},{q(a['target_id'])}::uuid,"
            f"{q(a['name_en_raw'])},{q(a['note'])});"
        )
    parts.append("commit;")
    path.write_text("\n".join(parts), encoding="utf-8")


def push_postgrest(terms, aliases):
    import requests
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.")
    h = {"apikey": key, "authorization": f"Bearer {key}",
         "content-type": "application/json", "prefer": "return=minimal"}
    for table, rows in (("terms", terms), ("term_aliases", aliases)):
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            r = requests.post(f"{url}/rest/v1/{table}", headers=h, json=chunk, timeout=60)
            if r.status_code >= 300:
                sys.exit(f"{table} 삽입 실패 ({r.status_code}): {r.text[:500]}")
            print(f"  {table}: {i + len(chunk)}/{len(rows)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="검사만 하고 아무것도 쓰지 않는다")
    ap.add_argument("--emit-sql", metavar="PATH", help="SQL 파일로 출력 (SQL Editor 붙여넣기용)")
    args = ap.parse_args()

    terms = read_terms()
    aliases, orphans = read_aliases(terms)
    problems = check(terms, aliases, orphans)

    print(f"terms {len(terms)} / aliases {len(aliases)} / 위반 {len(problems)}")
    for p in problems[:20]:
        print(f"  ! {p}")
    if problems:
        sys.exit("제약 위반이 있어 중단합니다.")

    if args.dry_run:
        print("dry-run — 쓰지 않았습니다.")
        return
    if args.emit_sql:
        emit_sql(terms, aliases, Path(args.emit_sql))
        print(f"SQL 생성: {args.emit_sql}")
        return
    push_postgrest(terms, aliases)
    print("이관 완료.")


if __name__ == "__main__":
    main()
