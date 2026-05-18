import csv
import json
import math
import os
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import snowflake.connector
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
# Snowflake connection
# ---------------------------------------------------------------------------

_sf_conn = None


def _get_conn():
    global _sf_conn
    if _sf_conn is None:
        _sf_conn = snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            database=os.getenv("SNOWFLAKE_DATABASE"),
            schema=os.getenv("SNOWFLAKE_SCHEMA"),
            role=os.getenv("SNOWFLAKE_ROLE"),
            autocommit=True,
        )
    return _sf_conn


def _sf_query(sql: str, params=None) -> list[dict]:
    cur = _get_conn().cursor()
    try:
        cur.execute(sql, params or ())
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def _sf_execute(sql: str, params=None) -> None:
    cur = _get_conn().cursor()
    try:
        cur.execute(sql, params or ())
    finally:
        cur.close()


def _sf_executemany(sql: str, params_list: list) -> None:
    cur = _get_conn().cursor()
    try:
        cur.executemany(sql, params_list)
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# country.tsv stays as a local file
# ---------------------------------------------------------------------------

def _load_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# ---------------------------------------------------------------------------
# Static reference data – declared here, populated in the startup event
# ---------------------------------------------------------------------------

_directors:       dict[str, dict]       = {}
_writers_dict:    dict[str, dict]       = {}
_movie_dirs:      dict[str, list]       = {}
_movie_wris:      dict[str, list]       = {}
_ml_data:         dict[str, dict]       = {}
_imdb_genres:     dict[str, list[str]]  = {}
_ml_genres:       dict[str, list[str]]  = {}
_movie_tags:      dict[str, list[dict]] = {}
_imdb_rows:       dict[str, dict]       = {}
_movie_imdb_awards: dict[str, dict]     = {}
_movie_languages: dict[str, list[str]]  = {}
_movie_continents: dict[str, list[str]] = {}
_iso_continent:   dict[str, str]        = {}
_user_similarity: dict[str, list[dict]] = {}

_global_n_users    = 0
_global_avg_movies = 0.0
_global_avg_rating = 0.0
_global_std        = 0.0


