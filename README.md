# 와인 한글명 사전 & 매칭 엔진

한국어로 입력한 와인 이름을 원어명으로 매칭한다.

```
샤또 딸보        ->  Château Talbot         (1.00)
디켐             ->  Château d'Yquem        (1.00)
로칠드           ->  Mouton Rothschild …    (0.95)
d'abruzzo        ->  Montepulciano d'Abruzzo (0.97)
ㅊ뮫굳ㅅ         ->  Cabernet Sauvignon      (한영 자판 오입력 복구)
```

Vivino 등 해외 서비스는 원어 기준으로만 검색된다. 한글 음차 표기는 표준이 없어
사람마다 다르게 쓴다(딸보/탈보/타르보). 이 프로젝트가 그 간극을 메운다.

---

## 빠른 시작

```bash
pip install pandas
python scripts/build.py     # seed -> data/dist 생성
python scripts/audit.py     # 데이터 무결성 점검
```

---

## 저장소 구조

```
├── CLAUDE.md               ← Claude Code 작업 지침 (먼저 읽을 것)
├── docs/
│   ├── REQUIREMENTS.md     요구사항, 애플리케이션 스코프
│   ├── ARCHITECTURE.md     매칭 엔진 동작 원리
│   ├── DATA_MODEL.md       데이터 스키마
│   ├── MIGRATION.md        이전 환경에서 옮긴 경위
│   └── DECISIONS.md        설계 판단과 근거
├── data/
│   ├── seed/               사람이 편집하는 소스 (진실의 원천)
│   └── dist/               빌드 산출물 (편집 금지)
├── src/matcher/
│   ├── jamo_matcher.py     자모 정규화 (빌드용)
│   └── matcher.js          매칭 엔진 (런타임용)
├── scripts/
│   ├── build.py            seed -> dist
│   ├── audit.py            무결성 점검
│   └── freeze_seed.py      최초 이관용 (1회성)
└── tests/
```

---

## 데이터 규모

| 타입 | 표기 수 | 항목 수 |
|---|---|---|
| 생산자 | 1,613 | 1,048 |
| 지역 | 1,029 | 957 |
| 품종 | 458 | 322 |
| **합계** | **3,100** | **2,327** |

---

## 데이터를 고치려면

**배포 페이지 우상단의 톱니바퀴**를 누른다. 추가·수정·삭제가 즉시 사전에 반영되고,
잠시 뒤 GitHub Action이 `data/seed/`·`data/dist/`를 자동으로 커밋한다.

`data/`의 파일은 **직접 편집하지 않는다.** 사전의 원천은 Supabase이고 git의 CSV는
export 사본이라, 손으로 고쳐도 다음 동기화에 덮어써진다.

제출 시점에 막아주는 것들:

| 상황 | 결과 |
|---|---|
| 이미 있는 원어명을 또 추가 | 거부 — 캐노니컬이 쪼개지는 걸 막는다 |
| 대상 없는 별칭 | 거부 — 어디에도 안 붙는 고아 별칭 방지 |
| 별칭이 달린 항목 삭제 | 거부 — 어떤 별칭인지 알려준다 |
| 한글명에 한글이 없음 | 경고만 (`1865` 같은 정당한 예외가 있다) |

별칭이 정말 필요한지 판단하는 기준은 `CLAUDE.md`를 참조한다.
된소리·띄어쓰기·반모음 차이는 **자동 흡수되므로 별칭이 불필요**하다.

운영·복구 절차는 `docs/SUPABASE.md`.

---

## 알아둘 것

**Python과 JS의 정규화 테이블은 반드시 동일해야 한다.**
어긋나면 에러 없이 매칭만 조용히 틀린다. 상세는 `CLAUDE.md` 참조.
