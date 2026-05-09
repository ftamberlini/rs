import { showMovieFromId } from './main.js';

// ── State ────────────────────────────────────────────────────────────────────

export let _ratingsData = [];
let _ratingsPage = 0;
const RATINGS_PAGE_SIZE = 5;

// ── User Stats ───────────────────────────────────────────────────────────────

export async function loadUserStats(userid) {
  const section = document.getElementById('userStatsSection');
  try {
    const res  = await fetch(`/user_stats/${encodeURIComponent(userid)}`);
    const data = await res.json();
    if (!data.count) { section.hidden = true; section.style.display = 'none'; return; }

    const summary = document.getElementById('statsSummary');
    summary.innerHTML = '';
    const g = data.global;
    [
      ['Movies Rated',  data.count,          'Average per user', g.avg_movies],
      ['Average Rating', data.avg.toFixed(2), 'Global Average',  g.avg_rating.toFixed(2)],
      ['Std Dev',        data.std.toFixed(2), 'Global Std Dev',  g.std.toFixed(2)],
    ].forEach(([label, value, globalLabel, globalVal]) => {
      const card = document.createElement('div');
      card.className = 'stat-card';
      card.innerHTML =
        `<span class="stat-value">${value}</span>` +
        `<span class="meta-label" style="text-align: center;">${label}</span>` +
        `<span class="stat-global"><strong>${globalVal}</strong> ${globalLabel}</span>`;
      summary.appendChild(card);
    });

    function renderAvgList(elId, label, items, nameKey) {
      const el = document.getElementById(elId);
      el.innerHTML = `<span class="meta-label" style="display:block;margin-bottom:0.5rem">${label}</span>`;
      const row = document.createElement('div');
      row.className = 'genre-avg-row';
      items.forEach((item, i) => {
        if (i > 0) {
          const sep = document.createElement('span');
          sep.className = 'genre-sep';
          sep.textContent = '|';
          row.appendChild(sep);
        }
        const span = document.createElement('span');
        span.className = 'genre-avg-item';
        span.innerHTML = `${item[nameKey]} <strong>${item.avg.toFixed(1)}</strong> <span class="genre-count">(${item.count})</span>`;
        row.appendChild(span);
      });
      el.appendChild(row);
    }

    renderAvgList('statsGenres',    'Avg Rating by Genre',                    data.genre_avg,     'genre');
    renderAvgList('statsContinent', 'Avg Rating by Continent',                data.continent_avg, 'continent');
    renderAvgList('statsLanguages', 'Avg Rating by Language (Top 5)',         data.language_avg,  'language');
    renderAvgList('statsWins',      'Avg Rating by Award Wins',               data.wins_avg,      'wins');
    renderAvgList('statsSpWins',    'Avg Rating by Special Award Wins',       data.sp_wins_avg,   'label');
    renderAvgList('statsSpNoms',    'Avg Rating by Special Award Nominations',data.sp_noms_avg,   'label');

    const histEl = document.getElementById('statsHistogram');
    histEl.innerHTML = '<span class="meta-label" style="display:block;margin-bottom:0.5rem">Rating Distribution</span>';
    const maxCount = Math.max(...data.histogram.map(h => h.count), 1);
    data.histogram.forEach(({ rating, count }) => {
      const row = document.createElement('div');
      row.className = 'hist-row';
      const lbl = document.createElement('span');
      lbl.className = 'hist-label';
      lbl.textContent = rating;
      const track = document.createElement('div');
      track.className = 'hist-track';
      const bar = document.createElement('div');
      bar.className = 'hist-bar';
      bar.style.width = `${(count / maxCount) * 100}%`;
      const cnt = document.createElement('span');
      cnt.className = 'hist-count';
      cnt.textContent = count || '';
      track.appendChild(bar);
      row.appendChild(lbl);
      row.appendChild(track);
      row.appendChild(cnt);
      histEl.appendChild(row);
    });

    section.hidden = false;
    section.style.display = '';
  } catch { /* silently ignore */ }
}

