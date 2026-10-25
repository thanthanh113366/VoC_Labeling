/* =====================================================================
   Web gán nhãn VoC — frontend thuần JS
   Schema bám sát sheet GanNhan của Mau_thu_100_review_VoC.xlsx
   ===================================================================== */

const S = {
  annotator: localStorage.getItem('voc.annotator') || 'A',
  meta: null,
  reviews: [],
  current: null,      // review đang mở
  units: [],          // model đang sửa
  pendingSel: null,   // {start,end,text} vùng chọn chờ tạo unit
  evidenceMode: null, // {ui, ii} đang chờ chọn bằng chứng
  tab: 'label',
  adjCurrent: null,
  me: null,          // {username, annotator, display_name, auth_required}
};

/* ---------- utils ---------- */
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
const cpArr = (s) => Array.from(s);
const cpLen = (s) => Array.from(s).length;

/** code point offset -> slice (JS string) */
function sliceCP(text, a, b) {
  return cpArr(text).slice(a, b).join('');
}

function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'on' + (isErr ? ' err' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => { t.className = ''; }, 2200);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.headers.get('content-type')?.includes('json') ? r.json() : r.text();
}

/* ---------- selection ---------- */
function utf16LenPrefix(full, utf16Idx) {
  // đếm code point của đoạn full[0:utf16Idx]
  return cpLen(full.slice(0, utf16Idx));
}

function selectionSpan() {
  const box = $('revText');
  if (!box || !S.current) return null;
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!box.contains(range.commonAncestorContainer)) return null;

  const pre = document.createRange();
  pre.selectNodeContents(box);
  pre.setEnd(range.startContainer, range.startOffset);
  const start16 = pre.toString().length;

  const selected = range.toString();
  if (!selected.trim()) return null;

  const text = S.current.text;
  const start = utf16LenPrefix(text, start16);
  const end = start + cpLen(selected);
  if (start < 0 || end > cpLen(text) || start >= end) return null;
  return { start, end, text: sliceCP(text, start, end) };
}

function onSelectCapture() {
  const sp = selectionSpan();
  if (!sp) return;

  if (S.evidenceMode) {
    const { ui, ii } = S.evidenceMode;
    const iss = S.units[ui]?.issues?.[ii];
    if (iss) {
      iss.ev_start = sp.start;
      iss.ev_end = sp.end;
      iss.evidence = sp.text;
      S.evidenceMode = null;
      renderUnits();
      toast('Đã đặt bằng chứng');
    }
    return;
  }
  S.pendingSel = sp;
  updateSelHint();
}

function updateSelHint() {
  const el = $('selHint');
  if (!el) return;
  if (S.pendingSel) {
    const n = cpLen(S.pendingSel.text);
    el.innerHTML = `Đã chọn <b>${n}</b> ký tự — bấm <b>Tạo unit</b> (hoặc Ctrl+Enter).`;
  } else {
    el.textContent = 'Bôi đen một đoạn trong review để tạo unit.';
  }
}

/* ---------- load ---------- */
async function boot() {
  const B = window.__BOOT__;
  if (B && B.meta) {
    // dữ liệu đã được server nhúng vào HTML -> vẽ ngay, không chờ fetch
    S.meta = B.meta;
    S.reviews = B.reviews || [];
    S.me = B.me || null;
    if (S.me && S.me.auth_required && S.me.annotator) S.annotator = S.me.annotator;
    $('sourceSub').textContent =
      `${S.meta.total_reviews} review · nguồn: ${S.meta.source_file}`;
    $('guideText').innerHTML = renderGuide(S.meta.guide);
    if (B.current) {
      S.current = B.current;
      S.units = (B.current.units || []).map(normalizeUnit);
    }
    renderReviewList();
    renderAdjList();
    updateProgress();
    if (S.current) renderEditor();
    applyAnnotatorUI();
    if (S.annotator !== ((B.me && B.me.annotator) || 'A')) loadReviews().catch(() => {});
    if (location.hash && !S.current) {
      openReview(decodeURIComponent(location.hash.slice(1))).catch(() => {});
    }
    return;
  }

  S.meta = await api('/api/meta');
  try { S.me = await api('/api/me'); } catch (e) { S.me = null; }
  if (S.me && S.me.auth_required && S.me.annotator) S.annotator = S.me.annotator;
  $('sourceSub').textContent =
    `${S.meta.total_reviews} review · nguồn: ${S.meta.source_file}`;
  $('guideText').innerHTML = renderGuide(S.meta.guide);
  await loadReviews();
  applyAnnotatorUI();
}

