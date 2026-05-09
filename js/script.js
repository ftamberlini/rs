// This file has been split into:
//   previous_rating.js  — Previous Ratings tab (stats, ratings table)
//   new_ratings.js      — New Ratings tab (movies grid, star rating, save)
//   recommender.js      — Recommender tab
//   main.js             — Global state, shared movie detail, form/container handlers
// It is no longer loaded by index.html.

const emailInput     = document.getElementById('email');
const countrySelect  = document.getElementById('country');

(async () => {
  try {
    const res  = await fetch('/countries');
    const list = await res.json();
    list.forEach(({ name, iso }) => {
      const opt = document.createElement('option');
      opt.value       = iso;
      opt.textContent = name;
      countrySelect.appendChild(opt);
    });
  } catch { /* silently ignore */ }
})();
const btnContinue    = document.getElementById('btnSearch');
const btnNewUser     = document.getElementById('btnNewUser');
const btnChangeEmail = document.getElementById('btnChangeEmail');
const btnEditUser    = document.getElementById('btnEditUser');
const btnSubmit      = document.getElementById('btnSubmit');
const stepEmail      = document.getElementById('stepEmail');
const stepDisplay    = document.getElementById('stepDisplay');
const stepFields     = document.getElementById('stepFields');
const emailConfirmed = document.getElementById('emailConfirmed');
const successMsg     = document.getElementById('successMsg');
const form           = document.getElementById('registrationForm');

document.addEventListener('click', e => {
  const btn = e.target.closest('.section-toggle');
  if (!btn) return;
  const targetId = btn.dataset.target;
  const content  = document.getElementById(targetId);
  if (!content) return;
  const collapsed = content.style.display === 'none';
  content.style.display = collapsed ? '' : 'none';
  btn.textContent = collapsed ? '−' : '+';
});

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.dataset.tab;
    switchTab(tabId);
    if (tabId === 'tabNew' && !_moviesLoaded) {
      _moviesLoaded = true;
      loadMovies();
    }
  });
});

function showLoader() {
  document.getElementById('loadingOverlay').hidden = false;
}

function hideLoader() {
  document.getElementById('loadingOverlay').hidden = true;
}

function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.style.display = p.id === tabId ? '' : 'none';
  });
}

function showStep1() {
  stepEmail.hidden    = false;
  stepDisplay.hidden  = true;
  stepFields.hidden   = true;
  successMsg.hidden   = true;
  emailInput.disabled = false;
  emailInput.value    = '';
  clearFields();

  document.getElementById('mainTabs').style.display = 'none';
  switchTab('tabPrevious');

  const uss = document.getElementById('userStatsSection');
  uss.hidden = true; uss.style.display = 'none';
  const urs = document.getElementById('userRatingsSection');
  urs.hidden = true; urs.style.display = 'none';
  document.getElementById('ratingsBody').innerHTML = '';
  const md = document.getElementById('movieDetail');
  md.hidden = true; md.style.display = 'none';
  const mdn = document.getElementById('movieDetailNew');
  mdn.hidden = true; mdn.style.display = 'none';
  document.getElementById('moviesGrid').innerHTML = '';
  document.getElementById('recResults').innerHTML = '';
  const srm = document.getElementById('saveRatingsMsg');
  srm.style.display = 'none'; srm.textContent = '';
  _moviesLoaded = false;
  _currentUserId = null;
}

function showMovieSections() {
  document.getElementById('mainTabs').style.display = '';
}

function clearFields() {
  document.getElementById('name').value    = '';
  document.getElementById('dob').value     = '';
  document.getElementById('country').value = '';
  document.getElementById('race').value    = '';
  document.querySelector('input[name="gender"][value="not_informed"]').checked = true;
}

function fillFields(user) {
  document.getElementById('name').value    = user.name            || '';
  document.getElementById('dob').value     = user.date_of_birth   || '';
  document.getElementById('country').value = user.country         || '';
  document.getElementById('race').value    = user.race            || '';
  const genderRadio = document.querySelector(`input[name="gender"][value="${user.gender}"]`);
  if (genderRadio) genderRadio.checked = true;
}

