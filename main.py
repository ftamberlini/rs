import csv
import json
import math
import os
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import oracledb
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse as _JSONResponse
from fastapi.staticfiles import StaticFiles


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


class JSONResponse(_JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")

load_dotenv()

app = FastAPI()
app.mount("/css", StaticFiles(directory="css"), name="css")
app.mount("/js",  StaticFiles(directory="js"),  name="js")

COUNTRY_PATH = Path("data/country.tsv")

# ---------------------------------------------------------------------------
# Database connection — Oracle (Autonomous Database with Wallet)
# ---------------------------------------------------------------------------

_conn = None


def _new_conn():
    return oracledb.connect(
        user=os.getenv("ORACLE_USER"),
        password=os.getenv("ORACLE_PASSWORD"),
        dsn=os.getenv("ORACLE_DSN"),
        config_dir=os.getenv("ORACLE_WALLET_DIR"),
        wallet_location=os.getenv("ORACLE_WALLET_DIR"),
        wallet_password=os.getenv("ORACLE_WALLET_PASSWORD"),
    )


def _get_conn():
    global _conn
    if _conn is None:
        _conn = _new_conn()
    return _conn


def _reset_conn():
    global _conn
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass
    _conn = _new_conn()
    return _conn


def _adapt_sql(sql: str) -> str:
    counter = 0
    result = []
    i = 0
    while i < len(sql):
        if sql[i:i+2] == "%s":
            counter += 1
            result.append(f":{counter}")
            i += 2
        else:
            result.append(sql[i])
            i += 1
    return "".join(result)


def _sf_query(sql: str, params=None) -> list[dict]:
    for attempt in range(2):
        try:
            cur = _get_conn().cursor()
            try:
                cur.execute(_adapt_sql(sql), params or ())
                cols = [c[0] for c in cur.description] if cur.description else []
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                cur.close()
        except Exception:
            if attempt == 0:
                _reset_conn()
            else:
                raise


def _sf_execute(sql: str, params=None) -> None:
    for attempt in range(2):
        try:
            cur = _get_conn().cursor()
            try:
                cur.execute(_adapt_sql(sql), params or ())
                return
            finally:
                cur.close()
        except Exception:
            if attempt == 0:
                _reset_conn()
            else:
                raise


def _sf_executemany(sql: str, params_list: list) -> None:
    for attempt in range(2):
        try:
            cur = _get_conn().cursor()
            try:
                cur.executemany(_adapt_sql(sql), params_list)
                return
            finally:
                cur.close()
        except Exception:
            if attempt == 0:
                _reset_conn()
            else:
                raise


# ---------------------------------------------------------------------------
# ISO → Continent (loaded once from local TSV — tiny file)
# ---------------------------------------------------------------------------

def _load_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))

_iso_continent: dict[str, str] = {
    r["ISO"]: r["CONTINENT"] for r in _load_tsv(COUNTRY_PATH) if r.get("ISO")
}

_RAND = "DBMS_RANDOM.VALUE"

# ---------------------------------------------------------------------------
# Lazy global stats cache
# ---------------------------------------------------------------------------

_global_stats_cache: dict | None = None

def _get_global_stats() -> dict:
    global _global_stats_cache
    if _global_stats_cache is None:
        row = _sf_query("""
            SELECT COUNT(DISTINCT USERID)            AS N_USERS,
                   COUNT(*) / COUNT(DISTINCT USERID) AS AVG_MOVIES,
                   AVG(RATING)                       AS AVG_RATING,
                   STDDEV_POP(RATING)                AS STD_RATING
            FROM USER_MOVIE_RATING
        """)[0]
        _global_stats_cache = {
            "avg_movies": round(float(row["AVG_MOVIES"] or 0), 1),
            "avg_rating": round(float(row["AVG_RATING"] or 0), 2),
            "std":        round(float(row["STD_RATING"] or 0), 2),
        }
    return _global_stats_cache

# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _clean(val) -> str:
    v = (str(val) if val is not None else "").strip()
    return "" if v in ("N/A", "") else v

