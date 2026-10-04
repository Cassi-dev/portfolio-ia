English version: [README.en.md](README.en.md)

# Triador e pontuador de currículos

Você cola a descrição da vaga e sobe uma pilha de currículos em PDF. O sistema reprova antes de pontuar quem não atende o obrigatório, ranqueia o resto de 0 a 100, explica cada nota, lista o que falta em cada candidato e exporta o ranking em CSV. Projeto 04 do desafio "7 Projetos de IA para Construir em um Fim de Semana".

```bash
python projeto_04_triador_curriculos/dados_ficticios.py            # (já gerados) recria os 40 currículos fictícios
streamlit run projeto_04_triador_curriculos/app_triador.py
python projeto_04_triador_curriculos/avaliar_ranking.py            # reproduz os números abaixo
```

> **Dados pessoais.** Currículo é dado pessoal (LGPD). Todos os currículos deste repositório são **fictícios**, gerados por script, com e-mails `@example.com`. Não coloque currículos reais em demonstrações públicas.

## Como funciona

1. **Extração** ([texto.py](texto.py)): PyMuPDF em ordem de leitura. PDF escaneado é recusado com mensagem clara (não há OCR).
2. **Seções** ([secoes.py](secoes.py)): formação, experiência, competências etc., em português ou inglês. Pontuar o documento inteiro como um bloco só dá nota sem sentido. Se nenhuma seção é reconhecida, o texto inteiro é analisado e o candidato leva um aviso.
3. **Filtro antes da nota** ([pontuacao.py](pontuacao.py)): requisito obrigatório, anos mínimos e formação mínima são **filtro, não peso**. Quem reprova aparece com o motivo exato e não recebe nota (senão o ranking mente).
4. **Nota por seção, de 0 a 100**: competências (cobertura dos requisitos, obrigatórios com peso 2, mais similaridade semântica), experiência (tempo calculado dos períodos mais similaridade) e formação. O cosseno nunca é mostrado; ninguém em RH sabe ler "0,78".
5. **Tempo de experiência** ([experiencia.py](experiencia.py)): soma os meses dos períodos do currículo, sem contar a mesma época duas vezes ("2 anos" e "10 anos de Python" têm vetores quase iguais; o cosseno não vê a diferença). Data só com ano é tratada de forma conservadora.
6. **IA opcional** ([analise_llm.py](analise_llm.py)): com uma chave, os 10 melhores são reavaliados com critérios explícitos (nota 60% regras + 40% IA), com justificativa, pontos fortes e lacunas. Sem chave, tudo continua funcionando por regras e a interface avisa (modo degradado). A IA nunca desfaz o filtro.
7. **Análise de lacunas e carta de retorno** para quem não passou, com o motivo real e o que estudar.
8. **CSV para o RH** ([exportacao.py](exportacao.py)): `;`, vírgula decimal e BOM UTF-8, para o Excel em português abrir sem estragar acentos.

## Privacidade e viés

- Tudo é analisado localmente. Só o que vai para a API de um LLM passa por [privacidade.py](privacidade.py): e-mail, telefone, CPF, links e o nome viram marcadores (`[CANDIDATO]`); as datas e as habilidades são preservadas. Há teste garantindo que nada disso vaza no prompt.
- O prompt instrui a ignorar nome, gênero, idade, foto e local. **Modo anônimo** troca nome e arquivo por "Candidato 01" na tela e no CSV.
- É apoio à decisão, não decisão automática: a pessoa de RH deve revisar (a LGPD dá ao titular o direito de pedir revisão de decisões automatizadas).

## Os números (currículos fictícios, vaga de exemplo)

40 currículos gerados por 7 arquétipos com aderência conhecida: 8 sêniores ideais (nota 3), 10 plenos sólidos (2), 6 plenos básicos (1) e 16 de nota 0 pensados para enganar: 6 **juniores recheados de palavras-chave**, 5 **seniores de outra stack** (Java/Scala, sem Python), 3 **sem Git** e 2 de marketing.

| Método | NDCG@10 | Precisão@5 (nota ≥ 2) | Nota 0 no top 10 | Notas 3 entre as 8 primeiras |
|---|---|---|---|---|
| Só cosseno (o ingênuo) | **0,64** | 0,80 | **2** | **2 de 8** |
| Regras, sem o filtro obrigatório | 1,00 | 1,00 | 0 | 8 de 8 |
| Regras completas | 1,00 | 1,00 | 0 | 8 de 8 |

O que o cosseno sozinho mostra, medido: o júnior recheado de palavras-chave tem o **maior** cosseno com a vaga (0,945 em média) e o sênior ideal tem 0,935. A similaridade premia o vocabulário, não o tempo de casa.

Sub-tarefas com verdade-base própria: erro médio de **0,02 ano** na experiência extraída (máximo 0,5, nos currículos que só informam o ano), **40/40** seções reconhecidas, **precisão e revocação 1,0** na detecção dos 10 requisitos. Robustez (sem acentos, tudo em maiúsculas, cabeçalhos em inglês, sem cabeçalhos): NDCG@10 de 1,0 e nenhuma aprovação muda.

### Como ler esses números (com honestidade)

- **O 1,00 não é prova de qualidade.** Os currículos e a nota-gabarito saem do mesmo gerador que eu escrevi, com faixas de anos que não se sobrepõem e formatos que o parser conhece. Ele funciona como **teste de regressão** e como demonstração de que o ranking só por cosseno falha nos casos adversariais do e-book (0,64), não como estimativa de desempenho em currículos reais.
- Que o "sem filtro" também dê 1,00 mostra que, neste conjunto, o filtro não muda o NDCG (as notas de seção já derrubam os de nota 0). O filtro existe por outro motivo: dar ao RH um motivo objetivo e auditável de reprovação.
- A generalização do parser é testada à parte, com casos escritos à mão em formatos diferentes ([tests/test_p4_triador.py](../tests/test_p4_triador.py)). Isso já achou dois bugs meus (o "3" de "3 anos" apagado como numeração de lista e "até o momento" que zerava o período).
- O que faria o número valer: currículos reais anonimizados, com aderência rotulada por pessoas de RH.

## Limitações

- Sem OCR (PDF escaneado é recusado). Documentos em duas colunas ou muito gráficos podem embaralhar a leitura.
- A taxonomia tem ~55 habilidades de tecnologia; o que não está nela é procurado como frase literal (sem sinônimos). Nível de idioma não é avaliado.
- Não distingue "5 anos de Python" de "5 anos de experiência no total": conta o tempo de trabalho, não o tempo por tecnologia.
- A camada de IA foi testada com um cliente simulado, **nunca contra o Gemini de verdade**. Rode o app com a sua chave uma vez para conferir.
- Português e inglês apenas.
