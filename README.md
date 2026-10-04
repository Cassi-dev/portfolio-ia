English version: [README.en.md](README.en.md)

# Projetos de IA

Projetos de IA aplicada construídos a partir do desafio "7 Projetos de IA para Construir em um Fim de Semana", com um núcleo compartilhado (`core/`), testes automatizados e dois princípios: **quando o sistema não usa IA, ele avisa** (modo degradado), e **todo projeto publica um número medido**.

| # | Projeto | Como rodar | Número medido |
|---|---------|------------|---------------|
| 01 | [Chatbot RAG](projeto_01_chatbot_rag/) sobre documentos próprios: blocos com seção, reranker, "não sei", citações conferidas, defesa contra injeção, sincronização incremental | `streamlit run projeto_01_chatbot_rag/app.py` | 68 perguntas em 8 documentos fictícios: recall@1 0,889 → 0,963 e MRR 0,941 → 0,981; "não sei" recusa 71% do que não tem resposta (ponto fraco). **Respostas com IA: rodar `6_avaliar_resposta.py` com sua chave** |
| 02 | [Monitor de mercado](projeto_02_analisador_acoes/): painel de sentimento x preço **e** serviço de monitoramento (base de eventos, pontuação incremental, detecção de mudança, cardápio do concorrente por foto, Radar em HTML com revisão, medição de ruído) | `streamlit run projeto_02_analisador_acoes/app_radar.py` | 80 manchetes reais rotuladas à mão: **58,8% de ruído**, 45% dele duplicata. Trocar a deduplicação por embeddings tirou **11 das 21 repetições** (a regra anterior tirava 0). 2º ciclo: 0 novas, 0 enviadas à IA |
| 03 | [Estúdio de vídeos](projeto_03_resumidor_youtube/): cria vídeo de **qualquer assunto** a partir de um contexto (roteiro editável, 5 layouts, 5 temas, locução), analisa vídeos do YouTube (map-reduce, quiz, cortes) e mantém o Reels da TACTO | `streamlit run projeto_03_resumidor_youtube/app_youtube.py` | 90 testes do gerador, número em destaque só se estiver no contexto; qualidade do roteiro com o Gemini: **rodar com sua chave**; ainda sem métrica de qualidade do resumo |
| 04 | [Triador de currículos](projeto_04_triador_curriculos/): filtro antes da nota, tempo de experiência calculado dos períodos, privacidade (LGPD), CSV para o RH | `streamlit run projeto_04_triador_curriculos/app_triador.py` | NDCG@10 em 40 currículos **fictícios**: só cosseno 0,64, regras 1,00 (conjunto sintético: vale como teste de regressão, não como estimativa; ver README) |
| 05 | [Text-to-SQL seguro](projeto_05_gerador_sql/): validação por AST + SQLite somente leitura | `streamlit run projeto_05_gerador_sql/app_sql.py` | acurácia de execução em 50 perguntas: gabarito 100%, modo offline 0%, **Gemini: rodar com sua chave** |

Ainda não feitos: 06 (pesquisa multiagente) e 07 (finanças pessoais).

**Atalho no Windows:** dê duplo clique em [iniciar_apps.bat](iniciar_apps.bat) para abrir um menu que inicia cada app (portas 8501 a 5, no navegador) e mostra o que está rodando. Ou pelo terminal: `iniciar_apps.bat 1 3` inicia o 1 e o 3, `iniciar_apps.bat parar` para todos.

## Preparando o ambiente

Crie o ambiente virtual **fora de pastas sincronizadas** (OneDrive/Dropbox): um `.venv` tem dezenas de milhares de arquivos.

```bash
python -m venv ~/.venvs/projetos-ia
source ~/.venvs/projetos-ia/Scripts/activate      # Windows PowerShell: ~\.venvs\projetos-ia\Scripts\Activate.ps1
pip install -r requirements-dev.txt               # dependências + pytest + pacote local `core`
```

`requirements.lock.txt` guarda as versões exatas com que tudo foi testado. A chave do Gemini é colada na barra lateral de cada app; sem ela os apps funcionam em modo offline e mostram um aviso do que deixou de ser feito por IA.

## Estrutura

```
core/                    código compartilhado
  llm.py                   cliente Gemini: retry só em erro transitório (429/5xx), timeout, saída estruturada
                           validada por Pydantic com um reparo, cache em disco, log de latência e tokens
  degradacao.py            textos padrão do modo degradado
  embeddings.py            embeddings multilíngues (e5) com os prefixos query/passage; similaridade texto x texto
  midia.py                 localização do ffmpeg
projeto_0X_*/            um app Streamlit por projeto, cada um com README e o seu número medido
tests/                   pytest: funções puras, segurança, indexação, IA simulada e "fumaça" dos apps
.github/workflows/       CI (pytest a cada push)
```

## Testes

```bash
pytest                   # unitários + fumaça dos apps (sem rede e sem chave de API)
pytest -m network        # inclui o que usa a internet (RSS, Yahoo Finance)
```

A IA é simulada nos testes com um cliente falso, então a suíte cobre retry, resposta fora do schema, cota esgotada e cache sem gastar chamada. **O que os testes não provam**: o comportamento contra o Gemini de verdade (o `response_schema` com os modelos Pydantic foi validado na conversão do SDK, mas nenhuma chamada real foi feita neste ambiente). Rode `avaliar_acuracia.py --modo gemini` uma vez com a sua chave para fechar essa lacuna.

