English version: [README.en.md](README.en.md)

# Monitor de notícias: sentimento, mudança e preço de ações

Duas formas de uso sobre a mesma base: o **painel sob demanda** (sentimento de notícias x preço de uma ação) e o **monitor**, que roda sozinho, guarda o que já viu e aponta o que mudou desde a última vez. Projeto 02 do desafio "7 Projetos de IA para Construir em um Fim de Semana". Estudo de NLP, **não é recomendação de investimento**.

```bash
streamlit run projeto_02_analisador_acoes/app_mercado.py            # painel de uma ação, sob demanda
python projeto_02_analisador_acoes/rodar_monitor.py --criar-exemplo # cria o cadastro para editar
python projeto_02_analisador_acoes/rodar_monitor.py                 # um ciclo do monitor
```

## O monitor

O painel sozinho não é um monitor: ele recomeça do zero a cada consulta, então não sabe dizer o que mudou. O monitor acrescenta estado.

1. **Cadastro** ([monitorados.py](monitorados.py)): um cliente (um restaurante, uma carteira) e os seus alvos — ele mesmo, os concorrentes e temas de mercado. Fica em `monitorados.json`, validado por Pydantic na carga, para um erro de digitação aparecer na hora em vez de virar coleta vazia. O modelo é [monitorados.exemplo.json](monitorados.exemplo.json); o arquivo real tem nome e e-mail de cliente e fica fora do git.
2. **Coleta por termos livres** ([coleta_noticias.py](coleta_noticias.py)): a busca deixou de aceitar só ticker. Qualquer conjunto de termos serve, com um tema opcional para desambiguar ("Bar do Zé" sozinho traz o país inteiro).
3. **Base de eventos** ([base_eventos.py](base_eventos.py)): SQLite local. Cada manchete vira uma linha com identidade estável (hash de alvo + título normalizado). Duas camadas de deduplicação: a exata, que impede a mesma manchete de entrar duas vezes, e a de quase-duplicata (Jaccard ≥ 0,60), que junta a mesma notícia saída em cinco portais.
4. **Pontuação incremental** ([ciclo.py](ciclo.py)): só o que ainda não tem score vai para a IA, em lotes de 60. Antes, o lote inteiro era reenviado a cada execução — o cache é da chamada toda, então uma manchete nova repagava as outras cem.
5. **Detectores** ([deteccao.py](deteccao.py)): novidade, pico de volume, virada de sentimento e palavras-gatilho ("interdição", "recuperação judicial", "inaugura"). São funções puras sobre listas, testadas sem banco e sem rede.
6. **Linha de comando** ([rodar_monitor.py](rodar_monitor.py)): `--listar`, `--cliente`, `--historico`, `--json`, `--sem-ia`. É o comando que um agendador chama.

## O Radar: o que o cliente recebe

O produto não é o app nem o banco — é o arquivo que chega. O Radar é um HTML autocontido (imprime em PDF pelo navegador) com o que mudou, cada linha com fonte, data e link.

```bash
streamlit run projeto_02_analisador_acoes/app_radar.py         # revisar, gerar e aprovar
python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze --itens
python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze
python projeto_02_analisador_acoes/gerar_radar.py --aprovar 1
```

Três decisões que vêm da natureza do serviço:

1. **Nada é gerado por IA no relatório.** Ele só organiza fatos que já estão na base. Um parágrafo de abertura escrito por um modelo seria o único ponto do produto onde caberia uma invenção — justamente no que vai assinado para o cliente. O rodapé diz isso a quem lê.
2. **O período é "desde o último Radar que você recebeu"**, não "os últimos 7 dias": nada é contado duas vezes nem cai no vão entre duas edições. Rascunho descartado não move o corte, então o que estava nele volta no próximo.
3. **Ninguém recebe nada sem uma pessoa ter lido.** O Radar nasce como `rascunho` e precisa passar por `aprovado`. O envio em si é manual, de propósito.

