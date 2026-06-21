"""
rs_movie_category.py — Gera data/movie_category.tsv

Identifica filmes candidatos a cotas de diversidade (cota de tela):

  director_women   : 1 se o diretor é majoritariamente ou exclusivamente feminino
  director_nowhite : 1 se o diretor é majoritariamente ou exclusivamente não-branco
  director_region  : 1 se o diretor não é de origem europeia nem norte-americana
  movie_region     : 1 se a produção não é europeia nem norte-americana
  movie_region_bra : 1 se o filme tem o Brasil como país de produção

Fontes:
  Oracle  — MOVIE_DIRECTOR_GENDER_ENCODING, MOVIE_DIRECTOR_RACE_ENCODING,
             MOVIE_DIRECTOR_REGION_ENCODING, MOVIE_COUNTRY
  Local   — data/country.tsv  (mapeamento ISO → Continente)

Uso:
  uv run python rs_movie_category.py
  uv run python rs_movie_category.py --output data/movie_category.tsv
"""

import argparse
import csv
import os
from pathlib import Path

import oracledb
from dotenv import load_dotenv

load_dotenv()

# ── Constantes ────────────────────────────────────────────────────────────────

COUNTRY_TSV = Path("data/country.tsv")

# Continentes considerados "não-diversos" para as cotas de região
NON_DIVERSE_CONTINENTS = {"Europe", "North America"}

BRA_ISO = "BRA"


# ── Conexão Oracle ────────────────────────────────────────────────────────────

def _conn():
    return oracledb.connect(
        user=os.getenv("ORACLE_USER"),
        password=os.getenv("ORACLE_PASSWORD"),
        dsn=os.getenv("ORACLE_DSN"),
        config_dir=os.getenv("ORACLE_WALLET_DIR"),
        wallet_location=os.getenv("ORACLE_WALLET_DIR"),
        wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
    )


# ── Carregamento de tabelas Oracle ────────────────────────────────────────────

def _load_gender(conn) -> dict[int, dict]:
    """
    {movieid: {imdbid, gender_ef, gender_mf}}

    GENDER_EF = Exclusive Female  (diretor 100% feminino)
    GENDER_MF = Majority Female   (diretoria com maioria feminina)
    director_women = 1 quando GENDER_EF=1 OU GENDER_MF=1
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT MOVIEID, IMDBID, GENDER_EF, GENDER_MF
            FROM   MOVIE_DIRECTOR_GENDER_ENCODING
        """)
        rows = {}
        for movieid, imdbid, ef, mf in cur.fetchall():
            if movieid is None:
                continue
            rows[int(movieid)] = {
                "imdbid":    imdbid or "",
                "gender_ef": int(ef or 0),
                "gender_mf": int(mf or 0),
            }
        return rows
    finally:
        cur.close()


def _load_race(conn) -> dict[int, dict]:
    """
    {movieid: {race_enowhite, race_mnowhite}}

    RACE_ENOWHITE = Exclusive Non-White
    RACE_MNOWHITE = Majority Non-White
    director_nowhite = 1 quando RACE_ENOWHITE=1 OU RACE_MNOWHITE=1
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT MOVIEID, RACE_ENOWHITE, RACE_MNOWHITE
            FROM   MOVIE_DIRECTOR_RACE_ENCODING
        """)
        rows = {}
        for movieid, enowhite, mnowhite in cur.fetchall():
            if movieid is None:
                continue
            rows[int(movieid)] = {
                "race_enowhite": int(enowhite or 0),
                "race_mnowhite": int(mnowhite or 0),
            }
        return rows
    finally:
        cur.close()


def _load_region_director(conn) -> dict[int, dict]:
    """
    {movieid: {region_na, region_eu}}

    REGION_NA = diretor de origem norte-americana
    REGION_EU = diretor de origem europeia

    director_region = 1 quando REGION_NA=0 E REGION_EU=0
    (diretor não é de origem europeia nem norte-americana)

    Nota: a condição usa E (AND), não OU (OR). Com OR, todo diretor europeu
    (region_na=0) ou americano (region_eu=0) seria marcado incorretamente.
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT MOVIEID, REGION_NA, REGION_EU
            FROM   MOVIE_DIRECTOR_REGION_ENCODING
        """)
        rows = {}
        for movieid, region_na, region_eu in cur.fetchall():
            if movieid is None:
                continue
            rows[int(movieid)] = {
                "region_na": int(region_na or 0),
                "region_eu": int(region_eu or 0),
            }
        return rows
    finally:
        cur.close()


