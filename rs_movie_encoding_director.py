"""
rs_movie_encoding_director.py — Gera movie_encoding_director.tsv

Colunas de saída:
  movieid, imdbid, title
  genre_{NOME}        — de movie_encoding.tsv
  lang_{IDIOMA}       — de movie_encoding.tsv
  <colunas>           — de MOVIE_DIRECTOR_GENDER_ENCODING  (Oracle)
  <colunas>           — de MOVIE_DIRECTOR_RACE_ENCODING    (Oracle)
  <colunas>           — de MOVIE_DIRECTOR_REGION_ENCODING  (Oracle)

Uso:
  uv run python rs_movie_encoding_director.py
  uv run python rs_movie_encoding_director.py --encoding data/movie_encoding.tsv --output data/movie_encoding_director.tsv
"""

import argparse
import csv
import os
from pathlib import Path

import oracledb
from dotenv import load_dotenv

load_dotenv()


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


def _query_table(conn, table: str) -> tuple[list[str], dict[int, dict]]:
    """
    Lê uma tabela inteira e retorna (colunas_sem_movieid, {movieid: {col: val}}).
    Assume que a tabela tem uma coluna MOVIEID.
    Colunas de identificação (MOVIEID, IMDBID, TITLE) são excluídas do resultado.
    """
    # Colunas que não são encodings e não devem ser incluídas no output
    SKIP_COLS = {"MOVIEID", "IMDBID", "TITLE"}

    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        cols_all = [d[0].upper() for d in cur.description]

        if "MOVIEID" not in cols_all:
            raise ValueError(f"Tabela {table} não tem coluna MOVIEID")

        mid_idx  = cols_all.index("MOVIEID")
        data_cols = [c for i, c in enumerate(cols_all) if cols_all[i] not in SKIP_COLS]

        rows: dict[int, dict] = {}
        for row in cur.fetchall():
            try:
                mid = int(row[mid_idx])
            except (TypeError, ValueError):
                continue
            rows[mid] = {
                col: (row[i] if row[i] is not None else 0)
                for i, col in enumerate(cols_all)
                if col not in SKIP_COLS
            }
        return data_cols, rows
    finally:
        cur.close()


# ── Carregamento do TSV base ───────────────────────────────────────────────────

def load_base(encoding_path: str) -> tuple[list[str], dict[int, dict]]:
    """
    Lê movie_encoding.tsv e extrai:
      movieid, imdbid, title, genre_*, lang_*
    Ignora div_* e country_*.
    """
    src = Path(encoding_path)
    if not src.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {src}\n"
            "Execute rs_movie_encoding.py primeiro."
        )

    print(f"Lendo {src} ...")
    movies: dict[int, dict] = {}
    keep_cols: list[str] = []

    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        header = reader.fieldnames or []

        # Colunas a manter (além dos identificadores)
        keep_cols = [
            c for c in header
            if c.startswith("genre_") or c.startswith("lang_")
        ]

        for row in reader:
            try:
                mid = int(row["movieid"])
            except (TypeError, ValueError):
                continue
            movies[mid] = {
                "imdbid": row.get("imdbid", ""),
                "title":  row.get("title", ""),
                **{c: row.get(c, "0") for c in keep_cols},
            }

    print(f"  {len(movies):,} filmes carregados do TSV.")
    return keep_cols, movies


# ── Geração ────────────────────────────────────────────────────────────────────

