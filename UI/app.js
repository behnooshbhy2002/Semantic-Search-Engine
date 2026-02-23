/* ═══════════════════════════════════════════════════════════════
   IranDoc Search UI — app.js
   ═══════════════════════════════════════════════════════════════ */

const API = 'http://localhost:5000';

// Tokens from the original (non-expanded) query — used for highlighting
let _queryTokens = [];

// Currently selected parser mode: "llm" | "rule"
let _parserMode = 'llm';

/* ── Helpers ──────────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── On page load ─────────────────────────────────────────────── */
(async () => {
  // Health check
  try {
    const r = await fetch(`${API}/api/health`);
    $('apiStatus').textContent = r.ok ? '✅ سرور متصل است' : '⚠️ سرور در دسترس نیست';
    if (!r.ok) $('apiStatus').style.color = '#c8522a';
  } catch {
    $('apiStatus').textContent = '⚠️ سرور در دسترس نیست';
    $('apiStatus').style.color = '#c8522a';
  }

  // Load cross-encoder list
  await loadModels();
})();

/* ── Load cross-encoder list from API ────────────────────────── */
async function loadModels() {
  const sel = $('ceSelect');
  try {
    const r    = await fetch(`${API}/api/models`);
    const data = await r.json();
    sel.innerHTML = '';
    data.models.forEach(m => {
      const opt    = document.createElement('option');
      opt.value    = m.key;
      opt.textContent = m.label;
      if (m.default) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch {
    sel.innerHTML = '<option value="">خطا در بارگذاری مدل‌ها</option>';
  }
}

/* ── Advanced panel toggle ────────────────────────────────────── */
function toggleAdvanced() {
  const body  = $('advancedBody');
  const arrow = $('advArrow');
  const open  = body.classList.toggle('open');
  arrow.textContent = open ? '▴' : '▾';
}

/* ── Parser mode toggle ───────────────────────────────────────── */
function setParser(mode) {
  _parserMode = mode;
  $('parserLlmBtn').classList.toggle('active', mode === 'llm');
  $('parserRuleBtn').classList.toggle('active', mode === 'rule');
  $('parserHint').textContent = mode === 'llm'
    ? 'فیلترها از طریق LLM استخراج می‌شوند — در صورت خطا، به روش دستی سوئیچ می‌شود'
    : 'فیلترها با قوانین دستی (Regex/Fuzzy) استخراج می‌شوند — بدون نیاز به API';
}

/* ── Keyboard shortcut ────────────────────────────────────────── */
$('searchInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') runSearch();
});

/* ── Append a filter keyword to the input field ──────────────── */
function addFilter(text) {
  const inp = $('searchInput');
  const val = inp.value.trim();
  if (!val.includes(text)) inp.value = val ? val + ' ' + text : text;
  inp.focus();
}

/* ── Tokenise a query string into searchable terms ───────────── */
function tokenise(query) {
  return query.split(/\s+/).filter(t => t.length >= 2);
}

/* ── Highlight query tokens inside a plain-text string ───────── */
function highlight(text, tokens) {
  if (!text || !tokens.length) return escHtml(text);
  const escaped = tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp('(' + escaped.join('|') + ')', 'g');
  return escHtml(text).replace(re, '<mark class="hl">$1</mark>');
}

/* ── Show the expanded query box ─────────────────────────────── */
function renderExpandedQuery(original, expanded) {
  const box = $('expandedBox');
  if (!expanded || expanded === original) {
    box.classList.remove('visible');
    return;
  }
  const originalTokens = new Set(tokenise(original));
  const chips = tokenise(expanded).map(tok => {
    const cls = originalTokens.has(tok) ? 'original' : 'added';
    return '<span class="exp-term ' + cls + '">' + escHtml(tok) + '</span>';
  }).join('');
  $('expandedTerms').innerHTML = chips;
  box.classList.add('visible');
}

/* ── Main search ──────────────────────────────────────────────── */
async function runSearch() {
  const query  = $('searchInput').value.trim();
  const top_k  = parseInt($('topKSelect').value);
  const ce_key = $('ceSelect').value;
  const btn    = $('searchBtn');
  if (!query) return;

  _queryTokens = tokenise(query);

  btn.disabled = true;
  $('statusBar').classList.remove('visible');
  $('expandedBox').classList.remove('visible');
  $('resultsContainer').innerHTML =
    '<div class="state-box"><div class="spinner"></div><p>در حال جستجو...</p></div>';

  const t0 = Date.now();

  try {
    const resp = await fetch(`${API}/api/search`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        query,
        top_k,
        use_bm25:    true,
        parser_mode: _parserMode,
        ce_key:      ce_key || undefined,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || 'خطای سرور');
    }

    const data    = await resp.json();
    const elapsed = ((Date.now() - t0) / 1000).toFixed(2);

    // Status bar
    $('statusBar').classList.add('visible');
    $('statusCount').innerHTML = '<strong>' + data.count + '</strong> نتیجه یافت شد';
    $('statusTime').textContent = elapsed + ' ثانیه';

    // Parser badge
    const parserLabel = data.parser_used === 'llm' ? '🤖 LLM' : '⚙️ Regex';
    $('statusParser').textContent = parserLabel;
    $('statusParser').className   = 'status-badge ' +
      (data.parser_used === 'llm' ? 'status-badge--llm' : 'status-badge--rule');

    // Cross-encoder badge
    $('statusCe').textContent = '📐 ' + (data.ce_key || ce_key || '');

    // Update the CE select to reflect what the server is actually using
    if (data.ce_key && $('ceSelect').value !== data.ce_key) {
      $('ceSelect').value = data.ce_key;
    }

    renderExpandedQuery(query, data.expanded_query);
    if (data.expanded_query) _queryTokens = tokenise(data.expanded_query);

    if (data.results.length === 0) {
      $('resultsContainer').innerHTML =
        '<div class="state-box"><div class="icon">📭</div>' +
        '<p>نتیجه‌ای یافت نشد. عبارت جستجو را تغییر دهید.</p></div>';
    } else {
      $('resultsContainer').innerHTML = data.results
        .map((doc, i) => renderCard(doc, i + 1)).join('');

      $('resultsContainer').querySelectorAll('.abstract-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
          const abs  = btn.nextElementSibling;
          const open = abs.classList.toggle('expanded');
          btn.classList.toggle('open', open);
          btn.querySelector('.toggle-text').textContent = open ? 'بستن چکیده' : 'نمایش چکیده';
        });
      });
    }

  } catch (err) {
    $('resultsContainer').innerHTML =
      '<div class="state-box"><div class="icon">⚠️</div>' +
      '<p>خطا در اتصال به سرور: ' + escHtml(err.message) + '</p></div>';
  } finally {
    btn.disabled = false;
  }
}