function renderGuide(txt) {
  return String(txt || '')
    .split('\n').filter(Boolean)
    .map((line) => {
      const i = line.indexOf('  —  ');
      if (i > 0) {
        return `<div style="margin:6px 0"><b>${esc(line.slice(0, i))}</b> — ${esc(line.slice(i + 5))}</div>`;
      }
      return `<div style="margin:6px 0">${esc(line)}</div>`;
    }).join('');
}

async function loadReviews() {
  S.reviews = await api(`/api/reviews?annotator=${S.annotator}`);
  renderReviewList();
  renderAdjList();
  updateProgress();
}

function updateProgress() {
  const done = S.reviews.filter((r) => Number(r.n_rows) > 0).length;
  $('progText').textContent = `${done}/${S.reviews.length}`;
  $('progBar').style.width = (100 * done / Math.max(1, S.reviews.length)) + '%';
}

function renderReviewList() {
  const groups = {};
  S.reviews.forEach((r) => {
    (groups[r.case_id] = groups[r.case_id] || []).push(r);
  });
  let html = '';
  Object.keys(groups).forEach((caseId) => {
    html += `<div class="case-group"><div class="case-title">${esc(caseId)}</div>`;
    groups[caseId].forEach((r) => {
      const cls = Number(r.n_rows) > 0 ? 'done' : '';
      const on = S.current && S.current.review_id === r.review_id ? ' on' : '';
      html += `<div class="rv${on}" data-rid="${esc(r.review_id)}">
        <span class="dot ${cls}"></span>
        <span class="id">${esc(r.review_id)}</span>
        <span class="meta">${esc(r.length || '')} · ${esc(r.n_words || '')}w</span>
      </div>`;
    });
    html += '</div>';
  });
  $('reviewList').innerHTML = html;
}

/* ---------- editor ---------- */
async function openReview(rid) {
  const rev = await api(`/api/reviews/${rid}?annotator=${S.annotator}`);
  S.current = rev;
  S.units = (rev.units || []).map(normalizeUnit);
  S.pendingSel = null;
  S.evidenceMode = null;
  renderEditor();
  renderReviewList();
}

function normalizeUnit(u) {
  return {
    unit_id: u.unit_id || 'u?',
    start: Number(u.start),
    end: Number(u.end),
    text: u.text || '',
    sentiment: u.sentiment || '',
    issue_present: u.issue_present || 'no',
    can_thao_luan: u.can_thao_luan || '',
    ghi_chu: u.ghi_chu || '',
    issues: (u.issues || []).map((i) => ({
      category: i.category || '',
      severity: i.severity || '',
      ev_start: i.ev_start ?? null,
      ev_end: i.ev_end ?? null,
      evidence: i.evidence || '',
    })),
  };
}

function nextUnitId() {
  let max = 0;
  S.units.forEach((u) => {
    const m = /^u(\d+)$/.exec(u.unit_id);
    if (m) max = Math.max(max, +m[1]);
  });
  return 'u' + (max + 1);
}