def _load_movie_countries(conn) -> dict[int, list[str]]:
    """
    {movieid: [iso1, iso2, ...]}  — um filme pode ter múltiplos países.
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT MOVIEID, ISO FROM MOVIE_COUNTRY WHERE MOVIEID IS NOT NULL")
        rows: dict[int, list[str]] = {}
        for movieid, iso in cur.fetchall():
            if movieid is None or iso is None:
                continue
            mid = int(movieid)
            rows.setdefault(mid, []).append(str(iso).strip().upper())
        return rows
    finally:
        cur.close()


# ── Mapeamento ISO → Continente ───────────────────────────────────────────────

def _load_iso_continent(path: Path) -> dict[str, str]:
    """
    Lê data/country.tsv e retorna {ISO: CONTINENT}.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Arquivo de países não encontrado: {path}\n"
            "Certifique-se de que data/country.tsv existe."
        )
    mapping = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            iso = (row.get("ISO") or "").strip().upper()
            continent = (row.get("CONTINENT") or "").strip()
            if iso and continent:
                mapping[iso] = continent
    return mapping


# ── Lógica de categorização ───────────────────────────────────────────────────

def _director_women(g: dict) -> int:
    """1 se GENDER_EF=1 ou GENDER_MF=1."""
    return 1 if (g.get("gender_ef", 0) or g.get("gender_mf", 0)) else 0


def _director_nowhite(r: dict) -> int:
    """1 se RACE_ENOWHITE=1 ou RACE_MNOWHITE=1."""
    return 1 if (r.get("race_enowhite", 0) or r.get("race_mnowhite", 0)) else 0


def _director_region(reg: dict) -> int:
    """
    1 se REGION_NA=0 E REGION_EU=0
    (diretor não é de origem europeia nem norte-americana).
    """
    return 1 if (reg.get("region_na", 0) == 0 and reg.get("region_eu", 0) == 0) else 0


def _movie_region(isos: list[str], iso_continent: dict[str, str]) -> int:
    """
    1 se o filme tem pelo menos um país de produção fora da Europa e América do Norte.

    Um filme pode ter múltiplos países. Basta um país não-europeu e não-norte-americano
    para que o filme seja elegível à cota de região.
    """
    for iso in isos:
        continent = iso_continent.get(iso, "")
        if continent and continent not in NON_DIVERSE_CONTINENTS:
            return 1
    return 0


def _movie_region_bra(isos: list[str]) -> int:
    """1 se BRA está entre os países de produção."""
    return 1 if BRA_ISO in isos else 0


# ── Geração do arquivo ────────────────────────────────────────────────────────

def generate(output: str):
    iso_continent = _load_iso_continent(COUNTRY_TSV)
    print(f"Mapeamento ISO→Continente: {len(iso_continent)} países")

    print("Conectando ao Oracle...")
    conn = _conn()
    try:
        print("  Lendo MOVIE_DIRECTOR_GENDER_ENCODING ...")
        gender_data = _load_gender(conn)

        print("  Lendo MOVIE_DIRECTOR_RACE_ENCODING ...")
        race_data = _load_race(conn)

        print("  Lendo MOVIE_DIRECTOR_REGION_ENCODING ...")
        region_dir_data = _load_region_director(conn)

        print("  Lendo MOVIE_COUNTRY ...")
        country_data = _load_movie_countries(conn)
    finally:
        conn.close()

    # União de todos os movieids conhecidos
    all_mids = sorted(
        set(gender_data) | set(race_data) | set(region_dir_data) | set(country_data)
    )
    print(f"\nTotal de filmes: {len(all_mids):,}")

    # Defaults para filmes sem dados em alguma tabela
    _empty_gender  = {"imdbid": "", "gender_ef": 0, "gender_mf": 0}
    _empty_race    = {"race_enowhite": 0, "race_mnowhite": 0}
    _empty_reg_dir = {"region_na": 0, "region_eu": 0}

    header = [
        "movieid", "imdbid",
        "director_women", "director_nowhite", "director_region",
        "movie_region", "movie_region_bra",
    ]

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    counters = {col: 0 for col in header[2:]}

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)

        for mid in all_mids:
            g   = gender_data.get(mid,      _empty_gender)
            r   = race_data.get(mid,        _empty_race)
            reg = region_dir_data.get(mid,  _empty_reg_dir)
            isos = country_data.get(mid,    [])

            dw  = _director_women(g)
            dnw = _director_nowhite(r)
            dr  = _director_region(reg)
            mr  = _movie_region(isos, iso_continent)
            mrb = _movie_region_bra(isos)

            for col, val in zip(header[2:], [dw, dnw, dr, mr, mrb]):
                counters[col] += val

            writer.writerow([
                mid,
                g.get("imdbid", ""),
                dw, dnw, dr, mr, mrb,
            ])

    size_kb = out.stat().st_size / 1024
    print(f"\nArquivo gerado: {out}  ({size_kb:.0f} KB)")

    print("\nResumo das categorias:")
    total = len(all_mids)
    for col, cnt in counters.items():
        print(f"  {col:<20}: {cnt:>6,} filmes  ({cnt/total*100:.1f}%)")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera movie_category.tsv com flags de diversidade para cotas de tela"
    )
    parser.add_argument(
        "--output", default="data/movie_category.tsv",
        help="Caminho do arquivo de saída (default: data/movie_category.tsv)"
    )
    args = parser.parse_args()
    generate(args.output)
