"""
rs_movie_encoding_stats.py — Distribuição de filmes por feature

Lê data/movie_encoding.tsv e gera quatro arquivos de contagem:
  data/movie_genre.tsv      — filmes por gênero
  data/movie_diversity.tsv  — filmes por grupo de diversidade
  data/movie_language.tsv   — filmes por idioma
  data/movie_country.tsv    — filmes por país

Uso:
  uv run python rs_movie_encoding_stats.py
  uv run python rs_movie_encoding_stats.py --input data/movie_encoding.tsv
"""

import argparse
import csv
from pathlib import Path

DIVERSITY_LABELS = {
    "div_fem_nowhite":  "Fem+NoWhite  (gender=0, race=0)",
    "div_fem_white":    "Fem+White    (gender=0, race=1)",
    "div_fem_mix":      "Fem+Mix      (gender=0, race=2)",
    "div_male_nowhite": "Male+NoWhite (gender=1, race=0)",
    "div_male_white":   "Male+White   (gender=1, race=1)",
    "div_male_mix":     "Male+Mix     (gender=1, race=2)",
    "div_mix_nowhite":  "Mix+NoWhite  (gender=2, race=0)",
    "div_mix_white":    "Mix+White    (gender=2, race=1)",
    "div_mix_unknown":  "Mix+Unknown  (gender=2, race=2)",
}


def run(input_path: str):
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {src}\n"
                                "Execute rs_movie_encoding.py primeiro.")

    out_dir = src.parent

    # Contadores por grupo de feature
    counts: dict[str, dict[str, int]] = {
        "genre":    {},
        "div":      {},
        "lang":     {},
        "country":  {},
    }

    total = 0
    print(f"Lendo {src} ...")

    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            total += 1
            for col, val in row.items():
                if val != "1":
                    continue
                if col.startswith("genre_"):
                    key = col[len("genre_"):]
                    counts["genre"][key] = counts["genre"].get(key, 0) + 1
                elif col.startswith("div_"):
                    key = col[len("div_"):]
                    counts["div"][key] = counts["div"].get(key, 0) + 1
                elif col.startswith("lang_"):
                    key = col[len("lang_"):]
                    counts["lang"][key] = counts["lang"].get(key, 0) + 1
                elif col.startswith("country_"):
                    key = col[len("country_"):]
                    counts["country"][key] = counts["country"].get(key, 0) + 1

    print(f"  {total} filmes processados.\n")

    # ── movie_genre.tsv ───────────────────────────────────────────────────────
    path = out_dir / "movie_genre.tsv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["genre", "n_movies", "pct"])
        for genre, cnt in sorted(counts["genre"].items(), key=lambda x: -x[1]):
            w.writerow([genre, cnt, f"{cnt/total*100:.1f}%"])
    _print_table("Gêneros", counts["genre"], total)

    # ── movie_diversity.tsv ───────────────────────────────────────────────────
    path = out_dir / "movie_diversity.tsv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["diversity_group", "label", "n_movies", "pct"])
        for key in DIVERSITY_LABELS:
            short = key[len("div_"):]
            cnt   = counts["div"].get(short, 0)
            label = DIVERSITY_LABELS[key]
            w.writerow([short, label, cnt, f"{cnt/total*100:.1f}%"])
    _print_table("Diversidade", counts["div"], total,
                 label_map={k[len("div_"):]: v for k, v in DIVERSITY_LABELS.items()})

    # ── movie_language.tsv ────────────────────────────────────────────────────
    path = out_dir / "movie_language.tsv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["language", "n_movies", "pct", "in_top19"])
        for lang, cnt in sorted(counts["lang"].items(), key=lambda x: -x[1]):
            in_top = "no" if lang == "other" else "yes"
            w.writerow([lang, cnt, f"{cnt/total*100:.1f}%", in_top])
    _print_table("Idiomas", counts["lang"], total)

    # ── movie_country.tsv ─────────────────────────────────────────────────────
    path = out_dir / "movie_country.tsv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["country_iso", "n_movies", "pct", "in_top29"])
        for ctry, cnt in sorted(counts["country"].items(), key=lambda x: -x[1]):
            in_top = "no" if ctry == "other" else "yes"
            w.writerow([ctry, cnt, f"{cnt/total*100:.1f}%", in_top])
    _print_table("Países", counts["country"], total)

    print("Arquivos gerados em", out_dir)


def _print_table(title: str, data: dict[str, int], total: int,
                 label_map: dict[str, str] | None = None, top: int = 10):
    print(f"── {title} ({'top ' + str(top) if len(data) > top else str(len(data)) + ' itens'}) ──")
    sorted_items = sorted(data.items(), key=lambda x: -x[1])
    for key, cnt in sorted_items[:top]:
        label = label_map[key] if label_map else key
        bar   = "█" * int(cnt / total * 40)
        print(f"  {label:<30}  {cnt:>6}  {cnt/total*100:5.1f}%  {bar}")
    if len(data) > top:
        rest = sum(v for _, v in sorted_items[top:])
        print(f"  {'... outros':<30}  {rest:>6}  {rest/total*100:5.1f}%")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distribuição de features do encoding")
    parser.add_argument("--input", default="data/movie_encoding.tsv")
    args = parser.parse_args()
    run(args.input)
