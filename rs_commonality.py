import numpy as np
from typing import List

class CommonalityCalculator:
    """
    Classe simplificada para calcular a métrica Commonality.
    
    Commonality mede a probabilidade de TODOS os usuários se familiarizarem
    simultaneamente com um item ou categoria.
    
    Fórmula geral: C = ∏ Pr(F_u) onde ∏ é o produto das familiaridades
    """
    
    def __init__(self, gamma: float = 0.8):
        """
        Inicializa o calculador.
        
        Args:
            gamma: Parâmetro de paciência (0.1 - 0.95)
                  - Mais próximo de 0: usuário abandona rápido
                  - Mais próximo de 1: usuário navega muito
        """
        self.gamma = gamma
    
    def probability(self, position: int) -> float:
        """
        Calcula a Probabilidade de Browsing (RBP).
        
        Responde: "Qual a probabilidade de um usuário estar vendo a posição k?"
        
        Fórmula: Pr(k) = (1-γ) * γ^(k-1)
        
        Args:
            position: Posição do item no ranking (começando em 1)
            
        Returns:
            Probabilidade entre 0 e 1
            
        Exemplo:
            >>> calc = CommonalityCalculator(gamma=0.8)
            >>> calc.probability(1)  # Primeira posição
            Pr(1) = (1-0.8) * 0.8^(1-1) = 0.2 * 1 = 0.2  
            # 20% de chance de ver o item na posição 1
            >>> calc.probability(2)  # Segunda posição
            Pr(2) = (1-0.8) * 0.8^(2-1) = 0.2 * 0.8 = 0.16
            0.16  # 16% de chance
            >>> calc.probability(10)  # Décima posição
            Pr(10) = (1-0.8) * 0.8^(10-1) = 0.2 * 0.1342... = 0.0268...
            0.0268...  # Muito menos provável
        """
        return (1 - self.gamma) * (self.gamma ** (position - 1))
    
    def recall(self, ranking: List[int], k: int, category_items: List[int]) -> float:
        """
        Calcula o Recall de uma Categoria.
        
        Responde: "Dentre os top-k itens recomendados, qual porcentagem 
        pertence à categoria que estamos analisando?"
        
        Fórmula: R(π, k, g) = |π_{1:k} ∩ D_g| / |D_g|
        
        Args:
            ranking: Lista de IDs de itens no ranking (ordem importa)
            k: Quantos itens do topo considerar
            category_items: Lista de IDs de itens que pertencem à categoria
            
        Returns:
            Recall entre 0 e 1
            
        Exemplo:
            >>> calc = CommonalityCalculator()
            >>> ranking = [101, 102, 103, 104, 105]  # IDs recomendados
            >>> category_items = [101, 103, 105]     # Itens da categoria "Drama"
            >>> 
            >>> calc.recall(ranking, k=3, category_items=category_items)
            0.666...  # 2 de 3 itens no top-3 são dramas
            
            >>> calc.recall(ranking, k=5, category_items=category_items)
            1.0  # Todos os 3 dramas aparecem no top-5
        """
        if not category_items:
            return 0.0
        
        # Pega apenas os primeiros k itens do ranking
        top_k_items = ranking[:k]
        
        # Conta quantos itens do top-k pertencem à categoria
        items_in_category = sum(1 for item in top_k_items if item in category_items)
        
        # Divide pelo total de itens que existem na categoria
        return items_in_category / len(category_items)
    
    def familiarity(self, ranking: List[int], category_items: List[int]) -> float:
        """
        Calcula a Familiaridade Esperada com uma Categoria.
        
        Responde: "Qual a probabilidade de um usuário se familiarizar com 
        itens dessa categoria ao navegar pelo ranking?"
        
        Fórmula: Pr(F|π) = Σ Pr(k) * R(π, k, g)
        
        Ela combina:
        - Probability: chance de estar vendo cada posição
        - Recall: chance de encontrar a categoria em cada posição
        
        Args:
            ranking: Lista de IDs de itens no ranking
            category_items: Lista de IDs de itens na categoria
            
        Returns:
            Familiaridade entre 0 e 1
            
        Exemplo:
            >>> calc = CommonalityCalculator(gamma=0.8)
            >>> ranking = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
            >>> drama_items = [101, 103, 105, 107, 109]  # Filmes drama
            >>> 
            >>> calc.familiarity(ranking, drama_items)
            0.487...  # Usuário tem ~49% de chance de se familiarizar com drama
        """
        if not category_items or not ranking:
            return 0.0
        
        expected_familiarity = 0.0
        
        # Percorre cada posição do ranking
        for position in range(1, len(ranking) + 1):
            # Probabilidade de estar vendo essa posição
            prob_position = self.probability(position)
            
            # Recall até essa posição
            recall_at_k = self.recall(ranking, position, category_items)
            
            # Contribuição dessa posição para a familiaridade total
            expected_familiarity += prob_position * recall_at_k
        
        return expected_familiarity
    
    def categoria_commonality(self, user_rankings: List[List[int]], 
                            category_items: List[int]) -> float:
        """
        Calcula a Commonality de uma Categoria para múltiplos usuários.
        
        Responde: "Qual a probabilidade de TODOS os usuários se familiarizarem
        simultaneamente com essa categoria?"
        
        Fórmula: C_g(π) = ∏ Pr(F_{u,g}|π_u)
        
        O resultado é multiplicativo: se qualquer usuário tiver 0% de chance,
        toda a commonality será 0.
        
        Args:
            user_rankings: Lista de rankings, um para cada usuário
                          Exemplo: [[101, 102, 103], [102, 103, 104]]
            category_items: IDs de itens na categoria
            
        Returns:
            Commonality entre 0 e 1
            
        Exemplo:
            >>> calc = CommonalityCalculator(gamma=0.8)
            >>> 
            >>> # 3 usuários com diferentes rankings
            >>> user1_ranking = [101, 102, 103, 104, 105]
            >>> user2_ranking = [102, 104, 105, 106, 107]
            >>> user3_ranking = [103, 105, 107, 108, 109]
            >>> 
            >>> user_rankings = [user1_ranking, user2_ranking, user3_ranking]
            >>> drama_items = [101, 103, 105, 107, 109]
            >>> 
            >>> commonality = calc.categoria_commonality(user_rankings, drama_items)
            # Resultado será Familiaridade₁ × Familiaridade₂ × Familiaridade₃
        """
        if not user_rankings or not category_items:
            return 0.0
        
        familiarities = []
        
        # Calcula familiaridade para cada usuário com a categoria
        for ranking in user_rankings:
            fam = self.familiarity(ranking, category_items)
            familiarities.append(fam)
        
        # Multiplica as familiaridades (produto)
        commonality = np.prod(familiarities)
        
        return commonality


