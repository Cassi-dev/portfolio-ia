English version: [README.en.md](README.en.md)

# Chatbot RAG sobre Documentos Próprios

Chatbot que responde perguntas sobre PDFs, `.txt` e `.md` que você envia, mostrando de qual arquivo, página e **seção** tirou cada resposta, e admitindo quando não sabe. Projeto 01 do desafio "7 Projetos de IA para Construir em um Fim de Semana".

```bash
python projeto_01_chatbot_rag/1_processar_documentos.py     # sincroniza o índice com documentos/ (só reindexa o que mudou)
streamlit run projeto_01_chatbot_rag/app.py
```

Sem chave de API o app roda em **modo 100% local** (mostra o trecho mais relevante, com fonte). Com uma chave do Google Gemini, a resposta é escrita em linguagem natural **com citações que o sistema confere** nos documentos.

## Como funciona

1. **Indexação** ([indexacao.py](indexacao.py), [estrutura.py](estrutura.py)): blocos de frases inteiras (~500 caracteres, 15% de sobreposição). Cada bloco começa com **"Documento > Seção"** e guarda a seção nos metadados (o e-book pede arquivo, página e seção). Há um bloco de visão geral por documento (título, abertura e lista de seções). O ID é um hash do conteúdo: reindexar é idempotente, reenviar um arquivo *substitui* os blocos dele, e a sincronização **pula o que não mudou** (hash do arquivo + versão da indexação).
2. **Busca** ([recuperacao.py](recuperacao.py)): 5 modos. `vetorial` (embeddings multilíngues), `bm25` (palavras-chave, implementação própria), `hibrido` (os dois, fundidos por RRF) e as versões com **reranker** cross-encoder (`mmarco-mMiniLMv2`). Filtro por documento.
3. **Modo "não sei"**: com reranker, a decisão usa a nota dele (mais nítida); sem, usa a distância do melhor bloco. O corte é ajustável na tela.
4. **Resposta com citações verificáveis** ([resposta.py](resposta.py)): a IA responde em formato estruturado e copia a frase exata que sustenta cada afirmação. O sistema confere se ela existe no trecho citado; um número trocado ("30 dias" no lugar de "7 dias") reprova sempre. Resposta cuja citação não confere **não é mostrada**: aparece o trecho original e um aviso.
5. **Segurança contra injeção de instruções** ([seguranca_rag.py](seguranca_rag.py)): um documento pode conter texto escrito para enganar o modelo ("ignore as regras..."). Os trechos entram no prompt como dado, entre delimitadores numerados, com limite de tamanho e de quantidade, sem caracteres invisíveis, e com a instrução explícita de nunca obedecê-los. Padrões típicos de injeção são detectados e a tela avisa.
6. **Conversa**: a pergunta de continuação ("e posso dividir?") é reescrita como pergunta completa a partir do histórico (com chave).
7. **Registro e feedback** ([registro.py](registro.py)): cada consulta grava pergunta, modo, decisão e latência por etapa em `registros/consultas.jsonl` (só na sua máquina, fora do git; `RAG_LOG=0` desliga). Os 👍/👎 viram candidatos a pergunta de teste com [4_exportar_feedback.py](4_exportar_feedback.py), para você revisar.
8. **Documentos**: painel para listar, filtrar a busca, remover e sincronizar; PDF escaneado passa por OCR do Gemini no upload.

## Os números

[5_avaliar_recuperacao.py](5_avaliar_recuperacao.py) mede a busca em **68 perguntas** sobre **8 documentos fictícios** em português ([corpus_ficticio/](corpus_ficticio/)): 8 literais, 24 paráfrases, 16 com números ou siglas, 6 abrangentes ("do que trata este documento?") e 14 **sem resposta**, das quais 6 são "quase do assunto" (ex.: "qual o valor do plano de saúde odontológico?", quando o manual só fala do plano de saúde). Cada pergunta com resposta aponta para uma frase de evidência, então o gabarito continua valendo se o corte dos blocos mudar. Um trecho acerta quando é do arquivo esperado e contém a evidência.

```bash
python projeto_01_chatbot_rag/5_avaliar_recuperacao.py      # ~4 min, roda offline
```

| Indexação + busca | recall@1 | recall@3 | MRR@5 | AUROC "não sei" | AUROC "quase do assunto" | latência média |
|---|---|---|---|---|---|---|
| antiga + vetorial (era o sistema) | 0,889 | 1,000 | 0,941 | 0,824 | 0,599 | 22 ms |
| antiga + bm25 | 0,815 | 0,944 | 0,886 | 0,778 | 0,486 | 1 ms |
| antiga + híbrido | 0,907 | 0,981 | 0,942 | 0,824 | 0,599 | 23 ms |
| antiga + vetorial + reranker | 0,870 | 0,944 | 0,917 | 0,854 | 0,691 | 1016 ms |
| **contextual + vetorial** | **0,963** | 0,981 | 0,976 | 0,819 | 0,586 | 26 ms |
| contextual + bm25 | 0,852 | 0,926 | 0,896 | 0,767 | 0,457 | 1 ms |
| contextual + híbrido | 0,944 | 1,000 | 0,969 | 0,819 | 0,586 | 29 ms |
| **contextual + vetorial + reranker** (padrão) | **0,963** | 1,000 | **0,981** | **0,874** | **0,707** | 713 ms |

