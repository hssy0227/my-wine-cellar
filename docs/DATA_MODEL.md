# DATA_MODEL — 데이터 스키마

## 파일 구조

```
data/
├── seed/                  # 사람이 편집하는 소스 (진실의 원천)
│   ├── grapes.csv         # 품종
│   ├── regions.csv        # 지역·아펠라시옹
│   ├── producers.csv      # 생산자·퀴베
│   ├── aliases.csv        # 이표기 별칭
│   └── hierarchy.csv      # 산지 계층 (국가→광역→지구→마을→생산자)
└── dist/                  # 빌드 산출물 (직접 편집 금지)
    ├── wine_terms.csv     # 통합 사전 (검수용)
    ├── wine_terms.json    # 통합 사전 (앱 탑재용, 경량)
    └── wine_hierarchy.csv # 계층 평면 테이블
```

---

## seed 스키마

### grapes.csv / regions.csv / producers.csv

| 컬럼 | 필수 | 설명 |
|---|---|---|
| `name_en` | O | 원어명. **캐노니컬을 결정하는 키**. 정확해야 한다 |
| `name_ko` | O | 대표 한글 표기 |
| `tier` | | AVA·DOCG·AOC 등 법적 등급 (검색 미사용, 표시용) |
| `region_group` | | 대분류 (Bordeaux, Italy 등). 생산자에만 사용 |
| `note` | | 자유 메모 (출처, 판단 근거) |

### aliases.csv

| 컬럼 | 필수 | 설명 |
|---|---|---|
| `alias_ko` | O | 이표기 한글 |
| `name_en` | O | 어느 항목에 붙일지 (위 3개 파일의 `name_en`과 일치해야 함) |
| `type` | O | `grape` / `region` / `producer` |
| `note` | | 왜 이 별칭이 필요한지 |

> `name_en`이 어느 파일에도 없으면 빌드가 경고를 낸다.
> 오타로 인한 고아 별칭을 막기 위한 장치다.

---

## dist 스키마 (wine_terms.csv)

빌드가 생성한다. 14개 컬럼.

| 컬럼 | 설명 |
|---|---|
| `canonical_id` | 같은 대상을 묶는 그룹 ID. `gra00001` / `reg00042` / `pro00123` 형식 |
| `type` | `grape` / `region` / `producer` |
| `name_ko` | 이 행의 한글 표기 (대표 또는 별칭) |
| `name_ko_primary` | 같은 그룹의 대표 표기. **검색 결과에 실제 표시되는 이름** |
| `is_alias` | `0`=대표, `1`=별칭 |
| `name_en` | 원어명 |
| `name_display` | 화면 표시용 원어명 (등급 표기 제거) |
| `tier` | 법적 등급 |
| `key_ko` | **자모 정규화 검색 키**. 빌드 시 계산 |
| `key_en` | **로마자 정규화 검색 키**. 접두어(Chateau 등) 제거된 형태 |
| `key_len` | `key_ko` 길이 (가지치기용) |
| `region_group` | 대분류 |
| `ko_source` | 이 한글명의 출처 (아래 표 참조) |
| `wikidata` | Wikidata URI (있는 경우) |

### ko_source 값

| 값 | 뜻 |
|---|---|
| `manual` | 수기 작성 |
| `added` | 기존 데이터에 없어 신규 추가 |
| `alias` | 이표기 별칭 |
| `stripped` | 접두어 제거 자동 생성 (샤토 라투르 → 라투르) |
| `auto` | 영어 지명 조립 자동 생성 (AVA 등) |
| `wikidata` | Wikidata 원본 라벨 |
| `producer` | 생산자 사전 원본 |

---

## dist 스키마 (wine_terms.json)

CSV와 내용은 같고 키 이름만 축약했다. 앱 번들 크기를 줄이기 위함.

| JSON 키 | CSV 컬럼 |
|---|---|
| `i` | canonical_id |
| `t` | type 첫 글자 (`g`/`r`/`p`) |
| `ko` | name_ko |
| `p` | name_ko_primary |
| `en` | name_en |
| `d` | name_display |
| `tr` | tier |
| `k` | key_ko |
| `ke` | key_en |

**런타임에 `kt`(어절별 키 배열)가 동적으로 추가된다.** JSON에는 저장하지 않는다 —
파일 크기가 30% 이상 늘어나는데, 로드 시 계산해도 수 ms면 끝나기 때문.

---

## 계층 데이터 (hierarchy.csv)

산지 계층은 **행정구역이 아니라 와인 산지 기준**이다.

포이약은 행정상 지롱드 주 소속이지만, 와인 계층에서는 메독 아래다.
Wikidata의 `P131`(상위 행정구역)을 그대로 쓰면 이 둘이 어긋난다.
그래서 계층은 도메인 지식으로 직접 정의했다.