function setFieldsDisabled(disabled) {
  stepFields.querySelectorAll('input, select, button').forEach(el => {
    el.disabled = disabled;
  });
}

btnContinue.addEventListener('click', async () => {
  const query = emailInput.value.trim();
  const isId    = /^\d+$/.test(query);
  const isEmail = query.includes('@');
  if (!query || (!isId && !isEmail)) {
    emailInput.focus();
    return;
  }

  btnContinue.disabled = true;
  btnContinue.textContent = 'Searching…';

  try {
    const res  = await fetch(`/lookup?query=${encodeURIComponent(query)}`);
    const data = await res.json();

    if (!data.found) {
      alert('User not found.');
      return;
    }

    const user = data.user;
    if (isId) emailInput.value = user.email;

    emailConfirmed.textContent = emailInput.value;
    emailInput.disabled = true;
    stepEmail.hidden   = true;
    stepDisplay.hidden = false;
    stepFields.hidden  = true;
    successMsg.hidden  = true;

    document.getElementById('viewName').textContent    = `${user.userid || ''} (${user.name || '—'})`.trim();
    document.getElementById('viewDob').textContent     = formatDate(user.date_of_birth) || '—';
    document.getElementById('viewGender').textContent  = user.gender          || '—';
    document.getElementById('viewRace').textContent    = user.race            || '—';
    document.getElementById('viewCountry').textContent = user.country         || '—';

    _currentUserId = user.userid;
    fillFields(user);
    showMovieSections();
    showLoader();
    try {
      await Promise.all([loadUserStats(user.userid), loadUserRatings(user.userid)]);
      if (_ratingsData.length > 0) await showMovieFromId(_ratingsData[0].movieid);
    } finally {
      hideLoader();
    }
  } catch {
    alert('Failed to check email. Please try again.');
  } finally {
    btnContinue.disabled = false;
    btnContinue.textContent = 'Search';
  }
});

btnNewUser.addEventListener('click', () => {
  emailInput.disabled = false;
  emailInput.value    = '';
  stepEmail.hidden    = true;
  stepDisplay.hidden  = true;
  stepFields.hidden   = false;
  successMsg.hidden   = true;
  clearFields();
  btnSubmit.textContent = 'Save';
  setFieldsDisabled(false);
  showMovieSections();
});

btnChangeEmail.addEventListener('click', showStep1);

btnEditUser.addEventListener('click', () => {
  stepDisplay.hidden = true;
  stepFields.hidden  = false;
  successMsg.hidden  = true;
  btnSubmit.textContent = 'Update';
  setFieldsDisabled(false);
});

// ── Movie Detail (by ID) ─────────────────────────────────────────────────────

async function showMovieFromId(movieid, sfx = '') {
  try {
    const res  = await fetch(`/movie/${encodeURIComponent(movieid)}`);
    const data = await res.json();
    if (!data.title) return;
    const md = document.getElementById('movieDetail' + sfx);
    md.hidden = false; md.style.display = '';
    const contentId = 'movieDetailContent' + sfx;
    const content   = document.getElementById(contentId);
    if (content && content.style.display === 'none') {
      content.style.display = '';
      const btn = document.querySelector(`.section-toggle[data-target="${contentId}"]`);
      if (btn) btn.textContent = '−';
    }
    showMovieDetail(data, sfx);
  } catch { /* silently ignore */ }
}

// ── User Stats ───────────────────────────────────────────────────────────────

