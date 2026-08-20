/**
 * 사전 관리 패널 (톱니바퀴).
 *
 * 이전에는 data/seed/*.csv를 직접 fetch해 파싱했지만, 이제 원천은 Supabase다.
 * git의 CSV는 동기화 지연만큼 낡을 수 있으므로 /api/admin-list로 읽는다.
 * 그 엔드포인트가 비밀번호 게이트 뒤에 있어서, 패널을 열 때 한 번 인증하고
 * 세션 동안 재사용한다 — 제출할 때마다 다시 입력하는 것보다 낫다.
 *
 * 비밀번호는 sessionStorage에만 둔다(탭을 닫으면 사라진다). 어차피 서버가
 * 매 요청 검증하므로 클라이언트 보관은 편의일 뿐 권한이 아니다.
 */
const FILES = {
  grapes:    { label: '품종',   columns: ['name_en', 'name_ko', 'tier', 'region_group', 'ko_source', 'note'] },
  regions:   { label: '지역',   columns: ['name_en', 'name_ko', 'tier', 'region_group', 'ko_source', 'note'] },
  producers: { label: '생산자', columns: ['name_en', 'name_ko', 'tier', 'region_group', 'ko_source', 'note'] },
  aliases:   { label: '별칭',   columns: ['alias_ko', 'name_en', 'type', 'note'] },
};
const LABEL = {
  name_en: '원어명', name_ko: '한글명', tier: '등급/AVA', region_group: '권역',
  ko_source: '출처', note: '메모', alias_ko: '별칭(한글)', type: '타입',
};
const TYPE_LABEL = { grape: '품종', region: '지역', producer: '생산자' };
const PW_KEY = 'wine-admin-pw';

const state = { file: 'grapes', query: '', page: 0, pageSize: 50, rows: [] };

const $modal = document.getElementById('adminModal');
const $body = document.getElementById('adminBody');
const $title = document.getElementById('adminTitle');

const pw = () => sessionStorage.getItem(PW_KEY) || '';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

document.getElementById('adminGear').addEventListener('click', () => {
  $modal.showModal();
  pw() ? openList() : askPassword();
});
document.getElementById('adminClose').addEventListener('click', () => $modal.close());
$modal.addEventListener('click', (e) => { if (e.target === $modal) $modal.close(); });

async function api(path, payload) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw(), ...payload }),
  });
  const data = await res.json().catch(() => ({ ok: false, error: 'bad_response' }));
  if (res.status === 401) {
    sessionStorage.removeItem(PW_KEY);
    throw new Error('비밀번호가 틀렸습니다.');
  }
  return data;
}

/* ── 비밀번호 ──────────────────────────────────────────────────── */

function askPassword(message) {
  $title.textContent = '사전 관리';
  $body.innerHTML = `
    <form class="admin-form" id="pwForm">
      ${message ? `<div class="admin-banner err">${esc(message)}</div>` : ''}
      <div class="admin-field">
        <label for="pw">비밀번호</label>
        <input id="pw" type="password" autocomplete="current-password" required />
      </div>
      <p class="admin-note">사전을 편집하려면 인증이 필요합니다. 탭을 닫으면 다시 물어봅니다.</p>
      <div class="admin-actions"><button class="btn" type="submit">확인</button></div>
    </form>`;
  document.getElementById('pwForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    sessionStorage.setItem(PW_KEY, document.getElementById('pw').value);
    try {
      await openList();
    } catch (err) {
      askPassword(err.message);
    }
  });
  document.getElementById('pw').focus();
}

/* ── 목록 ──────────────────────────────────────────────────────── */

async function openList() {
  $title.textContent = '사전 관리';
  $body.innerHTML = '<p class="admin-note">불러오는 중…</p>';
  const data = await api('/api/admin-list', { file: state.file });
  if (!data.ok) throw new Error(data.message || '목록을 불러오지 못했습니다.');
  state.rows = data.rows;
  state.page = 0;
  drawList();
}