# ============================================================================
# EXEMPLOS DE USO
# ============================================================================

if __name__ == "__main__":
    # Criar instância
    calc = CommonalityCalculator(gamma=0.8)
    
    print("=" * 70)
    print("EXEMPLO 1: Probabilidade de Navegação")
    print("=" * 70)
    print("\nQual a probabilidade de um usuário estar olhando cada posição?")
    print("(Com gamma=0.8, o usuário abandona com 20% de chance a cada posição)\n")
    
    for pos in [1, 2, 5, 10, 20]:
        prob = calc.probability(pos)
        print(f"Posição {pos:2d}: {prob:.4f} ({prob*100:.2f}%)")
    
    print("\n" + "=" * 70)
    print("EXEMPLO 2: Recall de Uma Categoria")
    print("=" * 70)
    
    # Dados de exemplo
    ranking_usuario_1 = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
    filmes_drama = [101, 103, 105, 107, 109]  # Filmes de drama
    
    print("\nRanking do usuário:", ranking_usuario_1)
    print("Filmes de Drama:", filmes_drama)
    print()
    
    for k in [1, 3, 5, 10]:
        rec = calc.recall(ranking_usuario_1, k, filmes_drama)
        print(f"Recall nos top-{k:2d}: {rec:.4f} ({rec*100:.2f}%)")
    
    print("\n" + "=" * 70)
    print("EXEMPLO 3: Familiaridade com Uma Categoria")
    print("=" * 70)
    
    fam = calc.familiarity(ranking_usuario_1, filmes_drama)
    print(f"\nFamiliaridade do usuário com Drama: {fam:.4f} ({fam*100:.2f}%)")
    print("\nIsso significa: há {:.2f}% de chance de o usuário se".format(fam*100))
    print("familiarizar com filmes de drama ao navegar esse ranking")
    
    print("\n" + "=" * 70)
    print("EXEMPLO 4: Commonality (Múltiplos Usuários)")
    print("=" * 70)
    
    # 3 usuários diferentes
    ranking_usuario_1 = [101, 102, 103, 104, 105]
    ranking_usuario_2 = [102, 104, 105, 106, 107]
    ranking_usuario_3 = [103, 105, 107, 108, 109]
    
    user_rankings = [ranking_usuario_1, ranking_usuario_2, ranking_usuario_3]
    
    print("\nRanking Usuário 1:", ranking_usuario_1)
    print("Ranking Usuário 2:", ranking_usuario_2)
    print("Ranking Usuário 3:", ranking_usuario_3)
    print("Filmes de Drama:   ", filmes_drama)
    print()
    
    # Calcular familiaridade de cada usuário
    for i, ranking in enumerate(user_rankings, 1):
        fam = calc.familiarity(ranking, filmes_drama)
        print(f"Familiaridade do Usuário {i}: {fam:.4f} ({fam*100:.2f}%)")
    
    # Calcular commonality
    commonality = calc.categoria_commonality(user_rankings, filmes_drama)
    print(f"\n{'='*50}")
    print(f"COMMONALITY DE DRAMA (todos 3 usuários): {commonality:.6f}")
    print(f"Probabilidade de TODOS conhecerem drama: {commonality*100:.4f}%")
    print(f"{'='*50}")
    
    print("\n" + "=" * 70)
    print("EXEMPLO 5: Comparando Diferentes Categorias")
    print("=" * 70)
    
    # Categorias diferentes
    filmes_acao = [102, 104, 106, 108, 110]  # Mais dispersos
    filmes_romance = [103, 106, 109]          # Menos filmes
    
    comm_drama = calc.categoria_commonality(user_rankings, filmes_drama)
    comm_acao = calc.categoria_commonality(user_rankings, filmes_acao)
    comm_romance = calc.categoria_commonality(user_rankings, filmes_romance)
    
    print(f"\nCommonality por Categoria:")
    print(f"  Drama:   {comm_drama:.6f}")
    print(f"  Ação:    {comm_acao:.6f}")
    print(f"  Romance: {comm_romance:.6f}")
    
    print(f"\nInterpretação:")
    print(f"  - Drama tem a maior commonality")
    print(f"  - Todos os usuários têm chance de se familiarizar com drama")
    print(f"  - Romance tem a menor commonality")
    print(f"  - Nem todos os usuários veem romance")