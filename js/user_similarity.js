import { loadUserStats, loadUserRatings, getRatingsData } from './previous_rating.js';
import { showMovieFromId } from './main.js';

const SIM_SFXS = ['Sim', 'SimOther'];

function _clearSections() {
  SIM_SFXS.forEach(sfx => {
    ['userStatsSection', 'userRatingsSection', 'movieDetail'].forEach(base => {
      const el = document.getElementById(base + sfx);
      if (el) { el.hidden = true; el.style.display = 'none'; }
    });
    const rb = document.getElementById('ratingsBody' + sfx);
    if (rb) rb.innerHTML = '';
  });
  const h = document.getElementById('simOtherHeading');
  if (h) h.textContent = '—';
  const b = document.getElementById('simScoreBadge');
  if (b) b.textContent = '';
}

export function clearUserSimilarity() {
  _clearSections();
  const sel = document.getElementById('simUserSelect');
  if (sel) sel.innerHTML = '';
}

export async function loadUserSimilarity(userid) {
  _clearSections();

  await Promise.all([
    loadUserStats(userid, 'Sim'),
    loadUserRatings(userid, 'Sim', 'Sim'),
  ]);
  const d = getRatingsData('Sim');
  if (d.length > 0) showMovieFromId(d[0].movieid, 'Sim');

  const sel = document.getElementById('simUserSelect');
  sel.innerHTML = '';

  try {
    const res     = await fetch(`/user_similarity/${encodeURIComponent(userid)}`);
    const similar = await res.json();

    if (!Array.isArray(similar) || !similar.length) {
      const opt = document.createElement('option');
      opt.disabled = true; opt.selected = true;
      opt.textContent = 'No similar users found';
      sel.appendChild(opt);
      return;
    }

    similar.forEach(({ user_id, similarity }) => {
      const opt = document.createElement('option');
      opt.value         = user_id;
      opt.dataset.score = similarity;
      opt.textContent   = `User ${user_id}  (${(similarity * 100).toFixed(1)}% similar)`;
      sel.appendChild(opt);
    });

    await _loadOtherUser(similar[0].user_id, similar[0].similarity);
  } catch { /* silently ignore */ }
}

async function _loadOtherUser(userid, similarity) {
  const h = document.getElementById('simOtherHeading');
  if (h) h.textContent = `User ${userid}`;
  const b = document.getElementById('simScoreBadge');
  if (b) b.textContent = `${(similarity * 100).toFixed(1)}% similar`;

  await Promise.all([
    loadUserStats(userid, 'SimOther'),
    loadUserRatings(userid, 'SimOther', 'SimOther'),
  ]);
  const d = getRatingsData('SimOther');
  if (d.length > 0) showMovieFromId(d[0].movieid, 'SimOther');
}

document.getElementById('simUserSelect')?.addEventListener('change', async (e) => {
  const opt = e.target.selectedOptions[0];
  await _loadOtherUser(opt.value, parseFloat(opt.dataset.score));
});
