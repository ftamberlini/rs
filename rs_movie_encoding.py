"""
rs_movie_encoding.py — Gera movie_encoding.tsv

Colunas:
  movieid, imdbid, title
  genre_{NOME}        — 0/1 por gênero (multi-hot)
  div_{LABEL}         — 0/1 por grupo de diversidade (one-hot, 9 grupos)
  lang_{IDIOMA}       — 0/1 para os 19 idiomas mais frequentes (multi-hot)
  lang_other          — 0/1 se o filme tem idioma fora do top-19
  country_{ISO}       — 0/1 para os 29 países mais frequentes (multi-hot)
  country_other       — 0/1 se o filme tem país fora do top-29

Uso:
  uv run python rs_movie_encoding.py
  uv run python rs_movie_encoding.py --output outro_nome.tsv
"""

import argparse
import csv
import os
import re
from pathlib import Path

import oracledb
from dotenv import load_dotenv

load_dotenv()

# ── Constantes (devem coincidir com rs_rec_rl.py) ─────────────────────────────
TOP_LANGUAGES = 19
TOP_COUNTRIES = 29

DIVERSITY_LABELS = [
    "Fem_NoWhite", "Fem_White", "Fem_Mix",
    "Male_NoWhite", "Male_White", "Male_Mix",
    "Mix_NoWhite", "Mix_White", "Mix_Unknown",
]

# ── Oracle ─────────────────────────────────────────────────────────────────────

def _conn():
    return oracledb.connect(
        user=os.getenv("ORACLE_USER"),
        password=os.getenv("ORACLE_PASSWORD"),
        dsn=os.getenv("ORACLE_DSN"),
        config_dir=os.getenv("ORACLE_WALLET_DIR"),
        wallet_location=os.getenv("ORACLE_WALLET_DIR"),
        wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
    )

def _q(conn, sql, params=()):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _col(name: str) -> str:
    """Normaliza nome para cabeçalho de coluna: minúsculo, sem espaços/hífens."""
    return re.sub(r"[^a-z0-9_]", "_", name.strip().lower())