function renderEditor() {
  const r = S.current;
  if (!r) return;
  const lenCls = 'chip len-' + (r.length || '');
  $('editor').innerHTML = `
    <div class="card">
      <div class="rev-head">
        <span class="rid">${esc(r.review_id)}</span>
        <span class="chip">${esc(r.case_id)}</span>
        <span class="chip">${esc(r.provider)}</span>
        <span class="chip">${esc(r.source)}</span>
        <span class="chip">${esc(String(r.date || '').slice(0, 10))}</span>
        <span class="${lenCls}">${esc(r.length || '')}</span>
        <span class="chip">${esc(r.n_words || '')} từ</span>
        <span class="chip">${esc(r.country || '')}</span>
      </div>

      <div id="revText"></div>

      <div class="toolbar">
        <button class="btn primary" id="btnAddUnit">+ Tạo unit từ vùng chọn</button>
        <span class="hint" id="selHint"></span>
      </div>
      <div class="mode-banner" id="modeBanner"></div>
    </div>

    <div id="unitHost"></div>

    <div style="display:flex;gap:10px;align-items:center">
      <button class="btn primary" id="btnSave">Lưu nhãn (Ctrl+S)</button>
      <button class="btn" id="btnNext">Review tiếp theo →</button>
      <span class="hint" id="saveHint"></span>
    </div>
  `;
  renderReviewText();
  renderUnits();
  updateSelHint();
  renderModeBanner();
}

/** vẽ text + highlight unit và bằng chứng (offset là code point) */
function renderReviewText() {
  const box = $('revText');
  const text = S.current.text;
  const marks = [];
  S.units.forEach((u, ui) => {
    marks.push({ s: u.start, e: u.end, cls: 'hl' });
    (u.issues || []).forEach((iss) => {
      if (iss.ev_start != null && iss.ev_end != null) {
        marks.push({ s: iss.ev_start, e: iss.ev_end, cls: 'hl evidence' });
      }
    });
  });
  const total = cpLen(text);
  const pts = new Set([0, total]);
  marks.forEach((m) => {
    if (m.s >= 0 && m.e <= total && m.s < m.e) { pts.add(m.s); pts.add(m.e); }
  });
  const sorted = [...pts].sort((a, b) => a - b);
  let html = '';
  for (let k = 0; k < sorted.length - 1; k++) {
    const a = sorted[k], b = sorted[k + 1];
    const act = marks.filter((m) => m.s <= a && m.e >= b);
    const seg = esc(sliceCP(text, a, b));
    if (act.length) {
      const cls = act.map((m) => m.cls).join(' ');
      html += `<span class="${cls}">${seg}</span>`;
    } else {
      html += seg;
    }
  }
  box.innerHTML = html;
}

function renderModeBanner() {
  const b = $('modeBanner');
  if (!b) return;
  if (S.evidenceMode) {
    b.className = 'mode-banner on';
    b.innerHTML = `Đang chọn <b>bằng chứng</b> — bôi đen đoạn văn trong review. 
      <button class="btn sm" id="btnCancelMode" style="margin-left:8px">Hủy</button>`;
    $('btnCancelMode').onclick = () => { S.evidenceMode = null; renderModeBanner(); };
  } else {
    b.className = 'mode-banner';
    b.innerHTML = '';
  }
}

function catLabel(key) {
  const c = (S.meta.categories || []).find((x) => x.key === key);
  return c ? c.label : key;
}

function opt(list, cur, ph) {
  let h = `<option value="">${esc(ph || '—')}</option>`;
  list.forEach((v) => {
    const val = typeof v === 'string' ? v : v.key;
    const lab = typeof v === 'string' ? v : v.label;
    h += `<option value="${esc(val)}" ${val === cur ? 'selected' : ''}>${esc(lab)}</option>`;
  });
  return h;
}