def generate(encoding_path: str, output: str):
    # 1. Carrega colunas base do TSV
    base_cols, base_data = load_base(encoding_path)

    # 2. Carrega as três tabelas do Oracle
    print("Conectando ao Oracle...")
    conn = _conn()
    try:
        print("  Lendo MOVIE_DIRECTOR_GENDER_ENCODING ...")
        gender_cols, gender_data = _query_table(conn, "MOVIE_DIRECTOR_GENDER_ENCODING")

        print("  Lendo MOVIE_DIRECTOR_RACE_ENCODING ...")
        race_cols, race_data = _query_table(conn, "MOVIE_DIRECTOR_RACE_ENCODING")

        print("  Lendo MOVIE_DIRECTOR_REGION_ENCODING ...")
        region_cols, region_data = _query_table(conn, "MOVIE_DIRECTOR_REGION_ENCODING")
    finally:
        conn.close()

    print(f"\n  Colunas gênero    : {len(gender_cols)}")
    print(f"  Colunas raça      : {len(race_cols)}")
    print(f"  Colunas região    : {len(region_cols)}")

    # 3. Monta cabeçalho final
    # Normaliza nomes das colunas Oracle para lowercase
    gender_cols_lc = [c.lower() for c in gender_cols]
    race_cols_lc   = [c.lower() for c in race_cols]
    region_cols_lc = [c.lower() for c in region_cols]

    header = (
        ["movieid", "imdbid", "title"]
        + base_cols
        + [f"dir_gender_{c}" for c in gender_cols_lc]
        + [f"dir_race_{c}"   for c in race_cols_lc]
        + [f"dir_region_{c}" for c in region_cols_lc]
    )

    print(f"\nColunas no arquivo de saída:")
    print(f"  Identificação  : 3")
    print(f"  Gênero (filme) : {len([c for c in base_cols if c.startswith('genre_')])}")
    print(f"  Idioma (filme) : {len([c for c in base_cols if c.startswith('lang_')])}")
    print(f"  Dir. gênero    : {len(gender_cols)}")
    print(f"  Dir. raça      : {len(race_cols)}")
    print(f"  Dir. região    : {len(region_cols)}")
    print(f"  Total colunas  : {len(header)}")

    # 4. Escreve o TSV
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Universo de filmes = união de todos os movieids
    all_mids = sorted(
        set(base_data.keys())
        | set(gender_data.keys())
        | set(race_data.keys())
        | set(region_data.keys())
    )

    print(f"\nGerando {output} com {len(all_mids):,} filmes...")

    zero_gender = {c: 0 for c in gender_cols}
    zero_race   = {c: 0 for c in race_cols}
    zero_region = {c: 0 for c in region_cols}

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)

        for mid in all_mids:
            base   = base_data.get(mid, {})
            gender = gender_data.get(mid, zero_gender)
            race   = race_data.get(mid, zero_race)
            region = region_data.get(mid, zero_region)

            row = (
                [mid, base.get("imdbid", ""), base.get("title", "")]
                + [base.get(c, "0") for c in base_cols]
                + [gender.get(c, 0) for c in gender_cols]
                + [race.get(c, 0)   for c in race_cols]
                + [region.get(c, 0) for c in region_cols]
            )
            writer.writerow(row)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"Arquivo gerado: {out}  ({size_mb:.1f} MB)")

    # 5. Sumário de cobertura
    only_tsv    = len(set(base_data) - set(gender_data) - set(race_data) - set(region_data))
    only_oracle = len((set(gender_data) | set(race_data) | set(region_data)) - set(base_data))
    both        = len(set(base_data) & (set(gender_data) | set(race_data) | set(region_data)))
    print(f"\nCobertura:")
    print(f"  Filmes com dados TSV + Oracle  : {both:,}")
    print(f"  Filmes só no TSV               : {only_tsv:,}")
    print(f"  Filmes só no Oracle            : {only_oracle:,}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera movie_encoding_director.tsv combinando TSV local e Oracle"
    )
    parser.add_argument(
        "--encoding", default="data/movie_encoding.tsv",
        help="Caminho do movie_encoding.tsv (default: data/movie_encoding.tsv)"
    )
    parser.add_argument(
        "--output", default="data/movie_encoding_director.tsv",
        help="Caminho do arquivo de saída (default: data/movie_encoding_director.tsv)"
    )
    args = parser.parse_args()
    generate(args.encoding, args.output)
