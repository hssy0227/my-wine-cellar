/**
 * 검색 UI + 사전 적재.
 *
 * 매칭 엔진은 /src/matcher/matcher.js를 모듈로 가져온다. 예전에는 이 파일 안에
 * 엔진 전체가 복사돼 있었는데, 그 사본은 어떤 테스트도 검증하지 않는 세 번째
 * 정규화 테이블이었다(CLAUDE.md 규칙 1이 막으려던 바로 그 상태). 이제 테이블은
 * jamo_matcher.py와 matcher.js 둘뿐이고, test_sync.py가 그 둘을 대조한다.
 *
 * 사전 적재 순서 — 오프라인에서 즉시 뜨는 게 목표다:
 *   1. 지난번 버전 URL이 있으면 그것부터 받는다. 내용주소 URL이라 Service Worker가
 *      cache-first로 즉시 돌려주고, 네트워크가 없어도 검색이 된다.
 *   2. 동시에 manifest를 확인해 새 버전이면 받아서 핫스왑한다(새로고침 불필요).
 *   3. 캐시도 manifest도 없으면 git의 /data/dist/wine_terms.json으로 떨어진다.
 *      Supabase가 정지·삭제돼도 첫 방문자가 사전을 받을 수 있는 마지막 고리다.
 */
import { createMatcher, normEn, toJamo, TYPE_NAME } from '/src/matcher/matcher.js';

const VERSION_KEY = 'wine-dict-version';
const URL_KEY = 'wine-dict-url';
const BUILT_KEY = 'wine-dict-built-at';
const GIT_FALLBACK = '/data/dist/wine_terms.json';

let matcher = null;
let DATA = [];
let type = 'all';

const $q = document.getElementById('q');
const $res = document.getElementById('res');
const $th = document.getElementById('th');
const $thv = document.getElementById('thv');
const $jamo = document.getElementById('jamo');
const $stat = document.getElementById('stat');
const $freshness = document.getElementById('freshness');

/* ── 사전 적재 ─────────────────────────────────────────────────── */

function applyData(data, meta) {
  DATA = data;
  matcher = createMatcher(DATA);
  $stat.textContent = DATA.length.toLocaleString() + '개 표기 · 생산자 ' +
    DATA.filter(r => r.t === 'p').length.toLocaleString() + ' · 지역 ' +
    DATA.filter(r => r.t === 'r').length.toLocaleString() + ' · 품종 ' +
    DATA.filter(r => r.t === 'g').length.toLocaleString();
  if (meta) showFreshness(meta);
}

function showFreshness({ version, builtAt, stale }) {
  if (!$freshness) return;
  if (!stale) { $freshness.textContent = ''; $freshness.classList.remove('on'); return; }
  // 오프라인이면 숨기지 않고 사실대로 보여준다 — 낡은 사전을 최신인 척하지 않는다.
  const age = builtAt ? ` (${relativeTime(builtAt)})` : '';
  $freshness.textContent = `오프라인 · 사전 v${(version || '?').slice(0, 7)}${age}`;
  $freshness.classList.add('on');
}

function relativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  if (!isFinite(diff)) return '';
  const d = Math.floor(diff / 86400000);
  if (d >= 1) return `${d}일 전`;
  const h = Math.floor(diff / 3600000);
  return h >= 1 ? `${h}시간 전` : '방금';
}

const DICT_CACHE = 'wine-dict-v1';   // sw.js의 DICT_CACHE와 같은 이름이어야 한다