function drawList() {
  const cfg = FILES[state.file];
  const q = state.query.toLowerCase();
  const filtered = q
    ? state.rows.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(q)))
    : state.rows;
  const start = state.page * state.pageSize;
  const page = filtered.slice(start, start + state.pageSize);
  const pages = Math.max(1, Math.ceil(filtered.length / state.pageSize));

  const tabs = Object.keys(FILES).map(k =>
    `<button class="chip${k === state.file ? ' on' : ''}" type="button" data-tab="${k}">${FILES[k].label}</button>`).join('');
  const head = cfg.columns.map(c => `<th>${LABEL[c] || c}</th>`).join('');
  const body = page.map((r, i) => {
    const cells = cfg.columns.map(c => {
      const v = c === 'type' ? (TYPE_LABEL[r[c]] || r[c]) : r[c];
      return `<td>${esc(v)}</td>`;
    }).join('');
    return `<tr data-row="${start + i}">${cells}</tr>`;
  }).join('');

  $body.innerHTML = `
    <div class="admin-tabs">${tabs}</div>
    <div class="admin-toolbar">
      <input class="admin-search" id="adminSearch" type="text" placeholder="검색…" value="${esc(state.query)}" autocomplete="off" />
      <button class="btn" type="button" id="addBtn">+ 새 항목 추가</button>
    </div>
    <div class="admin-table-wrap">
      <table class="admin-table"><thead><tr>${head}</tr></thead><tbody>${
        body || `<tr><td colspan="${cfg.columns.length}" style="color:var(--muted);padding:20px 10px">결과 없음</td></tr>`
      }</tbody></table>
    </div>
    <div class="admin-pager">
      <button type="button" id="prev" ${state.page === 0 ? 'disabled' : ''}>이전</button>
      <span>${filtered.length ? start + 1 : 0}–${Math.min(start + state.pageSize, filtered.length)} / ${filtered.length}</span>
      <button type="button" id="next" ${state.page >= pages - 1 ? 'disabled' : ''}>다음</button>
    </div>`;

  $body.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', async () => {
    state.file = b.dataset.tab; state.query = '';
    try { await openList(); } catch (e) { askPassword(e.message); }
  }));
  document.getElementById('adminSearch').addEventListener('input', (e) => {
    state.query = e.target.value; state.page = 0; drawList();
  });
  document.getElementById('addBtn').addEventListener('click', () => openForm('add', null));
  document.getElementById('prev').addEventListener('click', () => { state.page--; drawList(); });
  document.getElementById('next').addEventListener('click', () => { state.page++; drawList(); });
  $body.querySelectorAll('[data-row]').forEach(tr => tr.addEventListener('click',
    () => openForm('edit', filtered[+tr.dataset.row])));
}

/* ── 폼 ────────────────────────────────────────────────────────── */

function openForm(action, existing) {
  const cfg = FILES[state.file];
  $title.textContent = `${cfg.label} ${action === 'add' ? '추가' : '수정'}`;

  const fields = cfg.columns.map(c => {
    const val = existing ? existing[c] : '';
    if (c === 'type') {
      const opts = Object.entries(TYPE_LABEL).map(([v, l]) =>
        `<option value="${v}" ${val === v ? 'selected' : ''}>${l}</option>`).join('');
      return `<div class="admin-field"><label for="f-${c}">${LABEL[c]}</label>
        <select id="f-${c}"><option value="">선택</option>${opts}</select></div>`;
    }
    return `<div class="admin-field"><label for="f-${c}">${LABEL[c] || c}</label>
      <input id="f-${c}" type="text" value="${esc(val)}" autocomplete="off" /></div>`;
  }).join('');

  $body.innerHTML = `
    <form class="admin-form" id="editForm">
      ${fields}
      <div class="admin-field">
        <label for="f-reason">편집 메모 (선택)</label>
        <textarea id="f-reason" placeholder="왜 이렇게 고치는지 짧게 남겨두면 나중에 도움이 됩니다"></textarea>
      </div>
      <p class="admin-note">제출하면 즉시 사전에 반영되고 배포 페이지에서 바로 검색됩니다.
        git에는 잠시 뒤 자동으로 동기화됩니다.</p>
      <div class="admin-actions">
        ${action === 'edit' ? '<button type="button" class="btn secondary" id="delBtn">삭제</button>' : ''}
        <button type="button" class="btn secondary" id="cancelBtn">취소</button>
        <button type="submit" class="btn" id="submitBtn">제출</button>
      </div>
    </form>`;

  document.getElementById('cancelBtn').addEventListener('click',
    () => openList().catch(e => askPassword(e.message)));
  document.getElementById('editForm').addEventListener('submit', (e) => {
    e.preventDefault();
    submit(action, existing);
  });
  const del = document.getElementById('delBtn');
  if (del) del.addEventListener('click', () => {
    const name = existing.name_en || existing.alias_ko;
    if (confirm(`'${name}' 을(를) 삭제할까요? 배포 페이지에서 즉시 사라집니다.`)) {
      submit('delete', existing);
    }
  });
}

function matchOf(existing) {
  return state.file === 'aliases'
    ? { alias_ko: existing.alias_ko, name_en: existing.name_en, type: existing.type }
    : { name_en: existing.name_en };
}

