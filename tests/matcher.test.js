/**
 * matcher.js 골든 데이터 검증 + 회귀 테스트.
 *
 * tests/test_sync.py 와 짝을 이룬다. 같은 골든 데이터(data/dist/)를 Python과
 * JS 양쪽에서 통과시키는 것이 정규화 동기화의 실질적 보증이다.
 * 테이블 리터럴이 같아도 적용 순서·조건이 갈리면 여기서 잡힌다.
 *
 * 실행: node --test tests/
 */

import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { createMatcher, dist, normEn, toJamo } from '../src/matcher/matcher.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

let DATA;
let matcher;

before(() => {
  DATA = JSON.parse(readFileSync(join(ROOT, 'data/dist/wine_terms.json'), 'utf8'));
  assert.ok(DATA.length > 0, 'wine_terms.json이 비어 있습니다. build.py를 먼저 실행하세요');
  matcher = createMatcher(DATA);
});

/* ── 골든 데이터 대조 ───────────────────────────────────────────── */

describe('저장된 검색 키 재현', () => {
  test('toJamo(ko)가 저장된 key_ko와 전 행 일치한다', () => {
    const bad = DATA.filter(r => toJamo(r.ko) !== r.k);
    assert.deepEqual(
      bad.slice(0, 10).map(r => ({ ko: r.ko, 저장: r.k, 계산: toJamo(r.ko) })), [],
      `key_ko 불일치 ${bad.length}건 / 전체 ${DATA.length}행`);
  });

  test('normEn(en)이 저장된 key_en과 전 행 일치한다', () => {
    // 여기가 깨지면 사용자가 친 로마자 질의가 사전의 저장 키와 어긋난다.
    // 접두어 표(EN_PREFIX_RE)가 build.py와 갈릴 때 정확히 이 테스트가 잡는다.
    const bad = DATA.filter(r => normEn(r.en) !== r.ke);
    assert.deepEqual(
      bad.slice(0, 10).map(r => ({ en: r.en, 저장: r.ke, 계산: normEn(r.en) })), [],
      `key_en 불일치 ${bad.length}건 / 전체 ${DATA.length}행`);
  });
});

/* ── 편집거리 ───────────────────────────────────────────────────── */

describe('가중 편집거리', () => {
  test('인접 자모 자리바꿈이 0.6으로 계산된다', () => {
    // jamo_matcher.py의 weighted_distance와 같은 값이어야 한다.
    // 자리바꿈 항이 없으면 삭제+삽입 2회로 2.0이 나온다.
    const a = toJamo('가니');
    const b = a[0] + a[2] + a[1] + a[3];   // 2·3번째 자모를 도치
    assert.equal(dist(a, b), 0.6);
    assert.equal(1 - dist(a, b) / Math.max(a.length, b.length), 0.85);
  });

  test('CHEAP 자모(ㅡㅜㄹ) 삽입은 0.3만 부과한다', () => {
    // '탈보'(다ㄹ보) vs '타르보'(다르보) — ㄹ 뒤에 ㅡ가 하나 삽입된 형태
    const [a, b] = [toJamo('탈보'), toJamo('타르보')];
    assert.equal(dist(a, b), 0.3);
  });
});

/* ── 회귀 질의 ──────────────────────────────────────────────────── */
// canonical_id는 재빌드마다 재번호매김되므로(gra01049 → gra00315)
// 절대 ID로 단언하지 않는다. name_display / name_en으로 확인한다.

const top = (q, th = 0.80) => {
  const hits = matcher.scan(q, th, 'all');
  assert.ok(hits.length > 0, `'${q}' 검색 결과가 없습니다`);
  return hits[0];
};

