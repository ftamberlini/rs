"""
Computes cosine similarity between users from user_ratings.csv.

For each user, saves the top-N most similar users to data/user_similarity.csv.

Usage:
    uv run python rs_user_sim.py
    uv run python rs_user_sim.py --top-n 20 --batch-size 1000
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize

DATA_PATH = Path('data/user_ratings.csv')
OUT_PATH  = Path('data/user_similarity.csv')


def load_matrix(path: Path):
    print(f'Carregando {path}...')
    df = pd.read_csv(path, usecols=['userId', 'movieId', 'rating'])
    df.columns = ['user_id', 'item_id', 'rating']

    users  = df['user_id'].astype('category')
    items  = df['item_id'].astype('category')
    n_users = users.cat.categories.size
    n_items = items.cat.categories.size

    print(f'  {n_users:,} usuários  |  {n_items:,} filmes  |  {len(df):,} ratings')

    matrix = csr_matrix(
        (df['rating'].values, (users.cat.codes.values, items.cat.codes.values)),
        shape=(n_users, n_items),
        dtype=np.float32,
    )
    return matrix, users.cat.categories, items.cat.categories


def top_n_similar(matrix_norm: csr_matrix, user_idx: int, top_n: int) -> list[tuple[int, float]]:
    row  = matrix_norm[user_idx]
    sims = (row @ matrix_norm.T).toarray().ravel()
    sims[user_idx] = -1                          # exclui o próprio usuário
    top_idx  = np.argpartition(sims, -top_n)[-top_n:]
    top_idx  = top_idx[np.argsort(sims[top_idx])[::-1]]
    return [(int(i), float(sims[i])) for i in top_idx if sims[i] > 0]


def main(top_n: int, batch_size: int) -> None:
    matrix, user_ids, _ = load_matrix(DATA_PATH)

    print('Normalizando vetores (L2)...')
    matrix_norm = normalize(matrix, norm='l2', copy=True)

    n_users = matrix_norm.shape[0]
    print(f'Calculando top-{top_n} similares para {n_users:,} usuários...')

    rows = []
    for start in range(0, n_users, batch_size):
        end   = min(start + batch_size, n_users)
        batch = matrix_norm[start:end]
        sims  = (batch @ matrix_norm.T).toarray()   # (batch_size, n_users)

        for local_i, global_i in enumerate(range(start, end)):
            row            = sims[local_i].copy()
            row[global_i]  = -1                      # exclui o próprio usuário
            top_idx        = np.argpartition(row, -top_n)[-top_n:]
            top_idx        = top_idx[np.argsort(row[top_idx])[::-1]]
            uid            = user_ids[global_i]
            for j in top_idx:
                if row[j] > 0:
                    rows.append((uid, user_ids[j], round(float(row[j]), 6)))

        if (start // batch_size) % 10 == 0:
            pct = end / n_users * 100
            print(f'  {end:,}/{n_users:,} ({pct:.1f}%)')

    result = pd.DataFrame(rows, columns=['user_id', 'similar_user_id', 'cosine_similarity'])
    result.to_csv(OUT_PATH, index=False)
    print(f'\nSalvo em {OUT_PATH}  ({len(result):,} pares)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cosine similarity entre usuários')
    parser.add_argument('--top-n',      type=int, default=10,  help='top-N similares por usuário (default: 10)')
    parser.add_argument('--batch-size', type=int, default=500, help='usuários por batch (default: 500)')
    args = parser.parse_args()
    main(args.top_n, args.batch_size)
