from pathlib import Path

import joblib
from lenskit.batch import recommend

MODEL_DIR = Path('model')

MODELS = {'popular', 'random', 'bias', 'item_knn', 'user_knn', 'biased_mf'}


class Recommender:
    def __init__(
        self,
        users: list,
        model: str = 'popular',
        n: int = 10,
    ):
        if model not in MODELS:
            raise ValueError(f"Unknown model '{model}'. Options: {sorted(MODELS)}")

        model_path = MODEL_DIR / f'{model}.joblib'
        if not model_path.exists():
            raise FileNotFoundError(
                f"Trained model '{model}' not found at {model_path}. Run rs_fit.py first."
            )

        self.users     = users
        self.n         = n
        self._pipeline = joblib.load(model_path)

    def recs(self):
        return recommend(self._pipeline, self.users, self.n)


if __name__ == '__main__':
    r = Recommender(users=['5'], model='popular', n=10)
    for key, items in r.recs():
        print(key.user_id, items.to_df())
