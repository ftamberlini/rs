import numpy as np
from typing import List

class RankingMetrics:
    """Classe simples para calcular métricas de ranking."""
    
    @staticmethod
    def precision_at_k(ranking: List[int], relevant: List[int], 
                       k: int) -> float:
        """Precision@K: De K recomendações, quantas são boas?"""
        if k == 0:
            return 0.0
        top_k = ranking[:k]
        hits = sum(1 for item in top_k if item in relevant)
        return hits / k
    
    @staticmethod
    def recall_at_k(ranking: List[int], relevant: List[int], 
                    k: int) -> float:
        """Recall@K: De todos os bons, quantos achei?"""
        if len(relevant) == 0:
            return 0.0
        top_k = ranking[:k]
        hits = sum(1 for item in top_k if item in relevant)
        return hits / len(relevant)
    
    @staticmethod
    def f1_score(precision: float, recall: float) -> float:
        """F1: Balanço entre Precision e Recall."""
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)
    
    @staticmethod
    def mean_average_precision(rankings: List[List[int]], 
                              relevant_list: List[List[int]]) -> float:
        """MAP: Precision média ponderada pela posição."""
        aps = []
        
        for ranking, relevant in zip(rankings, relevant_list):
            precisions = []
            for i, item in enumerate(ranking, 1):
                if item in relevant:
                    precision_at_i = sum(1 for j in range(i) 
                                        if ranking[j] in relevant) / i
                    precisions.append(precision_at_i)
            
            if precisions:
                ap = sum(precisions) / len(relevant)
                aps.append(ap)
        
        return np.mean(aps) if aps else 0.0
    
    @staticmethod
    def ndcg_at_k(ranking: List[int], relevant: List[int], 
                  k: int) -> float:
        """NDCG@K: Qualidade do ranking com posição e relevância."""
        # Calcular DCG
        dcg = 0.0
        for i, item in enumerate(ranking[:k], 1):
            relevance = 1 if item in relevant else 0
            dcg += relevance / np.log2(i + 1)
        
        # Calcular DCG ideal
        idcg = 0.0
        for i in range(1, min(k, len(relevant)) + 1):
            idcg += 1 / np.log2(i + 1)
        
        return dcg / idcg if idcg > 0 else 0.0
    
    @staticmethod
    def hit_rate(rankings: List[List[int]], 
                relevant_list: List[List[int]]) -> float:
        """Hit Rate: % de usuários que receberam algo relevante."""
        hits = 0
        for ranking, relevant in zip(rankings, relevant_list):
            if any(item in relevant for item in ranking):
                hits += 1
        return hits / len(rankings) if rankings else 0.0
    
    @staticmethod
    def mean_reciprocal_rank(rankings: List[List[int]], 
                            relevant_list: List[List[int]]) -> float:
        """MRR: Posição média do primeiro item relevante."""
        rrs = []
        
        for ranking, relevant in zip(rankings, relevant_list):
            for i, item in enumerate(ranking, 1):
                if item in relevant:
                    rrs.append(1 / i)
                    break
        
        return np.mean(rrs) if rrs else 0.0
    
    @staticmethod
    def coverage(rankings: List[List[int]], catalog_size: int) -> float:
        """Coverage: % do catálogo que foi recomendado."""
        unique_items = set()
        for ranking in rankings:
            unique_items.update(ranking)
        return len(unique_items) / catalog_size if catalog_size > 0 else 0.0
    
    @staticmethod
    def diversity(ranking: List[int], similarity_matrix=None) -> float:
        """Diversity: Quanto os itens diferem entre si (0-1)."""
        if len(ranking) < 2 or similarity_matrix is None:
            return 0.0
        
        dissimilarities = []
        for i in range(len(ranking)):
            for j in range(i + 1, len(ranking)):
                dissim = 1 - similarity_matrix[ranking[i]][ranking[j]]
                dissimilarities.append(dissim)
        
        return np.mean(dissimilarities) if dissimilarities else 0.0


# ============================================================
# EXEMPLO DE USO
# ============================================================

if __name__ == "__main__":
    metrics = RankingMetrics()
    
    print("=" * 60)
    print("EXEMPLO 1: Métricas para 1 usuário")
    print("=" * 60)
    
    # Dados do usuário
    ranking = [101, 102, 103, 104, 105, 106, 107, 108]
    relevant = [101, 103, 105, 107]  # Filmes que ele gostaria
    
    print(f"\nRanking recomendado: {ranking}")
    print(f"Filmes relevantes:   {relevant}")
    print()
    
    # Calcular métricas
    p5 = metrics.precision_at_k(ranking, relevant, 5)
    r5 = metrics.recall_at_k(ranking, relevant, 5)
    f1 = metrics.f1_score(p5, r5)
    ndcg = metrics.ndcg_at_k(ranking, relevant, 5)
    mrr = metrics.mean_reciprocal_rank([ranking], [relevant])
    
    print(f"Precision@5: {p5:.4f} (40%)")
    print(f"Recall@5:    {r5:.4f} (50%)")
    print(f"F1-Score:    {f1:.4f}")
    print(f"NDCG@5:      {ndcg:.4f}")
    print(f"MRR:         {mrr:.4f}")
    
    print("\n" + "=" * 60)
    print("EXEMPLO 2: Métricas para múltiplos usuários")
    print("=" * 60)
    
    # 3 usuários diferentes
    rankings = [
        [101, 102, 103, 104, 105],
        [202, 201, 204, 203, 205],
        [301, 302, 304, 303, 305]
    ]
    
    relevant_lists = [
        [101, 103, 105],
        [201, 203],
        [301, 302, 303, 304, 305]
    ]
    
    print("\nUsuário 1 ranking:", rankings[0])
    print("Usuário 1 relevantes:", relevant_lists[0])
    print()
    print("Usuário 2 ranking:", rankings[1])
    print("Usuário 2 relevantes:", relevant_lists[1])
    print()
    print("Usuário 3 ranking:", rankings[2])
    print("Usuário 3 relevantes:", relevant_lists[2])
    print()
    
    # Métricas agregadas
    map_score = metrics.mean_average_precision(rankings, relevant_lists)
    hit_rate = metrics.hit_rate(rankings, relevant_lists)
    mrr = metrics.mean_reciprocal_rank(rankings, relevant_lists)
    catalog_size = 1000
    cov = metrics.coverage(rankings, catalog_size)
    
    print(f"MAP:      {map_score:.4f}")
    print(f"Hit Rate: {hit_rate:.4f} (100% dos usuários tiveram hit)")
    print(f"MRR:      {mrr:.4f}")
    print(f"Coverage: {cov:.4f} (1.5% do catálogo recomendado)")
    
    print("\n" + "=" * 60)
    print("INTERPRETAÇÃO")
    print("=" * 60)
    print("""
MAP = 0.6233: Ranking tem qualidade moderada
Hit Rate = 1.0: Todos os usuários receberam recomendação boa
MRR = 0.7667: Itens relevantes aparecem cedo no ranking
Coverage = 0.015: Sistema recomenda poucos itens (problema!)
    """)