/* ── Render a single result card ─────────────────────────────── */
function renderCard(doc, rank) {
  return '<div class="result-card" style="animation-delay:' + ((rank - 1) * 0.045) + 's">' +
    renderCardHeader(doc, rank) + renderCardBody(doc) + '</div>';
}

/* ── Card header ─────────────────────────────────────────────── */
function renderCardHeader(doc, rank) {
  const score = (doc.score * 100).toFixed(1);
  const tags = [
    doc.id         ? '<span class="meta-tag tag-id">ID: '    + escHtml(doc.id)         + '</span>' : '',
    doc.degree     ? '<span class="meta-tag tag-degree">'    + escHtml(doc.degree)      + '</span>' : '',
    doc.year       ? '<span class="meta-tag tag-year">'      + escHtml(doc.year)        + '</span>' : '',
    doc.doc_type   ? '<span class="meta-tag tag-type">'      + escHtml(doc.doc_type)    + '</span>' : '',
    doc.university ? '<span class="meta-tag tag-uni">🏛️ '   + escHtml(doc.university)  + '</span>' : '',
    '<span class="meta-tag tag-score">' + score + '٪</span>',
  ].filter(Boolean).join('');

  return '<div class="card-header">' +
    '<div class="card-rank">' + rank + '</div>' +
    '<div class="card-header-right">' +
      '<div class="card-title">' + highlight(doc.title || '—', _queryTokens) + '</div>' +
      '<div class="card-meta">' + tags + '</div>' +
    '</div></div>';
}

/* ── Card body ───────────────────────────────────────────────── */
function renderCardBody(doc) {
  const people = [
    buildPersonRow('✍️',  'پدیدآور',     doc.authors),
    buildPersonRow('👨‍🏫', 'استاد راهنما', doc.advisors),
    buildPersonRow('👨‍💼', 'استاد مشاور', doc.co_advisors),
  ].filter(Boolean).join('');

  const abstract = doc.abs_text
    ? '<div class="card-abstract-wrap">' +
        '<div class="abstract-toggle"><span class="toggle-arrow">▼</span>' +
        '<span class="toggle-text">نمایش چکیده</span></div>' +
        '<div class="card-abstract">' + highlight(doc.abs_text, _queryTokens) + '</div>' +
      '</div>'
    : '';

  const keywords = buildKeywords(doc.keyword_text);
  if (!people && !abstract && !keywords) return '';

  return '<div class="card-body">' +
    (people   ? '<div class="card-people">' + people + '</div>' : '') +
    abstract + keywords +
    '</div>';
}

/* ── Person row ──────────────────────────────────────────────── */
function buildPersonRow(icon, label, value) {
  if (!value || !value.trim()) return '';
  const names = value.split(/[،,;\/]/).map(n => n.trim()).filter(Boolean);
  const nameHtml = names.length > 1
    ? '<div class="person-name-list">' +
        names.map(n => '<span class="person-name-chip">' + escHtml(n) + '</span>').join('') +
      '</div>'
    : '<span class="person-name">' + escHtml(names[0]) + '</span>';
  return '<div class="person-row">' +
    '<span class="person-icon">' + icon + '</span>' +
    '<span class="person-label">' + label + ':</span>' +
    nameHtml + '</div>';
}

/* ── Keywords section ────────────────────────────────────────── */
function buildKeywords(raw) {
  if (!raw || !raw.trim()) return '';
  const kws = raw.split(/[\n]/).map(k => k.trim()).filter(Boolean);
  if (!kws.length) return '';
  const chips = kws.map(k => {
    const isMatch = _queryTokens.some(t => k.includes(t) || t.includes(k));
    const cls = isMatch ? 'keyword-chip keyword-chip--match' : 'keyword-chip';
    return '<span class="' + cls + '">' + escHtml(k) + '</span>';
  }).join('');
  return '<div class="card-keywords-wrap">' +
    '<div class="keywords-label">🔑 کلیدواژه‌ها</div>' +
    '<div class="keywords-list">' + chips + '</div></div>';
}