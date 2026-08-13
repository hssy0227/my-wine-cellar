/**
 * 한글 음차 표기 → 원어명 매칭 엔진 (런타임용).
 *
 * wine_match_test_v0.3.html 의 <script> 블록에서 추출했다.
 * docs/MIGRATION.md 3단계 참조.
 *
 * ※ 정규화 테이블은 src/matcher/jamo_matcher.py 와 반드시 일치해야 한다.
 *   사전 키(key_ko/key_en)는 빌드 시 Python이 만들고 조회 키는 여기서 만든다.
 *   어긋나면 에러 없이 매칭만 조용히 깨진다. tests/test_sync.py 가 자동 검증한다.
 *
 * 의존성 없음.
 */

/* ── 자모 정규화 (jamo_matcher.py의 CONSONANT_FOLD와 동일) ───────── */
export const CONS_FOLD = {
  'ᄁ':'ᄀ','ᄏ':'ᄀ','ᄄ':'ᄃ','ᄐ':'ᄃ','ᄈ':'ᄇ','ᄑ':'ᄇ','ᄍ':'ᄌ','ᄎ':'ᄌ','ᄊ':'ᄉ',
  'ᆨ':'ᄀ','ᆩ':'ᄀ','ᆿ':'ᄀ','ᆪ':'ᄀ','ᆫ':'ᄂ','ᆬ':'ᄂ','ᆭ':'ᄂ','ᆮ':'ᄃ','ᇀ':'ᄃ',
  'ᆯ':'ᄅ','ᆰ':'ᄅ','ᆱ':'ᄅ','ᆲ':'ᄅ','ᆳ':'ᄅ','ᆴ':'ᄅ','ᆵ':'ᄅ','ᆶ':'ᄅ','ᆷ':'ᄆ',
  'ᆸ':'ᄇ','ᇁ':'ᄇ','ᆹ':'ᄇ','ᆺ':'ᄉ','ᆻ':'ᄉ','ᆽ':'ᄌ','ᆾ':'ᄌ','ᇂ':'ᄒ'
};
// 반모음(y-)은 음차 표기에서 자유변이다. 쪼/쬬, 지아코모/자코모,
// 산지오베제/산조베제처럼 같은 원어를 두 가지로 옮기는 일이 흔하다.
export const VOW_FOLD = {'ᅢ':'ᅦ','ᅤ':'ᅨ','ᅬ':'ᅰ','ᅫ':'ᅰ',
                         'ᅣ':'ᅡ','ᅧ':'ᅥ','ᅭ':'ᅩ','ᅲ':'ᅮ','ᅨ':'ᅦ'};
export const CHEAP = new Set(['ᅳ','ᅮ','ᄅ']);

export function toJamo(s){
  let out='';
  for(const ch of s.normalize('NFD')){
    if(/\s/.test(ch) || '·-–—.,\'"()'.includes(ch)) continue;
    let c = CONS_FOLD[ch] || VOW_FOLD[ch] || ch;
    if(c === 'ᄋ') continue;          // 초성 이응은 음가 없음
    out += c;
  }
  return out;
}

export function dist(a,b){
  // Damerau-Levenshtein: 삽입·삭제·치환에 더해 인접 자모 자리바꿈을 0.6으로 센다.
  // '다브루초'와 '다부르초'는 ㅡ/ㅜ와 ㅗ/ㅜ가 뒤집힌 형태인데, 자리바꿈이
  // 없으면 삭제+삽입 2회로 계산돼 실제 체감보다 훨씬 멀어진다.
  const n=a.length, m=b.length;
  let prev2=null;
  let prev=new Float64Array(m+1);
  for(let j=1;j<=m;j++) prev[j]=prev[j-1]+(CHEAP.has(b[j-1])?0.3:1);
  for(let i=1;i<=n;i++){
    const cur=new Float64Array(m+1);
    cur[0]=prev[0]+(CHEAP.has(a[i-1])?0.3:1);
    for(let j=1;j<=m;j++){
      cur[j] = a[i-1]===b[j-1] ? prev[j-1]
        : Math.min(prev[j]+(CHEAP.has(a[i-1])?0.3:1),
                   cur[j-1]+(CHEAP.has(b[j-1])?0.3:1),
                   prev[j-1]+1);
      if(i>1 && j>1 && a[i-1]===b[j-2] && a[i-2]===b[j-1]){
        cur[j]=Math.min(cur[j], prev2[j-2]+0.6);
      }
    }
    prev2=prev; prev=cur;
  }
  return prev[m];
}

