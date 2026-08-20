# SUPABASE — 운영 런북

사전의 원천은 Supabase다. 이 문서는 그 구조와, 뭔가 잘못됐을 때 무엇을 보는지 적는다.

---

## 데이터가 흐르는 길

```
관리 패널(톱니바퀴)
   │  POST /api/admin-submit  (비밀번호)
   ▼
Vercel 함수
   │  1. Supabase에서 seed 전체 스냅샷 읽기
   │  2. 메모리에서 검증·적용        (api/_lib/seed_ops.py)
   │  3. build() 1회                (scripts/build.py — 유일한 파생 구현)
   │  4. audit 차집합                (직전 아티팩트 기준)
   │  5. DB 반영                    ← 빌드가 성공한 뒤에야
   │  6. Storage에 발행              (내용주소 JSON + manifest)
   │  7. GitHub repository_dispatch
   ▼
GitHub Action (export.yml)
   │  Supabase → data/seed/ → build.py → npm test → 커밋
   ▼
git  (회귀 테스트의 골든 데이터 · 복구 사본 · 페이지 최후 폴백)
```

읽기는 이렇게 간다:

```
브라우저 → SW 캐시 → /api/dict-manifest → Supabase Storage
                                    ↘ (전부 실패) /data/dist/wine_terms.json (git)
```

---

## 왜 이렇게 나눴는가

**파생은 `build.py` 한 곳에만.** canonical_id·대표 표기·`key_ko`는 전체 데이터에
의존하는 함수라, SQL 트리거로 옮기면 두 번째 구현이 생긴다. 검증이 어긋나면
제약 위반으로 시끄럽게 실패하지만, 파생이 어긋나면 **검색 결과만 조용히 틀린다**
(CLAUDE.md 규칙 1·4).

**git은 강등됐을 뿐 필수다.** 회귀 테스트가 `data/dist/`를 골든 데이터로 쓴다.
동기화가 멈추면 CI는 낡은 데이터로 통과하는데 실서비스는 최신을 쓰는 괴리가 생긴다.
그래서 export 실패는 이슈를 연다.

**쓰기는 반드시 함수를 통과한다.** DB에 직접 쓰면 사전이 재발행되지 않아 라이브가
낡는다. 이것이 Supabase Auth를 도입하지 않은 이유다 — Auth의 가치는 클라이언트가
DB와 직접 대화하게 하는 것인데, 이 시스템은 그 능력을 가지면 안 된다.

---

## 스키마

| 테이블 | 역할 |
|---|---|
| `terms` | 품종·지역·생산자. `type` 판별자 하나로 묶음 |
| `term_aliases` | 별칭. `target_id` FK로 대상을 가리킨다 |
| `seed_state` | 개정 카운터. 동시 편집 감지(CAS)와 동기화 정합성 검사에 쓴다 |
| `artifacts` | 발행 이력 + **다음 편집의 audit 기준선** |
| `edit_log` | 편집 이력. PR 리뷰를 포기한 대가로 사후 추적을 여기서 보장 |

주의해야 할 컬럼 셋:

- **`terms.seq`** — CSV 행 순서. `build()`의 canonical_id 부여가 행 순서에 의존한다.
  기본값이 없어서 대시보드에서 손으로 insert하면 **실패한다** — 조용히 어긋나느니
  실패하는 게 낫기 때문이다. (품종을 하나 추가하면 그 뒤 2,642개 행의 canonical_id가
  밀린다. 생산자는 마지막 파일이라 0건.)
- **`terms.key_en_norm`** — Python `search_key_en()`이 계산해서 넣는다. DB는 모양만 검사.
- **`term_aliases.name_en_raw`** — CSV 원문 철자 보존(434건 중 14건이 target과 다름,
  `Albarino` vs `Albariño`). 이게 있어야 export가 바이트 동일해진다.

삭제는 **소프트 삭제**(`deleted_at`)다. 되돌리려면 `deleted_at`을 null로 되돌린다.

---

## 환경변수

| 이름 | Vercel | GitHub Actions | 비고 |
|---|---|---|---|
| `SUPABASE_URL` | Prod + Preview | 필요 | 키가 없으면 무력하므로 비밀 아님 |
| `SUPABASE_SERVICE_ROLE_KEY` | **Production만** | 필요 | git·브라우저 절대 금지 |
| `EDIT_PASSWORD` | Prod + Preview(**다른 값**) | 불필요 | |
| `GITHUB_TOKEN` / `GITHUB_REPO` | Prod | 불필요 | 동기화 신호 발신용 |

Preview에 service key를 넣지 않는 건 의도적이다 — 공개 프리뷰 URL에서 쓰기가
fail-closed 된다. RLS는 전 테이블에 켜고 정책을 두지 않아 service_role만 통과한다.

---

## 문제가 생겼을 때

**페이지에 사전이 안 뜬다**
`/api/dict-manifest`를 열어본다. `not_configured`면 `SUPABASE_URL` 미설정,
`manifest_unavailable`이면 Storage에 `manifest.json`이 없거나 프로젝트가 정지 상태다.
후자면 `scripts/publish_dict.py`를 돌려 다시 발행한다. 그 사이에도 이미 방문했던
브라우저는 캐시로 계속 검색된다.

**편집이 "Supabase 프로젝트가 일시정지" 라고 한다**
무료 티어는 7일 무활동 시 정지된다. 대시보드에서 Resume. 야간 동기화 크론이
매일 DB를 건드리므로 평소엔 정지되지 않는다 — 정지됐다면 크론도 멈춰 있다는 뜻이니
Actions 탭을 함께 확인한다(저장소가 60일 무활동이면 GitHub이 스케줄을 끈다).

**git 동기화가 실패해 이슈가 열렸다**
`data/seed`·`data/dist`가 Supabase와 어긋난 상태다. Actions 로그를 본다.
`npm test` 실패면 데이터가 회귀 테스트를 깬 것이므로 커밋되지 않은 게 정상이다.

**canonical_id가 통째로 바뀐 커밋이 올라왔다**
품종이나 지역을 추가하면 정상이다(위 `seq` 설명). 생산자 추가나 단순 수정에서
이런 일이 나면 `seq`가 어긋난 것이니 확인이 필요하다.

**전부 되돌리고 싶다**
커밋 `3812462`이 Supabase 도입 직전 상태다. git에 완전한 사본이 있으므로
Supabase 프로젝트를 삭제해도 데이터는 잃지 않는다. `schema.sql` 재실행 +
이관 워크플로 재실행으로 복구된다.

---

## 정기 작업

`scripts/publish_dict.py` — 현재 DB 상태로 사전을 다시 발행한다. 멱등하다.
아티팩트가 꼬였거나 Storage를 실수로 비웠을 때 쓴다.

`scripts/verify_parity.py` — Supabase ↔ git 바이트 대조. 이관 검증용이지만
"정말 같은가"를 확인하고 싶을 때 언제든 돌릴 수 있다.