def _genres_imdb(movieid: str) -> list[str]:
    return [r["GENRE"] for r in _sf_query(
        "SELECT GENRE FROM MOVIE_IMDB_GENRE WHERE MOVIEID = %s", (movieid,)
    )]

def _genres_ml(movieid: str) -> list[str]:
    return [r["GENRE"] for r in _sf_query(
        "SELECT GENRE FROM MOVIE_ML_GENRE WHERE MOVIEID = %s", (movieid,)
    )]

def _tags(movieid: str) -> list[dict]:
    rows = _sf_query(
        'SELECT TAG, "COUNT" FROM MOVIE_TAG WHERE MOVIEID = %s ORDER BY "COUNT" DESC FETCH FIRST 20 ROWS ONLY',
        (movieid,),
    )
    return [{"tag": r["TAG"], "count": int(r["COUNT"] or 0)} for r in rows]

def _ratings(ml: dict, imdb: dict) -> list[dict]:
    result: list[dict] = []
    ml_score = _clean(ml.get("RATING_ML"))
    if ml_score:
        entry: dict = {"source": "Movie Lens", "score": f"{float(ml_score):.1f}/5"}
        ml_votes = _clean(ml.get("VOTES_ML"))
        if ml_votes:
            entry["votes"] = ml_votes
        result.append(entry)
    imdb_score = _clean(imdb.get("IMDBRATING"))
    if imdb_score:
        entry = {"source": "IMDb", "score": f"{float(imdb_score):.1f}/10"}
        imdb_votes = _clean(imdb.get("IMDBVOTES"))
        if imdb_votes:
            entry["votes"] = imdb_votes
        result.append(entry)
    rt = _clean(imdb.get("RTRATING"))
    if rt:
        result.append({"source": "Rotten Tomatoes", "score": f"{float(rt):.0f}/100"})
    mc = _clean(imdb.get("MCRATING"))
    if mc:
        result.append({"source": "Metacritic", "score": f"{float(mc):.0f}/100"})
    return result

def _people(movieid: str, role: str) -> list[dict]:
    if role == "director":
        rows = _sf_query("""
            SELECT D.NAME, D.GENDER, D.RACE, D.NATIONALITY, D.ETHNICITY, D.RELIGION
            FROM DIRECTOR D JOIN MOVIE_DIRECTOR MD ON D.DIRECTORID = MD.DIRECTORID
            WHERE MD.MOVIEID = %s
        """, (movieid,))
    else:
        rows = _sf_query("""
            SELECT W.NAME, W.GENDER, W.RACE, W.NATIONALITY, W.ETHNICITY, W.RELIGION
            FROM WRITER W JOIN MOVIE_WRITER MW ON W.WRITERID = MW.WRITERID
            WHERE MW.MOVIEID = %s
        """, (movieid,))
    result = []
    for p in rows:
        entry = {}
        for key, col in [("name", "NAME"), ("gender", "GENDER"), ("race", "RACE"),
                          ("nationality", "NATIONALITY"), ("ethnicity", "ETHNICITY"),
                          ("religion", "RELIGION")]:
            val = (p.get(col) or "").strip()
            if val and val != "N/A":
                entry[key] = val
        if entry.get("name"):
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse("index.html")