function unitCardHtml(u, ui) {
  const hasIssue = u.issue_present === 'yes';
  let issuesHtml = '';
  if (hasIssue) {
    const issues = u.issues.length ? u.issues : [emptyIssue()];
    if (!u.issues.length) u.issues = issues;
    issuesHtml = `<div class="issues">
      ${issues.map((iss, ii) => issueHtml(iss, ui, ii)).join('')}
      <button class="btn sm" data-act="add-issue" data-ui="${ui}">+ Thêm nhóm lỗi</button>
    </div>`;
  }
  return `<div class="unit">
    <div class="unit-head">
      <span class="unit-id">${esc(u.unit_id)}</span>
      <span class="unit-text">${esc(u.text)}</span>
      <span class="hint" style="white-space:nowrap">[${u.start},${u.end})</span>
      <button class="btn sm danger" data-act="del-unit" data-ui="${ui}">Xóa</button>
    </div>
    <div class="unit-body">
      <div class="grid">
        <label class="fld">Sentiment
          <select data-act="set" data-field="sentiment" data-ui="${ui}">
            ${opt(S.meta.sentiments, u.sentiment, '— chọn —')}
          </select>
        </label>
        <label class="fld">Có vấn đề?
          <select data-act="set" data-field="issue_present" data-ui="${ui}">
            ${opt(['yes', 'no'], u.issue_present, '— chọn —')}
          </select>
        </label>
        <label class="fld">Cần thảo luận
          <select data-act="set" data-field="can_thao_luan" data-ui="${ui}">
            ${opt([{key:'',label:'không'},{key:'yes',label:'yes'}], u.can_thao_luan, 'không')}
          </select>
        </label>
        <label class="fld">Ghi chú
          <input type="text" data-act="note" data-ui="${ui}"
                 value="${esc(u.ghi_chu)}" placeholder="ngắn gọn">
        </label>
      </div>
      ${issuesHtml}
    </div>
  </div>`;
}

function emptyIssue() {
  return { category: '', severity: '', ev_start: null, ev_end: null, evidence: '' };
}

function issueHtml(iss, ui, ii) {
  const hasEv = iss.ev_start != null;
  const evBlock = hasEv
    ? `<div class="evbox">
         <span class="hint">Bằng chứng [${iss.ev_start},${iss.ev_end})</span>
         <div class="evtext">${esc(iss.evidence)}</div>
         <button class="btn sm" data-act="clr-ev" data-ui="${ui}" data-ii="${ii}">Xóa bằng chứng</button>
       </div>`
    : `<div class="evbox">
         <span class="hint">Bằng chứng</span>
         <div class="evtext empty">chưa chọn</div>
         <button class="btn sm" data-act="pick-ev" data-ui="${ui}" data-ii="${ii}">Chọn bằng chứng</button>
       </div>`;

  return `<div class="issue">
    <label class="fld">Nhóm lỗi
      <select data-act="set-issue" data-field="category" data-ui="${ui}" data-ii="${ii}">
        ${opt(S.meta.categories, iss.category, '— chọn —')}
      </select>
    </label>
    <label class="fld">Severity
      <select data-act="set-issue" data-field="severity" data-ui="${ui}" data-ii="${ii}">
        ${opt(S.meta.severities, iss.severity, '— chọn —')}
      </select>
    </label>
    ${evBlock}
    <button class="btn sm danger" data-act="del-issue" data-ui="${ui}" data-ii="${ii}">✕</button>
  </div>`;
}

function renderUnits() {
  const host = $('unitHost');
  if (!host) return;
  if (!S.units.length) {
    host.innerHTML = `<div class="card empty-state">
      Chưa có unit nào. Bôi đen đoạn văn trong review rồi bấm <b>+ Tạo unit từ vùng chọn</b>.
    </div>`;
    return;
  }
  host.innerHTML = S.units.map((u, i) => unitCardHtml(u, i)).join('');
}

/* ---------- unit actions ---------- */
function addUnitFromSelection() {
  const sp = S.pendingSel;
  if (!sp) { toast('Hãy bôi đen một đoạn trong review trước.', true); return; }
  const overlap = S.units.find((u) => !(sp.end <= u.start || sp.start >= u.end));
  if (overlap) { toast(`Chồng lấn với ${overlap.unit_id}`, true); return; }
  if (S.units.some((u) => u.start === sp.start && u.end === sp.end)) {
    toast('Đoạn này đã là unit rồi.', true); return;
  }
  S.units.push({
    unit_id: nextUnitId(),
    start: sp.start, end: sp.end, text: sp.text,
    sentiment: '', issue_present: 'no', can_thao_luan: '', ghi_chu: '',
    issues: [],
  });
  S.pendingSel = null;
  renderReviewText();
  renderUnits();
  updateSelHint();
}

