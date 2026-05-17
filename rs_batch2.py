import json
import math
import os
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv
from lenskit.batch import recommend
from lenskit.data import from_interactions_df
from lenskit.metrics import NDCG, RBP, RunAnalysis
from lenskit.splitting import SampleFrac, crossfold_users
import snowflake.connector

from rs_fit import DATA_PATH, build_pipeline, _MODELS

N_RECS       = 10
TEST_FRAC    = 0.2
N_PARTITIONS = 5

MODELS = ['bias', 'item_knn', 'user_knn', 'biased_mf']


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


def load_ratings() -> pd.DataFrame:
    data = pd.read_csv(DATA_PATH).rename(columns={
        'USERID':  'user_id',
        'MOVIEID': 'item_id',
        'RATING':  'rating',
        'userId':  'user_id',
        'movieId': 'item_id',
    })
    data['user_id'] = data['user_id'].astype(str)
    data['item_id'] = data['item_id'].astype(str)
    data['rating']  = data['rating'].astype(float)
    if 'timestamp' not in data.columns:
        data['timestamp'] = pd.Timestamp('2000-01-01')
    return data


def main():
    load_dotenv()

    print(f'Carregando dados de {DATA_PATH}...')
    ratings = load_ratings()
    dataset = from_interactions_df(ratings)

    print(f'Total: {len(ratings)} ratings, {ratings["user_id"].nunique()} usuários, '
          f'{ratings["item_id"].nunique()} filmes\n')

    all_results = []
    all_rows: list[tuple] = []
    ts = datetime.now(timezone.utc)

    for (train, test) in crossfold_users(dataset, N_PARTITIONS, SampleFrac(TEST_FRAC)):
        test_users = list(test.user_ids())
        print(f'Partição — {len(test_users)} usuários de teste\n')

        for model_name in MODELS:
            print(f'  [{model_name}] treinando...', end=' ', flush=True)
            pipeline = build_pipeline(model_name)
            pipeline.train(train)
            print('ok — gerando recomendações...', end=' ', flush=True)

            params_str = json.dumps(_MODELS[model_name][1] if _MODELS.get(model_name) else {})
            recs = []

            for key, items in recommend(pipeline, test_users, N_RECS):
                df = items.to_df()
                df['user_id']   = key.user_id
                df['algorithm'] = model_name
                recs.append(df)

                for _, row in df.iterrows():
                    all_rows.append((
                        _safe_int(key.user_id),
                        _safe_int(row.get('item_id')),
                        _safe_int(row.get('item_num')),
                        _safe_float(row.get('score')),
                        _safe_int(row.get('rank')),
                        ts,
                        model_name,
                        params_str,
                    ))

            if not recs:
                print('sem resultados.')
                continue

            recs_df = pd.concat(recs, ignore_index=True)

            analysis = RunAnalysis()
            analysis.add_metric(NDCG)
            analysis.add_metric(RBP)
            result = analysis.compute(recs_df, test, n_jobs=1)
            result['algorithm'] = model_name
            all_results.append(result)
            print(f'ok — {len(recs_df)} recomendações geradas.')

    if not all_results:
        print('\nNenhum resultado para exibir.')
        return

    combined = pd.concat(all_results, ignore_index=True)
    summary  = combined.groupby('algorithm')[['NDCG', 'RBP']].mean()

    print('\n--- COMPARATIVO FINAL ---')
    print(summary.sort_values('NDCG', ascending=False).to_string())

    if not all_rows:
        print('\nNenhuma linha para inserir.')
        return

    print(f'\nConectando ao Snowflake e inserindo {len(all_rows)} linhas...')
    conn = _sf_connect()
    cur  = conn.cursor()
    try:
        batch_id = _next_batch_id(cur)
        print(f'REC_BATCH_ID: {batch_id}')
        cur.executemany(
            'INSERT INTO RECOMMENDATION'
            ' (REC_BATCH_ID, USERID, ITEM_ID, ITEM_NUM, SCORE, "RANK", TIMESTAMP, MODEL, PARAMETERS)'
            ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [(batch_id, *r) for r in all_rows],
        )
        print(f'Done — {len(all_rows)} linhas inseridas com REC_BATCH_ID={batch_id}.')
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
