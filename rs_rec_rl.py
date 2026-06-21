"""
rs_rec_rl.py — Recomendação de filmes com Aprendizado por Reforço (RL)

Três agentes DQN cooperativos (Tianshou + Gymnasium) decidem em sequência:
  Agente 1 → gênero do próximo filme
  Agente 2 → grupo de diversidade (gênero/raça dos diretores)
  Agente 3 → país de origem e idioma

Cada agente é treinado em seu próprio gymnasium.Env e cooperam na simulação final.

Dependências:
  pip install tianshou>=1.0 gymnasium torch numpy oracledb python-dotenv
"""

import os
import random
from functools import partial
from typing import Optional

import numpy as np
import torch
import gymnasium as gym
from gymnasium import spaces
import oracledb
from dotenv import load_dotenv

from tianshou.data import Batch, Collector, VectorReplayBuffer
from tianshou.env import DummyVectorEnv
from tianshou.policy import DQNPolicy
from tianshou.trainer import OffpolicyTrainer
from tianshou.utils.net.common import Net

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

HISTORY_USER_SIZE  = 10     # últimos N filmes avaliados pelo usuário
HISTORY_SYS_SIZE   = 100    # últimos N filmes recomendados pelo sistema
TOP_LANGUAGES      = 19     # idiomas mais frequentes (+ 1 bucket "outros" = 20 dims)
TOP_COUNTRIES      = 29     # países mais frequentes (+ 1 bucket "outros" = 30 dims)
N_DIVERSITY_GROUPS = 9      # 3 categorias de gênero × 3 de raça

# Rótulos descritivos dos grupos de diversidade (gender × race)
DIVERSITY_LABELS = [
    "Fem+NoWhite",   "Fem+White",   "Fem+Mix",
    "Male+NoWhite",  "Male+White",  "Male+Mix",
    "Mix+NoWhite",   "Mix+White",   "Mix+Unknown",
]

# ──────────────────────────────────────────────────────────────────────────────
# 1. Conexão Oracle
# ──────────────────────────────────────────────────────────────────────────────

def _new_conn():
    return oracledb.connect(
        user=os.getenv("ORACLE_USER"),
        password=os.getenv("ORACLE_PASSWORD"),
        dsn=os.getenv("ORACLE_DSN"),
        config_dir=os.getenv("ORACLE_WALLET_DIR"),
        wallet_location=os.getenv("ORACLE_WALLET_DIR"),
        wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
    )

def _query(conn, sql: str, params=()) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


# ──────────────────────────────────────────────────────────────────────────────
# 2. Carregamento de Dados
# ──────────────────────────────────────────────────────────────────────────────