function collectPayload() {
  return {
    units: S.units.map((u) => ({
      unit_id: u.unit_id,
      start: u.start,
      end: u.end,
      sentiment: u.sentiment,
      issue_present: u.issue_present,
      can_thao_luan: u.can_thao_luan,
      ghi_chu: u.ghi_chu,
      issues: (u.issue_present === 'yes' ? u.issues : []).map((i) => ({
        category: i.category,
        severity: i.severity,
        ev_start: i.ev_start,
        ev_end: i.ev_end,
        can_thao_luan: u.can_thao_luan,
        ghi_chu: u.ghi_chu,
      })),
    })),
  };
}

async function saveCurrent() {
  if (!S.current) return;
  try {
    $('saveHint').textContent = 'đang lưu…';
    const out = await api(
      `/api/reviews/${S.current.review_id}?annotator=${S.annotator}`,
      { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectPayload()) }
    );
    $('saveHint').textContent = `đã lưu ${out.rows} dòng`;
    toast(`Đã lưu ${S.current.review_id} (${out.rows} dòng)`);
    await loadReviews();
  } catch (e) {
    $('saveHint').textContent = 'lỗi lưu';
    toast('Lỗi: ' + e.message, true);
  }
}

function gotoNext() {
  const list = S.reviews;
  const idx = list.findIndex((r) => S.current && r.review_id === S.current.review_id);
  const next = list[idx + 1] || list[0];
  if (next) openReview(next.review_id);
}

/* ---------- adjudication ---------- */
function renderAdjList() {
  const host = $('adjList');
  if (!host) return;
  // hiện review đã có nhãn của A hoặc B
  const rows = S.reviews.filter((r) => (Number(r.n_rows_a) + Number(r.n_rows_b)) > 0);
  host.innerHTML = rows.length
    ? rows.map((r) => {
        const both = Number(r.n_rows_a) > 0 && Number(r.n_rows_b) > 0;
        const cls = both ? 'done' : 'part';
        const who = `A:${Number(r.n_rows_a) > 0 ? '✓' : '—'} B:${Number(r.n_rows_b) > 0 ? '✓' : '—'}`;
        return `<div class="rv" data-adj="${esc(r.review_id)}">
        <span class="dot ${cls}"></span>
        <span class="id">${esc(r.review_id)}</span>
        <span class="meta">${esc(who)}</span>
      </div>`;
      }).join('')
    : `<div class="empty-state" style="padding:24px">Chưa có review nào được gán.</div>`;
}

function miniUnits(units) {
  if (!units || !units.length) return `<div class="hint">(trống)</div>`;
  return units.map((u) => {
    const tags = [`<span class="tag ${u.sentiment === 'positive' ? 'pos' : u.sentiment === 'negative' ? 'neg' : 'neu'}">${esc(u.sentiment || '?')}</span>`];
    if (u.issue_present === 'yes') {
      if (!u.issues.length) tags.push('<span class="tag">uncertain</span>');
      u.issues.forEach((i) => {
        tags.push(`<span class="tag">${esc(catLabel(i.category) || '(chưa chọn)')}</span>`);
        if (i.severity) tags.push(`<span class="tag ${esc(i.severity)}">${esc(i.severity)}</span>`);
      });
    } else {
      tags.push('<span class="tag low">không có vấn đề</span>');
    }
    const ev = u.issues.find((i) => i.evidence)
      ? `<div class="evtext" style="margin-top:5px">${esc(u.issues.find((i) => i.evidence).evidence)}</div>` : '';
    return `<div class="mini-unit">
      <div class="t">${esc(u.text)}</div>
      <div>${tags.join('')}</div>
      ${ev}
    </div>`;
  }).join('');
}

