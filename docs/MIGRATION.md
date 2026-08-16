# MIGRATION — 이관 가이드

## 왜 그냥 파일만 옮기면 안 되는가

이전 작업 환경(대화형 세션)에서 만든 스크립트들은 **순차 변형(mutation) 방식**이었다.

```
fill_ko.py            grapes_ko.csv, regions_ko.csv 를 처음부터 생성 (덮어쓰기)
  ↓
refine.py             접미사 정제 + 자동 채움
  ↓
make_grapes_extra.py  이탈리아 품종 병합
  ↓
fix_abruzzo_type.py   d'Abruzzo 타입 오류 수정
  ↓
fix_moscato_asti.py   Moscato d'Asti 원어명 유실 수정
  ↓
fix_sonoma_tokaj.py   Sonoma Coast / Tokaji Aszú 수정
  ↓
fix_mislabeled.py     지역인데 생산자로 등록된 7건 수정
  ↓
merge_grapes3.py      품종 대조표 124건 병합
  ↓
merge_synonyms.py     동의어 캐노니컬 9쌍 통합
  ↓
build_db.py           wine_terms.csv / .json 생성
```

문제는 이렇다:

1. **순서가 코드 어디에도 없다.** 사람의 기억에만 있었다
2. **멱등하지 않다.** `fill_ko.py`를 다시 돌리면 아래 9단계 수정이 전부 사라진다
3. **fix 스크립트가 일회성이다.** 이미 적용된 상태에서 또 돌리면 중복이 생기거나 실패한다

새 환경에서 이 체인을 재현하려다 실패하면 원인 파악이 매우 어렵다.
조용히 데이터 일부만 빠진 채 빌드가 성공해버릴 수 있다.

---

## 해결: 현재 상태를 seed로 동결한다

스크립트 체인을 재현하는 대신, **이미 검증된 현재 CSV를 새 출발점으로 삼는다.**

근거:
- 현재 `wine_terms.csv`는 회귀 테스트 100% 통과 상태다 (신의 물방울 329건, 파커 16건)
- `audit.py`의 "오류 의심" 0건이다
- 즉 **지금 상태 자체가 검증된 결과물**이다. 과정을 재현할 이유가 없다

### 변환 절차

```
[이전]  파이썬 사전 리터럴 20여 개 + fix 스크립트 9개 → CSV
[이후]  seed CSV (사람이 편집) → build.py 1개 → dist
```

`scripts/freeze_seed.py`가 이 변환을 수행한다.
현재 `wine_terms.csv`를 읽어 타입별 seed CSV로 분해한다.

```bash
python scripts/freeze_seed.py --from /path/to/wine_terms_v0.3.csv
```

이후로는 파이썬 사전 리터럴을 편집하지 않는다. **seed CSV가 진실의 원천이다.**

---

## 이관 체크리스트

### 1단계: 저장소 초기화

```bash
git init wine-dict
cd wine-dict
# 이 저장소의 파일 구조를 복사
```

### 2단계: 데이터 동결

기존 대화에서 받은 파일 중 **아래 3개만** 필요하다. 나머지 파이썬 소스는 옮기지 않는다.

| 파일 | 용도 |
|---|---|
| `wine_terms_v0.3.csv` | seed로 분해할 원본 |
| `wine_hierarchy_v0.2.csv` | 계층 데이터 (그대로 seed로) |
| `wine_match_test_v0.3.html` | 매칭 로직 추출용 참조 |

```bash
python scripts/freeze_seed.py --from wine_terms_v0.3.csv
cp wine_hierarchy_v0.2.csv data/seed/hierarchy.csv
```

### 3단계: 매칭 로직 분리 ✅ 완료

`src/matcher/matcher.js` 생성, `jamo_matcher.py`에 자리바꿈 규칙 추가,
`tests/test_sync.py` · `tests/matcher.test.js` 작성까지 끝났다.

현재 매칭 로직은 `make_html.py` 안에 **문자열로 박혀 있다**.
이걸 실제 JS 파일로 꺼낸다.

```
make_html.py 의 HTML 템플릿 내 <script> 블록
  → src/matcher/matcher.js          (순수 로직, export)
  → src/matcher/jamo_matcher.py     (Python 대응, 이미 별도 파일)
```