async function loadUserStats(userid) {
  const section = document.getElementById('userStatsSection');
  try {
    const res  = await fetch(`/user_stats/${encodeURIComponent(userid)}`);
    const data = await res.json();
    if (!data.count) { section.hidden = true; section.style.display = 'none'; return; }

    // Summary row
    const summary = document.getElementById('statsSummary');
    summary.innerHTML = '';
    const g = data.global;
    [
      ['Movies Rated', data.count,          'Average per user',  g.avg_movies],
      ['Average Rating',   data.avg.toFixed(2), 'Global Average',    g.avg_rating.toFixed(2)],
      ['Std Dev',      data.std.toFixed(2), 'Global Std Dev',    g.std.toFixed(2)],
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

    renderAvgList('statsGenres',    'Avg Rating by Genre',     data.genre_avg,     'genre');
    renderAvgList('statsContinent', 'Avg Rating by Continent', data.continent_avg, 'continent');
    renderAvgList('statsLanguages', 'Avg Rating by Language (Top 5)', data.language_avg, 'language');
    renderAvgList('statsWins',   'Avg Rating by Award Wins',           data.wins_avg,    'wins');
    renderAvgList('statsSpWins', 'Avg Rating by Special Award Wins',   data.sp_wins_avg, 'label');
    renderAvgList('statsSpNoms', 'Avg Rating by Special Award Nominations', data.sp_noms_avg, 'label');

    // Histogram
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

let _ratingsData = [];
let _ratingsPage = 0;
const RATINGS_PAGE_SIZE = 5;

async function loadUserRatings(userid) {
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

// ── Movies ──────────────────────────────────────────────────────────────────

let _moviesLoaded  = false;
let _currentUserId = null;

const POSTER_PLACEHOLDER = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450">' +
  '<rect width="300" height="450" fill="#e0ddd8"/>' +
  '<text x="150" y="210" text-anchor="middle" fill="#aaa" font-family="sans-serif" font-size="15">No Poster</text>' +
  '</svg>'
)}`;

async function loadMovies() {
  const grid = document.getElementById('moviesGrid');
  grid.innerHTML = '';
  const url = '/movies' + (_currentUserId ? `?userid=${encodeURIComponent(_currentUserId)}` : '');
  try {
    const res    = await fetch(url);
    const movies = await res.json();
    const cards  = [];

    movies.forEach(m => {
      const card = createMovieCard(m, async () => {
        cards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        if (m.movieid) {
          await showMovieFromId(m.movieid, 'New');
        } else {
          const md = document.getElementById('movieDetailNew');
          md.hidden = false; md.style.display = '';
          showMovieDetail(m, 'New');
        }
        document.getElementById('movieDetailNew').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
      grid.appendChild(card);
      cards.push(card);
    });

    if (movies.length > 0) {
      cards[0].classList.add('active');
      const first = movies[0];
      if (first.movieid) {
        await showMovieFromId(first.movieid, 'New');
      } else {
        const md = document.getElementById('movieDetailNew');
        md.hidden = false; md.style.display = '';
        showMovieDetail(first, 'New');
      }
    }
  } catch { /* server may not be running in static preview */ }
}

function createMovieCard(movie, onTitleClick) {
  const card = document.createElement('div');
  card.className = 'movie-card';

  const img = document.createElement('img');
  img.className   = 'movie-poster';
  img.src         = movie.poster;
  img.alt         = movie.title;
  img.loading     = 'lazy';
  img.onerror     = () => { img.onerror = null; img.src = POSTER_PLACEHOLDER; };

  const info  = document.createElement('div');
  info.className  = 'movie-info';

  const title = document.createElement('h3');
  title.className = 'movie-title';
  title.textContent = movie.title;
  title.addEventListener('click', onTitleClick);

  const year  = document.createElement('span');
  year.className  = 'movie-year';
  year.textContent = movie.year;

  info.appendChild(title);
  info.appendChild(year);
  info.appendChild(createStarRating(movie.movieid || ''));

  card.appendChild(img);
  card.appendChild(info);
  return card;
}

function showMovieDetail(movie, sfx = '') {
  const g = id => document.getElementById(id + sfx);
  const detailPoster   = g('detailPoster');
  detailPoster.alt     = movie.title;
  detailPoster.onerror = () => { detailPoster.onerror = null; detailPoster.src = POSTER_PLACEHOLDER; };
  detailPoster.src     = movie.poster;
  g('detailTitle').textContent    = movie.title;
  renderRatings(movie.ratings, sfx);
  g('detailYear').textContent     = movie.year;
  g('detailReleased').textContent = formatDate(movie.released);
  g('detailRuntime').textContent  = movie.runtime;
  g('detailCountry').textContent  = movie.country;
  g('detailLanguage').textContent = movie.language;
  g('detailGenre').textContent    = movie.genre;
  g('detailDirector').textContent = movie.director;
  g('detailWriter').textContent   = movie.writer;
  g('detailCast').textContent     = movie.cast;
  g('detailAwards').textContent   = movie.awards !== 'N/A' ? movie.awards : '—';
  g('detailPlot').textContent     = movie.plot;
  renderPeople(movie.directors, movie.writers, sfx);
  renderGenresTags(movie.genres_imdb, movie.genres_ml, movie.tags, sfx);
}

function renderGenresTags(genresImdb, genresMl, tags, sfx = '') {
  const container = document.getElementById('detailGenresTags' + sfx);
  container.innerHTML = '';

  function addChipRow(label, items, chipClass, textFn) {
    if (!items || items.length === 0) return;
    const row = document.createElement('div');
    row.className = 'chip-row';
    const lbl = document.createElement('span');
    lbl.className   = 'meta-label';
    lbl.textContent = label;
    row.appendChild(lbl);
    items.forEach(item => {
      const chip = document.createElement('span');
      chip.className   = `chip ${chipClass}`;
      chip.textContent = textFn(item);
      row.appendChild(chip);
    });
    container.appendChild(row);
  }

  addChipRow('Genres IMDB', genresImdb, 'chip--genre', g => g);
  addChipRow('Genres ML',   genresMl,   'chip--genre', g => g);
  addChipRow('Tags', tags, 'chip--tag', ({ tag, count }) => `${tag} (${count})`);
}

function renderPeople(directors, writers, sfx = '') {
  const container = document.getElementById('detailPeople' + sfx);
  container.innerHTML = '';

  function capitalizeInitials(text) {
  return text
      .toLowerCase()
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  [['Directors', directors], ['Writers', writers]].forEach(([label, people]) => {
    if (!people || people.length === 0) return;

    const group = document.createElement('div');
    group.className = 'people-group';

    const heading = document.createElement('span');
    heading.className = 'meta-label';
    heading.textContent = label;
    group.appendChild(heading);

    people.forEach(p => {
      const attrs = ['gender', 'race', 'nationality', 'ethnicity', 'religion']
        .filter(k => p[k])
        .map(k => p[k].toLowerCase())
        .join(' · ');

      const line = document.createElement('div');
      line.className = 'person-line';

      const nameSpan = document.createElement('span');
      nameSpan.className   = 'person-line-name';
      nameSpan.textContent = capitalizeInitials(p.name) || '';
      line.appendChild(nameSpan);

      if (attrs) line.appendChild(document.createTextNode(' — ' + attrs));

      group.appendChild(line);
    });

    container.appendChild(group);
  });
}

function formatDate(raw) {
  if (!raw) return '';
  const d = new Date(raw + 'T00:00:00');
  if (isNaN(d)) return raw;
  const dd  = String(d.getUTCDate()).padStart(2, '0');
  const mmm = d.toLocaleString('en', { month: 'short', timeZone: 'UTC' });
  const yyyy = d.getUTCFullYear();
  return `${dd} - ${mmm} - ${yyyy}`;
}

function renderRatings(ratings, sfx = '') {
  const container = document.getElementById('detailRatings' + sfx);
  container.innerHTML = '';
  if (!ratings || ratings.length === 0) return;

  const sourceClass = {
    'Movie Lens':      'rb-ml',
    'IMDb':            'rb-imdb',
    'Rotten Tomatoes': 'rb-rt',
    'Metacritic':      'rb-mc',
  };

  ratings.forEach(({ source, score, votes }) => {
    const badge = document.createElement('div');
    badge.className = `rating-badge ${sourceClass[source] ?? ''}`.trim();

    const src = document.createElement('span');
    src.className   = 'rb-source';
    src.textContent = source;

    const sc = document.createElement('span');
    sc.className   = 'rb-score';
    sc.textContent = score;

    badge.appendChild(src);
    badge.appendChild(sc);

    if (votes) {
      const v = document.createElement('span');
      v.className   = 'rb-votes';
      v.textContent = `${votes} votes`;
      badge.appendChild(v);
    }

    container.appendChild(badge);
  });
}

function createStarRating(movieId = '') {
  const container = document.createElement('div');
  container.className = 'star-rating';
  if (movieId) container.dataset.movieid = movieId;

  let current  = 0;
  const items  = [];

  for (let i = 1; i <= 5; i++) {
    const wrap = document.createElement('span');
    wrap.className = 'star-wrap';

    const bg = document.createElement('span');
    bg.className  = 'star-bg';
    bg.textContent = '★';

    const fg = document.createElement('span');
    fg.className  = 'star-fg';
    fg.textContent = '★';

    wrap.appendChild(bg);
    wrap.appendChild(fg);
    items.push({ fg, pos: i });

    wrap.addEventListener('mousemove', (e) => {
      const { left, width } = wrap.getBoundingClientRect();
      paint((e.clientX - left) < width / 2 ? i - 0.5 : i);
    });

    wrap.addEventListener('click', (e) => {
      const { left, width } = wrap.getBoundingClientRect();
      current = (e.clientX - left) < width / 2 ? i - 0.5 : i;
      container.dataset.rating = String(current);
      paint(current);
    });

    container.appendChild(wrap);
  }

  container.addEventListener('mouseleave', () => paint(current));

  function paint(value) {
    items.forEach(({ fg, pos }) => {
      fg.style.width = value >= pos ? '100%' : value >= pos - 0.5 ? '50%' : '0%';
    });
  }

  return container;
}

// ── New Ratings tab ──────────────────────────────────────────────────────────

document.getElementById('btnSaveRatings').addEventListener('click', async () => {
  const msg = document.getElementById('saveRatingsMsg');
  if (!_currentUserId) {
    showSaveMsg(msg, 'No user selected.', 'error');
    return;
  }

  const ratings = [];
  document.querySelectorAll('#moviesGrid .star-rating').forEach(el => {
    const rating  = parseFloat(el.dataset.rating  || '0');
    const movieid = el.dataset.movieid || '';
    if (movieid && rating > 0) ratings.push({ movieid, rating });
  });

  if (ratings.length === 0) {
    showSaveMsg(msg, 'Rate at least one movie before saving.', 'warn');
    return;
  }

  const btn = document.getElementById('btnSaveRatings');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  msg.style.display = 'none';

  try {
    const res = await fetch('/new_ratings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ userid: _currentUserId, ratings }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    showSaveMsg(msg, `${data.saved} rating(s) saved. Loading new movies…`, 'success');
    await loadMovies();
    showSaveMsg(msg, `${data.saved} rating(s) saved successfully. New movies loaded.`, 'success');
  } catch {
    showSaveMsg(msg, 'Failed to save ratings. Please try again.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save New Ratings';
  }
});

function showSaveMsg(el, text, type) {
  el.textContent = text;
  el.className = `save-ratings-msg save-ratings-msg--${type}`;
  el.style.display = '';
}

// ── Recommender tab ──────────────────────────────────────────────────────────

document.getElementById('btnSimulateRec').addEventListener('click', () => {
  alert('Simulate Recommendations: coming soon.');
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  btnSubmit.disabled = true;
  btnSubmit.textContent = 'Saving…';

  try {
    const fd = new FormData(form);
    fd.set('email', emailInput.value);
    const res = await fetch('/submit', {
      method: 'POST',
      body: fd,
    });

    if (!res.ok) throw new Error('Server error');

    setFieldsDisabled(true);
    const action = btnSubmit.textContent.includes('Update') ? 'updated' : 'saved';
    successMsg.textContent = `Registration ${action} successfully.`;
    successMsg.hidden = false;
    btnSubmit.textContent = 'Submitted';
  } catch {
    btnSubmit.disabled = false;
    alert('Failed to save. Please try again.');
  }
});
