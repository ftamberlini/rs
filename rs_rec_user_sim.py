"""
RecUserSim — User-similarity-based movie recommender.

Usage:
    rec = RecUserSim(user_id=1, n=10, k=10, ranking="TOPN")
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
class RecUserSim:
    user_id:  int
    n:        int   = 10
    k:        int   = 10
    ranking:  str   = "TOPN"   # TOPN | STOR

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
            (batch_id, self.user_id, movie_id, None, score, rank, ts, "user_sim", params_str)
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
        Score = μ_u + Σ(sim(u,v) × (rating(v,m) − μ_v)) / Σ|sim(u,v)|
        where μ_u and μ_v are the mean ratings of the input user and each neighbor.
        """

        # 1. k most similar neighbors
        neighbors = self._query(
            """SELECT SIMILAR_USER_ID, PEARSON_SIMILARITY
               FROM USER_SIMILARITY
               WHERE USER_ID = :1
               ORDER BY PEARSON_SIMILARITY DESC
               FETCH FIRST :2 ROWS ONLY""",
            (self.user_id, self.k),
        )
        if not neighbors:
            return []

        sim_map: dict[int, float] = {
            int(r["SIMILAR_USER_ID"]): float(r["PEARSON_SIMILARITY"])
            for r in neighbors
        }
        neighbor_ids = list(sim_map.keys())

        # 2. Mean rating of input user (μ_u)
        user_mean_rows = self._query(
            "SELECT AVG(RATING) AS MU FROM USER_MOVIE_RATING WHERE USERID = :1",
            (self.user_id,),
        )
        mu_u = float(user_mean_rows[0]["MU"] or 0.0) if user_mean_rows else 0.0

        # 3. Movies already seen by the input user
        seen_rows = self._query(
            "SELECT MOVIEID FROM USER_MOVIE_RATING WHERE USERID = :1",
            (self.user_id,),
        )
        seen_ids: set[int] = {int(r["MOVIEID"]) for r in seen_rows}

        # 4. Mean rating per neighbor (μ_v) + their ratings
        bind_vars = {f"n{i}": nid for i, nid in enumerate(neighbor_ids)}
        in_clause  = ", ".join(f":n{i}" for i in range(len(neighbor_ids)))

        mean_rows = self._query(
            f"""SELECT USERID, AVG(RATING) AS MU
                FROM USER_MOVIE_RATING
                WHERE USERID IN ({in_clause})
                GROUP BY USERID""",
            bind_vars,
        )
        mu_v: dict[int, float] = {
            int(r["USERID"]): float(r["MU"] or 0.0) for r in mean_rows
        }

        ratings = self._query(
            f"""SELECT USERID, MOVIEID, RATING
                FROM USER_MOVIE_RATING
                WHERE USERID IN ({in_clause})""",
            bind_vars,
        )

        # 5. Mean-centered weighted score per unseen movie:
        #    score(m) = μ_u + Σ( sim(u,v) × (rating(v,m) − μ_v) ) / Σ|sim(u,v)|
        score_num: dict[int, float] = {}
        score_den: dict[int, float] = {}

        for r in ratings:
            mid = int(r["MOVIEID"])
            if mid in seen_ids:
                continue
            uid    = int(r["USERID"])
            sim    = sim_map.get(uid, 0.0)
            rating = float(r["RATING"])
            mean_v = mu_v.get(uid, 0.0)
            score_num[mid] = score_num.get(mid, 0.0) + sim * (rating - mean_v)
            score_den[mid] = score_den.get(mid, 0.0) + abs(sim)

        candidates: list[tuple[int, float]] = [
            (mid, mu_u + score_num[mid] / score_den[mid])
            for mid in score_num
            if score_den[mid] > 0
        ]

        if not candidates:
            return []

        # 5. Ranking
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

    parser = argparse.ArgumentParser(description="User-similarity recommender")
    parser.add_argument("--user-id",  type=int, required=True)
    parser.add_argument("--n",        type=int, default=10)
    parser.add_argument("--k",        type=int, default=10, help="number of neighbors (5-50)")
    parser.add_argument("--ranking",  choices=["TOPN", "STOR"], default="TOPN")
    args = parser.parse_args()

    rec     = RecUserSim(user_id=args.user_id, n=args.n, k=args.k, ranking=args.ranking)
    results = rec.recommend()

    print(f"\nTop-{args.n} recommendations for user {args.user_id} "
          f"(k={args.k}, ranking={args.ranking}):\n")
    for rank, (movie_id, score) in enumerate(results, 1):
        print(f"  {rank:2}. movie_id={movie_id:<8}  score={score:.4f}")
