import { showMovieFromId } from './main.js';

const MODELS = [
  { key: 'bias',      label: 'Bias'      },
  { key: 'user_knn',  label: 'User KNN'  },
  { key: 'biased_mf', label: 'Biased MF' },
];

let _data     = [];
let _batches  = [];
let _batchIdx = 0;

export async function loadPrevRecommendations(userid) {
  _data = []; _batches = []; _batchIdx = 0;
  clearAll();

  try {
    const res  = await fetch(`/user_recommendations/${encodeURIComponent(userid)}`);
    const rows = await res.json();

    if (!Array.isArray(rows) || !rows.length) {
      renderPagination(-1);
      return;
    }

    _data = rows;
    const seen = new Set();
    rows.forEach(r => {
      if (!seen.has(r.rec_batch_id)) { seen.add(r.rec_batch_id); _batches.push(r.rec_batch_id); }
    });

    renderBatch(0);
  } catch (e) {
    MODELS.forEach(({ key }) => {
      const el = document.getElementById(`prevRecBody_${key}`);
      if (el) el.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#c00;padding:1rem">Error: ${e.message}</td></tr>`;
    });
  }
}

function renderBatch(idx) {
  _batchIdx = idx;
  const batchId = _batches[idx];
  const batchRows = _data.filter(r => r.rec_batch_id === batchId);

  MODELS.forEach(({ key }) => {
    const rows = batchRows.filter(r => r.model === key);
    const date = rows.length ? rows[0].date : '';
    const dateEl = document.getElementById(`prevRecDate_${key}`);
    if (dateEl) dateEl.textContent = date ? `— ${date}` : '';
    renderTable(key, rows);
    renderMetrics(key, rows);
  });

  const top = batchRows.reduce((best, r) =>
    (r.score != null && (best === null || r.score > best.score)) ? r : best, null);
  if (top) showMovieFromId(top.item_id, 'PrevRec');

  renderPagination(idx);
}

function renderTable(modelKey, rows) {
  const tbody = document.getElementById(`prevRecBody_${modelKey}`);
  tbody.innerHTML = '';

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#aaa;padding:0.8rem">No data.</td></tr>';
    return;
  }

  rows.forEach(({ item_id, title, genres, score, rank, rating_ml, votes_ml, rating_imdb, votes_imdb }) => {
    const tr = document.createElement('tr');
    tr.className = 'ratings-row';
    tr.addEventListener('click', () => showMovieFromId(item_id, 'PrevRec'));

    const tdTitle = document.createElement('td');
    tdTitle.textContent = title; tdTitle.title = `movieid: ${item_id}`;

    const tdGenres = document.createElement('td');
    const wrap = document.createElement('div');
    wrap.className = 'chip-cell';
    genres.forEach(g => {
      const chip = document.createElement('span');
      chip.className = 'chip chip--genre'; chip.textContent = g;
      wrap.appendChild(chip);
    });
    tdGenres.appendChild(wrap);

    const tdScore = document.createElement('td');
    tdScore.className = 'rating-cell';
    tdScore.textContent = score != null ? score.toFixed(3) : '—';

    const tdRank = document.createElement('td');
    tdRank.className = 'rating-cell';
    tdRank.textContent = rank ?? '—';

    const tdRating = document.createElement('td');
    const ratingWrap = document.createElement('div');
    ratingWrap.style.cssText = 'display:flex;gap:0.25rem;align-items:center;white-space:nowrap';
    if (rating_ml != null) {
      const badge = document.createElement('span');
      badge.className = 'rating-badge rb-ml';
      badge.style.cssText = 'font-size:.7rem;padding:0.1rem 0.35rem;gap:0.2rem';
      badge.innerHTML = `<span class="rb-source">ML</span><span class="rb-score">${rating_ml.toFixed(1)}</span>`;
      badge.title = `votes ml: ${votes_ml != null ? votes_ml.toLocaleString() : '—'}`;
      ratingWrap.appendChild(badge);
    }
    if (rating_imdb != null) {
      const badge = document.createElement('span');
      badge.className = 'rating-badge rb-imdb';
      badge.style.cssText = 'font-size:.7rem;padding:0.1rem 0.35rem;gap:0.2rem';
      badge.innerHTML = `<span class="rb-source">IMDb</span><span class="rb-score">${rating_imdb.toFixed(1)}</span>`;
      badge.title = `votes imdb: ${votes_imdb != null ? votes_imdb.toLocaleString() : '—'}`;
      ratingWrap.appendChild(badge);
    }
    if (!rating_ml && !rating_imdb) ratingWrap.textContent = '—';
    tdRating.appendChild(ratingWrap);

    tr.append(tdTitle, tdGenres, tdScore, tdRank, tdRating);
    tbody.appendChild(tr);
  });
}

function _avg(rows, key) {
  const vals = rows.map(r => r[key]).filter(v => v != null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

function renderMetrics(modelKey, rows) {
  const container = document.getElementById(`prevRecMetrics_${modelKey}`);
  container.innerHTML = '';

  const avgRatingMl   = _avg(rows, 'rating_ml');
  const avgVotesMl    = _avg(rows, 'votes_ml');
  const avgRatingImdb = _avg(rows, 'rating_imdb');
  const avgVotesImdb  = _avg(rows, 'votes_imdb');

  [
    { label: 'Avg ML Rating',    value: avgRatingMl,   fmt: v => v.toFixed(2) },
    { label: 'Avg ML Users',     value: avgVotesMl,    fmt: v => Math.round(v).toLocaleString() },
    { label: 'Avg IMDB Rating',  value: avgRatingImdb, fmt: v => v.toFixed(2) },
    { label: 'Avg IMDB Votes',   value: avgVotesImdb,  fmt: v => Math.round(v).toLocaleString() },
  ].forEach(({ label, value, fmt }) => {
    const card = document.createElement('div');
    card.className = 'stat-card';
    card.innerHTML =
      `<span class="stat-value">${value != null ? fmt(value) : '—'}</span>` +
      `<span class="meta-label" style="text-align:center">${label}</span>`;
    container.appendChild(card);
  });
}

function renderPagination(idx) {
  const pag = document.getElementById('prevRecPagination');
  pag.innerHTML = '';

  if (idx < 0 || !_batches.length) {
    pag.innerHTML = '<span style="color:#aaa;font-size:.9rem">No previous recommendations found.</span>';
    return;
  }

  const total = _batches.length;

  const btnPrev = document.createElement('button');
  btnPrev.className = 'btn btn--sm'; btnPrev.textContent = '‹ Prev';
  btnPrev.disabled = idx === 0;
  btnPrev.addEventListener('click', () => renderBatch(_batchIdx - 1));

  const info = document.createElement('span');
  info.className = 'pagination-info';
  info.textContent = `Rec #${_batches[idx]}  (${idx + 1} / ${total})`;

  const btnNext = document.createElement('button');
  btnNext.className = 'btn btn--sm'; btnNext.textContent = 'Next ›';
  btnNext.disabled = idx >= total - 1;
  btnNext.addEventListener('click', () => renderBatch(_batchIdx + 1));

  pag.append(btnPrev, info, btnNext);
}

function clearAll() {
  MODELS.forEach(({ key }) => {
    const tbody = document.getElementById(`prevRecBody_${key}`);
    if (tbody) tbody.innerHTML = '';
    const metrics = document.getElementById(`prevRecMetrics_${key}`);
    if (metrics) metrics.innerHTML = '';
  });
  const pag = document.getElementById('prevRecPagination');
  if (pag) pag.innerHTML = '';
}