export const TYPE_NAME = {p:'생산자', r:'지역', g:'품종'};

/* ── 한영 자판 오입력 복구 ──────────────────────────────────
   영타로 치려다 한글 모드면 'cabernet'이 'ㅊㅁ며ㅜㄷㅅ'으로 들어온다.
   자모를 QWERTY 위치로 되돌려 영문 질의로 복원한다. */
export const JA2EN = {
  'ㅂ':'q','ㅃ':'Q','ㅈ':'w','ㅉ':'W','ㄷ':'e','ㄸ':'E','ㄱ':'r','ㄲ':'R',
  'ㅅ':'t','ㅆ':'T','ㅛ':'y','ㅕ':'u','ㅑ':'i','ㅐ':'o','ㅒ':'O','ㅔ':'p',
  'ㅖ':'P','ㅁ':'a','ㄴ':'s','ㅇ':'d','ㄹ':'f','ㅎ':'g','ㅗ':'h','ㅓ':'j',
  'ㅏ':'k','ㅣ':'l','ㅋ':'z','ㅌ':'x','ㅊ':'c','ㅍ':'v','ㅠ':'b','ㅜ':'n',
  'ㅡ':'m'
};
export const COMPLEX = {
  'ㄳ':'rt','ㄵ':'sw','ㄶ':'sg','ㄺ':'fr','ㄻ':'fa','ㄼ':'fq','ㄽ':'ft',
  'ㄾ':'fx','ㄿ':'fv','ㅀ':'fg','ㅄ':'qt','ㅘ':'hk','ㅙ':'ho','ㅚ':'hl',
  'ㅝ':'nj','ㅞ':'np','ㅟ':'nl','ㅢ':'ml'
};

const CHO_L = 'ᄀᄁᄂᄃᄄᄅᄆᄇᄈᄉᄊᄋᄌᄍᄎᄏᄐᄑᄒ';
const CHO_C2 = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
const JUNG_L = 'ᅡᅢᅣᅤᅥᅦᅧᅨᅩᅪᅫᅬᅭᅮᅯᅰᅱᅲᅳᅴᅵ';
const JUNG_C2 = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ';
const JONG_L = 'ᆨᆩᆪᆫᆬᆭᆮᆯᆰᆱᆲᆳᆴᆵᆶᆷᆸᆹᆺᆻᆼᆽᆾᆿᇀᇁᇂ';
const JONG_C2 = 'ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ';

export function jamoToCompat(ch){
  let i;
  if((i = CHO_L.indexOf(ch)) >= 0) return CHO_C2[i];
  if((i = JUNG_L.indexOf(ch)) >= 0) return JUNG_C2[i];
  if((i = JONG_L.indexOf(ch)) >= 0) return JONG_C2[i];
  return ch;
}

export function hangulToQwerty(s){
  let out = '';
  for(const ch of s.normalize('NFD')){
    if(/\s/.test(ch)){ out += ' '; continue; }
    // NFD 자모(초성/중성/종성)를 호환 자모로 되돌린 뒤 매핑
    const compat = jamoToCompat(ch);
    if(COMPLEX[compat]) out += COMPLEX[compat];
    else if(JA2EN[compat]) out += JA2EN[compat];
    else if(/[a-zA-Z0-9]/.test(ch)) out += ch;
    else return '';   // 매핑 불가 문자가 있으면 자판 오입력이 아니다
  }
  return out.trim();
}

/* 로마자 질의 정규화: 발음기호 제거, 소문자, 기호 제거 */
// scripts/build.py 의 EN_PREFIX_RE 와 문자 단위로 동일해야 한다.
// 'ch.'/'dom.'은 마침표를 요구한다 — Dom Pérignon 의 'Dom'은 Domaine 의 약어가
// 아니라 브랜드명의 일부라서, 맨단어 'dom'을 떼면 저장 키('dom perignon')와
// 조회 키('perignon')가 갈려 정확 매칭이 실패한다.
export const EN_PREFIX_RE =
  /^(chateau|ch\.|domaine|dom\.|tenuta|bodegas?|vina|vinedo|weingut|maison|casa|castello|quinta|marchesi|marques\s+de)\s+/i;