**주의**: 두 파일의 정규화 테이블이 동일해야 한다. `CLAUDE.md`의 규칙 1 참조.
`tests/test_sync.py`가 이를 자동 검증한다.

#### 분리하면서 발견한 불일치 3건

로직을 꺼내 양쪽을 나란히 놓자 규칙 1이 경고하던 상황이 **이미 발생해 있었다.**
자모 테이블(`CONSONANT_FOLD`/`VOWEL_FOLD`/`CHEAP`)은 온전했지만 나머지가 갈려 있었다.

| 항목 | 어긋난 내용 | 영향 | 채택 |
|---|---|---|---|
| `marques de` 접두어 | `build.py`만 제거 | `Marques de Riscal` 등 6행 정확매칭 실패 | Python |
| `dom` / `ch` 접두어 | JS는 맨단어, Python은 `dom.`/`ch.` | `Dom Perignon` 3행 정확매칭 실패 | Python |
| 자리바꿈(0.6) | JS에만 있음 | 발화 시 유사도 0.50 vs 0.85 | JS |

`Dom Pérignon`의 `Dom`은 `Domaine`의 약어가 아니라 브랜드명의 일부라 떼면 안 된다.
자리바꿈은 `docs/ARCHITECTURE.md` 2단계가 규정한 설계인데 Python 구현이 빠뜨리고 있었다.
셋 다 **에러 없이 결과만 틀리는** 유형이라, 회귀 테스트 없이는 재발을 눈치챌 수 없다.

### 4단계: 검증

```bash
python scripts/build.py
npm test                # 회귀 테스트 통과 확인
python scripts/audit.py # 오류 의심 0건 확인
```

빌드 결과 `data/dist/wine_terms.csv`가 이관 전 원본과 **행 수·캐노니컬 수가 일치**하면 성공이다.

```
기대값: 3,100행 / 2,327 캐노니컬
       생산자 1,613 / 지역 1,029 / 품종 458
```

> **캐노니컬이 2,328이 아니라 2,327인 이유.** v0.3에서는 `Xarel·lo`(가운뎃점)와
> `Xarel-lo`(하이픈)가 별개 캐노니컬이었는데, `build.py`의 캐노니컬 키가 하이픈·공백을
> 무시하면서 하나로 병합됐다. 같은 카탈루냐 품종의 두 표기이므로 병합이 옳다
> (`CLAUDE.md` 규칙 2의 하이픈 처리와 같은 방향). 유실이 아니라 중복 제거다.

> **`audit.py`의 "오류 의심"은 현재 1건이다** — `Norton`(품종 + 생산자).
> `docs/DECISIONS.md` D10이 의도적으로 허용한 동명이인이므로 수정 대상이 아니다.

---

## 옮기지 않는 것

아래 파일들은 **역할이 끝났으므로 이관하지 않는다.** 참고가 필요하면 대화 기록을 본다.

| 파일 | 이유 |
|---|---|
| `fill_ko.py`, `producers.py`, `producers2.py`, `kami_dict.py`, `parker_new.py`, `italian_grapes.py`, `regions_extra.py`, `hierarchy.py` | 파이썬 사전 리터럴. seed CSV로 대체됨 |
| `fix_*.py`, `merge_*.py`, `refine.py` | 일회성 수정 스크립트. 결과가 이미 CSV에 반영됨 |
| `translit.py`, `anglicize.py` | 자동 음차 생성기. 품질이 낮아 실질적으로 미사용 (AVA 채움에만 제한적 사용) |
| `wikidata_wine_harvest*.md` | 최초 데이터 수확 기록. 재실행할 일 없음 |
| `eval_matcher.py`, `validate_wine_dict.py` | 초기 평가 도구. `audit.py` + 회귀 테스트로 대체됨 |

다만 **판단 근거는 `docs/DECISIONS.md`에 옮겨 적었다.** 코드는 버리되 지식은 남긴다.

---

## 이관 후 첫 작업 제안

1. **회귀 테스트를 CI에 건다.** 지금까지 발견한 버그 대부분이 "조용히 틀리는" 유형이라
   자동 검증이 없으면 재발을 눈치채기 어렵다
2. **실제 셀러 데이터로 히트율을 측정한다.** 지금까지는 프록시 데이터로만 쟀다
3. 그 결과를 보고 `REQUIREMENTS.md`의 애플리케이션 방향(A/B/C)을 확정한다
