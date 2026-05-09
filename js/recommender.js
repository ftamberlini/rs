import { _currentUserId, POSTER_PLACEHOLDER, showMovieFromId } from './main.js';

const btnSimulate = document.getElementById('btnSimulateRec');
const modelSelect = document.getElementById('modelSelect');
const recResults  = document.getElementById('recResults');
btnSimulate.addEventListener('click', async () => {
  if (!_currentUserId) {
    alert('Please select a user first.');
    return;
  }

  const model = modelSelect.value;
  const n     = Math.min(50, Math.max(5, parseInt(document.getElementById('recN').value) || 10));
  btnSimulate.disabled     = true;
  btnSimulate.textContent  = 'Loading…';
  recResults.innerHTML     = '<p class="rec-loading">Training model and generating recommendations…</p>';

  try {
    const params = new URLSearchParams({ userid: _currentUserId, model, n });
    const res    = await fetch(`/recommend?${params}`);
    const data = await res.json();

    recResults.innerHTML = '';

    if (!data.length) {
      recResults.innerHTML = '<p class="rec-empty">No recommendations found for this user.</p>';
      return;
    }

    const grid = document.createElement('div');
    grid.className = 'movies-grid';

    data.forEach(movie => {
      const card = document.createElement('div');
      card.className = 'movie-card';

      const rankBadge = document.createElement('span');
      rankBadge.className   = 'rec-rank-badge';
      rankBadge.textContent = `#${movie.rank}`;

      const img = document.createElement('img');
      img.className = 'movie-poster';
      img.alt       = movie.title;
      img.onerror   = () => { img.onerror = null; img.src = POSTER_PLACEHOLDER; };
      img.src       = movie.poster || POSTER_PLACEHOLDER;

      const info = document.createElement('div');
      info.className = 'movie-info';

      const title = document.createElement('div');
      title.className   = 'movie-title';
      title.textContent = movie.title;

      const meta = document.createElement('div');
      meta.className = 'movie-meta';
      const parts = [movie.year, movie.runtime, movie.genre].filter(Boolean);
      meta.textContent = parts.join(' · ');

      info.appendChild(title);
      info.appendChild(meta);

      if (movie.score != null) {
        const score = document.createElement('div');
        score.className   = 'rec-score';
        score.textContent = `Score: ${movie.score.toFixed(3)}`;
        info.appendChild(score);
      }

      card.appendChild(rankBadge);
      card.appendChild(img);
      card.appendChild(info);
      card.addEventListener('click', () => showMovieFromId(movie.movieid, 'New'));
      grid.appendChild(card);
    });

    recResults.appendChild(grid);
  } catch {
    recResults.innerHTML = '<p class="rec-empty">Failed to load recommendations. Please try again.</p>';
  } finally {
    btnSimulate.disabled    = false;
    btnSimulate.textContent = 'Simulate Recommendations';
  }
});
