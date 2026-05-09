from pathlib import Path

import joblib
import pandas as pd
from lenskit.als import BiasedMFScorer
from lenskit.basic import BiasScorer, PopScorer, RandomSelector, TrainingItemsCandidateSelector
from lenskit.basic.history import UserTrainingHistoryLookup
from lenskit.data import from_interactions_df
from lenskit.knn import ItemKNNScorer, UserKNNScorer
from lenskit.pipeline import PipelineBuilder, topn_pipeline

MODEL_DIR  = Path('model')
DATA_PATH  = Path('data/user_ratings.csv')

_MODELS = {
    'popular':   (PopScorer,      {}),
    'random':    None,
    'bias':      (BiasScorer,     {}),
    'item_knn':  (ItemKNNScorer,  {'nnbrs': 20}),
    'user_knn':  (UserKNNScorer,  {'nnbrs': 20}),
    'biased_mf': (BiasedMFScorer, {'features': 20, 'iterations': 20, 'reg': 0.1}),
}


def load_data() -> object:
    data = pd.read_csv(DATA_PATH).rename(columns={
        'USERID':  'user_id',
        'MOVIEID': 'item_id',
        'RATING':  'rating',
    })
    data['user_id']   = data['user_id'].astype(str)
    data['item_id']   = data['item_id'].astype(str)
    data['rating']    = data['rating'].astype(float)
    data['timestamp'] = pd.Timestamp('2000-01-01')
    return from_interactions_df(data)


def build_pipeline(model_name: str) -> object:
    if model_name == 'random':
        b     = PipelineBuilder('random')
        query = b.create_input('query', object)
        b.add_component('history-lookup', UserTrainingHistoryLookup, query=query)
        cands = b.add_component('candidate-selector', TrainingItemsCandidateSelector, query=query)
        b.add_component('recommender', RandomSelector, items=cands, query=query)
        return b.build()

    cls, defaults = _MODELS[model_name]
    return topn_pipeline(cls(**defaults))


def fit():
    MODEL_DIR.mkdir(exist_ok=True)
    print(f'Loading data from {DATA_PATH}...')
    dataset = load_data()

    for name in _MODELS:
        print(f'  Training {name}...', end=' ', flush=True)
        try:
            pipeline = build_pipeline(name)
            pipeline.train(dataset)
            out = MODEL_DIR / f'{name}.joblib'
            joblib.dump(pipeline, out)
            print(f'saved -> {out}')
        except Exception as e:
            print(f'FAILED: {e}')

    print('Done.')


if __name__ == '__main__':
    fit()