Na revisão você desmarca o que for ruído. Excluir um item o tira do Radar **e dos detectores**, para sempre — e cada exclusão é um rótulo humano de "isto não é sinal", que é a matéria-prima para medir alarme falso mais adiante. Dá para restaurar.

Quando não há nada, o Radar diz "semana sem novidade" em vez de chegar vazio: isso também é informação.

### Rodar sozinho e entregar

O monitor coleta sem ninguém por perto; o Radar continua saindo pela sua mão.

```bash
schtasks /create /tn "Radar - monitor semanal" /tr "caminho\monitor_agendado.bat" /sc weekly /d MON /st 07:00
python projeto_02_analisador_acoes/gerar_radar.py --simular-envio 7    # mostra o e-mail, não envia
python projeto_02_analisador_acoes/gerar_radar.py --enviar 7           # envia de verdade
```

[monitor_agendado.bat](monitor_agendado.bat) é o que o Agendador de Tarefas chama: roda todos os clientes e grava log por dia em `logs/`, porque tarefa agendada que falha falha em silêncio. O comando de agendamento está comentado dentro do próprio arquivo.

O envio ([entrega.py](entrega.py)) tem três travas, por ser a única parte que fala com o mundo em nome do cliente:

1. **Só Radar aprovado sai.** Rascunho, descartado e já enviado são recusados com o motivo. A revisão humana não é contornável.
2. **A senha nunca entra no repositório.** Tudo vem de variáveis de ambiente (`RADAR_SMTP_HOST`, `RADAR_SMTP_USUARIO`, `RADAR_SMTP_SENHA`, e opcionalmente `RADAR_SMTP_PORTA` e `RADAR_REMETENTE`). No Gmail, use uma senha de aplicativo.
3. **`--simular-envio` mostra exatamente o que sairia** — remetente, destinatário, assunto, corpo e anexo — sem senha e sem tocar na rede.

O corpo do e-mail traz os destaques **congelados no momento da geração**, não uma nova leitura da base: o cliente recebe o que você revisou e aprovou, mesmo que o monitor já tenha coletado outra coisa desde então. O Radar completo vai anexado em HTML; não mando no corpo porque cliente de e-mail corta CSS de cabeçalho e o relatório chegaria torto.

Nenhum e-mail foi enviado no desenvolvimento: os testes usam um SMTP simulado, e os três caminhos de recusa (rascunho, sem configuração, cliente sem e-mail) foram exercitados de verdade.

### O que a checagem visual pegou

Gerando o Radar com os 80 eventos reais e um cardápio, apareceram dois defeitos que nenhum teste unitário pegaria: os preços saíam como `R$ 12.00` (padrão do Python, não o brasileiro) e o destaque repetia o nome do alvo ("Boteco Central: Boteco Central sofre interdição..."). Os dois estão corrigidos e cobertos por teste.

## Cardápio por foto

Notícia cobre mal restaurante pequeno. O dado que o dono realmente quer — o preço do concorrente — não está em fonte gratuita, e raspar marketplace está fora: os termos do iFood proíbem coleta automatizada para monitorar ou concorrer. A origem aqui é uma foto.

```bash
python projeto_02_analisador_acoes/cardapio_ficticio.py          # gera dois cardápios de teste e o gabarito
GEMINI_API_KEY=... python projeto_02_analisador_acoes/adicionar_cardapio.py \
    --cliente bar-do-ze --alvo concorrente-a --comparar foto.jpg
```

A foto (ou PDF) vira uma tabela de itens e preços ([cardapio.py](cardapio.py)), e da segunda captura em diante o monitor diz o que subiu, baixou, entrou e saiu. **A imagem não é guardada**: fica só a tabela extraída e o nome do arquivo.

A divisão de trabalho é a de sempre no repositório: o modelo só **lê** e copia o preço como está impresso (`"R$ 48,90"`); quem converte para número, casa os itens entre capturas e calcula variação é o Python, onde dá para testar sem gastar chamada.

