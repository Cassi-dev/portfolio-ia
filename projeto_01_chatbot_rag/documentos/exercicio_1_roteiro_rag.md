# PROJETO 01: Chatbot RAG sobre seus próprios documentos (INICIANTE)

Um chatbot que responde perguntas sobre os PDFs, notas e manuais que você entregar a ele — e que mostra de onde tirou cada resposta.

## Por que construir isso
RAG é o alicerce de praticamente todo produto de IA corporativo: base de conhecimento interna, assistente de documentação, atendimento. Construir do zero te dá domínio real de chunking, embeddings, busca vetorial e orquestração de LLM — nessa ordem de importância.

## Passo a Passo

### 1. Ingestão e chunking
Carregue PDFs, .txt e .md. Quebre em blocos de 500-800 tokens com 10-15% de sobreposição. Guarde metadados (arquivo, página, seção) junto de cada bloco — é o que permite citar a fonte depois.

### 2. Embeddings e índice
Converta cada bloco em vetor com bge-m3, multilingual-e5 ou text-embedding-3-small. Grave no ChromaDB local para prototipar; migre para pgvector quando virar produção.

### 3. Cadeia de recuperação
Busque os k blocos mais próximos da pergunta, monte o contexto e instrua o modelo a responder somente com base nele. A instrução de recusa é tão importante quanto a busca.

### 4. Interface de conversa
Streamlit com histórico de sessão. Exiba as fontes ao lado da resposta — arquivo e página. Sem isso, você tem uma demo bonita que ninguém consegue auditar.

## Stack Recomendada
- Linguagem: Python 3.11+
- Orquestração: LangChain
- Banco Vetorial: ChromaDB (protótipo) ou pgvector (produção)
- Embeddings: sentence-transformers
- Modelos LLM: Claude ou GPT
- Interface: Streamlit

## O que ninguém te conta
- Comece no ChromaDB local e gratuito. Banco vetorial em nuvem é problema de depois.
- Tamanho de bloco muda tudo. Teste 256, 512 e 1024 com as mesmas 20 perguntas e compare.
- Em português, embeddings multilíngues batem os modelos treinados só em inglês. Teste antes de assumir.
- Metadados em cada bloco não são enfeite: é o que transforma resposta em resposta citada.

## Desafio Extra
Implemente o modo 'não sei!': se a similaridade do melhor bloco ficar abaixo de um limiar, o bot admite que não encontrou em vez de inventar. É o que separa demo de produto.