// ── User Ratings ─────────────────────────────────────────────────────────────

export async function loadUserRatings(userid) {
  const section = document.getElementById('userRatingsSection');
  _ratingsData = [];
  _ratingsPage = 0;

  try {
    const res  = await fetch(`/user_ratings/${encodeURIComponent(userid)}`);
    const rows = await res.json();

    if (rows.length === 0) {
      section.hidden = true;
      section.style.display = 'none';
      return;
    }

    _ratingsData = rows;
    renderRatingsPage(0);
    section.hidden = false;
    section.style.display = '';
  } catch { /* silently ignore */ }
}

function renderRatingsPage(page) {
  const tbody = document.getElementById('ratingsBody');
  tbody.innerHTML = '';

  const start = page * RATINGS_PAGE_SIZE;
  _ratingsData.slice(start, start + RATINGS_PAGE_SIZE).forEach(({ movieid, title, genres_ml, tags, rating, date }) => {
    const tr = document.createElement('tr');
    tr.className = 'ratings-row';
    tr.addEventListener('click', () => showMovieFromId(movieid));

    const tdTitle = document.createElement('td');
    tdTitle.textContent = title;
    tdTitle.title = movieid;

    const tdGenres = document.createElement('td');
    const genreWrap = document.createElement('div');
    genreWrap.className = 'chip-cell';
    genres_ml.forEach(g => {
      const chip = document.createElement('span');
      chip.className = 'chip chip--genre';
      chip.textContent = g;
      genreWrap.appendChild(chip);
    });
    tdGenres.appendChild(genreWrap);

    const tdTags = document.createElement('td');
    const tagWrap = document.createElement('div');
    tagWrap.className = 'chip-cell';
    tags.forEach(t => {
      const chip = document.createElement('span');
      chip.className = 'chip chip--tag';
      chip.textContent = t;
      tagWrap.appendChild(chip);
    });
    tdTags.appendChild(tagWrap);

    const tdRating = document.createElement('td');
    tdRating.className = 'rating-cell';
    tdRating.textContent = rating.toFixed(1);

    const tdDate = document.createElement('td');
    tdDate.textContent = date;

    tr.appendChild(tdTitle);
    tr.appendChild(tdGenres);
    tr.appendChild(tdTags);
    tr.appendChild(tdRating);
    tr.appendChild(tdDate);
    tbody.appendChild(tr);
  });

  renderRatingsPagination(page);
}

function renderRatingsPagination(page) {
  const total = Math.ceil(_ratingsData.length / RATINGS_PAGE_SIZE);
  let pag = document.getElementById('ratingsPagination');
  if (!pag) {
    pag = document.createElement('div');
    pag.id = 'ratingsPagination';
    pag.className = 'ratings-pagination';
    document.getElementById('userRatingsSection').appendChild(pag);
  }
  pag.innerHTML = '';
  if (total <= 1) return;

  const btnPrev = document.createElement('button');
  btnPrev.className = 'btn btn--sm';
  btnPrev.textContent = '‹ Prev';
  btnPrev.disabled = page === 0;
  btnPrev.addEventListener('click', () => { _ratingsPage--; renderRatingsPage(_ratingsPage); });

  const info = document.createElement('span');
  info.className = 'pagination-info';
  info.textContent = `${page + 1} / ${total}  (${_ratingsData.length} movies)`;

  const btnNext = document.createElement('button');
  btnNext.className = 'btn btn--sm';
  btnNext.textContent = 'Next ›';
  btnNext.disabled = page >= total - 1;
  btnNext.addEventListener('click', () => { _ratingsPage++; renderRatingsPage(_ratingsPage); });

  pag.appendChild(btnPrev);
  pag.appendChild(info);
  pag.appendChild(btnNext);
}