describe('README에 문서화된 매칭', () => {
  test('샤또 딸보 → Chateau Talbot (된소리 흡수, 1.00)', () => {
    const h = top('샤또 딸보');
    assert.equal(h.r.d, 'Chateau Talbot');
    assert.equal(h.s, 1);
  });

  test('디켐 → Chateau d\'Yquem (접두어 제거 별칭, DECISIONS D11)', () => {
    const h = top('디켐');
    assert.equal(h.r.d, "Chateau d'Yquem");
    assert.equal(h.s, 1);
  });

  test('로칠드 → 뒷어절 검색으로 Rothschild 계열을 찾는다', () => {
    // 사전 키는 공백 없는 통짜라 접두사 매칭으로는 절대 못 찾는다.
    // 어절 단위 인덱스(KT)가 있어야 잡힌다.
    const hits = matcher.scan('로칠드', 0.80, 'all');
    const names = hits.map(h => h.r.d);
    assert.ok(names.some(n => n.includes('Mouton Rothschild')),
      `Mouton Rothschild가 결과에 없습니다: ${names.join(', ')}`);
    assert.ok(names.some(n => n.includes('Lafite Rothschild')),
      `Lafite Rothschild가 결과에 없습니다: ${names.join(', ')}`);
    assert.ok(hits.every(h => h.s >= 0.80));
  });

  test("d'abruzzo → 아포스트로피를 삭제해 토큰을 붙인다", () => {
    // CLAUDE.md 규칙 2. 공백으로 치환하면 'd abruzzo'로 갈려 매칭이 깨진다.
    const names = matcher.scan("d'abruzzo", 0.80, 'all').map(h => h.r.d);
    assert.ok(names.some(n => n.includes("Montepulciano d'Abruzzo")),
      `Montepulciano d'Abruzzo가 결과에 없습니다: ${names.join(', ')}`);
  });

  test('ㅊ뮫굳ㅅ → 한영 자판 오입력을 cabernet으로 복구한다', () => {
    const hits = matcher.scan('ㅊ뮫굳ㅅ', 0.80, 'all');
    assert.ok(hits.length > 0, '자판 복구 결과가 없습니다');
    assert.equal(hits[0].via, 'kbd');
    assert.equal(hits[0].typed, 'cabernet');
    const names = hits.map(h => h.r.d);
    assert.ok(names.includes('Cabernet Sauvignon'),
      `Cabernet Sauvignon이 결과에 없습니다: ${names.join(', ')}`);
  });
});

/* ── 접두어 불일치 회귀 ─────────────────────────────────────────── */
// 이관 중 발견한 실제 버그. matcher.js의 EN_PREFIX_RE가 build.py와 달라
// 저장 키와 조회 키가 갈려 있었다. 에러 없이 결과만 틀리는 유형이라
// 테스트가 없으면 재발을 눈치챌 수 없다.

describe('EN_PREFIX_RE 동기화 회귀', () => {
  test("'dom perignon' — Dom은 브랜드명이라 떼지 않는다", () => {
    // 맨단어 'dom'을 접두어로 떼면 조회 키가 'perignon'이 되는데
    // 저장 키는 'dom perignon'이라 정확 매칭이 실패했다.
    assert.equal(normEn('Dom Perignon'), 'dom perignon');
    const h = top('dom perignon');
    assert.equal(h.r.d, 'Dom Perignon');
    assert.equal(h.s, 1);
  });

  test("'marques de riscal' — Marques de는 떼야 한다", () => {
    // build.py는 떼는데 matcher.js에는 규칙이 없어서
    // 저장 키 'riscal' vs 조회 키 'marques de riscal'로 갈렸다.
    assert.equal(normEn('Marques de Riscal'), 'riscal');
    const h = top('marques de riscal');
    assert.equal(h.r.d, 'Marques de Riscal');
    assert.equal(h.s, 1);
  });

  test("'domaine'/'chateau'는 그대로 떼어 축약 검색을 지원한다", () => {
    assert.equal(normEn('Chateau Margaux'), 'margaux');
    assert.equal(normEn('Chateau Talbot'), 'talbot');
  });
});

/* ── 정밀도 슬라이더 (DECISIONS.md D8) ──────────────────────────── */

describe('정밀도 슬라이더', () => {
  test('임계값을 올리면 결과가 실제로 줄어든다', () => {
    // D8: 초기엔 0.60~0.85 구간이 죽어 있어 슬라이더가 아무 일도 안 했다.
    // 접두사 점수를 0.80 + 0.20 × 덮는비율로 바꿔 유효 구간을 만들었다.
    const counts = [0.80, 0.90, 0.95].map(th => matcher.scan('몬테', th, 'all').length);
    assert.ok(counts[0] > counts[2],
      `슬라이더가 동작하지 않습니다: ${counts.join(' → ')}`);
    for (let i = 1; i < counts.length; i++) {
      assert.ok(counts[i] <= counts[i - 1],
        `임계값을 올렸는데 결과가 늘었습니다: ${counts.join(' → ')}`);
    }
  });
});

/* ── 타입 필터 ──────────────────────────────────────────────────── */

describe('타입 필터', () => {
  test("type을 지정하면 해당 타입만 반환한다", () => {
    for (const t of ['g', 'r', 'p']) {
      const hits = matcher.scan('몬테', 0.80, t);
      assert.ok(hits.every(h => h.r.t === t),
        `타입 ${t} 필터에 다른 타입이 섞였습니다`);
    }
  });
});
