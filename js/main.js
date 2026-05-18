import { loadUserStats, loadUserRatings, getRatingsData } from './previous_rating.js';
import { loadMovies } from './new_ratings.js';
import { loadPrevRecommendations } from './prev_recommendations.js';
import { loadUserSimilarity, clearUserSimilarity } from './user_similarity.js';
import './recommender.js';

// ── Global state (shared across all tab files) ────────────────────────────────

export let _currentUserId = null;
let _moviesLoaded  = false;

export const POSTER_PLACEHOLDER = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450">' +
  '<rect width="300" height="450" fill="#e0ddd8"/>' +
  '<text x="150" y="210" text-anchor="middle" fill="#aaa" font-family="sans-serif" font-size="15">No Poster</text>' +
  '</svg>'
)}`;

// ── DOM references ────────────────────────────────────────────────────────────

const emailInput     = document.getElementById('email');
const countrySelect  = document.getElementById('country');
const btnContinue    = document.getElementById('btnSearch');
const btnNewUser     = document.getElementById('btnNewUser');
const btnChangeEmail = document.getElementById('btnChangeEmail');
const btnEditUser    = document.getElementById('btnEditUser');
const btnSaveUser      = document.getElementById('btnSaveUser');
const stepEmail      = document.getElementById('stepEmail');
const stepDisplay    = document.getElementById('stepDisplay');
const stepFields     = document.getElementById('stepFields');
const emailConfirmed = document.getElementById('emailConfirmed');
const successMsg     = document.getElementById('successMsg');
const form           = document.getElementById('registrationForm');

// ── Country list loader ───────────────────────────────────────────────────────

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

// ── Section collapse (delegated) ──────────────────────────────────────────────

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

// ── Tab switching ─────────────────────────────────────────────────────────────

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

// ── Loader ────────────────────────────────────────────────────────────────────

function showLoader() {
  document.getElementById('loadingOverlay').hidden = false;
}

function hideLoader() {
  document.getElementById('loadingOverlay').hidden = true;
}

// ── Navigation helpers ────────────────────────────────────────────────────────

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
  const mdpr = document.getElementById('movieDetailPrevRec');
  mdpr.hidden = true; mdpr.style.display = 'none';
  ['bias', 'user_knn', 'biased_mf'].forEach(k => {
    const b = document.getElementById(`prevRecBody_${k}`);     if (b) b.innerHTML = '';
    const m = document.getElementById(`prevRecMetrics_${k}`);  if (m) m.innerHTML = '';
  });
  const pp = document.getElementById('prevRecPagination'); if (pp) pp.innerHTML = '';
  document.getElementById('moviesGrid').innerHTML = '';
  document.getElementById('recResults').innerHTML = '';
  const srm = document.getElementById('saveRatingsMsg');
  srm.style.display = 'none'; srm.textContent = '';
  clearUserSimilarity();
  _moviesLoaded  = false;
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
  document.getElementById('name').value    = user.name          || '';
  document.getElementById('dob').value     = user.date_of_birth || '';
  document.getElementById('country').value = user.country       || '';
  document.getElementById('race').value    = user.race          || '';
  const genderRadio = document.querySelector(`input[name="gender"][value="${user.gender}"]`);
  if (genderRadio) genderRadio.checked = true;
}

function setFieldsDisabled(disabled) {
  stepFields.querySelectorAll('input, select, button').forEach(el => {
    el.disabled = disabled;
  });
}

// ── Shared movie detail ───────────────────────────────────────────────────────

export async function showMovieFromId(movieid, sfx = '') {
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

export function showMovieDetail(movie, sfx = '') {
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

function renderPeople(directors, writers, sfx = '') {
  const container = document.getElementById('detailPeople' + sfx);
  container.innerHTML = '';

  function capitalizeInitials(text) {
    return text.toLowerCase().split(' ')
      .map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  }

  [['Directors', directors], ['Writers', writers]].forEach(([label, people]) => {
    if (!people || people.length === 0) return;
    const group = document.createElement('div');
    group.className = 'people-group';
    const heading = document.createElement('span');
    heading.className   = 'meta-label';
    heading.textContent = label;
    group.appendChild(heading);
    people.forEach(p => {
      const attrs = ['gender', 'race', 'nationality', 'ethnicity', 'religion']
        .filter(k => p[k]).map(k => p[k].toLowerCase()).join(' · ');
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

function formatDate(raw) {
  if (!raw) return '';
  const d = new Date(raw + 'T00:00:00');
  if (isNaN(d)) return raw;
  const dd  = String(d.getUTCDate()).padStart(2, '0');
  const mmm = d.toLocaleString('en', { month: 'short', timeZone: 'UTC' });
  const yyyy = d.getUTCFullYear();
  return `${dd} - ${mmm} - ${yyyy}`;
}

// ── Container event listeners ─────────────────────────────────────────────────

emailInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') btnContinue.click();
});

btnContinue.addEventListener('click', async () => {
  const query   = emailInput.value.trim();
  const isId    = /^\d+$/.test(query);
  const isEmail = query.includes('@');
  if (!query || (!isId && !isEmail)) { emailInput.focus(); return; }

  btnContinue.disabled = true;
  btnContinue.textContent = 'Searching…';

  try {
    const res  = await fetch(`/lookup?query=${encodeURIComponent(query)}`);
    const data = await res.json();

    if (!data.found) { alert('User not found.'); return; }

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
    document.getElementById('viewGender').textContent  = user.gender  || '—';
    document.getElementById('viewRace').textContent    = user.race    || '—';
    document.getElementById('viewCountry').textContent = user.country || '—';

    _currentUserId = user.userid;
    fillFields(user);
    showMovieSections();
    showLoader();
    try {
      await Promise.all([loadUserStats(user.userid), loadUserRatings(user.userid), loadPrevRecommendations(user.userid), loadUserSimilarity(user.userid)]);
      const _rd = getRatingsData();
      if (_rd.length > 0) await showMovieFromId(_rd[0].movieid);
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
  btnSaveUser.textContent = 'Save';
  setFieldsDisabled(false);
  showMovieSections();
});

btnChangeEmail.addEventListener('click', showStep1);

btnEditUser.addEventListener('click', () => {
  stepDisplay.hidden = true;
  stepFields.hidden  = false;
  successMsg.hidden  = true;
  btnSaveUser.textContent = 'Update';
  setFieldsDisabled(false);
});

btnSaveUser.addEventListener('click', async (e) => {
  btnSaveUser.disabled = true;
  btnSaveUser.textContent = 'Saving…';
  try {
    const fd = new FormData(form);
    fd.set('email', emailInput.value);
    const res = await fetch('/submit', { method: 'POST', body: fd });
    if (!res.ok) throw new Error('Server error');
    setFieldsDisabled(true);
    const action = btnSaveUser.textContent.includes('Update') ? 'updated' : 'saved';
    successMsg.textContent = `Registration ${action} successfully.`;
    successMsg.hidden = false;
    btnSaveUser.textContent = 'Submitted';
  } catch {
    btnSaveUser.disabled = false;
    alert('Failed to save. Please try again.');
  }
});