## Convenção de modo degradado

Toda etapa que pode cair em fallback devolve `degradado` (bool) e `motivo_degradado` (texto), e a interface mostra um aviso amarelo com o motivo (sem chave de API, falha da API, resposta fora do formato). Nenhum fallback devolve texto genérico fingindo ser resultado.

## Quando a cota da API acaba

O 429 do Gemini chega como um texto longo com o JSON do erro dentro, e as duas coisas que mudam o que fazer ficavam escondidas nele: **quanto esperar** (`retryDelay`) e **qual cota** estourou ([core/cota.py](core/cota.py)).

- **Limite por minuto**: resolve esperando. O backoff era de 2 s e 4 s, curto demais — agora a espera é a que a própria API sugeriu (dezenas de segundos), e **uma só**: esperar três vezes congelaria a tela por minutos sem ganho.
- **Limite por dia**: esperar não resolve. Não há repetição nenhuma, e a mensagem manda usar outra chave, ativar o faturamento ou voltar amanhã.

A explicação é escrita uma vez, a partir do erro inteiro, e viaja marcada como pronta para leitura (`FalhaLLM.amigavel`). Sem essa marca ela era embrulhada de novo em "falha na chamada da IA (...)" e cortada em 140 caracteres, no meio de uma palavra — apareceu assim em uso real.

Em ambos os casos a chave fica **bloqueada** pelo tempo indicado ([core/llm.py](core/llm.py)): cota é da chave, não de uma chamada. Sem isso, cada etapa seguinte de um map-reduce repetia as tentativas e a espera por nada — era o que fazia quatro etapas falharem devagar, uma depois da outra, com o mesmo erro. A primeira chamada bem-sucedida libera o bloqueio.

## Quanto custa, em dinheiro

Medido rodando o pipeline inteiro contra um cliente falso que registra os prompts, num vídeo de 18min30 (17.141 caracteres de transcrição): **8 chamadas, 60.090 caracteres de entrada e 9.509 de saída** — cerca de 15.000 tokens de entrada e 2.400 de saída, contando ~4 caracteres por token.

Aos preços de `gemini-3.6-flash` (US$ 0,75 por milhão de tokens de entrada e US$ 3,75 de saída, consultados em [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing)):

| | por vídeo | 100 vídeos |
|---|---|---|
| Análise completa + 1 vídeo montado | **US$ 0,020** | US$ 2,02 |
| Cada idioma extra | US$ 0,001 | — |

Por duração: 5 min ≈ US$ 0,013; 18 min ≈ US$ 0,020; 45 min ≈ US$ 0,034; 90 min ≈ US$ 0,057. A partir de 1º de janeiro de 2027 o preço do modelo dobra; `gemini-3.5-flash-lite` sai por cerca de metade do atual.

**Esses números são um piso, e subestimam a fatura.** Eles contam só os tokens do prompt e da resposta visível. O modelo também gasta **tokens de pensamento**, cobrados como saída, à mesma tarifa de US$ 3,75 por milhão — e a medição offline não tem como vê-los. Num caso com 12 mil tokens de pensamento, a conta vai de US$ 0,020 para US$ 0,065. O uso real medido por quem rodou com chave ficou em torno de R$ 0,16 por vídeo.

Por isso o app passou a contar `thoughts_token_count`, que ficava de fora de `estatisticas()`, e a barra lateral mostra o custo em dólar da sessão a partir dos tokens que a própria API reportou ([core/preco.py](core/preco.py)). É medição, não estimativa.

**88% da entrada é a transcrição indo três vezes** — no map, nos cortes e no roteiro. É o alvo óbvio se o custo virar problema: as três etapas poderiam partir dos resumos parciais em vez do texto inteiro, ou usar o cache de contexto da própria API (US$ 0,075 por milhão, mais armazenamento por hora).

A barra lateral mostra o gasto da sessão, quanto veio do cache em disco (repetir a mesma análise não gasta cota nem dinheiro de novo) e quantos segundos faltam do bloqueio.

## Backlog conhecido

- P1: o "não sei" só por nota de relevância recusa 71% do que não tem resposta; falta medir a checagem de suficiência pela IA (`6_avaliar_resposta.py`, precisa de chave) e um gabarito com documentos reais (o atual é fictício e autoescrito). O híbrido está implementado, mas não ajudou neste corpus.
- P2: as 10 repetições que a deduplicação por embedding ainda não pega; medir o acerto dos **alertas** (exige vários ciclos, não só uma coleta); rotular manchetes para comparar léxico x LLM x FinBERT; envio do Radar por e-mail e agendamento; medir a leitura de cardápio contra o gabarito com uma chave real; avaliações do Google e preço de insumo como novos tipos de evento; perguntar à base de eventos em português reaproveitando o validador de SQL do P5; backtest de 12 meses.
- P3: Whisper para vídeos sem legenda; limpeza de legenda automática; legenda sincronizada por palavra no vídeo.
- P4: currículos reais anonimizados com aderência rotulada por RH (o conjunto sintético satura); OCR; comparar a etapa de IA com as regras usando uma chave real.
- P5: rodar o gabarito com o Gemini e publicar o número; schemas colados pelo usuário.
