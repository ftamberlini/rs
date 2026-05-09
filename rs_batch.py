import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import snowflake.connector
from dotenv import load_dotenv
from lenskit.batch import recommend

MODEL_DIR = Path('model')

_MODEL_PARAMS = {
    'bias':      {},
    'user_knn':  {'nnbrs': 20},
    'biased_mf': {'features': 20, 'iterations': 20, 'reg': 0.1},
}


def _sf_connect():
    return snowflake.connector.connect(
        account=os.getenv('SNOWFLAKE_ACCOUNT'),
        user=os.getenv('SNOWFLAKE_USER'),
        password=os.getenv('SNOWFLAKE_PASSWORD'),
        warehouse=os.getenv('SNOWFLAKE_WAREHOUSE'),
        database=os.getenv('SNOWFLAKE_DATABASE'),
        schema=os.getenv('SNOWFLAKE_SCHEMA'),
        role=os.getenv('SNOWFLAKE_ROLE'),
        autocommit=True,
    )


def _safe_int(val):
    try:
        f = float(val)
        return None if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None


def _safe_float(val):
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _next_batch_id(cur) -> int:
    cur.execute('SELECT COALESCE(MAX(REC_BATCH_ID), 0) + 1 FROM RECOMMENDATION')
    return cur.fetchone()[0]


def run_batch(user_start: int, user_end: int, n: int = 10) -> None:
    load_dotenv()

    users = [str(u) for u in range(user_start, user_end + 1)]
    ts    = datetime.now(timezone.utc)
    rows: list[tuple] = []

    for model_name, params in _MODEL_PARAMS.items():
        model_path = MODEL_DIR / f'{model_name}.joblib'
        if not model_path.exists():
            print(f'[SKIP] {model_name}: model file not found at {model_path}')
            continue

        print(f'[{model_name}] running for users {user_start}–{user_end}...', flush=True)
        pipeline   = joblib.load(model_path)
        params_str = json.dumps(params)

        for key, items in recommend(pipeline, users, n):
            userid = int(key.user_id)
            for _, row in items.to_df().iterrows():
                rows.append((
                    userid,
                    _safe_int(row.get('item_id')),
                    _safe_int(row.get('item_num')),
                    _safe_float(row.get('score')),
                    _safe_int(row.get('rank')),
                    ts,
                    model_name,
                    params_str,
                ))

        print(f'[{model_name}] done — {len(rows)} total rows collected.')

    if not rows:
        print('No rows to insert.')
        return

    conn = _sf_connect()
    cur  = conn.cursor()
    try:
        batch_id = _next_batch_id(cur)
        print(f'REC_BATCH_ID: {batch_id} — inserting {len(rows)} rows into RECOMMENDATION...')
        cur.executemany(
            'INSERT INTO RECOMMENDATION'
            ' (REC_BATCH_ID, USERID, ITEM_ID, ITEM_NUM, SCORE, "RANK", TIMESTAMP, MODEL, PARAMETERS)'
            ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [(batch_id, *r) for r in rows],
        )
        print(f'Done — {len(rows)} rows inserted with REC_BATCH_ID={batch_id}.')
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Batch recommendation generator')
    parser.add_argument('--user-start', type=int, default=1,   metavar='N')
    parser.add_argument('--user-end',   type=int, default=100, metavar='N')
    parser.add_argument('--n',          type=int, default=10,  metavar='N',
                        help='number of recommendations per user (default: 10)')
    args = parser.parse_args()
    run_batch(args.user_start, args.user_end, args.n)