export function normEn(s){
  // 기호는 지우되 단어 사이 공백은 보존한다. 토큰 단위 비교(lookupEn)가
  // 이 공백에 의존하므로, 여기서 지워버리면 다어절 질의가 한 덩어리가 돼
  // 토큰 매칭이 항상 무력화된다.
  // 아포스트로피·하이픈은 단어를 가르지 않고 이어붙인다(d'Abruzzo,
  // Pontet-Canet). 공백으로 바꾸면 'd abruzzo'처럼 토큰이 갈라져
  // 아래 토큰 단위 매칭이 무력화된다. build.py의 search_key_en과
  // 반드시 같은 규칙이어야 한다 — 저장 키와 조회 키가 여기서 갈리면
  // 매칭 자체가 깨진다.
  return s.replace(EN_PREFIX_RE,'')
          .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
          .replace(/['’-]/g,'')
          .replace(/[^A-Za-z0-9\s]+/g,' ')
          .toLowerCase().trim().replace(/\s+/g,' ');
}

/**
 * 사전 데이터를 받아 조회 함수를 만든다.
 *
 * HTML 판은 모듈 스코프의 DATA를 클로저로 참조했다. 테스트와 재사용이
 * 가능하도록 데이터 주입형으로 바꿨다. 로직은 그대로다.
 *
 * @param {Array<{i,t,ko,p,en,d,tr,k,ke}>} data  data/dist/wine_terms.json
 */
export function createMatcher(data){
  const DATA = data;

  /* ── 인덱스 ─────────────────────────────────────────────────── */
  const EXACT = new Map();
  for(const r of DATA){
    if(!EXACT.has(r.k)) EXACT.set(r.k, []);
    EXACT.get(r.k).push(r);
  }
  // 한글 이름을 어절 단위로도 인덱싱한다.
  // r.k는 공백이 제거된 통짜 키라 '무동로지ᄅ드'처럼 붙어 있고, 접두사 매칭은
  // 문자열 앞에서만 일치를 보므로 '로칠드'(뒷어절)로는 절대 찾을 수 없다.
  // 어절별 자모 키를 미리 만들어 두면 뒷단어 검색이 가능해진다.
  // (세귀르, 밀롱, 바주, 샹베르탱 등 다어절 이름 전반에 해당하는 문제)
  const KT = new Map();
  for(const r of DATA){
    const toks = (r.ko||'').split(/[\s·]+/).filter(Boolean);
    if(toks.length < 2) continue;          // 한 어절이면 r.k와 동일
    KT.set(r, toks.map(toJamo).filter(t => t.length >= 2));
  }
  const EXACT_EN = new Map();
  for(const r of DATA){
    const k = (r.ke||'').replace(/\s+/g,'');
    if(!k) continue;
    if(!EXACT_EN.has(k)) EXACT_EN.set(k, []);
    EXACT_EN.get(k).push(r);
  }

  /* 영문(로마자) 조회 — 한글 조회와 같은 3단계 구조 */
  function lookupEn(q, th, type){
    const qk = normEn(q);
    if(qk.length < 2) return [];
    const pool = type==='all' ? DATA : DATA.filter(r=>r.t===type);
    const seen = new Map();
    const push = (r,s) => {
      const cur = seen.get(r.i);
      if(!cur || s > cur.s) seen.set(r.i, {r, s});
    };
    const qkFlat = qk.replace(/\s+/g,'');
    for(const r of (EXACT_EN.get(qkFlat)||[])){
      if(type==='all'||r.t===type) push(r,1);
    }

    // 토큰 단위 비교. 'ke'는 공백을 보존한 채로 저장돼 있다
    // ("trebbiano d abruzzo"). 이걸 통짜로 이어붙이면 'dabruzzo' 같은
    // 마지막 토큰이 22자짜리 덩어리 속 '부분 문자열'로만 잡혀 점수가
    // 낮게 나온다. 토큰 경계를 지켜야 짧은 질의도 정당하게 높은 점수를 받는다.
    let hadPrefix = false;
    const qToks = qk.split(/\s+/).filter(Boolean);
    for(const r of pool){
      const kRaw = r.ke || '';
      if(!kRaw) continue;
      const kToks = kRaw.split(/\s+/).filter(Boolean);
      // 하이픈 결합어(Calon-Segur, Clerc-Milon)는 검색 키에서 한 단어로
      // 붙지만, 사용자는 뒷부분만으로도 찾는다. 표시명에서 하이픈 조각을
      // 추가 토큰으로 뽑아 'segur', 'milon' 검색이 제값을 받게 한다.
      const hyphenParts = String(r.en||'').toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
        .split(/[^a-z0-9]+/).filter(t => t.length >= 3);
      for(const p of hyphenParts){
        if(!kToks.includes(p)) kToks.push(p);
      }
      const kFlat = kRaw.replace(/\s+/g,'');

      // 1) 전체 문자열 접두 일치 (기존 동작 유지: 'chateau margaux' 등)
      if(kFlat.length >= qkFlat.length && kFlat.startsWith(qkFlat)){
        hadPrefix = true;
        const s = 0.80 + 0.20*(qkFlat.length/kFlat.length);
        if(s >= th) push(r, s);
        continue;
      }

      // 2) 토큰 단위 일치. 질의가 한 단어면 대상의 '어느 한 토큰'과 비교한다.
      //    전체 길이가 아니라 그 토큰의 길이만으로 커버율을 매겨,
      //    긴 복합명(Montepulciano d'Abruzzo)에서도 짧은 질의가 불리하지 않다.
      if(qToks.length === 1){
        let best = 0;
        for(const t of kToks){
          if(t === qk){ best = Math.max(best, 0.97); }
          else if(t.length >= qk.length && t.startsWith(qk) && qk.length >= 2){
            best = Math.max(best, 0.84 + 0.13*(qk.length/t.length));
          }
        }
        if(best > 0){
          hadPrefix = true;
          if(best >= th) push(r, best);
          continue;
        }
      }

      // 3) 문자 단위 부분 포함 — 위 두 방식이 전부 실패했을 때만 쓰는 최후 수단
      if(kFlat.length > qkFlat.length && kFlat.includes(qkFlat) && qkFlat.length >= 3){
        hadPrefix = true;
        const s = 0.75 + 0.20*(qkFlat.length/kFlat.length);
        if(s >= th) push(r, s);
      }
    }
    // 오타 보정: 접두/부분 일치가 없을 때 돌린다.
    // 'cabernat'처럼 끝 한 글자만 틀리면 startsWith/includes가 전부 실패한다.
    // 대상이 길면(Cabernet Sauvignon) 전체 길이로 비교해도 유사도가 죽으므로,
    // 질의 길이만큼의 앞부분과도 비교해 접두 구간의 오타를 잡는다.
    if(seen.size === 0 && !hadPrefix){
      for(const r of pool){
        const k = (r.ke||'').replace(/\s+/g,'');
        if(!k) continue;
        // 오타 보정은 임계값보다 약간 관대하게. 슬라이더가 접두사 매칭
        // 정밀도를 조절하는 쪽이고, 오타는 애초에 후보가 없을 때만 돈다.
        // 오타 보정은 정밀도와 무관하게 일정 수준을 유지한다. 상한이 없으면
        // 정밀도를 올렸을 때 접두사 후보가 사라진 자리를 오타 후보가 채운다.
        const tol = Math.min(Math.max(th - 0.05, 0.55), 0.88);
        if(Math.abs(k.length-qkFlat.length) <= Math.max(qkFlat.length*0.5,3)){
          const s = 1 - dist(qkFlat,k)/Math.max(qkFlat.length,k.length);
          if(s>=tol) push(r,s);
        } else if(k.length > qkFlat.length && qkFlat.length >= 3){
          const head = k.slice(0, qkFlat.length);
          const s = 1 - dist(qkFlat,head)/qkFlat.length;
          if(s>=tol) push(r, s*0.95);   // 부분 일치이므로 약간 감점
        }
      }
    }
    return [...seen.values()]
      .sort((a,b)=> b.s-a.s || (a.r.ke||'').length-(b.r.ke||'').length)
      .slice(0,10);
  }

  function lookup(q, th, type, allowPrefix){
    const qk = toJamo(q);
    if(!qk) return [];
    const pool = type==='all' ? DATA : DATA.filter(r=>r.t===type);
    const seen = new Map();

    const push = (r,s) => {
      const cur = seen.get(r.i);
      if(!cur || s > cur.s) seen.set(r.i, {r, s});
    };
    // 1) 완전 일치
    for(const r of (EXACT.get(qk)||[])){
      if(type==='all'||r.t===type) push(r,1);
    }
    // 2) 접두사 일치 — 타이핑 중간 상태를 잡는다.
    //    편집거리만 쓰면 '몬테'와 '몬테풀치아노'는 뒷부분이 통째로 빠져
    //    유사도가 임계값 아래로 떨어져 후보에 아예 오르지 못한다.
    //    점수는 입력이 대상을 덮는 비율로 매겨, 짧은 이름이 위로 오게 한다.
    if(allowPrefix !== false && qk.length >= 2){
      for(const r of pool){
        // 전체 문자열 접두 일치
        if(r.k.length >= qk.length && r.k.startsWith(qk)){
          // 입력이 대상을 덮는 비율. 임계값을 올리면 '몬테'처럼 짧은 질의로
          // 딸려오던 긴 이름들이 먼저 잘려나가, 슬라이더가 실제로 동작한다.
          const cover = qk.length / r.k.length;
          const s = 0.80 + 0.20 * cover;
          if(s >= th) push(r, s);
          continue;
        }
        // 어절 단위 일치 — '로칠드'로 '무통 로칠드'를 찾기 위한 경로.
        // 점수는 그 어절 안에서의 덮는 비율로 매긴다. 이름 전체 길이로
        // 나누면 뒷어절 검색이 항상 불리해져 후보에 오르지 못한다.
        const kt = KT.get(r);
        if(kt){
          let best = 0;
          for(const t of kt){
            if(t === qk) best = Math.max(best, 0.95);
            else if(t.length > qk.length && t.startsWith(qk))
              best = Math.max(best, 0.82 + 0.13 * (qk.length / t.length));
          }
          if(best > 0 && best >= th) push(r, best);
        }
      }
    }
    // 3) 오타 보정 — 위에서 아무것도 못 찾았을 때만
    if(seen.size===0){
      for(const r of pool){
        if(Math.abs(r.k.length-qk.length) > Math.max(qk.length*0.4,3)) continue;
        const s = 1 - dist(qk,r.k)/Math.max(qk.length,r.k.length);
        if(s>=th) push(r,s);
      }
    }
    return [...seen.values()]
      .sort((a,b)=> b.s-a.s || a.r.k.length-b.r.k.length)
      .slice(0,10);
  }

  function scanKo(text, th, type){
    const toks = text.trim().split(/[\s·]+/).filter(Boolean);
    if(toks.length<=1) return lookup(text,th,type);
    const acc = new Map();
    // 전체 문자열 우선 조회. 5토큰짜리 고유명(샤토 스미스 오 라피트 블랑)은
    // n-gram 상한(3)에 걸려 조각으로는 절대 잡히지 않는다.
    // full=true로 표시해 아래 정렬에서 항상 최우선이 되게 한다. 점수만으로는
    // 부족하다 — '테누테 루비노'(전체 일치, 1.00)와 '루비노' 조각이 우연히
    // 겹치는 'Ruffino'(조각 일치, 1.00)가 동점이면 전체 일치가 이겨야 한다.
    for(const h of lookup(text,th,type,true)){
      acc.set(h.r.i, {...h, frag: text, full: true});
    }
    for(let n=Math.min(3,toks.length); n>=1; n--){
      for(let i=0;i+n<=toks.length;i++){
        const frag = toks.slice(i,i+n).join(' ');
        if(frag.replace(/\s/g,'').length<2) continue;
        // 조각 조회에서는 접두사 매칭을 끈다. '샤토 디샹'의 '샤토'가
        // 수백 개 샤토를 전부 후보로 끌어와 정답을 파묻기 때문.
        // 단 마지막 조각은 타이핑 중일 수 있으므로 허용한다.
        const isTail = (i + n === toks.length);
        for(const h of lookup(frag,th,type, isTail && n===1)){
          const cur = acc.get(h.r.i);
          if(!cur || (!cur.full && h.s>cur.s)) acc.set(h.r.i, {...h, frag});
        }
      }
    }
    return [...acc.values()]
      .sort((a,b)=> (b.full?1:0)-(a.full?1:0) || b.s-a.s || a.r.k.length-b.r.k.length)
      .slice(0,10);
  }

  /* 여러 단어로 된 와인명은 토큰 조각으로 훑는다 */
  function scan(text, th, type){
    const q = text.trim();
    if(!q) return [];

    const hasHangul = /[가-힣ㄱ-ㅎㅏ-ㅣ]/.test(q);
    const hasLatin  = /[A-Za-z]/.test(q);

    // 로마자 입력 → 영문 조회
    if(hasLatin && !hasHangul){
      const en = lookupEn(q, th, type);
      if(en.length) return en.map(h => ({...h, via:'en'}));
    }

    // 한글 입력이지만 자판 오입력일 수 있다 ('ㅊㅁ며ㅜㄷㅅ' = cabernet)
    if(hasHangul){
      const ko = scanKo(q, th, type);
      if(ko.length) return ko;
      const recovered = hangulToQwerty(q);
      if(recovered.length >= 2){
        const en = lookupEn(recovered, th, type);
        if(en.length) return en.map(h => ({...h, via:'kbd', typed:recovered}));
      }
      return [];
    }
    return scanKo(q, th, type);
  }

  return { scan, scanKo, lookup, lookupEn };
}