async function fetchJson(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

async function fetchDict(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  // 페이지에서 직접 캐시에 넣는다. Service Worker에 맡기면 첫 방문을 놓친다 —
  // SW가 활성화되어 페이지를 통제하기 전에 이 fetch가 이미 끝나버리기 때문이다.
  // 그러면 캐시가 빈 채로 오프라인이 되어 검색이 아예 안 된다.
  if ('caches' in window) {
    try {
      const cache = await caches.open(DICT_CACHE);
      await cache.put(url, r.clone());
      // 이전 버전 payload 정리 — 556KB짜리가 쌓이지 않게.
      for (const k of await cache.keys()) {
        if (new URL(k.url).href !== new URL(url, location.href).href) cache.delete(k);
      }
    } catch { /* 캐시 실패는 치명적이지 않다 — 검색은 그대로 동작한다 */ }
  }
  return r.json();
}

async function loadDictionary() {
  const cachedUrl = localStorage.getItem(URL_KEY);
  const cachedVersion = localStorage.getItem(VERSION_KEY);
  let booted = false;

  // 1) 지난 버전으로 즉시 부팅 (SW 캐시 → 오프라인에서도 동작)
  if (cachedUrl) {
    try {
      applyData(await fetchDict(cachedUrl), {
        version: cachedVersion, builtAt: localStorage.getItem(BUILT_KEY), stale: true,
      });
      booted = true;
      run();
    } catch { /* 캐시가 없거나 만료됨 — 아래에서 새로 받는다 */ }
  }

  // 2) 최신 버전 확인 후 필요하면 핫스왑
  try {
    const m = await fetchJson('/api/dict-manifest', { cache: 'no-store' });
    if (!m.ok) throw new Error(m.error || 'manifest 없음');
    if (m.version !== cachedVersion || !booted) {
      applyData(await fetchDict(m.url), { version: m.version, builtAt: m.built_at, stale: false });
      localStorage.setItem(VERSION_KEY, m.version);
      localStorage.setItem(URL_KEY, m.url);
      localStorage.setItem(BUILT_KEY, m.built_at || '');
      if (booted) toast(`사전이 업데이트되었습니다 · ${m.rows.toLocaleString()}개 표기`);
      booted = true;
      run();
    } else {
      showFreshness({ stale: false });
    }
    return;
  } catch { /* 오프라인이거나 Supabase 정지 — 아래 폴백 */ }

  // 3) git 폴백. 최초 방문 + Supabase 장애일 때의 마지막 보루.
  if (!booted) {
    try {
      applyData(await fetchDict(GIT_FALLBACK), { version: 'git', stale: true });
      run();
    } catch {
      $res.innerHTML = '<div class="empty">사전을 불러오지 못했습니다. ' +
        '네트워크를 확인하고 새로고침해 주세요.</div>';
    }
  }
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/* ── 검색 UI (기존 동작 그대로) ─────────────────────────────────── */

function showJamo(q, hits) {
  if (!q.trim()) { $jamo.classList.remove('on'); return; }
  $jamo.classList.add('on');
  const $raw = document.getElementById('j-raw');
  const $dec = document.getElementById('j-dec');
  const $key = document.getElementById('j-key');
  const lb0 = document.getElementById('lb0');
  const lb1 = document.getElementById('lb1');
  const lb2 = document.getElementById('lb2');
  const kbd = hits && hits[0] && hits[0].via === 'kbd';

  if (kbd) {
    lb0.textContent = '입력'; lb1.textContent = '자판 복구'; lb2.textContent = '검색어';
    $raw.textContent = q; $dec.textContent = '한글 모드로 입력된 영문';
    $key.innerHTML = '<em>' + hits[0].typed + '</em>';
    return;
  }
  if (!/[가-힣ㄱ-ㅎㅏ-ㅣ]/.test(q) && /[A-Za-z]/.test(q)) {
    lb0.textContent = '입력'; lb1.textContent = '방식'; lb2.textContent = '검색 키';
    $raw.textContent = q; $dec.textContent = '로마자 조회';
    $key.textContent = normEn(q);
    return;
  }
  lb0.textContent = '입력'; lb1.textContent = '자모 분해'; lb2.textContent = '정규화 키';
  $raw.textContent = q;
  $dec.textContent = [...q.normalize('NFD')].filter(c => !/\s/.test(c)).join(' ');
  const key = toJamo(q);
  const raw = [...q.normalize('NFD')].filter(c => !/\s/.test(c) && c !== 'ᄋ');
  $key.innerHTML = [...key].map(c => raw.includes(c) ? c : '<em>' + c + '</em>').join(' ');
}

function render(hits, q) {
  if (!q.trim()) {
    $res.innerHTML = '<div class="hint"><span>이렇게 검색해보세요.</span>' +
      '<div class="hint-examples" id="hintExamples">' +
      ['샤또 딸보', '디켐', '로칠드', '몬테풀치아노', "d'abruzzo", 'ㅊ뮫굳ㅅ']
        .map(e => '<button class="hint-chip" type="button">' + e + '</button>').join('') +
      '</div></div>';
    bindHints();
    return;
  }
  if (!hits.length) {
    $res.innerHTML = '<div class="empty">일치하는 항목이 없습니다. <b>정밀도</b>를 낮추거나, 사전에 없는 이름일 수 있습니다.</div>';
    return;
  }
  $res.innerHTML = hits.map(({ r, s, frag }) => {
    const cls = s >= 0.95 ? 's-hi' : s >= 0.85 ? 's-md' : 's-lo';
    const showVia = (frag && frag !== q) || r.ko !== r.p;
    const via = showVia
      ? '<span class="via">→ ' + (frag && frag !== q ? frag + ' · ' : '') + '<b>' + r.ko + '</b></span>'
      : '';
    return '<div class="hit">' +
      '<div class="score ' + cls + '">' + s.toFixed(2) + '</div>' +
      '<div class="body">' +
        '<div class="body-en">' + (r.d || r.en) + '</div>' +
        '<div class="body-ko">' + r.p + (via ? ' ' + via : '') + '</div>' +
      '</div>' +
      '<div class="meta"><span class="tag t-' + r.t + '">' + TYPE_NAME[r.t] +
        (r.tr ? ' · ' + r.tr : '') + '</span></div>' +
    '</div>';
  }).join('');
}

function bindHints() {
  document.querySelectorAll('.hint-chip').forEach(b => {
    b.addEventListener('click', () => { $q.value = b.textContent; run(); $q.focus(); });
  });
}

function run() {
  if (!matcher) return;           // 사전 적재 전 입력 — 적재되면 다시 호출된다
  const q = $q.value;
  const th = +$th.value / 100;
  const hits = matcher.scan(q, th, type);
  showJamo(q, hits);
  render(hits, q);
}

$q.addEventListener('input', run);
$th.addEventListener('input', () => { $thv.textContent = (+$th.value / 100).toFixed(2); run(); });
document.querySelectorAll('.chip').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); type = b.dataset.t; run();
}));
bindHints();

/* 편집 직후 관리 패널이 자기 변경을 바로 검색할 수 있게 한다 */
window.reloadDictionary = loadDictionary;

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js'));
}

loadDictionary();
