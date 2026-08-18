# -*- coding: utf-8 -*-
"""
사전 무결성 점검.

지금까지 발견된 결함들은 전부 같은 유형이었다:
  · 원어명 일부가 유실됨 (모스카토 다스티 -> "Moscato")
  · 타입이 틀림 (지역인데 producer 태그)
  · 한글명과 원어명의 어절 수가 크게 어긋남
이 스크립트는 그런 패턴을 자동으로 찾아 사람이 볼 목록으로 뽑는다.
확장 작업 전후로 돌려서 새 오류가 유입됐는지 비교하는 용도.
"""
import re
import sys
import unicodedata
from collections import defaultdict

import pandas as pd

HAN = re.compile(r"[가-힣]")
# 한글 이름에서 어절로 세지 않을 조사/전치사 대응어
KO_STOP = {"드", "디", "다", "델", "델라", "데", "뒤", "라", "르", "레",
           "이", "에", "아", "폰", "돈", "앤", "에이"}
EN_STOP = {"de", "di", "du", "da", "del", "della", "dello", "dei", "delle",
           "la", "le", "les", "el", "il", "lo", "y", "e", "et", "and",
           "the", "of", "von", "van", "d", "l", "a", "au", "aux", "dal"}


def norm_en(s):
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split()


def ko_words(s):
    return [w for w in str(s).split() if w not in KO_STOP]


def en_words(s):
    return [w for w in norm_en(s) if w not in EN_STOP and len(w) > 1]


def check(source="data/dist/wine_terms.csv"):
    """source가 DataFrame이면 그대로 쓰고(호출자 것은 건드리지 않게 복사),
    문자열/경로면 CSV로 읽는다. 편집 도구가 커밋 전에 파일 없이 바로 검증할 때
    DataFrame을 직접 넘긴다 (api/_lib/audit_adapter.py 참조)."""
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    df["name_ko"] = df["name_ko"].fillna("")
    df["name_en"] = df["name_en"].fillna("")
    issues = defaultdict(list)

    # ── 1. 어절 수 불일치 (원어명 일부 유실 의심) ────────────────
    # '모스카토 다스티'(2어절) -> 'Moscato'(1어절) 같은 케이스.
    # 대표 표기(is_alias=0)만 본다. 별칭은 축약형이 정상이다.
    for _, r in df[df.is_alias == 0].iterrows():
        kw, ew = ko_words(r.name_ko), en_words(r.name_en)
        if not kw or not ew:
            continue
        if len(kw) - len(ew) >= 1 and len(ew) <= 2:
            issues["원어명 유실 의심"].append(
                f"{r.name_ko}  ->  {r.name_en}   [{r.type}]")

    # ── 2. 같은 원어명이 여러 타입에 걸침 ────────────────────────
    # 품종+지역 동시 등재는 정상(Montepulciano d'Abruzzo)이지만,
    # producer가 섞이면 대개 오류다.
    for en, grp in df.groupby("name_en"):
        types = set(grp.type)
        if len(types) > 1:
            sev = "오류 의심" if "producer" in types and len(types) > 1 else "확인 필요"
            issues[f"타입 중복 ({sev})"].append(f"{en}: {sorted(types)}")

    # ── 3. 한글명에 한글이 없음 ─────────────────────────────────
    for _, r in df.iterrows():
        if r.name_ko and not HAN.search(r.name_ko):
            issues["한글명에 한글 없음"].append(f"{r.name_ko} [{r.type}]")

    # ── 4. 원어명이 비었거나 한글이 섞임 ────────────────────────
    for _, r in df.iterrows():
        if not str(r.name_en).strip():
            issues["원어명 비어있음"].append(f"{r.name_ko} [{r.type}]")
        elif HAN.search(str(r.name_en)):
            issues["원어명에 한글 섞임"].append(f"{r.name_ko} -> {r.name_en}")

    # ── 5. 동일 한글명이 서로 다른 원어를 가리킴 ────────────────
    for ko, grp in df.groupby("name_ko"):
        ens = set(grp.name_en)
        if len(ens) > 1:
            # 같은 canonical이면 정상
            if grp.canonical_id.nunique() > 1:
                issues["동일 한글명 → 다른 원어"].append(
                    f"{ko}: {sorted(ens)[:4]}")

    return issues


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/dist/wine_terms.csv"
    issues = check(path)
    total = sum(len(v) for v in issues.values())
    print(f"=== 사전 점검: {path} ===\n")
    for k in sorted(issues):
        v = issues[k]
        print(f"[{k}] {len(v)}건")
        for line in v[:15]:
            print(f"    {line}")
        if len(v) > 15:
            print(f"    ... 외 {len(v)-15}건")
        print()
    print(f"총 {total}건")