@app.on_event("startup")
def _load_static_data():
    global _global_n_users, _global_avg_movies, _global_avg_rating, _global_std

    _directors.update({r["DIRECTORID"]: r for r in _sf_query("SELECT * FROM DIRECTOR")})
    _writers_dict.update({r["WRITERID"]: r for r in _sf_query("SELECT * FROM WRITER")})

    for _r in _sf_query("SELECT MOVIEID, DIRECTORID FROM MOVIE_DIRECTOR"):
        _movie_dirs.setdefault(str(_r["MOVIEID"]), []).append(_r["DIRECTORID"])

    for _r in _sf_query("SELECT MOVIEID, WRITERID FROM MOVIE_WRITER"):
        _movie_wris.setdefault(str(_r["MOVIEID"]), []).append(_r["WRITERID"])

    _ml_data.update({str(r["MOVIEID"]): r for r in _sf_query("SELECT * FROM MOVIE_ML")})

    for _r in _sf_query("SELECT MOVIEID, GENRE FROM MOVIE_IMDB_GENRE"):
        _imdb_genres.setdefault(str(_r["MOVIEID"]), []).append(_r["GENRE"])

    for _r in _sf_query("SELECT MOVIEID, GENRE FROM MOVIE_ML_GENRE"):
        _ml_genres.setdefault(str(_r["MOVIEID"]), []).append(_r["GENRE"])

    for _r in _sf_query("SELECT MOVIEID, TAG, COUNT FROM MOVIE_TAG"):
        try:
            count = int(_r["COUNT"])
        except (ValueError, KeyError):
            count = 0
        _movie_tags.setdefault(str(_r["MOVIEID"]), []).append({"tag": _r["TAG"], "count": count})

    for _r in _sf_query("SELECT * FROM MOVIE_IMDB"):
        mid = str(_r.get("MOVIEID") or "").strip()
        if mid:
            _imdb_rows[mid] = _r
            _movie_imdb_awards[mid] = {
                "wins": _r.get("AWARD_WINNING"),
                "noms": _r.get("AWARD_NOMINATION"),
            }

    for _r in _sf_query("SELECT MOVIEID, LANGUAGE FROM MOVIE_LANGUAGE"):
        _movie_languages.setdefault(str(_r["MOVIEID"]), []).append(_r["LANGUAGE"])

    _iso_continent.update({
        r["ISO"]: r["CONTINENT"] for r in _load_tsv(COUNTRY_PATH) if r.get("ISO")
    })

    for _r in _sf_query("SELECT MOVIEID, ISO FROM MOVIE_COUNTRY"):
        iso = (_r.get("ISO") or "").strip()
        continent = _iso_continent.get(iso, "Other")
        existing = _movie_continents.setdefault(str(_r["MOVIEID"]), [])
        if continent not in existing:
            existing.append(continent)

    _global_stats = _sf_query("""
        SELECT
            COUNT(DISTINCT USERID)          AS N_USERS,
            COUNT(*) / COUNT(DISTINCT USERID) AS AVG_MOVIES,
            AVG(RATING)                     AS AVG_RATING,
            STDDEV_POP(RATING)              AS STD_RATING
        FROM USER_MOVIE_RATING
    """)[0]

    _global_n_users    = int(_global_stats["N_USERS"]    or 0)
    _global_avg_movies = round(float(_global_stats["AVG_MOVIES"]  or 0), 1)
    _global_avg_rating = round(float(_global_stats["AVG_RATING"]  or 0), 2)
    _global_std        = round(float(_global_stats["STD_RATING"]  or 0), 2)

    sim_path = Path("data/user_similarity.csv")
    if sim_path.exists():
        with open(sim_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = str(row["user_id"]).strip()
                _user_similarity.setdefault(uid, []).append({
                    "user_id":    str(row["similar_user_id"]).strip(),
                    "similarity": round(float(row["cosine_similarity"]), 4),
                })


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _genres_imdb(movieid: str) -> list[str]:
    return _imdb_genres.get(movieid, [])

def _genres_ml(movieid: str) -> list[str]:
    return _ml_genres.get(movieid, [])

def _tags(movieid: str) -> list[dict]:
    return sorted(_movie_tags.get(movieid, []), key=lambda x: x["count"], reverse=True)[:20]

def _clean(val) -> str:
    v = (str(val) if val is not None else "").strip()
    return "" if v in ("N/A", "") else v

def _ratings(movieid: str, row: dict) -> list[dict]:
    result: list[dict] = []
    ml = _ml_data.get(movieid, {})

    ml_score = _clean(ml.get("RATING_ML"))
    if ml_score:
        entry: dict = {"source": "Movie Lens", "score": f"{float(ml_score):.1f}/5"}
        ml_votes = _clean(ml.get("VOTES_ML"))
        if ml_votes:
            entry["votes"] = ml_votes
        result.append(entry)

    imdb_score = _clean(row.get("IMDBRATING"))
    if imdb_score:
        entry = {"source": "IMDb", "score": f"{float(imdb_score):.1f}/10"}
        imdb_votes = _clean(row.get("IMDBVOTES"))
        if imdb_votes:
            entry["votes"] = imdb_votes
        result.append(entry)

    rt = _clean(row.get("RTRATING"))
    if rt:
        result.append({"source": "Rotten Tomatoes", "score": f"{float(rt):.0f}/100"})

    mc = _clean(row.get("MCRATING"))
    if mc:
        result.append({"source": "Metacritic", "score": f"{float(mc):.0f}/100"})

    return result


def _people(movieid: str, role_map: dict, person_dict: dict) -> list[dict]:
    result = []
    for pid in role_map.get(movieid, []):
        p = person_dict.get(pid)
        if not p:
            continue
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
    ml     = _ml_data.get(movieid, {})
    r      = _imdb_rows.get(movieid)
    if not r:
        return JSONResponse({})
    return JSONResponse({
        "id":          movieid,
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
        "ratings":     _ratings(movieid, r),
        "directors":   _people(movieid, _movie_dirs, _directors),
        "writers":     _people(movieid, _movie_wris, _writers_dict),
        "genres_imdb": _genres_imdb(movieid),
        "genres_ml":   _genres_ml(movieid),
        "tags":        _tags(movieid),
    })


@app.get("/movies")
async def movies(userid: str = ""):
    rated: set[str] = set()
    if userid:
        for r in _sf_query("""
            SELECT MOVIEID FROM USER_MOVIE_RATING WHERE USERID = %s
            UNION
            SELECT MOVIEID FROM NEW_USER_MOVIE_RATING WHERE USERID = %s
        """, (userid, userid)):
            rated.add(str(r["MOVIEID"]))

    rows = [r for r in _imdb_rows.values()
            if _clean(r.get("POSTER")) and str(r.get("MOVIEID", "")) not in rated]
    sample = random.sample(rows, min(10, len(rows)))
    return JSONResponse([
        {
            "movieid":     str(r.get("MOVIEID", "")),
            "id":          str(r.get("MOVIEID", "")),
            "title":       r["TITLE"],
            "year":        r["YEAR"],
            "released":    r["RELEASED"],
            "runtime":     r["RUNTIME"],
            "country":     r["COUNTRY"],
            "language":    r["LANGUAGE"],
            "genre":       r["GENRE"],
            "director":    r["DIRECTOR"],
            "writer":      r["WRITER"],
            "cast":        r["ACTORS"],
            "plot":        r["PLOT"],
            "poster":      r["POSTER"],
            "ratings":     _ratings(str(r.get("MOVIEID", "")), r),
            "awards":      r["AWARDS"],
            "directors":   _people(str(r.get("MOVIEID", "")), _movie_dirs, _directors),
            "writers":     _people(str(r.get("MOVIEID", "")), _movie_wris, _writers_dict),
            "genres_imdb": _genres_imdb(str(r.get("MOVIEID", ""))),
            "genres_ml":   _genres_ml(str(r.get("MOVIEID", ""))),
            "tags":        _tags(str(r.get("MOVIEID", ""))),
        }
        for r in sample
    ])


@app.get("/user_stats/{userid}")
async def user_stats(userid: str):
    ratings = _sf_query("SELECT * FROM USER_MOVIE_RATING WHERE USERID = %s", (userid,))
    if not ratings:
        return JSONResponse({})

    def _award_bucket(n: int) -> str:
        if n == 0:    return "0"
        if n <= 10:   return "1-10"
        if n <= 50:   return "11-50"
        if n <= 100:  return "51-100"
        return "+100"

    values = []
    genre_totals,      genre_counts      = {}, {}
    continent_totals,  continent_counts  = {}, {}
    language_totals,   language_counts   = {}, {}
    wins_totals,       wins_counts       = {}, {}
    sp_wins_totals,    sp_wins_counts    = {}, {}
    sp_noms_totals,    sp_noms_counts    = {}, {}
    bins = {f"{i / 2:.1f}": 0 for i in range(1, 11)}

    _SPECIAL_AWARDS = [
        ("Oscar", "OSCAR_WINNING",  "OSCAR_NOMINATION"),
        ("BAFTA", "BAFTA_WINNING",  "BAFTA_NOMINATION"),
        ("Emmy",  "EMMY_WINNING",   "EMMY_NOMINATION"),
    ]

    for r in ratings:
        try:
            v = float(r["RATING"])
        except (ValueError, KeyError):
            continue
        values.append(v)
        mid = str(r["MOVIEID"])

        bucket = f"{max(0.5, min(5.0, round(v * 2) / 2)):.1f}"
        if bucket in bins:
            bins[bucket] += 1

        for g in _ml_genres.get(mid, []):
            genre_totals[g] = genre_totals.get(g, 0) + v
            genre_counts[g] = genre_counts.get(g, 0) + 1

        for c in _movie_continents.get(mid, []):
            continent_totals[c] = continent_totals.get(c, 0) + v
            continent_counts[c] = continent_counts.get(c, 0) + 1

        for l in _movie_languages.get(mid, []):
            language_totals[l] = language_totals.get(l, 0) + v
            language_counts[l] = language_counts.get(l, 0) + 1

        awards = _movie_imdb_awards.get(mid, {})
        for field, totals, counts in [
            ("wins", wins_totals, wins_counts),
        ]:
            raw = awards.get(field, "")
            try:
                n = int(float(raw)) if raw else 0
            except ValueError:
                n = 0
            bkt = _award_bucket(n)
            totals[bkt] = totals.get(bkt, 0) + v
            counts[bkt] = counts.get(bkt, 0) + 1

        imdb_row = _imdb_rows.get(mid, {})
        has_sp_win = has_sp_nom = False
        for label, col_w, col_n in _SPECIAL_AWARDS:
            def _int(val):
                try: return int(float(val)) if val else 0
                except ValueError: return 0
            if _int(imdb_row.get(col_w, "")):
                has_sp_win = True
                sp_wins_totals[label] = sp_wins_totals.get(label, 0) + v
                sp_wins_counts[label] = sp_wins_counts.get(label, 0) + 1
            if _int(imdb_row.get(col_n, "")):
                has_sp_nom = True
                sp_noms_totals[label] = sp_noms_totals.get(label, 0) + v
                sp_noms_counts[label] = sp_noms_counts.get(label, 0) + 1
        if not has_sp_win:
            sp_wins_totals["No Special Awards"] = sp_wins_totals.get("No Special Awards", 0) + v
            sp_wins_counts["No Special Awards"] = sp_wins_counts.get("No Special Awards", 0) + 1
        if not has_sp_nom:
            sp_noms_totals["No Special Nominations"] = sp_noms_totals.get("No Special Nominations", 0) + v
            sp_noms_counts["No Special Nominations"] = sp_noms_counts.get("No Special Nominations", 0) + 1

    if not values:
        return JSONResponse({})

    avg = sum(values) / len(values)
    std = math.sqrt(sum((v - avg) ** 2 for v in values) / len(values))

    def _avg_list(totals, counts, key):
        return sorted(
            [{key: k, "avg": round(totals[k] / counts[k], 1), "count": counts[k]} for k in totals],
            key=lambda x: x["avg"], reverse=True
        )

    def _award_list(totals, counts, key):
        return sorted(
            [{key: k, "avg": round(totals[k] / counts[k], 1), "count": counts[k]}
             for k in totals],
            key=lambda x: x["avg"], reverse=True
        )

    lang_top5 = sorted(
        [{"language": l, "avg": round(language_totals[l] / language_counts[l], 1), "count": language_counts[l]}
         for l in language_totals],
        key=lambda x: x["count"], reverse=True
    )[:5]
    lang_top5.sort(key=lambda x: x["avg"], reverse=True)

    return JSONResponse({
        "count":          len(values),
        "avg":            round(avg, 2),
        "std":            round(std, 2),
        "genre_avg":      _avg_list(genre_totals,     genre_counts,     "genre"),
        "continent_avg":  _avg_list(continent_totals, continent_counts, "continent"),
        "language_avg":   lang_top5,
        "wins_avg":       _award_list(wins_totals,    wins_counts,      "wins"),
        "sp_wins_avg":    _avg_list(sp_wins_totals,   sp_wins_counts,   "label"),
        "sp_noms_avg":    _avg_list(sp_noms_totals,   sp_noms_counts,   "label"),
        "histogram":      [{"rating": k, "count": v} for k, v in bins.items()],
        "global": {
            "avg_movies": _global_avg_movies,
            "avg_rating": _global_avg_rating,
            "std":        _global_std,
        },
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

    for r in _sf_query("SELECT * FROM USER_MOVIE_RATING WHERE USERID = %s", (userid,)):
        mid   = str(r["MOVIEID"])
        ml    = _ml_data.get(mid, {})
        title = (ml.get("TITLE") or "").strip() or mid

        genres = _ml_genres.get(mid, [])
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
        rows = _sf_query("SELECT * FROM USER WHERE USERID = %s", (int(q),))
    else:
        rows = _sf_query("SELECT * FROM USER WHERE EMAIL = %s", (q,))
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
    existing = _sf_query("SELECT USERID FROM USER WHERE EMAIL = %s", (email,))
    if existing:
        _sf_execute(
            "UPDATE USER SET NAME=%s, DATE_OF_BIRTH=%s, GENDER=%s, COUNTRY=%s, RACE=%s"
            " WHERE EMAIL=%s",
            (name, dob_date, gender, country, race, email),
        )
    else:
        max_rows = _sf_query("SELECT COALESCE(MAX(USERID), 0) + 1 AS NEXT_ID FROM USER")
        next_id  = int(max_rows[0]["NEXT_ID"]) if max_rows else 1
        _sf_execute(
            "INSERT INTO USER (USERID, NAME, EMAIL, DATE_OF_BIRTH, GENDER, COUNTRY, RACE)"
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
    for r in rows:
        item_id = str(r["ITEM_ID"])
        ml      = _ml_data.get(item_id, {})
        title   = (ml.get("TITLE") or "").strip() or item_id
        genres  = _ml_genres.get(item_id, [])
        ts      = r.get("TIMESTAMP")
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
        score     = r.get("SCORE")
        rank      = r.get("RANK")
        imdb_row  = _imdb_rows.get(item_id, {})

        def _num(val):
            try:
                return float(str(val).replace(",", "").strip())
            except (TypeError, ValueError):
                return None

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


@app.get("/recommend")
async def recommend_endpoint(userid: str, model: str = "popular", n: int = 10):
    from rs_rec import Recommender  # lazy import avoids circular dependency

    n   = max(1, min(10, n))
    rec = Recommender(users=[userid], model=model, n=n)
    results = []
    for _key, items in rec.recs():
        df = items.to_df() if hasattr(items, "to_df") else items
        for _, row in df.iterrows():
            item_id = str(row["item_id"])
            ml      = _ml_data.get(item_id, {})
            r       = _imdb_rows.get(item_id, {})
            score   = row.get("score")
            results.append({
                "rank":    int(row.get("rank", 0)),
                "score":   round(float(score), 4) if score is not None and score == score else None,
                "movieid": item_id,
                "title":   r.get("TITLE") or ml.get("TITLE") or item_id,
                "year":    r.get("YEAR", ""),
                "genre":   r.get("GENRE", ""),
                "runtime": r.get("RUNTIME", ""),
                "poster":  r.get("POSTER", ""),
                "plot":    r.get("PLOT", ""),
            })
    return JSONResponse(results)


@app.get("/user_similarity/{userid}")
async def user_similarity_endpoint(userid: str):
    return JSONResponse(_user_similarity.get(str(userid), []))