def _mid(val) -> int | None:
    """Converte MOVIEID para int, retorna None se inválido."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _diversity_group(genders: set, races: set) -> int:
    """Calcula índice 0-8 do grupo de diversidade."""
    whites = {"white", "caucasian", "european"}

    if not genders:
        g = 2
    elif genders == {"female"}:
        g = 0
    elif genders == {"male"}:
        g = 1
    else:
        g = 2

    if not races:
        r = 2
    elif races <= whites:
        r = 1
    else:
        r = 0

    return g * 3 + r


# ── Carregamento ───────────────────────────────────────────────────────────────

def load_data(conn):
    print("Carregando lista de gêneros...")
    genres = sorted(
        r["GENRE"]
        for r in _q(conn, "SELECT DISTINCT GENRE FROM MOVIE_ML_GENRE")
    )

    print("Carregando top idiomas...")
    top_langs = [
        r["LANGUAGE"]
        for r in _q(conn, """
            SELECT LANGUAGE FROM (
                SELECT LANGUAGE, COUNT(*) AS CNT FROM MOVIE_LANGUAGE
                GROUP BY LANGUAGE ORDER BY CNT DESC
            ) FETCH FIRST :1 ROWS ONLY
        """, (TOP_LANGUAGES,))
    ]

    print("Carregando top países...")
    top_countries = [
        r["ISO"]
        for r in _q(conn, """
            SELECT ISO FROM (
                SELECT ISO, COUNT(*) AS CNT FROM MOVIE_COUNTRY
                GROUP BY ISO ORDER BY CNT DESC
            ) FETCH FIRST :1 ROWS ONLY
        """, (TOP_COUNTRIES,))
    ]

    print("Carregando filmes (MOVIE_ML + MOVIE_IMDB)...")
    movies = {}
    for r in _q(conn, "SELECT MOVIEID, TITLE FROM MOVIE_ML WHERE MOVIEID IS NOT NULL"):
        mid = _mid(r["MOVIEID"])
        if mid is not None:
            movies[mid] = {"title": r["TITLE"] or "", "imdbid": ""}

    for r in _q(conn, "SELECT MOVIEID, IMDBID FROM MOVIE_IMDB WHERE MOVIEID IS NOT NULL"):
        mid = _mid(r["MOVIEID"])
        if mid in movies:
            movies[mid]["imdbid"] = r["IMDBID"] or ""

    print("Carregando gêneros por filme...")
    genre_map: dict[int, set] = {}
    for r in _q(conn, "SELECT MOVIEID, GENRE FROM MOVIE_ML_GENRE WHERE MOVIEID IS NOT NULL"):
        mid = _mid(r["MOVIEID"])
        if mid is not None:
            genre_map.setdefault(mid, set()).add(r["GENRE"])

    print("Carregando idiomas por filme...")
    lang_map: dict[int, set] = {}
    for r in _q(conn, "SELECT MOVIEID, LANGUAGE FROM MOVIE_LANGUAGE WHERE MOVIEID IS NOT NULL"):
        mid = _mid(r["MOVIEID"])
        if mid is not None:
            lang_map.setdefault(mid, set()).add(r["LANGUAGE"])

    print("Carregando países por filme...")
    country_map: dict[int, set] = {}
    for r in _q(conn, "SELECT MOVIEID, ISO FROM MOVIE_COUNTRY WHERE MOVIEID IS NOT NULL"):
        mid = _mid(r["MOVIEID"])
        if mid is not None:
            country_map.setdefault(mid, set()).add(r["ISO"])

    print("Carregando diversidade por filme (DIRECTOR)...")
    dir_genders: dict[int, set] = {}
    dir_races:   dict[int, set] = {}
    for r in _q(conn, """
        SELECT MD.MOVIEID,
               LOWER(D.GENDER) AS GENDER,
               LOWER(D.RACE)   AS RACE
        FROM MOVIE_DIRECTOR MD
        JOIN DIRECTOR D ON D.DIRECTORID = MD.DIRECTORID
        WHERE MD.MOVIEID IS NOT NULL
    """):
        mid = _mid(r["MOVIEID"])
        if mid is None:
            continue
        g  = (r["GENDER"] or "").strip()
        rc = (r["RACE"]   or "").strip()
        if g:  dir_genders.setdefault(mid, set()).add(g)
        if rc: dir_races.setdefault(mid, set()).add(rc)

    return movies, genres, top_langs, top_countries, \
           genre_map, lang_map, country_map, dir_genders, dir_races


# ── Geração do TSV ─────────────────────────────────────────────────────────────

def generate(output: str):
    conn = _conn()
    try:
        (movies, genres, top_langs, top_countries,
         genre_map, lang_map, country_map,
         dir_genders, dir_races) = load_data(conn)
    finally:
        conn.close()

    lang_set    = set(top_langs)
    country_set = set(top_countries)

    # Cabeçalhos das colunas encoded
    genre_cols   = [f"genre_{_col(g)}"       for g in genres]
    div_cols     = [f"div_{_col(lb)}"         for lb in DIVERSITY_LABELS]
    lang_cols    = [f"lang_{_col(l)}"         for l in top_langs] + ["lang_other"]
    country_cols = [f"country_{_col(c)}"      for c in top_countries] + ["country_other"]

    header = ["movieid", "imdbid", "title"] + genre_cols + div_cols + lang_cols + country_cols

    print(f"\nColunas no arquivo:")
    print(f"  Identificação  : 3  (movieid, imdbid, title)")
    print(f"  Gêneros        : {len(genre_cols)}")
    print(f"  Diversidade    : {len(div_cols)}")
    print(f"  Idiomas        : {len(lang_cols)}  (top-{TOP_LANGUAGES} + outros)")
    print(f"  Países         : {len(country_cols)}  (top-{TOP_COUNTRIES} + outros)")
    print(f"  Total colunas  : {len(header)}")
    print(f"\nGerando {output} com {len(movies)} filmes...")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)

        for mid in sorted(movies):
            info    = movies[mid]
            m_genres   = genre_map.get(mid, set())
            m_langs    = lang_map.get(mid, set())
            m_countries = country_map.get(mid, set())
            div_idx    = _diversity_group(
                dir_genders.get(mid, set()),
                dir_races.get(mid, set()),
            )

            # Gêneros: 1 se o filme tem aquele gênero
            genre_vals = [1 if g in m_genres else 0 for g in genres]

            # Diversidade: one-hot
            div_vals = [1 if i == div_idx else 0 for i in range(len(DIVERSITY_LABELS))]

            # Idiomas: 1 se top, flag "other" se tem idioma fora do top
            lang_vals = [1 if l in m_langs else 0 for l in top_langs]
            lang_vals.append(1 if m_langs - lang_set else 0)

            # Países: 1 se top, flag "other" se tem país fora do top
            country_vals = [1 if c in m_countries else 0 for c in top_countries]
            country_vals.append(1 if m_countries - country_set else 0)

            writer.writerow(
                [mid, info["imdbid"], info["title"]]
                + genre_vals + div_vals + lang_vals + country_vals
            )

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"Arquivo gerado: {out}  ({size_mb:.1f} MB)")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera movie_encoding.tsv")
    parser.add_argument("--output", default="data/movie_encoding.tsv",
                        help="Caminho do arquivo de saída (default: data/movie_encoding.tsv)")
    args = parser.parse_args()
    generate(args.output)