Cuidados que estão no código, porque cada um deles vira erro na cara do cliente:
- **Item não é o mesmo só porque o nome parece.** O casamento é por nome normalizado ("X-Salada" = "X Salada"); nomes só parecidos passam por um limiar alto e **os números do nome precisam bater**, então "Burger 180g" nunca vira "Burger 250g". Casamento por semelhança é reportado para conferência.
- **Preço ilegível não é preço que mudou.** Item sem preço legível em alguma das capturas vai para `sem_comparacao`, não para "subiu".
- **Foto cortada não é cardápio encolhido.** Se mais de 40% dos itens "sumirem", sai um aviso de que a foto pode estar incompleta.
- **Não há modo offline.** Sem chave de API não existe leitura de imagem, e o comando diz isso em vez de fingir.

### O que está verificado e o que não está

A comparação é testada contra um cenário de 15 itens com gabarito derivado dos preços ([cardapio_ficticio.py](cardapio_ficticio.py)): 4 altas, 1 queda, 2 itens novos, 1 removido, 1 sem comparação, 8 sem mudança. Escrevendo esse gabarito à mão eu classifiquei a queda do refrigerante como alta; passar a derivá-lo dos preços pegou o erro, e há um teste de regressão para isso.

**A leitura da imagem pelo Gemini nunca rodou.** O schema, o prompt, a montagem da chamada e o tratamento de erro são testados com um cliente simulado, mas a qualidade do que o modelo lê de uma foto — e mais ainda de uma foto torta, com pouca luz, de um cardápio plastificado — só aparece com uma chave. Os cardápios fictícios são imagens limpas geradas por computador: acertar neles é o piso, não a prova.

### O que a primeira execução real mostrou

Rodando contra o Google News com duas redes de restaurante e um tema de setor:

| | ciclo 1 | ciclo 2, minutos depois |
|---|---|---|
| Coletados | 80 | 80 |
| Novos | 80 | **0** |
| Mandados para a IA | 80 | **0** |

Esse zero é o ponto do exercício: o custo passa a acompanhar o que aparece de novo, não o tamanho da janela.

A primeira execução também revelou um defeito que eu não tinha previsto: **os três alvos acusaram "pico de volume"**. Não era pico. O RSS devolve muito mais notícia recente do que antiga (nos três casos, mais de 60% do mês caiu nos últimos 7 dias, contra ~23% se fosse uniforme), então a foto trazida pela primeira busca não serve de linha de base. Agora o detector recebe desde quando o alvo está realmente sendo observado, calcula a média só sobre esse período e não declara pico antes de 14 dias de observação. A primeira coleta é marcada como tal e não gera alerta nenhum — nela tudo é novo por definição.

## Quanto disso é ruído? (medido)

Um monitor que enche o cliente de lixo é cancelado. Este é o primeiro número real do projeto sobre isso.

Rotulei **as 80 manchetes reais** da coleta acima, uma a uma, com o motivo de cada descarte ([medir_monitor.py](medir_monitor.py) exporta e importa esses rótulos). O critério: vale mostrar a um dono de restaurante que acompanha o Madero, o Outback e o setor?

```bash
python projeto_02_analisador_acoes/medir_monitor.py --cliente rede-exemplo
```

| | |
|---|---|
| **Taxa de ruído** | **58,8%** (47 de 80) |
| Pior alvo | `setor-food-service`, 61% de ruído em 54 itens |
| Motivo nº 1 | **duplicata: 21 itens, 45% de todo o descarte** |
| Depois | regional irrelevante (19%), publieditorial (19%), página de arquivo (8%) |

Seis de cada dez itens seriam jogados fora na revisão. Isso mede **precisão** (o que aparece e não deveria), não cobertura: o que o monitor deixou de encontrar no mundo não está aqui e não dá para estimar com estes dados.

A revisão do Radar alimenta esse número sozinha: o que você descarta vira rótulo "ruído", o que sobrevive a um Radar aprovado vira "útil". Rótulo feito à mão nunca é sobrescrito pelo automático.

