English version: [README.en.md](README.en.md)

# Text-to-SQL seguro

Pergunte em português, receba o SQL (mostrado antes do resultado), o resultado e o motivo de cada bloqueio. Projeto 05 do desafio "7 Projetos de IA para Construir em um Fim de Semana".

```bash
streamlit run projeto_05_gerador_sql/app_sql.py
```

## Como funciona

1. **Prompt** ([motor_text_to_sql.py](motor_text_to_sql.py)): schema completo em toda chamada, 4 exemplos few-shot, **a data de hoje** (para "mês passado", "últimos 30 dias") e os **valores possíveis das colunas categóricas** (sem isso o modelo chuta `'PWA'` em vez de `'PWA TACTO'` e a consulta volta vazia, sem erro).
2. **Saída estruturada**: o modelo devolve um objeto `{sql}` validado por Pydantic. Sem cerca markdown para limpar.
3. **1ª trava, validador de AST** ([validador_seguranca.py](validador_seguranca.py)): aceita `SELECT`, `WITH` (inclusive recursivo) e `UNION/EXCEPT/INTERSECT`; bloqueia qualquer outra raiz, `PRAGMA`, `ATTACH`, escrita aninhada, vários comandos e funções como `load_extension`.
4. **2ª trava, o próprio SQLite** ([banco_dados.py](banco_dados.py)): conexão `mode=ro` + `PRAGMA query_only` + `set_authorizer` (só leitura), teto de 1.000 linhas e de 5 s (uma consulta recursiva infinita é interrompida). As travas são independentes: os testes atacam a segunda **sem** passar pela primeira.
5. **Ciclo de correção**: se o banco devolver erro, ele volta ao modelo (até 2 tentativas). Se a API falhar, cai no modo offline **com aviso**.

## A base de exemplo

40 clientes, 14 produtos, 400 pedidos e 1.024 itens, gerados com seed fixa (mesmos dados sempre) e **consistentes**: `pedidos.valor_total` é sempre a soma dos itens do pedido. (A versão anterior tinha 12 pedidos e 10 deles com total diferente da soma dos itens, o que tornava impossível medir acurácia.) `python projeto_05_gerador_sql/banco_dados.py --recriar` reconstrói a base.

## O número medido: acurácia de execução

50 perguntas em português (filtro, agregação, junção, ranking, datas, subconsulta) com o SQL de referência escrito à mão em [perguntas_gabarito.json](perguntas_gabarito.json). Um SQL gerado acerta quando o **resultado** é igual ao do gabarito (conjunto de linhas, números em 2 casas, nomes de coluna e ordem não contam, exceto nas perguntas marcadas como ordenadas).

```bash
python projeto_05_gerador_sql/avaliar_acuracia.py --modo gabarito      # sanidade do gabarito
python projeto_05_gerador_sql/avaliar_acuracia.py --modo offline       # baseline sem IA
GEMINI_API_KEY=... python projeto_05_gerador_sql/avaliar_acuracia.py --modo gemini
```

| Modo | Acurácia de execução |
|---|---|
| Gabarito contra ele mesmo (sanidade, valida as 50 consultas) | 50/50 (100%) |
| Offline, sem IA (baseline) | 0/50 (0%) |
| Gemini | **rode com a sua chave e cole aqui**: o resultado sai por categoria, com latência e tokens, em `resultados/avaliacao_gemini.json` |

O baseline de 0% é real: o modo offline só tem 3 consultas prontas e nenhuma delas responde às perguntas do gabarito. O gabarito foi checado por empates: nenhum ranking tem empate na fronteira do top-N.

## Limitações conhecidas

Comparar resultados é mais justo que comparar texto de SQL, mas ainda pode reprovar um SQL correto que devolva colunas extras. A base é sintética e pequena.
