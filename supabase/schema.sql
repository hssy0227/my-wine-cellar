-- 와인명 사전 — Supabase 스키마
--
-- Supabase SQL Editor에 통째로 붙여넣고 실행한다. 멱등하지 않으므로 최초 1회만.
--
-- 설계 원칙 (docs/DECISIONS.md D13, CLAUDE.md 규칙 4):
--   파생(derivation)은 scripts/build.py 한 곳에만 존재한다.
--   이 스키마는 **검증만** 한다 — search_key_en이나 자모 정규화를 SQL로 재구현하지 않는다.
--   이유는 실패 양상이다. 중복된 검증이 어긋나면 제약 위반으로 시끄럽게 실패하지만,
--   중복된 파생이 어긋나면 검색 결과만 조용히 틀린다(가야 -> Cowra 사고, CLAUDE.md 규칙 1).

create type term_type as enum ('grape', 'region', 'producer');

-- ── 사전 본체 ────────────────────────────────────────────────────────
-- 품종/지역/생산자를 한 테이블에 담는다. build.load_seed()가 어차피 3개 파일을
-- type 키로 합치므로, 3테이블로 쪼개면 그걸 되돌리는 UNION만 늘어난다.
create table terms (
  id            uuid primary key default gen_random_uuid(),

  -- CSV 행 순서. build()의 canonical_id 부여가 **행 순서에 의존**하기 때문에 필수다.
  -- DB가 다른 순서로 돌려주면 2,328개 canonical_id가 전부 재번호되어 dist가 통째로 바뀐다.
  -- 읽기는 항상 `order by type, seq`. 기본값을 주지 않는 이유: 대시보드에서 수동
  -- insert할 때 조용히 잘못된 순서로 들어가느니 실패하는 편이 낫다.
  seq           bigint      not null,

  type          term_type   not null,
  name_en       text        not null,
  name_ko       text        not null,

  -- Python build.search_key_en()이 계산해서 넣는다. DB는 **모양만** 검사하고
  -- 내용은 절대 계산하지 않는다. 발음기호 제거 + 아포스트로피/하이픈 삭제 규칙
  -- (CLAUDE.md 규칙 2)을 SQL로 옮기면 d'Abruzzo / Pontet-Canet에서 Python과
  -- 갈렸을 때 오류 없이 유니크 인덱스만 오염된다.
  key_en_norm   text        not null,

  tier          text        not null default '',
  region_group  text        not null default '',
  ko_source     text        not null default 'manual',
  note          text        not null default '',

  deleted_at    timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint terms_name_ko_not_blank check (btrim(name_ko) <> ''),
  constraint terms_name_en_not_blank check (btrim(name_en) <> ''),

  -- name_ko에 한글을 강제하지 **않는다**. '1865'(칠레 브랜드)처럼 한글이 없는
  -- 정당한 표기가 실제로 존재한다(audit.py의 기존 73건 중 "한글명에 한글 없음" 1건).
  -- 오타 방지는 API 층에서 경고로 처리하고, DB는 정당한 예외를 막지 않는다.

  constraint terms_name_en_no_hangul check (name_en !~ '[가-힣]'),
  constraint terms_key_en_shape      check (key_en_norm ~ '^[a-z0-9 ]*$'),
  constraint terms_ko_source_known
    check (ko_source in ('manual', 'added', 'wikidata', 'auto', 'alias', 'producer'))
);

create unique index terms_seq_uq on terms (seq);

-- Python의 중복 검사는 read-then-write라 경합에 취약하고, Supabase 대시보드에서
-- 손으로 넣는 행은 아예 우회한다. 최종 방어선은 여기다.
create unique index terms_type_key_en_uq
  on terms (type, key_en_norm) where deleted_at is null;

create index terms_read_order on terms (type, seq) where deleted_at is null;