class DataLoader:
    """Carrega e armazena em cache todos os dados de referência do Oracle."""

    def __init__(self):
        print("Conectando ao banco Oracle...")
        self.conn = _new_conn()
        self._load_reference_data()

    def _load_reference_data(self):
        print("Carregando dados de referência...")

        # Gêneros únicos
        rows = _query(self.conn,
            "SELECT DISTINCT GENRE FROM MOVIE_ML_GENRE ORDER BY GENRE")
        self.genres       = [r["GENRE"] for r in rows]
        self.genre_to_idx = {g: i for i, g in enumerate(self.genres)}
        self.n_genres     = len(self.genres)

        # Top idiomas por frequência
        rows = _query(self.conn, """
            SELECT LANGUAGE, COUNT(*) AS CNT FROM MOVIE_LANGUAGE
            GROUP BY LANGUAGE ORDER BY CNT DESC
            FETCH FIRST :1 ROWS ONLY
        """, (TOP_LANGUAGES,))
        self.languages    = [r["LANGUAGE"] for r in rows]
        self.lang_to_idx  = {l: i for i, l in enumerate(self.languages)}

        # Top países por frequência
        rows = _query(self.conn, """
            SELECT ISO, COUNT(*) AS CNT FROM MOVIE_COUNTRY
            GROUP BY ISO ORDER BY CNT DESC
            FETCH FIRST :1 ROWS ONLY
        """, (TOP_COUNTRIES,))
        self.countries       = [r["ISO"] for r in rows]
        self.country_to_idx  = {c: i for i, c in enumerate(self.countries)}

        # Top 50 combinações país × idioma (ação do Agente 3)
        rows = _query(self.conn, """
            SELECT mc.ISO, ml.LANGUAGE, COUNT(*) AS CNT
            FROM MOVIE_COUNTRY mc
            JOIN MOVIE_LANGUAGE ml ON ml.MOVIEID = mc.MOVIEID
            GROUP BY mc.ISO, ml.LANGUAGE
            ORDER BY CNT DESC
            FETCH FIRST 50 ROWS ONLY
        """)
        self.country_lang_combos = [(r["ISO"], r["LANGUAGE"]) for r in rows]
        self.cl_to_idx           = {cl: i for i, cl in enumerate(self.country_lang_combos)}
        self.n_country_lang      = len(self.country_lang_combos)

        # Features de todos os filmes (gêneros, idiomas, países, diversidade)
        print("Carregando features dos filmes (pode demorar)...")
        self.movies = self._load_movie_features()
        self.movie_ids = list(self.movies.keys())

        # IDs de usuários com histórico — split 80/20 treino/teste
        rows = _query(self.conn,
            "SELECT DISTINCT USERID FROM USER_MOVIE_RATING ORDER BY USERID")
        all_users = [int(r["USERID"]) for r in rows]
        random.shuffle(all_users)
        split = int(len(all_users) * 0.8)
        self.train_user_ids = all_users[:split]
        self.test_user_ids  = all_users[split:]
        self.user_ids       = all_users   # lista completa (usada na inferência)

        print(f"  {len(self.movie_ids)} filmes | {self.n_genres} gêneros | "
              f"{len(self.languages)} idiomas | {len(self.countries)} países | "
              f"{len(all_users)} usuários "
              f"(treino={len(self.train_user_ids)}, teste={len(self.test_user_ids)})")

    # ── Features por filme ────────────────────────────────────────────────────

    def _load_movie_features(self) -> dict[int, dict]:
        """Retorna dict[movie_id → {genres, languages, countries, diversity}]"""

        # Gêneros por filme
        genre_map: dict[int, list] = {}
        for r in _query(self.conn, "SELECT MOVIEID, GENRE FROM MOVIE_ML_GENRE"):
            genre_map.setdefault(int(r["MOVIEID"]), []).append(r["GENRE"])

        # Idiomas por filme
        lang_map: dict[int, list] = {}
        for r in _query(self.conn, "SELECT MOVIEID, LANGUAGE FROM MOVIE_LANGUAGE"):
            lang_map.setdefault(int(r["MOVIEID"]), []).append(r["LANGUAGE"])

        # Países por filme
        country_map: dict[int, list] = {}
        for r in _query(self.conn, "SELECT MOVIEID, ISO FROM MOVIE_COUNTRY"):
            country_map.setdefault(int(r["MOVIEID"]), []).append(r["ISO"])

        # Grupo de diversidade via tabela DIRECTOR + MOVIE_DIRECTOR
        diversity_map = self._compute_diversity_groups()

        all_ids = set(genre_map) | set(lang_map) | set(country_map)
        return {
            mid: {
                "genres":    genre_map.get(mid, []),
                "languages": lang_map.get(mid, []),
                "countries": country_map.get(mid, []),
                "diversity": diversity_map.get(mid, N_DIVERSITY_GROUPS - 1),
            }
            for mid in all_ids
        }

    def _compute_diversity_groups(self) -> dict[int, int]:
        """
        Atribui grupo de diversidade 0-8 a cada filme baseado no gênero/raça
        dos diretores.

        Grupos: gender_idx * 3 + race_idx
          gender: 0=feminino  1=masculino  2=misto/desconhecido
          race:   0=POC       1=branco     2=misto/desconhecido
        """
        rows = _query(self.conn, """
            SELECT MD.MOVIEID,
                   LOWER(D.GENDER) AS GENDER,
                   LOWER(D.RACE)   AS RACE
            FROM MOVIE_DIRECTOR MD
            JOIN DIRECTOR D ON D.DIRECTORID = MD.DIRECTORID
        """)

        movie_genders: dict[int, set] = {}
        movie_races:   dict[int, set] = {}
        for r in rows:
            mid = int(r["MOVIEID"])
            g   = (r["GENDER"] or "").strip()
            rc  = (r["RACE"]   or "").strip()
            if g:  movie_genders.setdefault(mid, set()).add(g)
            if rc: movie_races.setdefault(mid, set()).add(rc)

        def _gender_idx(genders: set) -> int:
            if not genders:           return 2
            if genders == {"female"}: return 0
            if genders == {"male"}:   return 1
            return 2

        def _race_idx(races: set) -> int:
            whites = {"white", "caucasian", "european"}
            if not races:      return 2
            if races <= whites: return 1   # todos brancos
            return 0                       # tem POC

        all_ids = set(movie_genders) | set(movie_races)
        return {
            mid: _gender_idx(movie_genders.get(mid, set())) * 3
               + _race_idx(movie_races.get(mid, set()))
            for mid in all_ids
        }

    # ── Dados por usuário ─────────────────────────────────────────────────────

    def load_user_ratings(self, user_id: int) -> dict[int, float]:
        rows = _query(self.conn,
            "SELECT MOVIEID, RATING FROM USER_MOVIE_RATING WHERE USERID = :1",
            (user_id,))
        return {int(r["MOVIEID"]): float(r["RATING"]) for r in rows}

    def load_system_history(self, user_id: int) -> list[int]:
        """Retorna os últimos HISTORY_SYS_SIZE filmes recomendados ao usuário."""
        rows = _query(self.conn, """
            SELECT ITEM_ID FROM RECOMMENDATION
            WHERE USERID = :1
            ORDER BY TIMESTAMP DESC, "RANK" ASC
            FETCH FIRST :2 ROWS ONLY
        """, (user_id, HISTORY_SYS_SIZE))
        return [int(r["ITEM_ID"]) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Encoding de Features
# ──────────────────────────────────────────────────────────────────────────────

class FeatureEncoder:
    """Converte dados de filmes em vetores numéricos de dimensão fixa."""

    def __init__(self, data: DataLoader):
        self.data = data
        # Vetor = multi-hot gênero + one-hot diversidade + multi-hot idioma + multi-hot país
        self.feature_dim = (
            data.n_genres
            + N_DIVERSITY_GROUPS
            + TOP_LANGUAGES + 1    # +1 bucket "outros idiomas"
            + TOP_COUNTRIES + 1    # +1 bucket "outros países"
        )

    def encode_movie(self, movie_id: int) -> np.ndarray:
        """Vetor float32 de um filme (multi-hot sobre gênero, diversidade, idioma, país)."""
        vec  = np.zeros(self.feature_dim, dtype=np.float32)
        feat = self.data.movies.get(movie_id, {})
        off  = 0

        # Gêneros (multi-hot)
        for g in feat.get("genres", []):
            if g in self.data.genre_to_idx:
                vec[off + self.data.genre_to_idx[g]] = 1.0
        off += self.data.n_genres

        # Grupo de diversidade (one-hot)
        dg = feat.get("diversity", N_DIVERSITY_GROUPS - 1)
        if dg < N_DIVERSITY_GROUPS:
            vec[off + dg] = 1.0
        off += N_DIVERSITY_GROUPS

        # Idiomas (multi-hot, posição TOP_LANGUAGES = bucket "outros")
        for l in feat.get("languages", []):
            idx = self.data.lang_to_idx.get(l, TOP_LANGUAGES)   # fora do top → "outros"
            vec[off + idx] = 1.0
        off += TOP_LANGUAGES + 1   # +1 para o bucket "outros"

        # Países (multi-hot, posição TOP_COUNTRIES = bucket "outros")
        for c in feat.get("countries", []):
            idx = self.data.country_to_idx.get(c, TOP_COUNTRIES)  # fora do top → "outros"
            vec[off + idx] = 1.0

        return vec

    def encode_movie_list(self, movie_ids: list[int]) -> np.ndarray:
        """Média dos vetores de uma lista de filmes (ou vetor zero se vazia)."""
        vecs = [self.encode_movie(m) for m in movie_ids if m in self.data.movies]
        return np.mean(vecs, axis=0).astype(np.float32) if vecs \
               else np.zeros(self.feature_dim, dtype=np.float32)

    def user_genre_preferences(self, ratings: dict[int, float]) -> np.ndarray:
        """Vetor (n_genres,) com rating médio do usuário por gênero (0 se nunca assistiu)."""
        totals = np.zeros(self.data.n_genres, dtype=np.float32)
        counts = np.zeros(self.data.n_genres, dtype=np.float32)
        for mid, rating in ratings.items():
            for g in self.data.movies.get(mid, {}).get("genres", []):
                if g in self.data.genre_to_idx:
                    idx = self.data.genre_to_idx[g]
                    totals[idx] += rating
                    counts[idx] += 1.0
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(counts > 0, totals / counts, 0.0).astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Ambiente Base
# ──────────────────────────────────────────────────────────────────────────────

class BaseMovieEnv(gym.Env):
    """
    Estado compartilhado entre os três ambientes de agentes.

    Componentes do estado base (base_obs_dim):
      - Preferência por gênero do usuário  : (n_genres,)
      - Média dos últimos 10 filmes do usuário : (feature_dim,)
      - Média dos últimos 100 filmes recomendados : (feature_dim,)
    """

    def __init__(self, data: DataLoader, encoder: FeatureEncoder,
                 user_ids: Optional[list] = None):
        super().__init__()
        self.data      = data
        self.encoder   = encoder
        # Permite restringir o ambiente a um subconjunto de usuários (treino ou teste)
        self._user_ids = user_ids if user_ids is not None else data.user_ids
        self.base_obs_dim = data.n_genres + 2 * encoder.feature_dim

        # Preenchido por _sample_episode() a cada reset
        self._user_id   = None
        self._ratings:  dict[int, float] = {}
        self._user_hist: list[int] = []
        self._sys_hist:  list[int] = []

    def _base_obs(self) -> np.ndarray:
        """Vetor de observação base (compartilhado pelos três agentes)."""
        pref     = self.encoder.user_genre_preferences(self._ratings)
        u_hist   = self.encoder.encode_movie_list(self._user_hist)
        s_hist   = self.encoder.encode_movie_list(self._sys_hist)
        return np.concatenate([pref, u_hist, s_hist]).astype(np.float32)

    def _sample_episode(self):
        """Sorteia um usuário do subconjunto configurado (treino ou teste)."""
        self._user_id   = random.choice(self._user_ids)
        self._ratings   = self.data.load_user_ratings(self._user_id)
        self._user_hist = list(self._ratings.keys())[-HISTORY_USER_SIZE:]
        self._sys_hist  = self.data.load_system_history(self._user_id)


# ──────────────────────────────────────────────────────────────────────────────
# 5a. Agente 1 — Seleção de Gênero
# ──────────────────────────────────────────────────────────────────────────────

class Agent1GenreEnv(BaseMovieEnv):
    """
    Agente 1 escolhe o gênero do próximo filme.

    Observação : estado base
    Ação       : índice de gênero  (0 … n_genres-1)
    Recompensa : α × preferência_histórica(gênero)
               + (1-α) × diversidade_vs_histórico_recente(gênero)
    """

    ALPHA = 0.6   # peso preferência vs. diversidade

    def __init__(self, data: DataLoader, encoder: FeatureEncoder):
        super().__init__(data, encoder)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.base_obs_dim,), dtype=np.float32,
        )
        self.action_space = spaces.Discrete(data.n_genres)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._sample_episode()
        return self._base_obs(), {}

    def step(self, action: int):
        genre  = self.data.genres[action]
        reward = self._reward(genre)
        # Episódio de passo único: uma decisão de recomendação por episódio
        return self._base_obs(), reward, True, False, {"genre": genre}

    def _reward(self, genre: str) -> float:
        """
        R1 = α × (rating_médio_do_gênero / 5)
           + (1-α) × fração_de_filmes_recentes_que_NÃO_têm_esse_gênero
        """
        idx  = self.data.genre_to_idx.get(genre, -1)
        pref = self.encoder.user_genre_preferences(self._ratings)

        pref_score = float(pref[idx]) / 5.0 if idx >= 0 else 0.0

        if not self._user_hist:
            div_score = 1.0
        else:
            presence = [
                1.0 if genre in self.data.movies.get(m, {}).get("genres", [])
                else 0.0
                for m in self._user_hist
            ]
            div_score = 1.0 - sum(presence) / len(presence)

        return self.ALPHA * pref_score + (1.0 - self.ALPHA) * div_score


