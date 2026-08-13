#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
검증된 wine_terms.csv를 seed CSV들로 분해한다.

이관 시 한 번만 실행한다. 이후로는 seed CSV가 진실의 원천이 되고,
파이썬 사전 리터럴(producers.py 등)은 더 이상 쓰지 않는다.

배경은 docs/MIGRATION.md 참조.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

TYPE_FILE = {"grape": "grapes.csv", "region": "regions.csv",
             "producer": "producers.csv"}
# 대표 항목이 들고 갈 컬럼
ENTRY_COLS = ["name_en", "name_ko", "tier", "region_group", "ko_source"]


def freeze(src: Path, out_dir: Path) -> int:
    df = pd.read_csv(src)
    required = {"canonical_id", "type", "name_ko", "is_alias", "name_en"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"입력 파일에 필수 컬럼이 없습니다: {sorted(missing)}")

    df["tier"] = df.get("tier", "")
    df["region_group"] = df.get("region_group", "")
    df["ko_source"] = df.get("ko_source", "")
    out_dir.mkdir(parents=True, exist_ok=True)

    total_entries = total_aliases = 0
    alias_rows = []

    for t, fname in TYPE_FILE.items():
        sub = df[df.type == t]
        if sub.empty:
            print(f"[!] type={t} 행이 없습니다")
            continue

        # 대표 항목: is_alias=0. 캐노니컬당 하나만 남긴다.
        entries = (sub[sub.is_alias == 0]
                   .drop_duplicates(subset="canonical_id", keep="first")
                   .loc[:, ENTRY_COLS]
                   .fillna(""))
        entries = entries[entries.name_en.astype(str).str.strip() != ""]
        entries = entries.sort_values("name_en")
        entries["note"] = ""
        entries.to_csv(out_dir / fname, index=False, encoding="utf-8-sig")
        total_entries += len(entries)
        print(f"  {fname:16} {len(entries):5d}건")

        # 별칭: is_alias=1. 어느 name_en에 붙는지로 연결한다.
        # stripped(접두어 제거 자동생성)는 빌드가 재생성하므로 seed에 넣지 않는다.
        al = sub[(sub.is_alias == 1) & (sub.ko_source != "stripped")]
        for _, r in al.iterrows():
            alias_rows.append({
                "alias_ko": r.name_ko,
                "name_en": r.name_en,
                "type": t,
                "note": "",
            })
        total_aliases += len(al)

    alias_df = pd.DataFrame(alias_rows).drop_duplicates()
    alias_df = alias_df.sort_values(["type", "name_en", "alias_ko"])
    alias_df.to_csv(out_dir / "aliases.csv", index=False, encoding="utf-8-sig")
    print(f"  {'aliases.csv':16} {len(alias_df):5d}건")

    stripped = (df.get("ko_source") == "stripped").sum()
    print(f"\n대표 {total_entries}건 · 별칭 {len(alias_df)}건")
    print(f"(자동생성 stripped {stripped}건은 빌드가 재생성하므로 seed 제외)")
    return total_entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True,
                    help="검증된 wine_terms.csv 경로")
    ap.add_argument("--out", default="data/seed", help="seed 출력 디렉터리")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.exists():
        sys.exit(f"파일을 찾을 수 없습니다: {src}")

    print(f"동결: {src}\n")
    freeze(src, Path(a.out))


if __name__ == "__main__":
    main()