### O conserto que veio do número

O maior pedaço do ruído era repetição, então fui atrás da deduplicação. Havia 11 histórias saídas em 2 a 5 portais, 21 repetições a eliminar. Testei as regras contra esses grupos ([deduplicacao.py](deduplicacao.py) traz a tabela inteira):

| Regra | Repetições removidas | Fusões erradas |
|---|---|---|
| jaccard ≥ 0,60 (o que estava no ar) | **0 de 21** | 0 |
| jaccard ≥ 0,35 | 5 de 21 | 1 |
| contenção ≥ 0,50 | 6 de 21 | 9 |
| embedding, cosseno ≥ 0,95 | 5 de 21 | 0 |
| **embedding, cosseno ≥ 0,93** (adotado) | **11 de 21** | 1 |

Palavra em comum não resolve: o portal reescreve o título inteiro. "Mulher encontra aparelho dentário em prato do Outback" e "Cliente relata ter encontrado objeto estranho em prato de rede famosa" são a mesma história e quase não compartilham palavras. Baixar o limiar por tokens começa a juntar notícias diferentes antes de pegar as repetições.

O monitor passou a usar embeddings (o mesmo `multilingual-e5-small` do Projeto 01) para decidir "é a mesma notícia". Coletando as mesmas fontes de novo: **79 manchetes, 68 guardadas — 11 repetições barradas**, exatamente o previsto. `--dedup tokens` volta ao modo antigo, sem modelo.

A fusão errada custa uma notícia real que não chega ao cliente. Em 80 manchetes foi uma (duas promoções do Outback). Quem preferir errar para o outro lado usa 0,95 e perde metade do ganho.

### O próximo conserto, já escrito e ainda não adotado

Sobrou a parte do ruído que não é repetição: notícia que não é sobre o alvo, página de arquivo, publieditorial, assunto de outra região. Nada disso tem a ver com sentimento — que é exatamente onde a IA era gasta até aqui.

[relevancia.py](relevancia.py) inverte isso: em vez de pontuar o humor da manchete, pergunta se ela vale o boletim daquele cliente. É mais barato (resposta de sim ou não) e ataca 100% do que foi medido.

**Não está ligado no ciclo**, de propósito. Primeiro se mede, contra os mesmos rótulos humanos:

```bash
GEMINI_API_KEY=... python projeto_02_analisador_acoes/avaliar_relevancia.py \
    --cliente rede-exemplo \
    --cadastro projeto_02_analisador_acoes/dados_medicao/cadastro.json \
    --banco projeto_02_analisador_acoes/dados_medicao/monitor.db
```

Os dados da medição ficam em [dados_medicao/](dados_medicao/): os 80 rótulos versionados como evidência do número acima, e o banco para rodar direto. Custa 4 chamadas da API.

O resultado diz o que importa: quanto do ruído o filtro pega e **quanto de notícia boa ele joga fora junto** — esse é o erro caro. Se compensar, ele entra na revisão desmarcando o provável ruído para você confirmar, nunca descartando sozinho. Foi assim que a troca da deduplicação foi decidida, e foi assim que a minha primeira hipótese sobre ela caiu.

### Duas ideias testadas e recusadas

O alvo de setor concentra 33 dos 47 descartes, e parecia óbvio que estreitar os termos resolveria. Não resolveu. Os experimentos estão em [experimentos/](experimentos/), com os números e o porquê:

| Ideia | Resultado | Decisão |
|---|---|---|
| Dividir o setor em 4 assuntos | taxa cai (60% → 36-43% em três dos quatro), mas o volume vai de 54 para **213** manchetes | recusada |
| Regra de nomes de lugares para "notícia de outra região" | pega 6 dos 9 regionais, ao custo de **5 dos 33 úteis** | recusada |