# ──────────────────────────────────────────────────────────────────────────────
# 5b. Agente 2 — Seleção de Grupo de Diversidade
# ──────────────────────────────────────────────────────────────────────────────

class Agent2DiversityEnv(BaseMovieEnv):
    """
    Agente 2 escolhe o grupo de diversidade (gênero × raça dos diretores),
    condicionado ao gênero selecionado pelo Agente 1.

    Observação : estado base + one-hot do gênero escolhido pelo Agente 1
    Ação       : índice do grupo de diversidade  (0 … N_DIVERSITY_GROUPS-1)
    Recompensa : distância entre o grupo escolhido e o centróide dos
                 grupos dos últimos 100 filmes recomendados (estimula diversidade)
    """

    def __init__(self, data: DataLoader, encoder: FeatureEncoder):
        super().__init__(data, encoder)
        obs_dim = self.base_obs_dim + data.n_genres
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32,
        )
        self.action_space = spaces.Discrete(N_DIVERSITY_GROUPS)
        self._genre_vec = np.zeros(data.n_genres, dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._sample_episode()
        # Durante o treino, simula a escolha aleatória do Agente 1
        g_idx = random.randrange(self.data.n_genres)
        self._genre_vec = np.zeros(self.data.n_genres, dtype=np.float32)
        self._genre_vec[g_idx] = 1.0
        return self._obs(), {}

    def _obs(self) -> np.ndarray:
        return np.concatenate([self._base_obs(), self._genre_vec])

    def step(self, action: int):
        reward = self._reward(action)
        return self._obs(), reward, True, False, {"diversity_group": action}

    def _reward(self, group_idx: int) -> float:
        """
        R2 = distância Euclidiana normalizada entre o one-hot do grupo
             escolhido e o centróide dos grupos do histórico de recomendações.
        Sem histórico → recompensa neutra 0.5.
        """
        if not self._sys_hist:
            return 0.5

        chosen = np.zeros(N_DIVERSITY_GROUPS, dtype=np.float32)
        chosen[group_idx] = 1.0

        hist_vecs = []
        for mid in self._sys_hist:
            dg = self.data.movies.get(mid, {}).get("diversity", N_DIVERSITY_GROUPS - 1)
            v  = np.zeros(N_DIVERSITY_GROUPS, dtype=np.float32)
            v[min(dg, N_DIVERSITY_GROUPS - 1)] = 1.0
            hist_vecs.append(v)

        centroid  = np.mean(hist_vecs, axis=0)
        dist      = float(np.linalg.norm(chosen - centroid))
        max_dist  = float(np.sqrt(2))   # distância máxima entre dois one-hots
        return min(dist / max_dist, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# 5c. Agente 3 — Seleção de País + Idioma
# ──────────────────────────────────────────────────────────────────────────────

class Agent3GeoLangEnv(BaseMovieEnv):
    """
    Agente 3 escolhe a combinação (país de origem, idioma), condicionado
    às escolhas dos Agentes 1 e 2.

    Observação : estado base + one-hot gênero + one-hot diversidade
    Ação       : índice da combinação país×idioma  (0 … n_country_lang-1)
    Recompensa : distância entre o combo escolhido e o centróide dos combos
                 dos últimos 100 filmes recomendados (estimula diversidade geográfica)
    """

    def __init__(self, data: DataLoader, encoder: FeatureEncoder):
        super().__init__(data, encoder)
        obs_dim = self.base_obs_dim + data.n_genres + N_DIVERSITY_GROUPS
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32,
        )
        self.action_space = spaces.Discrete(data.n_country_lang)
        self._genre_vec    = np.zeros(data.n_genres, dtype=np.float32)
        self._div_vec      = np.zeros(N_DIVERSITY_GROUPS, dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._sample_episode()
        # Simula escolhas aleatórias dos Agentes 1 e 2 durante o treino
        g_idx = random.randrange(self.data.n_genres)
        d_idx = random.randrange(N_DIVERSITY_GROUPS)
        self._genre_vec = np.zeros(self.data.n_genres, dtype=np.float32)
        self._genre_vec[g_idx] = 1.0
        self._div_vec = np.zeros(N_DIVERSITY_GROUPS, dtype=np.float32)
        self._div_vec[d_idx] = 1.0
        return self._obs(), {}

    def _obs(self) -> np.ndarray:
        return np.concatenate([self._base_obs(), self._genre_vec, self._div_vec])

    def step(self, action: int):
        reward = self._reward(action)
        return self._obs(), reward, True, False, {"country_lang_idx": action}

    def _reward(self, combo_idx: int) -> float:
        """
        R3 = distância entre o one-hot do combo escolhido e o centróide
             dos combos país×idioma dos últimos 100 filmes recomendados.
        """
        if not self._sys_hist:
            return 0.5

        n_cl   = self.data.n_country_lang
        chosen = np.zeros(n_cl, dtype=np.float32)
        chosen[combo_idx] = 1.0

        hist_vecs = []
        for mid in self._sys_hist:
            v = np.zeros(n_cl, dtype=np.float32)
            m = self.data.movies.get(mid, {})
            for c in m.get("countries", []):
                for l in m.get("languages", []):
                    idx = self.data.cl_to_idx.get((c, l))
                    if idx is not None:
                        v[idx] = 1.0
            hist_vecs.append(v)

        centroid = np.mean(hist_vecs, axis=0)
        dist     = float(np.linalg.norm(chosen - centroid))
        max_dist = float(np.sqrt(n_cl))
        return min(dist / max_dist, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# 6. Treinamento com DQN (Tianshou)
# ──────────────────────────────────────────────────────────────────────────────

def _build_dqn(obs_dim: int, action_dim: int, lr: float = 1e-3) -> DQNPolicy:
    """Cria uma política DQN com MLP de 3 camadas."""
    net = Net(
        state_shape=obs_dim,
        action_shape=action_dim,
        hidden_sizes=[256, 256, 128],
        device="cpu",
    )
    optimizer = torch.optim.Adam(net.parameters(), lr=lr)
    return DQNPolicy(
        model=net,
        optim=optimizer,
        action_space=spaces.Discrete(action_dim),
        discount_factor=0.99,
        estimation_step=1,
        target_update_freq=200,
    )


def train_agent(
    env_cls,
    data: DataLoader,
    encoder: FeatureEncoder,
    label: str       = "",
    n_envs: int      = 4,
    buffer_size: int = 20_000,
    n_epoch: int     = 5,
    step_per_epoch: int   = 2_000,
    step_per_collect: int = 100,
    batch_size: int  = 256,
    lr: float        = 1e-3,
) -> DQNPolicy:
    """
    Treina um agente DQN para um ambiente gymnasium.
    Retorna a política treinada.
    """
    print(f"\n{'─'*60}")
    print(f"Treinando {label}...")

    make_train = partial(env_cls, data, encoder, data.train_user_ids)
    make_test  = partial(env_cls, data, encoder, data.test_user_ids)
    train_envs = DummyVectorEnv([make_train] * n_envs)
    test_envs  = DummyVectorEnv([make_test])

    # Infere dimensões a partir de uma instância de referência
    ref_env    = make_train()
    obs_dim    = ref_env.observation_space.shape[0]
    action_dim = ref_env.action_space.n
    ref_env.close()

    policy  = _build_dqn(obs_dim, action_dim, lr=lr)
    buffer  = VectorReplayBuffer(buffer_size, buffer_num=n_envs)

    train_collector = Collector(policy, train_envs, buffer, exploration_noise=True)
    test_collector  = Collector(policy, test_envs)

    # Pré-preenche o buffer com transições aleatórias antes do treino
    train_collector.collect(n_step=batch_size * 4)

    total_steps = n_epoch * step_per_epoch   # total de steps de treino
    eps_start   = 0.5
    eps_end     = 0.05

    def train_fn(_epoch, global_step):
        # Decaimento linear de ε por step: 0.5 → 0.05 ao longo de todo o treino
        eps = max(eps_end, eps_start - (eps_start - eps_end) * global_step / total_steps)
        policy.set_eps(eps)

    def test_fn(_epoch, _step):
        policy.set_eps(0.0)   # greedy na avaliação

    result = OffpolicyTrainer(
        policy=policy,
        train_collector=train_collector,
        test_collector=test_collector,
        max_epoch=n_epoch,
        step_per_epoch=step_per_epoch,
        step_per_collect=step_per_collect,
        episode_per_test=20,
        batch_size=batch_size,
        train_fn=train_fn,
        test_fn=test_fn,
        verbose=True,
    ).run()

    print(f"  Concluído. Melhor recompensa: {result['best_reward']:.4f}")
    train_envs.close()
    test_envs.close()
    return policy


# ──────────────────────────────────────────────────────────────────────────────
# 7. Simulação de Recomendação
# ──────────────────────────────────────────────────────────────────────────────

def _agent_act(policy: DQNPolicy, obs: np.ndarray) -> int:
    """Executa inferência greedy de uma política treinada."""
    policy.set_eps(0.0)
    with torch.no_grad():
        obs_t  = torch.tensor(obs[None], dtype=torch.float32)
        result = policy(Batch(obs=obs_t, info={}))
    return int(result.act[0])


def _find_movie(
    data: DataLoader,
    seen: set,
    genre: Optional[str]       = None,
    diversity: Optional[int]   = None,
    country: Optional[str]     = None,
    language: Optional[str]    = None,
) -> Optional[int]:
    """
    Busca um filme não visto que satisfaça as restrições.
    Relaxa progressivamente: (gênero+diversidade+país+idioma) → (gênero+país) → (gênero).
    """
    def match(mid, req_genre, req_div, req_country, req_lang):
        f = data.movies.get(mid, {})
        return (
            mid not in seen
            and (req_genre   is None or req_genre   in f.get("genres", []))
            and (req_div     is None or f.get("diversity") == req_div)
            and (req_country is None or req_country in f.get("countries", []))
            and (req_lang    is None or req_lang    in f.get("languages", []))
        )

    for relaxed in [
        (genre, diversity, country, language),   # todas as restrições
        (genre, None,      country, None),        # só gênero + país
        (genre, None,      None,    None),        # só gênero
        (None,  None,      None,    None),        # qualquer não visto
    ]:
        pool = [m for m in data.movie_ids if match(m, *relaxed)]
        if pool:
            return random.choice(pool)
    return None


def recommend(
    user_id: int,
    data: DataLoader,
    encoder: FeatureEncoder,
    policy1: DQNPolicy,
    policy2: DQNPolicy,
    policy3: DQNPolicy,
    n: int = 10,
) -> list[dict]:
    """
    Gera n recomendações para user_id executando os três agentes em sequência.
    O histórico interno é atualizado a cada iteração.
    """
    ratings   = data.load_user_ratings(user_id)
    user_hist = list(ratings.keys())[-HISTORY_USER_SIZE:]
    sys_hist  = data.load_system_history(user_id)
    seen      = set(ratings.keys())

    recs = []
    for _ in range(n):
        pref     = encoder.user_genre_preferences(ratings)
        u_mean   = encoder.encode_movie_list(user_hist)
        s_mean   = encoder.encode_movie_list(sys_hist)
        base_obs = np.concatenate([pref, u_mean, s_mean])

        # ── Agente 1: gênero ─────────────────────────────────────────────────
        act1  = _agent_act(policy1, base_obs)
        genre = data.genres[act1]
        g_vec = np.zeros(data.n_genres, dtype=np.float32)
        g_vec[act1] = 1.0

        # ── Agente 2: grupo de diversidade ───────────────────────────────────
        act2  = _agent_act(policy2, np.concatenate([base_obs, g_vec]))
        d_vec = np.zeros(N_DIVERSITY_GROUPS, dtype=np.float32)
        d_vec[act2] = 1.0

        # ── Agente 3: país + idioma ───────────────────────────────────────────
        act3     = _agent_act(policy3, np.concatenate([base_obs, g_vec, d_vec]))
        country, language = data.country_lang_combos[act3]

        # ── Seleciona um filme que satisfaça as restrições ────────────────────
        movie_id = _find_movie(data, seen,
                               genre=genre, diversity=act2,
                               country=country, language=language)
        if movie_id is None:
            continue

        seen.add(movie_id)
        sys_hist = ([movie_id] + sys_hist)[:HISTORY_SYS_SIZE]
        feat = data.movies.get(movie_id, {})
        recs.append({
            "movie_id":        movie_id,
            "genre_chosen":    genre,
            "diversity_group": act2,
            "diversity_label": DIVERSITY_LABELS[act2],
            "country":         country,
            "language":        language,
            "movie_genres":    feat.get("genres", []),
            "movie_countries": feat.get("countries", []),
            "movie_languages": feat.get("languages", []),
        })
    return recs


# ──────────────────────────────────────────────────────────────────────────────
# 8. CLI / ponto de entrada
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RL Movie Recommender — 3 agentes DQN")
    parser.add_argument("--user-id",    type=int, default=None,
                        help="ID do usuário (aleatório se omitido)")
    parser.add_argument("--n",          type=int, default=10,
                        help="Número de filmes a recomendar")
    parser.add_argument("--epochs",     type=int, default=5,
                        help="Épocas de treino por agente")
    parser.add_argument("--skip-train", action="store_true",
                        help="Pula o treino e usa políticas aleatórias (teste rápido)")
    args = parser.parse_args()

    # 1. Carregamento de dados
    data    = DataLoader()
    encoder = FeatureEncoder(data)

    print(f"\nDimensão do vetor de features : {encoder.feature_dim}")
    print(f"Gêneros ({data.n_genres})     : {data.genres[:5]} ...")
    print(f"Idiomas ({len(data.languages)}) : {data.languages[:5]} ...")
    print(f"Países  ({len(data.countries)}) : {data.countries[:5]} ...")
    print(f"Combos país×idioma             : {data.n_country_lang}")

    # 2. Treino dos agentes
    if not args.skip_train:
        policy1 = train_agent(Agent1GenreEnv,     data, encoder,
                              label="Agente 1 (Gênero)", n_epoch=args.epochs)
        policy2 = train_agent(Agent2DiversityEnv, data, encoder,
                              label="Agente 2 (Diversidade)", n_epoch=args.epochs)
        policy3 = train_agent(Agent3GeoLangEnv,   data, encoder,
                              label="Agente 3 (País + Idioma)", n_epoch=args.epochs)
    else:
        print("\n[--skip-train] Usando políticas aleatórias para teste.")
        e1 = Agent1GenreEnv(data, encoder, data.train_user_ids)
        e2 = Agent2DiversityEnv(data, encoder, data.train_user_ids)
        e3 = Agent3GeoLangEnv(data, encoder, data.train_user_ids)
        policy1 = _build_dqn(e1.observation_space.shape[0], e1.action_space.n)
        policy2 = _build_dqn(e2.observation_space.shape[0], e2.action_space.n)
        policy3 = _build_dqn(e3.observation_space.shape[0], e3.action_space.n)
        for p in (policy1, policy2, policy3):
            p.set_eps(1.0)   # ações completamente aleatórias
        e1.close(); e2.close(); e3.close()

    # 3. Simulação de recomendação
    user_id = args.user_id or random.choice(data.user_ids)
    print(f"\n{'═'*60}")
    print(f"Recomendações para usuário {user_id} (n={args.n})")
    print(f"{'═'*60}")

    recs = recommend(user_id, data, encoder, policy1, policy2, policy3, n=args.n)

    header = f"{'#':>3}  {'movie_id':>8}  {'Gênero':<18}  {'País':<6}  {'Idioma':<12}  Diversidade"
    print(f"\n{header}")
    print("─" * len(header))
    for i, r in enumerate(recs, 1):
        print(f"{i:>3}. {r['movie_id']:>8}  {r['genre_chosen']:<18}  "
              f"{r['country']:<6}  {r['language']:<12}  {r['diversity_label']}")

    print(f"\n{len(recs)} filmes recomendados.")