async function openAdjudicate(rid) {
  const rev = await api(`/api/adjudicate/${rid}`);
  S.adjCurrent = rev;
  const decided = rev.decision
    ? `<span class="chip" style="background:#e6fcf5;color:#0b7285">đã có quyết định (${esc(rev.adjudicator || '')})</span>`
    : `<span class="chip">chưa có quyết định</span>`;
  $('adjPane').innerHTML = `
    <div class="card">
      <div class="rev-head">
        <span class="rid">${esc(rev.review_id)}</span>
        <span class="chip">${esc(rev.case_id)}</span>
        <span class="chip">${esc(rev.provider)}</span>
        ${decided}
      </div>
      <div style="white-space:pre-wrap;line-height:1.7;background:#fbfcfd;border:1px dashed #d7dee8;
                  border-radius:10px;padding:12px 14px">${esc(rev.text)}</div>
    </div>
    <div class="adj-grid">
      <div class="adj-col">
        <h3>Người A</h3>
        ${miniUnits(rev.sides.A)}
        <button class="btn" data-choose="A">Dùng kết quả A</button>
      </div>
      <div class="adj-col">
        <h3>Người B</h3>
        ${miniUnits(rev.sides.B)}
        <button class="btn" data-choose="B">Dùng kết quả B</button>
      </div>
    </div>`;
  document.querySelectorAll('[data-choose]').forEach((b) => {
    b.onclick = () => saveDecision(rev, b.dataset.choose);
  });
}

async function saveDecision(rev, side) {
  const units = rev.sides[side] || [];
  try {
    const out = await api(`/api/adjudicate/${rev.review_id}?adjudicator=ADJ`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ units }),
    });
    if (out.ok) {
      toast(`Đã lưu quyết định cho ${rev.review_id} (theo ${side})`);
      openAdjudicate(rev.review_id);
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, true);
  }
}

/* ---------- annotator / tabs ---------- */
function applyAnnotatorUI() {
  const authOn = !!(S.me && S.me.auth_required);
  const canAdjudicate = !authOn || (S.me && S.me.annotator === 'ADJ');
  document.querySelectorAll('[data-ann]').forEach((b) => {
    b.classList.toggle('on', b.dataset.ann === S.annotator);
    b.style.display = authOn ? 'none' : '';
  });
  const chip = $('userChip');
  if (chip) {
    if (authOn && S.me) {
      const role = S.me.annotator === 'ADJ' ? 'hòa giải' : ('người ' + S.me.annotator);
      chip.textContent = (S.me.display_name || S.me.username) + ' · ' + role;
      chip.style.display = '';
    } else {
      chip.style.display = 'none';
    }
  }
  if (!canAdjudicate && S.tab === 'adj') S.tab = 'label';
  document.querySelectorAll('[data-tab]').forEach((b) => {
    if (b.dataset.tab === 'adj') b.style.display = canAdjudicate ? '' : 'none';
    b.classList.toggle('on', b.dataset.tab === S.tab);
  });
  $('tabLabel').style.display = S.tab === 'label' ? '' : 'none';
  $('tabAdj').style.display = S.tab === 'adj' ? '' : 'none';
  $('tabGuide').style.display = S.tab === 'guide' ? '' : 'none';
  const lo = $('btnLogout');
  if (lo) lo.style.display = (S.meta && S.meta.auth_required) ? '' : 'none';
}

async function switchAnnotator(a) {
  if (S.me && S.me.auth_required) return;   // vai do tài khoản quyết định
  if (S.annotator === a) return;
  if (S.current) {
    const ok = confirm(`Chuyển sang Người ${a}? Nhãn chưa lưu của Người ${S.annotator} sẽ mất.`);
    if (!ok) return;
  }
  S.annotator = a;
  localStorage.setItem('voc.annotator', a);
  S.current = null;
  S.units = [];
  S.pendingSel = null;
  S.evidenceMode = null;
  applyAnnotatorUI();
  $('editor').innerHTML = `<div class="empty-state"><b>Chọn một review ở cột trái.</b></div>`;
  await loadReviews();
  toast(`Đang gán với tư cách Người ${a}`);
}