("antiga" = blocos sem cabeçalho; AUROC = chance de uma pergunta com resposta ter nota maior que uma sem resposta, 0,5 é acaso e 1,0 separa tudo. O resultado completo, com as 10 combinações e o recall por tipo de pergunta, fica em `resultados/avaliacao_recuperacao.json`.)

### O que os números dizem

- **Adotado: o cabeçalho contextual** ("Documento > Seção" no bloco). Recall@1 de 0,889 para 0,963 e MRR de 0,941 para 0,976 no vetorial, com ganho também no BM25 e no híbrido (não é sorte de uma configuração). É o ganho mais barato: sem custo de latência perceptível.
- **Adotado como padrão, com ressalva: o reranker.** Ele não melhora a ordem dos resultados isoladamente (sem o cabeçalho ele até piora: 0,870 contra 0,889), mas melhora a **separação do "não sei"**: AUROC de 0,819 para 0,874, e de 0,586 para 0,707 nas perguntas "quase do assunto". O preço é ~0,7 s por pergunta. Dá para trocar por "só vetorial" na barra lateral.
- **Não adotada: a busca híbrida (BM25 + vetor).** Neste corpus ela não ajudou (0,944 contra 0,963 no recall@1) e o BM25 sozinho é o pior (0,852). A literatura diz que ela ajuda em códigos, IDs e termos raros; este corpus quase não tem isso, e o vetor multilíngue já acerta siglas e números. Fica implementada e disponível, mas não é o padrão. Com muitos códigos de erro ou nomes próprios, vale medir de novo.
- **Removido: o remendo de palavras-chave** ("resumo", "contexto") que redirecionava perguntas abrangentes. Elas acertam 100% no recall@3 sem ele, graças ao bloco de visão geral.

### O "não sei" ainda é fraco

Com o corte escolhido em metade das perguntas e medido na outra metade, o melhor modo (contextual + reranker) responde 85% do que tem resposta e recusa **71%** do que não tem (sem reranker: 82% e 64%). Nas "quase do assunto" o AUROC é 0,71. Uma nota de relevância (distância ou reranker) não separa bem "o documento fala do assunto" de "o documento responde a pergunta". O próximo passo real é a IA checar se o trecho basta (já implementado como o campo `suficiente` da resposta) e **medir isso com uma chave**: [6_avaliar_resposta.py](6_avaliar_resposta.py) roda as 68 perguntas de ponta a ponta e mede acerto, omissão, resposta errada e, principalmente, **resposta indevida** em pergunta sem resposta.

```bash
GEMINI_API_KEY=... python projeto_01_chatbot_rag/6_avaliar_resposta.py      # ~70 chamadas da API
```

Os cortes padrão da tela (nota do reranker −4,0; distância 0,16) ficam perto do que a calibração cruzada achou neste corpus (cerca de −4,2 e 0,135) e são um pouco mais permissivos. Nos seus documentos, [3_calibrar_parametros.py](3_calibrar_parametros.py) calibra o corte com perguntas suas.

### Como ler (com honestidade)

Corpus e perguntas foram escritos por quem construiu o sistema, com parte das perguntas de propósito em paráfrase; com só 54 perguntas respondíveis, uma diferença de 2 perguntas mexe ~0,04 no recall. Serve para **comparar variações**, não como estimativa de desempenho em documentos reais.

## O que ainda não foi verificado

O caminho com o Gemini de verdade (resposta com citações, reescrita da pergunta, OCR, resumo de contexto) e a defesa contra injeção diante de um modelo real foram testados só com um cliente simulado. Os testes provam a lógica (uma citação com número trocado é barrada, um trecho com ordens é sinalizado e delimitado), não que um modelo específico obedeça às regras. O `6_avaliar_resposta.py` existe para fechar essa lacuna.

## Limitações

Sem busca em tabelas de PDF (o texto sai linearizado). PDF escaneado depende do OCR do Gemini. O reranker é multilíngue (mMARCO) e de tamanho médio (baixado no primeiro uso); modelos maiores podem separar melhor o "não sei", a um custo maior de latência. O registro guarda as perguntas em texto puro no seu computador.

## Stack

Python 3.11+ · ChromaDB · sentence-transformers (`multilingual-e5-small` e o reranker `mmarco-mMiniLMv2-L12-H384-v1`) · Streamlit · Google Gemini (opcional)
