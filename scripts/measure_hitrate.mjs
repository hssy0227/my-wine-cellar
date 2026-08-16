// 실제 셀러 데이터로 매칭 히트율을 측정한다.
// REQUIREMENTS.md 성공 기준 1번: "실제 셀러 와인 30개... 80% 이상이 원어명으로 잡힌다"
// (지금까지는 신의 물방울/파커 등 프록시 데이터로만 검증했다.)
//
// data/cellar_sample.txt (한 줄에 한 와인, 셀러에 있는 그대로의 한글 표기)를 읽어
// demo/index.html과 동일한 기본값(th=0.85, type=all)으로 top-3 후보를 출력한다.
// "맞았다/틀렸다" 판정은 사람이 실제 병과 대조해야 하므로 이 스크립트는 하지 않는다.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createMatcher, TYPE_NAME } from '../src/matcher/matcher.js';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const TH = 0.85; // demo/index.html의 슬라이더 기본값과 동일

const DATA = JSON.parse(readFileSync(path.join(ROOT, 'data/dist/wine_terms.json'), 'utf8'));
const matcher = createMatcher(DATA);

const listPath = process.argv[2] || path.join(ROOT, 'data/cellar_sample.txt');
const queries = readFileSync(listPath, 'utf8')
  .split('\n')
  .map(s => s.trim())
  .filter(Boolean);

let hitCount = 0;
for (const q of queries) {
  const hits = matcher.scan(q, TH, 'all');
  const top = hits.slice(0, 3);
  if (top.length > 0) hitCount++;
  const status = top.length > 0 ? '히트' : '미스';
  console.log(`\n[${status}] ${q}`);
  if (top.length === 0) {
    console.log('  (후보 없음)');
  } else {
    for (const h of top) {
      console.log(
        `  ${h.s.toFixed(2)}  ${h.r.d || h.r.en}  [${TYPE_NAME[h.r.t]}]  ← ${h.r.p}`
      );
    }
  }
}

console.log(`\n---`);
console.log(`후보 1개 이상 반환: ${hitCount}/${queries.length} (${(100 * hitCount / queries.length).toFixed(0)}%)`);
console.log(`※ 이 비율은 "후보가 나왔는가"이지 "정답인가"가 아니다. 위 목록에서 실제 병과 대조해 확인할 것.`);