/* ---------- events ---------- */
document.addEventListener('click', async (e) => {
  const t = e.target;

  const rv = t.closest('[data-rid]');
  if (rv && S.tab === 'label') { openReview(rv.dataset.rid); return; }

  const adj = t.closest('[data-adj]');
  if (adj) { openAdjudicate(adj.dataset.adj); return; }

  const ann = t.closest('[data-ann]');
  if (ann) { switchAnnotator(ann.dataset.ann); return; }

  const tab = t.closest('[data-tab]');
  if (tab) { S.tab = tab.dataset.tab; applyAnnotatorUI(); return; }

  if (t.id === 'btnAddUnit') { addUnitFromSelection(); return; }
  if (t.id === 'btnSave') { saveCurrent(); return; }
  if (t.id === 'btnNext') { gotoNext(); return; }
  if (t.id === 'btnExport') {
    window.location = `/api/export.csv?annotator=${S.annotator}`;
    return;
  }

  const act = t.dataset.act;
  if (!act) return;
  const ui = Number(t.dataset.ui);
  const ii = Number(t.dataset.ii);

  if (act === 'del-unit') {
    S.units.splice(ui, 1);
    renderReviewText(); renderUnits();
  } else if (act === 'add-issue') {
    const u = S.units[ui];
    if (u && !u.issues.length) u.issues.push(emptyIssue());
    u.issues.push(emptyIssue());
    renderUnits();
  } else if (act === 'del-issue') {
    S.units[ui].issues.splice(ii, 1);
    renderUnits();
  } else if (act === 'pick-ev') {
    S.evidenceMode = { ui, ii };
    renderModeBanner();
    toast('Bôi đen đoạn văn trong review để làm bằng chứng');
  } else if (act === 'clr-ev') {
    const iss = S.units[ui].issues[ii];
    iss.ev_start = iss.ev_end = null;
    iss.evidence = '';
    renderReviewText(); renderUnits();
  }
});

document.addEventListener('change', (e) => {
  const t = e.target;
  const act = t.dataset.act;
  if (!act) return;
  const ui = Number(t.dataset.ui);
  const ii = Number(t.dataset.ii);
  const field = t.dataset.field;

  if (act === 'set') {
    const u = S.units[ui];
    if (!u) return;
    u[field] = t.value;
    if (field === 'issue_present') {
      if (t.value === 'yes' && !u.issues.length) u.issues.push(emptyIssue());
      renderUnits();
    }
  } else if (act === 'set-issue') {
    const iss = S.units[ui]?.issues?.[ii];
    if (!iss) return;
    iss[field] = t.value;
  }
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.act !== 'note') return;
  const u = S.units[Number(t.dataset.ui)];
  if (u) u.ghi_chu = t.value;
});

document.addEventListener('mouseup', (e) => {
  if (e.target.closest && e.target.closest('#revText')) onSelectCapture();
});
document.addEventListener('keyup', (e) => {
  if (e.target.closest && e.target.closest('#revText')) onSelectCapture();
});

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 's') { e.preventDefault(); saveCurrent(); }
  if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); addUnitFromSelection(); }
});

boot().catch((e) => {
  console.error(e);
  const sub = document.getElementById('sourceSub');
  if (sub) sub.textContent = 'LỖI KHỞI ĐỘNG: ' + e.message;
  const ed = document.getElementById('editor');
  if (ed) ed.innerHTML = `<div class="card" style="border-color:#f1c5c5;background:#fff5f5">
     <b style="color:#b91c1c">Không tải được app</b>
     <pre style="white-space:pre-wrap;font-size:12px;margin-top:8px">${esc(e.message + '\n' + (e.stack || ''))}</pre>
   </div>`;
  toast('Không tải được app: ' + e.message, true);
});