@app.get("/countries")
async def countries():
    if not COUNTRY_PATH.exists():
        return JSONResponse([])
    with open(COUNTRY_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return JSONResponse([{"name": r["COUNTRY"], "iso": r["ISO"]} for r in rows])


@app.get("/movie/{movieid}")
async def movie_detail_by_id(movieid: str):
    imdb_rows = _sf_query("SELECT * FROM MOVIE_IMDB WHERE MOVIEID = %s", (movieid,))
    if not imdb_rows:
        return JSONResponse({})
    r  = imdb_rows[0]
    ml_rows = _sf_query("SELECT * FROM MOVIE_ML WHERE MOVIEID = %s", (movieid,))
    ml = ml_rows[0] if ml_rows else {}
    return JSONResponse({
        "id":          movieid,
        "imdb_id":     _clean(r.get("IMDBID", "")),
        "title":       r.get("TITLE", ""),
        "year":        r.get("YEAR", ""),
        "released":    r.get("RELEASED", ""),
        "runtime":     r.get("RUNTIME", ""),
        "country":     r.get("COUNTRY", ""),
        "language":    r.get("LANGUAGE", ""),
        "genre":       r.get("GENRE", ""),
        "director":    r.get("DIRECTOR", ""),
        "writer":      r.get("WRITER", ""),
        "cast":        r.get("ACTORS", ""),
        "plot":        r.get("PLOT", ""),
        "poster":      r.get("POSTER", ""),
        "awards":      r.get("AWARDS", ""),
        "ratings":     _ratings(ml, r),
        "directors":   _people(movieid, "director"),
        "writers":     _people(movieid, "writer"),
        "genres_imdb": _genres_imdb(movieid),
        "genres_ml":   _genres_ml(movieid),
        "tags":        _tags(movieid),
    })


@app.get("/movies")
async def movies(userid: str = ""):
    exclude = ""
    params: tuple = ()
    if userid:
        exclude = """AND MOVIEID NOT IN (
            SELECT MOVIEID FROM USER_MOVIE_RATING     WHERE USERID = %s
            UNION
            SELECT MOVIEID FROM NEW_USER_MOVIE_RATING WHERE USERID = %s
        )"""
        params = (userid, userid)
    rows = _sf_query(
        f"SELECT MOVIEID, TITLE, YEAR, POSTER FROM MOVIE_IMDB"
        f" WHERE POSTER IS NOT NULL AND POSTER != 'N/A' {exclude}"
        f" ORDER BY {_RAND} FETCH FIRST 10 ROWS ONLY",
        params or (),
    )
    return JSONResponse([
        {
            "movieid": str(r.get("MOVIEID", "")),
            "id":      str(r.get("MOVIEID", "")),
            "title":   r.get("TITLE", ""),
            "year":    r.get("YEAR", ""),
            "poster":  r.get("POSTER", ""),
        }
        for r in rows
    ])


@app.get("/user_stats/{userid}")
async def user_stats(userid: str):
    ratings = _sf_query("SELECT MOVIEID, RATING FROM USER_MOVIE_RATING WHERE USERID = %s", (userid,))
    if not ratings:
        return JSONResponse({})

    def _award_bucket(n: int) -> str:
        if n == 0:    return "0"
        if n <= 10:   return "1-10"
        if n <= 50:   return "11-50"
        if n <= 100:  return "51-100"
        return "+100"

    def _safe_int(val):
        try: return int(float(val)) if val else 0
        except (ValueError, TypeError): return 0

    values  = [float(r["RATING"]) for r in ratings if r.get("RATING") is not None]
    if not values:
        return JSONResponse({})

    rating_by_movie = {str(r["MOVIEID"]): float(r["RATING"]) for r in ratings if r.get("RATING") is not None}
    bins = {f"{i / 2:.1f}": 0 for i in range(1, 11)}
    for v in values:
        bucket = f"{max(0.5, min(5.0, round(v * 2) / 2)):.1f}"
        if bucket in bins:
            bins[bucket] += 1

    def _agg(rows, key_col, val_col="RATING"):
        totals, counts = {}, {}
        for r in rows:
            k = str(r[key_col] or "").strip()
            if not k:
                continue
            v = float(r[val_col])
            totals[k] = totals.get(k, 0) + v
            counts[k] = counts.get(k, 0) + 1
        return totals, counts

    # Genres (JOIN)
    genre_rows = _sf_query("""
        SELECT mg.GENRE, r.RATING FROM USER_MOVIE_RATING r
        JOIN MOVIE_ML_GENRE mg ON mg.MOVIEID = r.MOVIEID
        WHERE r.USERID = %s
    """, (userid,))
    genre_totals, genre_counts = _agg(genre_rows, "GENRE")

    # Languages (JOIN)
    lang_rows = _sf_query("""
        SELECT ml.LANGUAGE, r.RATING FROM USER_MOVIE_RATING r
        JOIN MOVIE_LANGUAGE ml ON ml.MOVIEID = r.MOVIEID
        WHERE r.USERID = %s
    """, (userid,))
    language_totals, language_counts = _agg(lang_rows, "LANGUAGE")

    # Continents (JOIN via MOVIE_COUNTRY + local ISO map)
    country_rows = _sf_query("""
        SELECT mc.ISO, r.RATING FROM USER_MOVIE_RATING r
        JOIN MOVIE_COUNTRY mc ON mc.MOVIEID = r.MOVIEID
        WHERE r.USERID = %s
    """, (userid,))
    continent_totals: dict = {}
    continent_counts: dict = {}
    for row in country_rows:
        iso = (row.get("ISO") or "").strip()
        c   = _iso_continent.get(iso, "Other")
        v   = float(row["RATING"])
        continent_totals[c] = continent_totals.get(c, 0) + v
        continent_counts[c] = continent_counts.get(c, 0) + 1

    # Awards (JOIN)
    award_rows = _sf_query("""
        SELECT mi.AWARD_WINNING, mi.OSCAR_WINNING, mi.OSCAR_NOMINATION,
               mi.BAFTA_WINNING, mi.BAFTA_NOMINATION, mi.EMMY_WINNING, mi.EMMY_NOMINATION,
               r.RATING
        FROM USER_MOVIE_RATING r
        JOIN MOVIE_IMDB mi ON mi.MOVIEID = r.MOVIEID
        WHERE r.USERID = %s
    """, (userid,))

    wins_totals, wins_counts = {}, {}
    sp_wins_totals, sp_wins_counts = {}, {}
    sp_noms_totals, sp_noms_counts = {}, {}
    _SP = [("Oscar","OSCAR_WINNING","OSCAR_NOMINATION"),
           ("BAFTA","BAFTA_WINNING","BAFTA_NOMINATION"),
           ("Emmy", "EMMY_WINNING", "EMMY_NOMINATION")]

    for row in award_rows:
        v   = float(row["RATING"])
        bkt = _award_bucket(_safe_int(row.get("AWARD_WINNING")))
        wins_totals[bkt] = wins_totals.get(bkt, 0) + v
        wins_counts[bkt] = wins_counts.get(bkt, 0) + 1
        has_win = has_nom = False
        for label, col_w, col_n in _SP:
            if _safe_int(row.get(col_w)):
                has_win = True
                sp_wins_totals[label] = sp_wins_totals.get(label, 0) + v
                sp_wins_counts[label] = sp_wins_counts.get(label, 0) + 1
            if _safe_int(row.get(col_n)):
                has_nom = True
                sp_noms_totals[label] = sp_noms_totals.get(label, 0) + v
                sp_noms_counts[label] = sp_noms_counts.get(label, 0) + 1
        if not has_win:
            sp_wins_totals["No Special Awards"] = sp_wins_totals.get("No Special Awards", 0) + v
            sp_wins_counts["No Special Awards"] = sp_wins_counts.get("No Special Awards", 0) + 1
        if not has_nom:
            sp_noms_totals["No Special Nominations"] = sp_noms_totals.get("No Special Nominations", 0) + v
            sp_noms_counts["No Special Nominations"] = sp_noms_counts.get("No Special Nominations", 0) + 1

    avg = sum(values) / len(values)
    std = math.sqrt(sum((v - avg) ** 2 for v in values) / len(values))

    def _avg_list(totals, counts, key):
        return sorted(
            [{key: k, "avg": round(totals[k] / counts[k], 1), "count": counts[k]} for k in totals],
            key=lambda x: x["avg"], reverse=True
        )

    lang_top5 = sorted(
        [{"language": l, "avg": round(language_totals[l] / language_counts[l], 1), "count": language_counts[l]}
         for l in language_totals],
        key=lambda x: x["count"], reverse=True
    )[:5]
    lang_top5.sort(key=lambda x: x["avg"], reverse=True)

    g = _get_global_stats()
    return JSONResponse({
        "count":          len(values),
        "avg":            round(avg, 2),
        "std":            round(std, 2),
        "genre_avg":      _avg_list(genre_totals,     genre_counts,     "genre"),
        "continent_avg":  _avg_list(continent_totals, continent_counts, "continent"),
        "language_avg":   lang_top5,
        "wins_avg":       _avg_list(wins_totals,       wins_counts,      "wins"),
        "sp_wins_avg":    _avg_list(sp_wins_totals,    sp_wins_counts,   "label"),
        "sp_noms_avg":    _avg_list(sp_noms_totals,    sp_noms_counts,   "label"),
        "histogram":      [{"rating": k, "count": v} for k, v in bins.items()],
        "global":         g,
    })


@app.get("/user_ratings/{userid}")
async def user_ratings(userid: str):
    result = []
    tags_rows = _sf_query(
        "SELECT MOVIEID, TAG FROM USER_MOVIE_TAG WHERE USERID = %s", (userid,)
    )
    tags_by_movie: dict[str, list[str]] = {}
    for t in tags_rows:
        tags_by_movie.setdefault(str(t["MOVIEID"]), []).append(t["TAG"])

    for r in _sf_query("""
        SELECT r.MOVIEID, r.RATING, r.TIMESTAMP, ml.TITLE
        FROM USER_MOVIE_RATING r
        LEFT JOIN MOVIE_ML ml ON ml.MOVIEID = r.MOVIEID
        WHERE r.USERID = %s
    """, (userid,)):
        mid   = str(r["MOVIEID"])
        title = (r.get("TITLE") or "").strip() or mid
        genres = [g["GENRE"] for g in _sf_query(
            "SELECT GENRE FROM MOVIE_ML_GENRE WHERE MOVIEID = %s", (mid,)
        )]
        tags   = tags_by_movie.get(mid, [])

        ts = r.get("TIMESTAMP", "")
        date_str = ""
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                date_str = dt.strftime("%b/%Y")
            except (ValueError, OSError):
                pass

        try:
            rating = float(r.get("RATING", 0))
        except ValueError:
            rating = 0.0

        result.append({
            "movieid":   mid,
            "title":     title,
            "genres_ml": genres,
            "tags":      tags,
            "rating":    rating,
            "date":      date_str,
        })

    result.sort(key=lambda x: x["rating"], reverse=True)
    return JSONResponse(result)


@app.get("/lookup")
async def lookup(query: str):
    q = query.strip()
    if q.isdigit():
        rows = _sf_query("SELECT * FROM USER_RS WHERE USERID = %s", (int(q),))
    else:
        rows = _sf_query("SELECT * FROM USER_RS WHERE EMAIL = %s", (q,))
    if rows:
        user = {k.lower(): v for k, v in rows[0].items()}
        return JSONResponse({"found": True, "user": user})
    return JSONResponse({"found": False})


@app.post("/submit")
async def submit(
    name: str = Form(...),
    email: str = Form(...),
    dob: str = Form(...),
    gender: str = Form(...),
    country: str = Form(...),
    race: str = Form(...),
):
    dob_date = date.fromisoformat(dob)
    existing = _sf_query("SELECT USERID FROM USER_RS WHERE EMAIL = %s", (email,))
    if existing:
        _sf_execute(
            "UPDATE USER_RS SET NAME=%s, DATE_OF_BIRTH=%s, GENDER=%s, COUNTRY=%s, RACE=%s"
            " WHERE EMAIL=%s",
            (name, dob_date, gender, country, race, email),
        )
    else:
        max_rows = _sf_query("SELECT COALESCE(MAX(USERID), 0) + 1 AS NEXT_ID FROM USER_RS")
        next_id  = int(max_rows[0]["NEXT_ID"]) if max_rows else 1
        _sf_execute(
            "INSERT INTO USER_RS (USERID, NAME, EMAIL, DATE_OF_BIRTH, GENDER, COUNTRY, RACE)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (next_id, name, email, dob_date, gender, country, race),
        )
    return JSONResponse({"status": "ok"})


@app.post("/new_ratings")
async def new_ratings(request: Request):
    body    = await request.json()
    userid  = str(body.get("userid", "")).strip()
    ratings = body.get("ratings", [])
    if not userid or not ratings:
        return JSONResponse({"status": "ok", "saved": 0})

    ts   = int(datetime.now(timezone.utc).timestamp())
    rows = [
        (userid, str(r.get("movieid", "")).strip(), r.get("rating", 0), ts)
        for r in ratings
        if str(r.get("movieid", "")).strip() and r.get("rating")
    ]
    if rows:
        _sf_executemany(
            "INSERT INTO NEW_USER_MOVIE_RATING (USERID, MOVIEID, RATING, TIMESTAMP)"
            " VALUES (%s, %s, %s, %s)",
            rows,
        )
    return JSONResponse({"status": "ok", "saved": len(rows)})


@app.get("/user_recommendations/{userid}")
async def user_recommendations(userid: str):
    rows = _sf_query(
        'SELECT REC_BATCH_ID, ITEM_ID, SCORE, "RANK", TIMESTAMP, MODEL'
        ' FROM RECOMMENDATION WHERE USERID = %s ORDER BY REC_BATCH_ID DESC, "RANK" ASC',
        (int(userid),),
    )
    result = []
    def _num(val):
        try:
            return float(str(val).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    for r in rows:
        item_id = str(r["ITEM_ID"])
        ml_rows  = _sf_query("SELECT TITLE, RATING_ML, VOTES_ML FROM MOVIE_ML WHERE MOVIEID = %s", (item_id,))
        ml       = ml_rows[0] if ml_rows else {}
        title    = (ml.get("TITLE") or "").strip() or item_id
        genres   = [g["GENRE"] for g in _sf_query(
            "SELECT GENRE FROM MOVIE_ML_GENRE WHERE MOVIEID = %s", (item_id,)
        )]
        imdb_rows_q = _sf_query("SELECT IMDBRATING, IMDBVOTES FROM MOVIE_IMDB WHERE MOVIEID = %s", (item_id,))
        imdb_row    = imdb_rows_q[0] if imdb_rows_q else {}
        ts       = r.get("TIMESTAMP")
        date_str = ""
        if ts:
            try:
                if hasattr(ts, "strftime"):
                    date_str = ts.strftime("%d/%m/%Y %H:%M")
                else:
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    date_str = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, OSError):
                pass
        score = r.get("SCORE")
        rank  = r.get("RANK")
        rating_ml   = _num(ml.get("RATING_ML"))
        votes_ml    = _num(ml.get("VOTES_ML"))
        rating_imdb = _num(imdb_row.get("IMDBRATING"))
        votes_imdb  = _num(imdb_row.get("IMDBVOTES"))

        result.append({
            "rec_batch_id": int(r["REC_BATCH_ID"]) if r.get("REC_BATCH_ID") is not None else None,
            "item_id":      item_id,
            "title":        title,
            "genres":       genres,
            "score":        round(float(score), 4) if score is not None else None,
            "rank":         int(rank) if rank is not None else None,
            "date":         date_str,
            "model":        r.get("MODEL", ""),
            "rating_ml":    round(rating_ml, 2)   if rating_ml   is not None else None,
            "votes_ml":     int(votes_ml)          if votes_ml    is not None else None,
            "rating_imdb":  round(rating_imdb, 2) if rating_imdb is not None else None,
            "votes_imdb":   int(votes_imdb)        if votes_imdb  is not None else None,
        })
    return JSONResponse(result)



@app.get("/user_similarity/{userid}")
async def user_similarity_endpoint(userid: str):
    rows = _sf_query(
        "SELECT SIMILAR_USER_ID, PEARSON_SIMILARITY FROM USER_SIMILARITY"
        " WHERE USER_ID = %s ORDER BY PEARSON_SIMILARITY DESC FETCH FIRST 10 ROWS ONLY",
        (int(userid),),
    )
    return JSONResponse([
        {"user_id": str(r["SIMILAR_USER_ID"]), "similarity": round(float(r["PEARSON_SIMILARITY"]), 4)}
        for r in rows
    ])
