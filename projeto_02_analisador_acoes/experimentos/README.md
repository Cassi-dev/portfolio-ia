English version: [README.en.md](README.en.md)

# Experimentos

Ideias testadas contra os rótulos humanos de [../dados_medicao/](../dados_medicao/) antes de virarem (ou não) código.

Ficam aqui porque **experimento que não deu certo também é resultado**: evita que a mesma ideia volte daqui a três meses como novidade.

```bash
python projeto_02_analisador_acoes/experimentos/dedup.py        # offline
python projeto_02_analisador_acoes/experimentos/regional.py     # offline
python projeto_02_analisador_acoes/experimentos/alvos.py        # coleta do Google News
```

| Experimento | Pergunta | Resultado | Decisão |
|---|---|---|---|
| [dedup.py](dedup.py) | Que regra reconhece "a mesma notícia de novo"? | Jaccard ≥ 0,60 pegava **0 de 21**; embedding (cosseno ≥ 0,93) pega **11 de 21** com 1 fusão errada | **Adotado** |
| [alvos.py](alvos.py) | Dividir o alvo de setor em assuntos derruba o ruído? | A taxa cai (60% → 36-43% em três dos quatro), mas o volume vai de 54 para **213** manchetes | **Não adotado** |
| [regional.py](regional.py) | Uma lista de lugares pega "notícia de outra região"? | 6 dos 9 regionais, ao custo de **5 dos 33 úteis** | **Não adotado** |

## Por que os dois últimos não foram adotados

**Dividir o alvo de setor.** Eu tinha previsto "ganho de graça" e não era. A taxa de ruído melhora, mas só na parte que eu conseguia medir — as manchetes que também apareciam na busca antiga e por isso já tinham rótulo. O que é certo é o volume: quatro buscas específicas cavam mais fundo na cauda longa e trazem quatro vezes mais item, quase tudo regional. Mais itens a revisar, com taxa melhor, dá mais trabalho, não menos. E `setor-eventos` saiu em 82% de ruído, pior que o alvo único: "feira OR congresso OR expo" traz evento local de qualquer cidade.

**Regra de lugares.** Marca 18 itens, acerta 13. Os 5 erros são justamente os melhores do Radar: "Outback chega ao Shopping Uberaba", "Papa Johns estreia em São Paulo", "Madero confirma restaurante no Paraná". A regra não distingue *notícia sobre um lugar* de *notícia nacional que cita um lugar* — e num monitor, perder o concorrente abrindo unidade é o erro mais caro que existe.

A primeira versão dela marcava 23 dos 33 úteis, o que parecia condenar a ideia. Era bug meu: montei a lista de lugares com `split()`, então "rio de janeiro" virou as palavras soltas "de" e "do", e "Pará" virou a preposição "para". Vale como lembrete de que resultado ruim demais merece uma olhada no código antes de virar conclusão.

## O que os dois dizem juntos

O ruído não é de assunto largo nem de geografia no título: é **tipo de conteúdo** (publieditorial, página de arquivo) e **pertinência ao cliente** (esta notícia de Manaus importa para uma rede nacional? e para um bar em Curitiba?). Nenhuma regra sobre o texto do título resolve isso, porque a resposta depende de quem é o cliente.

É exatamente o que [../relevancia.py](../relevancia.py) recebe como contexto. Medir esse filtro é o próximo passo, e é por isso que ele foi escrito antes de ser ligado.
