import { _currentUserId, showMovieFromId, showMovieDetail, POSTER_PLACEHOLDER } from './main.js';

// ── Movies grid ──────────────────────────────────────────────────────────────

export async function loadMovies() {
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
  img.className = 'movie-poster';
  img.src       = movie.poster;
  img.alt       = movie.title;
  img.loading   = 'lazy';
  img.onerror   = () => { img.onerror = null; img.src = POSTER_PLACEHOLDER; };

  const info = document.createElement('div');
  info.className = 'movie-info';

  const title = document.createElement('h3');
  title.className   = 'movie-title';
  title.textContent = movie.title;
  title.addEventListener('click', onTitleClick);

  const year = document.createElement('span');
  year.className   = 'movie-year';
  year.textContent = movie.year;

  info.appendChild(title);
  info.appendChild(year);
  info.appendChild(createStarRating(movie.movieid || ''));

  card.appendChild(img);
  card.appendChild(info);
  return card;
}

function createStarRating(movieId = '') {
  const container = document.createElement('div');
  container.className = 'star-rating';
  if (movieId) container.dataset.movieid = movieId;

  let current = 0;
  const items = [];

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

// ── Save ratings ─────────────────────────────────────────────────────────────

function showSaveMsg(el, text, type) {
  el.textContent = text;
  el.className   = `save-ratings-msg save-ratings-msg--${type}`;
  el.style.display = '';
}

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