```
L1 국가    France
L2 광역    Bordeaux
L3 지구    Medoc
L4 마을    Pauillac      (대개 AOC 단위)
L5 생산자  Chateau Latour
```

공식 지구 구분이 없는 산지는 **광역명을 반복**시킨다(알자스 → 알자스 → 알자스).
어색해 보이지만 레벨 수가 들쭉날쭉하면 피벗테이블이 깨진다.

### 한계

- 생산자는 **대표 산지 1곳만** 연결된다. 여러 지역에서 만드는 네고시앙(루이 자도,
  안티노리)은 본거지 기준이다. 다대다로 바꾸려면 별도 매핑 테이블이 필요하다.
- 그랑 크뤼 밭(로마네 콩티, 몽라셰)은 마을과 생산자 사이 레벨인데 포함하지 않았다.
  부르고뉴만 33개 그랑 크뤼에 프리미에 크뤼가 640개라 별도 작업 규모다.

---

## 데이터 규모 (v0.3 기준)

| 타입 | 전체 행 | 캐노니컬 |
|---|---|---|
| 생산자 | 1,613 | 1,048 |
| 지역 | 1,029 | 957 |
| 품종 | 458 | 323 |
| **합계** | **3,100** | **2,328** |

행 수와 캐노니컬 수의 차이(772)가 별칭 개수다.

---

## Supabase 스키마 (원천)

위의 seed CSV 스키마는 이제 **export 형식**이다. 사람이 편집하는 원천은 Supabase다.
전체 DDL은 `supabase/schema.sql`, 운영 절차는 `docs/SUPABASE.md`.

### `terms` — 품종·지역·생산자

3개 파일을 `type` 판별자 하나로 묶었다. `build.load_seed()`가 어차피 합치므로
쪼개면 되돌리는 UNION만 늘어난다.

| 컬럼 | 비고 |
|---|---|
| `seq` | CSV 행 순서. **기본값 없음** — 아래 참조 |
| `type` | `grape` / `region` / `producer` (enum) |
| `name_en`, `name_ko`, `tier`, `region_group`, `ko_source`, `note` | seed CSV와 1:1 |
| `key_en_norm` | Python `search_key_en()`이 계산. DB는 모양만 검사 |
| `deleted_at` | 소프트 삭제. null로 되돌리면 복구된다 |

**`seq`에 기본값을 두지 않은 이유**: `build()`의 canonical_id 부여가 행 순서에
의존한다. 대시보드에서 손으로 insert하면 실패하는데, 이건 의도된 것이다 —
조용히 순서가 어긋나 2,328개 캐노니컬이 재번호되느니 실패하는 게 낫다.

참고로 canonical_id 카운터는 타입 구분 없는 전역이라, **품종을 하나 추가하면
그 뒤 2,642행의 canonical_id가 밀린다**(지역 1,613행, 생산자 0행 — 생산자가
마지막 파일이라 영향이 없다). 기능상 문제는 없지만(내부 식별자이고 외부에서
참조하지 않는다) 동기화 커밋이 커진다.

**`key_en_norm`을 DB가 계산하지 않는 이유**: `docs/DECISIONS.md` D13.
발음기호·아포스트로피·하이픈 처리를 SQL로 재구현하면 Python과 갈릴 수 있고,
그러면 유니크 인덱스가 오류 없이 오염된다.

### `term_aliases` — 별칭

| 컬럼 | 비고 |
|---|---|
| `target_id` | `terms(id)` FK. 고아 별칭이 **구조적으로 불가능**해진다 |
| `name_en_raw` | CSV 원문 철자 보존 (export 전용) |
| `alias_ko`, `note`, `seq`, `deleted_at` | |

`type` 컬럼이 없다 — target이 결정한다. export할 때 조인해서 채운다.

**`name_en_raw`가 필요한 이유**: 434건 중 14건이 target과 철자가 다르다
(`Albarino` vs `Albariño`). 대조는 발음기호를 무시하고 하지만 CSV에는 원문이
그대로 있어야 export가 바이트 동일해진다.

### 부수 테이블

| 테이블 | 역할 |
|---|---|
| `seed_state` | 개정 카운터. 동시 편집 감지(CAS), 동기화 정합성 검사 |
| `artifacts` | 발행 이력 + **다음 편집의 audit 기준선**(`audit_summary`) |
| `edit_log` | 편집 전/후 스냅샷. PR 리뷰를 대신하는 사후 추적 |

파생된 3,100행은 Postgres에 넣지 않는다. 관계형으로 질의할 일이 없고, 넣으면
Storage의 발행본과 어긋날 수 있는 두 번째 일관성 표면이 생긴다.