-- ── 별칭 ─────────────────────────────────────────────────────────────
create table term_aliases (
  id           uuid primary key default gen_random_uuid(),
  seq          bigint      not null,
  alias_ko     text        not null,

  -- 텍스트쌍 대신 실제 행을 가리킨다. 고아 별칭이 구조적으로 불가능해지고,
  -- 삭제의 의미가 명확해진다. on delete cascade는 쓰지 않는다 — 소프트 삭제만 한다.
  target_id    uuid        not null references terms (id),

  -- CSV 원문 철자 보존. 현재 434건 중 14건이 target과 철자가 다르다
  -- (Albarino vs Albariño). 이 컬럼이 있어야 export가 바이트 동일해져서,
  -- 이관 커밋에 diff가 뜨면 그 자체로 버그 신호가 된다.
  -- 검증의 근거는 target_id이고, 이 컬럼은 export 전용이다.
  name_en_raw  text        not null,

  note         text        not null default '',
  deleted_at   timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint alias_ko_not_blank check (btrim(alias_ko) <> '')
);

create unique index term_aliases_seq_uq on term_aliases (seq);
create unique index term_aliases_uq
  on term_aliases (alias_ko, target_id) where deleted_at is null;
create index term_aliases_read_order on term_aliases (seq) where deleted_at is null;
create index term_aliases_target on term_aliases (target_id) where deleted_at is null;

-- ── 개정 카운터 ──────────────────────────────────────────────────────
-- 쓰기 함수가 스냅샷을 읽은 뒤 커밋하기 전에 이 값이 움직였는지 확인한다(CAS).
-- 야간 크론은 이 값과 artifacts.seed_revision을 비교해 유실된 동기화를 잡는다.
create table seed_state (
  id       int    primary key default 1 check (id = 1),
  revision bigint not null default 0
);
insert into seed_state (id, revision) values (1, 0);

create or replace function bump_seed_revision() returns trigger
language plpgsql as $$
begin
  update seed_state set revision = revision + 1 where id = 1;
  return null;
end;
$$;

create trigger terms_bump_revision
  after insert or update or delete on terms
  for each statement execute function bump_seed_revision();

create trigger term_aliases_bump_revision
  after insert or update or delete on term_aliases
  for each statement execute function bump_seed_revision();

-- ── 발행된 사전 아티팩트 ─────────────────────────────────────────────
create table artifacts (
  id              bigserial   primary key,
  version         text        not null unique,   -- payload sha256 앞 12자
  storage_path    text        not null,
  row_count       int         not null,
  canonical_count int         not null,
  seed_revision   bigint      not null,

  -- 이 빌드 시점의 audit 이슈 전체. 장식이 아니라 **다음 편집의 비교 기준선**이다.
  -- 이게 있으면 쓰기 경로에서 "수정 전" 빌드를 한 번 더 돌릴 필요가 없고,
  -- 재-파생한 값이 아니라 실제로 라이브인 값과 비교하게 되어 더 정확하다.
  audit_summary   jsonb       not null,

  built_at        timestamptz not null default now(),
  git_synced_at   timestamptz
);
create index artifacts_built_at on artifacts (built_at desc);

-- ── 편집 이력 ────────────────────────────────────────────────────────
-- PR 리뷰를 포기한 대가로, 사후 추적은 여기서 보장한다.
create table edit_log (
  id               bigserial   primary key,
  at               timestamptz not null default now(),
  actor            text,
  action           text        not null,   -- add | edit | delete
  table_name       text        not null,
  row_before       jsonb,
  row_after        jsonb,
  reason           text,
  artifact_version text
);
create index edit_log_at on edit_log (at desc);

-- ── RLS: 전부 켜고 정책은 만들지 않는다 ──────────────────────────────
-- 정책이 0개면 anon/authenticated는 전부 거부되고, service_role만 우회한다.
-- 브라우저에는 어떤 Supabase 키도 가지 않으므로 이게 올바른 자세다.
alter table terms         enable row level security;
alter table term_aliases  enable row level security;
alter table seed_state    enable row level security;
alter table artifacts     enable row level security;
alter table edit_log      enable row level security;

revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;
