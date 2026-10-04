import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import chromadb

from core.embeddings import EmbeddingFunctionMultilingue
from indexacao import sincronizar_pasta

BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_DOCUMENTOS = os.path.join(BASE, "documentos")
PASTA_BANCO = os.path.join(BASE, "banco_vetorial")

print("Sincronizando o banco vetorial com a pasta documentos/ ...")
colecao = chromadb.PersistentClient(path=PASTA_BANCO).get_or_create_collection(
    name="meus_documentos_ptbr",
    embedding_function=EmbeddingFunctionMultilingue(),
    metadata={"hnsw:space": "cosine"}
)

resumo = sincronizar_pasta(colecao, PASTA_DOCUMENTOS)
for nome, blocos in resumo["indexados"].items():
    print(f"  + {nome}: {blocos} blocos")
for nome in resumo["pulados"]:
    print(f"  = {nome}: sem mudança, pulado")
for nome in resumo["sem_texto"]:
    print(f"  ! {nome}: sem texto nativo (PDF escaneado?), mantido como estava. Use o upload do app com chave Gemini para OCR.")
for nome, erro in resumo["erros"].items():
    print(f"  x {nome}: não foi possível ler ({erro}); os outros arquivos seguiram normalmente")
for nome in resumo["removidos"]:
    print(f"  - {nome}: não está mais na pasta, removido do índice")
print(f"Pronto: {colecao.count()} blocos no índice.")
