"""
RecItemSim — Item-similarity-based movie recommender.

For each movie the user has rated, finds k similar items, aggregates
scores for unseen movies using a mean-centered weighted formula, then
ranks and saves the top-n recommendations to the RECOMMENDATION table.

Usage:
    rec = RecItemSim(user_id=1, n=10, k=20, ranking="TOPN")
    results = rec.recommend()   # [(movie_id, score), ...]
"""

import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

import oracledb
from dotenv import load_dotenv


@dataclass
class RecItemSim:
    user_id: int
    n:       int  = 10
    k:       int  = 20
    ranking: str  = "TOPN"   # TOPN | STOR

    _conn: object = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not 5 <= self.k <= 50:
            raise ValueError(f"k must be between 5 and 50, got {self.k}")
        if self.ranking not in ("TOPN", "STOR"):
            raise ValueError(f"ranking must be TOPN or STOR, got {self.ranking!r}")

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        if self._conn is None:
            load_dotenv()
            self._conn = oracledb.connect(
                user=os.getenv("ORACLE_USER"),
                password=os.getenv("ORACLE_PASSWORD"),
                dsn=os.getenv("ORACLE_DSN"),
                config_dir=os.getenv("ORACLE_WALLET_DIR"),
                wallet_location=os.getenv("ORACLE_WALLET_DIR"),
                wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
            )
        return self._conn

    def _query(self, sql: str, params=()) -> list[dict]:
        cur = self._get_conn().cursor()
        try:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _next_batch_id(self) -> int:
        cur = self._get_conn().cursor()
        try:
            cur.execute("SELECT COALESCE(MAX(REC_BATCH_ID), 0) + 1 FROM RECOMMENDATION")
            return cur.fetchone()[0]
        finally:
            cur.close()

    def _save(self, results: list[tuple[int, float]]) -> int:
        if not results:
            return 0
        batch_id   = self._next_batch_id()
        ts         = datetime.now(timezone.utc)
        params_str = json.dumps({"k": self.k, "ranking": self.ranking})
        rows = [
            (batch_id, self.user_id, movie_id, None, score, rank, ts, "item_sim", params_str)
            for rank, (movie_id, score) in enumerate(results, 1)
        ]
        cur = self._get_conn().cursor()
        try:
            cur.executemany(
                'INSERT INTO RECOMMENDATION'
                ' (REC_BATCH_ID, USERID, ITEM_ID, ITEM_NUM, SCORE, "RANK", TIMESTAMP, MODEL, PARAMETERS)'
                ' VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9)',
                rows,
            )
            self._get_conn().commit()
        finally:
            cur.close()
        print(f"Saved {len(rows)} recommendations with REC_BATCH_ID={batch_id}.")
        return batch_id

    # ------------------------------------------------------------------
    # Main method
    # ------------------------------------------------------------------

    def recommend(self) -> list[tuple[int, float]]:
        """
        Returns a list of (movie_id, score) tuples, length <= n.
        Score = μ_u + Σ( sim(i,j) × (rating(u,i) − μ_u) ) / Σ|sim(i,j)|
        where i = rated movie, j = candidate movie, μ_u = user mean rating.
        """

        # 1. Ratings of input user + mean (μ_u)
        rated_rows = self._query(
            "SELECT MOVIEID, RATING FROM USER_MOVIE_RATING WHERE USERID = :1",
            (self.user_id,),
        )
        if not rated_rows:
            return []

        rating_map: dict[int, float] = {
            int(r["MOVIEID"]): float(r["RATING"]) for r in rated_rows
        }
        seen_ids     = set(rating_map.keys())
        mu_u         = sum(rating_map.values()) / len(rating_map)
        rated_ids    = list(seen_ids)

        # 2. k most similar items for each rated movie (one query with IN)
        bind_vars = {f"m{i}": mid for i, mid in enumerate(rated_ids)}
        in_clause  = ", ".join(f":m{i}" for i in range(len(rated_ids)))
        sim_rows = self._query(
            f"""SELECT MOVIE_ID, SIMILAR_MOVIE_ID, SIMILARITY
                FROM ITEM_SIMILARITY
                WHERE MOVIE_ID IN ({in_clause})
                ORDER BY MOVIE_ID, SIMILARITY DESC""",
            bind_vars,
        )

        # Keep only top-k per seed movie
        k_per_movie: dict[int, list[tuple[int, float]]] = {}
        for r in sim_rows:
            seed   = int(r["MOVIE_ID"])
            cand   = int(r["SIMILAR_MOVIE_ID"])
            sim    = float(r["SIMILARITY"])
            bucket = k_per_movie.setdefault(seed, [])
            if len(bucket) < self.k:
                bucket.append((cand, sim))

        # 3. Mean-centered weighted score per unseen candidate:
        #    score(j) = μ_u + Σ( sim(i,j) × (rating(u,i) − μ_u) ) / Σ|sim(i,j)|
        score_num: dict[int, float] = {}
        score_den: dict[int, float] = {}

        for seed_id, similars in k_per_movie.items():
            user_rating = rating_map.get(seed_id, mu_u)
            centered    = user_rating - mu_u
            for (cand_id, sim) in similars:
                if cand_id in seen_ids:
                    continue
                score_num[cand_id] = score_num.get(cand_id, 0.0) + sim * centered
                score_den[cand_id] = score_den.get(cand_id, 0.0) + abs(sim)

        candidates: list[tuple[int, float]] = [
            (mid, mu_u + score_num[mid] / score_den[mid])
            for mid in score_num
            if score_den[mid] > 0
        ]

        if not candidates:
            return []

        # 4. Ranking
        if self.ranking == "TOPN":
            candidates.sort(key=lambda x: x[1], reverse=True)
            result = candidates[: self.n]
        else:
            # STOR — stochastic sampling, probability ∝ score (shifted to be > 0)
            movie_ids  = [c[0] for c in candidates]
            raw_scores = [c[1] for c in candidates]
            min_s      = min(raw_scores)
            shifted    = [s - min_s + 1e-9 for s in raw_scores]
            total      = sum(shifted)
            probs      = [s / total for s in shifted]

            n_sample = min(self.n, len(candidates))
            chosen   = random.choices(range(len(movie_ids)), weights=probs, k=n_sample * 3)

            seen_idx: set[int] = set()
            result = []
            for idx in chosen:
                if idx not in seen_idx:
                    seen_idx.add(idx)
                    result.append((movie_ids[idx], raw_scores[idx]))
                if len(result) == n_sample:
                    break

            if len(result) < n_sample:
                remaining = sorted(
                    [(movie_ids[i], raw_scores[i]) for i in range(len(movie_ids)) if i not in seen_idx],
                    key=lambda x: x[1], reverse=True,
                )
                result.extend(remaining[: n_sample - len(result)])

        self._save(result)
        return result


# ------------------------------------------------------------------
# CLI / quick test
# ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Item-similarity recommender")
    parser.add_argument("--user-id",  type=int, required=True)
    parser.add_argument("--n",        type=int, default=10)
    parser.add_argument("--k",        type=int, default=20)
    parser.add_argument("--ranking",  choices=["TOPN", "STOR"], default="TOPN")
    args = parser.parse_args()

    rec     = RecItemSim(user_id=args.user_id, n=args.n, k=args.k, ranking=args.ranking)
    results = rec.recommend()

    print(f"\nTop-{args.n} recommendations for user {args.user_id} "
          f"(k={args.k}, ranking={args.ranking}):\n")
    for rank, (movie_id, score) in enumerate(results, 1):
        print(f"  {rank:2}. movie_id={movie_id:<8}  score={score:.4f}")