A divisão melhora a taxa e piora a vida: buscas específicas cavam mais fundo na cauda longa e trazem quatro vezes mais item, quase tudo regional. Mais coisa para revisar, com taxa melhor, dá mais trabalho e não menos. A regra de lugares erra justamente nos melhores itens ("Outback chega ao Shopping Uberaba", "Papa Johns estreia em São Paulo"): ela não distingue *notícia sobre um lugar* de *notícia nacional que cita um lugar*.

Juntas, as duas dizem a mesma coisa: **o ruído não é de assunto largo nem de geografia no título.** É tipo de conteúdo (publieditorial, página de arquivo) e pertinência ao cliente — e isso depende de quem é o cliente, não do texto da manchete. É exatamente o contexto que o filtro de relevância recebe.

**Como ler estes números:** 80 manchetes, um único anotador (eu), sem segunda opinião. Mede o caso óbvio — duplicata, página de arquivo, publieditorial —, não o julgamento fino de relevância, que depende do cliente. O valor está na ordem de grandeza e no que ela aponta como próximo conserto, não na terceira casa decimal.

### Limites do monitor

Os limiares dos detectores (pico ≥ 2x a média, virada ≥ 0,30, mínimo de 3 eventos) continuam sendo **chutes, não números medidos** — o que foi medido acima é a relevância dos itens, não o acerto dos alertas. Para medir alerta seria preciso acompanhar vários ciclos e julgar cada interrupção; com uma coleta só não há o que medir. O léxico local foi escrito para manchete financeira e devolve quase sempre 0,00 em notícia de restaurante, então no perfil "negócio" o sentimento sem chave de API diz pouco — o ciclo avisa isso na saída. Notícia cobre mal restaurante pequeno: rede e regulação aparecem, o bar da esquina não. Só há um tipo de evento (notícia); cardápio, avaliação e preço de insumo são passos seguintes.

## O painel de uma ação

## Como funciona

1. **Coleta** ([coleta_noticias.py](coleta_noticias.py)): Google News RSS com o nome da empresa, o código do ativo e a janela (`when:30d`); mercado americano em inglês. Deduplicação por similaridade de Jaccard.
2. **Sentimento** ([analise_sentimento.py](analise_sentimento.py)): saída estruturada validada (`score` de -1 a +1, classificação, motivo). Sem chave, ou se a IA falhar ou pular uma manchete, cai no léxico e **marca a manchete** (`motor = lexico` + motivo), com aviso na tela. O léxico casa palavras inteiras e entende expressões que invertem o sentido ("cai menos que o esperado" é positivo).
3. **Alinhamento com o pregão** ([cruzamento_precos.py](cruzamento_precos.py)): cada notícia vale para o primeiro pregão em que pode ter refletido no preço, usando o calendário real da série de preços. Notícia depois do fechamento (17h em SP, 16h em NY) vale para o dia seguinte; fim de semana e feriado caem no próximo pregão; notícia depois do último pregão ainda não tem preço e fica de fora.
4. **Série suavizada**: média móvel exponencial por pregão (meia-vida ajustável). O decaimento relativo a "hoje", que a primeira versão usava, distorcia a série histórica.
5. **Rigor estatístico** ([analise_estatistica.py](analise_estatistica.py)): acerto de direção contra o **baseline** (melhor palpite constante) com p-valor binomial, e correlação com defasagem de 0 a 5 pregões. Com menos de 30 dias o veredito é "não conclusivo".

## O que mudou na coleta (medido)

A consulta antiga trazia manchetes de 2024 até 02/09/2026 e nenhuma dos últimos 16 dias (o parâmetro `limite_dias` existia mas nunca era usado). A nova traz 98 manchetes, todas entre 25/08 e 18/09 (87% citam a empresa no título). A hipótese de que a consulta antiga "soltava o ticker" da busca não se confirmou: 98% delas citavam a Petrobras.

## Limitações gerais

Sem um conjunto de manchetes rotuladas à mão ainda não há acurácia do classificador (léxico x LLM x FinBERT). O FinBERT é treinado em inglês, então a comparação justa seria nos tickers americanos. O RSS devolve no máximo ~100 itens, o que deixa a janela de 6 meses esparsa.