async function submit(action, existing, opts = {}) {
  const cfg = FILES[state.file];
  // 확인 인터스티셜을 거쳐 돌아온 경우, 폼이 이미 화면에서 사라졌으므로
  // 처음 제출할 때 읽어둔 값을 그대로 다시 쓴다.
  const row = opts.row || {};
  if (!opts.row && action !== 'delete') {
    cfg.columns.forEach(c => { row[c] = document.getElementById('f-' + c).value.trim(); });
  }
  const reasonEl = document.getElementById('f-reason');
  const reason = opts.reason !== undefined ? opts.reason : (reasonEl ? reasonEl.value.trim() : '');
  const btn = document.getElementById('submitBtn');
  if (btn) { btn.disabled = true; btn.textContent = '제출 중…'; }

  try {
    const data = await api('/api/admin-submit', {
      reason,
      confirm_audit: !!opts.confirmAudit,
      changes: [{
        file: state.file, action, row,
        match: action === 'add' ? null : matchOf(existing),
      }],
    });
    if (data.error === 'confirm_required') {
      confirmAudit(data, action, existing, row, reason);
      return;
    }
    showResult(data);
  } catch (err) {
    askPassword(err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '제출'; }
  }
}

/**
 * 원어명 유실 의심 확인 화면.
 *
 * 이 프로젝트에서 실제로 났던 사고가 이 유형이다 — "모스카토 다스티"가
 * "Moscato"로 저장돼도 검색은 멀쩡히 되고 결과만 틀렸다. 다른 경고와 달리
 * 이것만은 손을 멈추게 한다.
 */
function confirmAudit(data, action, existing, row, reason) {
  $title.textContent = '확인이 필요합니다';
  const lines = Object.entries(data.issues)
    .map(([k, v]) => `<b>${esc(k)}</b><br>` +
      v.slice(0, 5).map(x => '· ' + esc(x)).join('<br>')).join('<br><br>');
  $body.innerHTML = `
    <div class="admin-banner warn">${lines}</div>
    <p class="admin-note">한글명은 여러 어절인데 원어명이 짧으면 일부가 빠진 것일 수 있습니다.
      예를 들어 <b>모스카토 다스티</b>의 원어는 <b>Moscato</b>가 아니라
      <b>Moscato d'Asti</b>입니다. 검색은 되지만 결과가 조용히 틀리게 됩니다.<br><br>
      의도한 표기가 맞다면 그대로 진행하세요.</p>
    <div class="admin-actions">
      <button type="button" class="btn secondary" id="fixBtn">돌아가서 고치기</button>
      <button type="button" class="btn" id="proceedBtn">확인했습니다 · 그대로 진행</button>
    </div>`;
  document.getElementById('fixBtn').addEventListener('click',
    () => { openForm(action, existing); restoreForm(row, reason); });
  document.getElementById('proceedBtn').addEventListener('click',
    () => submit(action, existing, { row, reason, confirmAudit: true }));
}

function restoreForm(row, reason) {
  Object.entries(row).forEach(([k, v]) => {
    const el = document.getElementById('f-' + k);
    if (el) el.value = v;
  });
  const r = document.getElementById('f-reason');
  if (r) r.value = reason || '';
}

function showResult(data) {
  $title.textContent = data.ok ? '완료' : '실패';
  let html;
  if (data.ok) {
    const a = data.audit || {};
    const warn = (data.warnings || []).length
      ? `<div class="admin-banner warn">${data.warnings.map(esc).join('<br>')}</div>` : '';
    const issues = a.new_issue_count
      ? `<div class="admin-banner warn">이번 변경으로 무결성 경고 ${a.new_issue_count}건이 새로 생겼습니다:<br>` +
        Object.entries(a.new_issues).map(([k, v]) =>
          `<b>${esc(k)}</b> — ${v.slice(0, 3).map(esc).join(' / ')}`).join('<br>') + '</div>'
      : '';
    const sync = data.git_sync_requested === false
      ? '<div class="admin-banner warn">git 동기화 신호를 보내지 못했습니다. 야간 자동 동기화가 처리합니다.</div>' : '';
    html = `<div class="admin-banner ok">사전이 갱신됐습니다 · v${esc(data.version)} ·
      ${(data.rows || 0).toLocaleString()}개 표기</div>${warn}${issues}${sync}`;
    if (window.reloadDictionary) window.reloadDictionary();
  } else {
    const msg = data.error === 'unauthorized' ? '비밀번호가 틀렸습니다.'
      : (data.message || '알 수 없는 오류입니다.');
    html = `<div class="admin-banner err">${esc(msg)}</div>`;
  }
  $body.innerHTML = html +
    '<div class="admin-actions"><button type="button" class="btn secondary" id="backBtn">목록으로</button></div>';
  document.getElementById('backBtn').addEventListener('click',
    () => openList().catch(e => askPassword(e.message)));
}
