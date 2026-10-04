English version: [README.en.md](README.en.md)

# Estúdio de vídeos: criar vídeo de qualquer assunto, analisar vídeos do YouTube, editar vídeo próprio e Reels da TACTO Studio

Quatro modos no mesmo app Streamlit. Projeto 03 do desafio "7 Projetos de IA para Construir em um Fim de Semana", expandido.

```bash
streamlit run projeto_03_resumidor_youtube/app_youtube.py
```

## Modo "Criar vídeo de qualquer assunto" (padrão)

Você dá um **contexto** (um assunto, um artigo, notas de reunião, a descrição de um produto, o resumo de um vídeo do YouTube que acabou de analisar) e recebe um vídeo vertical (1080x1920, 24 fps, H.264) com locução neural em português.

1. **Roteiro** ([criador_reels.py](criador_reels.py)): a IA divide o contexto em 3 a 7 cenas e escolhe, para cada uma, um de 5 layouts: título, lista, número animado, comparação (antes/depois, mito/verdade) ou chamada final com botão. Você escolhe duração (15 a 90 s), tom, público e a chamada final.
2. **Edição**: cada cena vira um formulário com prévia do quadro; você muda layout, textos e fala antes de renderizar. Se algo estiver incompleto (uma lista com 1 item, um botão sem texto), o botão de renderizar fica bloqueado e diz o que falta.
3. **Vídeo** ([renderizador_generico.py](renderizador_generico.py)): 5 temas visuais, marca em texto ou logo enviado, voz masculina, feminina ou vídeo mudo. A legenda percorre a fala inteira durante a cena (em blocos, não sincronizada palavra a palavra).

**Só o que está no seu contexto.** O prompt proíbe inventar fatos, e o código confere: um número em destaque que não aparece no contexto é trocado por um título simples, e qualquer outro número da cena que não esteja no contexto gera um aviso ("confira antes de publicar"). O contexto vai ao modelo entre delimitadores como dado, e o texto do usuário não consegue fechar o delimitador.

**Sem chave** (modo degradado, com aviso): o texto é apenas dividido em cenas, na ordem, sem reescrever nada, e o vídeo sai igual. Fica menos variado e sem hashtags, mas funciona offline (só a locução precisa de internet; "sem voz" gera um vídeo mudo).

Como foi feito:
- O texto é medido antes de ser desenhado (tamanho e linhas), então não vaza do cartão; emojis são removidos da tela (a fonte os desenharia como quadradinho).
- Os quadros vão direto para o ffmpeg por pipe: nada de milhares de PNGs temporários, e a pasta temporária é apagada mesmo quando dá erro. Renderizar leva cerca de 0,8 s por segundo de vídeo.
- As fontes têm alternativas (Segoe, Arial, DejaVu, Liberation), então os testes rodam também no CI em Linux.

O que foi verificado: 90 testes automáticos (regras das cenas, números, prompt, cada layout em cada tema com texto absurdamente longo sem sair da tela, vídeo mudo e com locução simulada de ponta a ponta) e uma renderização real com a voz neural. **Não verificado com o Gemini de verdade**: o schema é aceito pelo SDK, mas a qualidade dos roteiros escritos por ele (ritmo, escolha de layouts, se respeita o limite de números) só aparece com a sua chave.

## Modo "Reels oficial da TACTO Studio"

Os 4 cenários fixos da TACTO (taxa do marketplace, PWA, IA + dados, chamada final), com o renderizador original ([renderizador_video_tacto.py](renderizador_video_tacto.py)), intactos. A TACTO também existe como tema no modo livre (paleta e logo), para criar vídeos novos com a marca.

## Modo "Analisar Vídeo do YouTube" (o projeto do e-book)

Cole a URL e receba, em abas, **Resumo**, **Tópicos** (cada minutagem é um link para o ponto do vídeo), **Quiz** de 5 perguntas com gabarito, **Cortes** para Reels e **Roteiro** — e, no fim do roteiro, o **vídeo pronto para postar**.

- **Map-reduce** ([agente_map_reduce.py](agente_map_reduce.py)): a transcrição vira fatias por tamanho (sem descartar texto), resumidas **em paralelo** e depois sintetizadas.
- **Contexto**: título e canal do vídeo (oEmbed do YouTube, sem chave) entram nos prompts.
- **Saída estruturada** ([esquemas_video.py](esquemas_video.py)): schemas Pydantic (5 perguntas com 4 alternativas e gabarito de 0 a 3, cortes de 1 a 180 s, timestamps `MM:SS`). Resposta fora do schema tem uma tentativa de reparo e, se falhar, vira aviso.
- **Transcrição inteira** nos cortes e no roteiro (a versão anterior olhava só os primeiros minutos). Só acima de 300 mil caracteres (cortes) ou 60 mil (roteiro) ela é amostrada de forma uniforme, cobrindo o vídeo todo.
- **Modo degradado**: sem chave, ou se a IA falhar, cada etapa diz que NÃO veio da IA e por quê. O quiz sem IA fica vazio (em vez de uma pergunta genérica inventada) e o roteiro avisa, na própria aba, que é o modelo da TACTO e não o do vídeo — e nesse estado ele não é usado para montar vídeo nenhum.

### Detalhes do renderizador oficial da TACTO

Renderiza um vídeo vertical (1080x1920, 24 fps, H.264) com locução neural em pt-BR, animações desenhadas com Pillow e montagem com ffmpeg ([renderizador_video_tacto.py](renderizador_video_tacto.py)). O ffmpeg vem do pacote `imageio-ffmpeg` (nada de caminho fixo), o código de saída dele é verificado e os frames temporários são apagados ao final.

**Sobre os números do vídeo**: o total, o nº de pedidos e o ticket médio da cena 3 vêm da base de demonstração do Projeto 05 (pedidos concluídos do canal PWA) e a tela diz "dados de demonstração". A versão anterior mostrava valores fixos que a base nunca teve. O botão de benchmark do PWA continua sendo uma demonstração ilustrativa (não mede nada) e agora diz isso na tela.

### A escolha dos cortes

São **5 sugestões** por vídeo, e elas começam e terminam onde a frase começa e termina.

Antes cortavam no meio do raciocínio, e a causa estava no que a IA enxergava: o prompt levava os blocos de resumo, que trazem **uma marcação de tempo a cada ~44 segundos**, e ela tinha que escolher o segundo do corte por aproximação dentro dessa janela. Agora o prompt leva as falas soltas da transcrição — uma marcação a cada ~4 segundos — e pede explicitamente raciocínio completo.

Mas o modelo continua aproximando, então há uma segunda camada que **não depende dele**: os tempos escolhidos são encaixados nas fronteiras de frase calculadas a partir das palavras cronometradas ([legendas.py](legendas.py)). O começo recua até 10 s para pegar o início da frase; o fim avança até a frase fechar, sem limite de tempo fixo — quem segura é a duração máxima de 90 s (teto do Reels e do TikTok). Encurtar o fim corta conteúdo, então só acontece quando não há frase nenhuma à frente e a fronteira está a menos de 2 s atrás. Isso vale também para os cortes mecânicos do modo degradado.

Medido em dois vídeos reais (18 e 22 minutos): os 10 cortes caem a menos de 1 segundo de uma fronteira de frase nas duas pontas, com 49 a 62 segundos de duração.

### O fatiador de cortes

O clipe é gerado **sem baixar o vídeo inteiro**: o yt-dlp devolve a URL do stream e o ffmpeg busca só o trecho pedido, por faixa HTTP. Um corte de 15 s em 1080p saiu em 11 segundos e 1,1 MB; 45 s levaram 40 s.

Não usamos o download parcial do próprio yt-dlp, e a razão é concreta: ele verifica se há ffmpeg com `FFmpegFD.available()`, que monta um objeto sem parâmetros e por isso **ignora o `ffmpeg_location` que passamos** — o próprio código do yt-dlp tem um `Fixme` reconhecendo isso. Em máquina sem ffmpeg no PATH do sistema, a checagem dá falso e ele aborta com "ffmpeg is not installed", mesmo com o ffmpeg empacotado ali do lado. Foi o que aconteceu no primeiro uso real.

**Qualidade** (até 4K, 1440p, 1080p, 720p, 480p ou 360p, escolhida na tela; o padrão é até 1440p). O primeiro uso real saiu em 360p e a causa não era o formato pedido: o código forçava `player_client: ["android"]`, e esse cliente só oferece o formato 18 — 360p com áudio junto. Medido no mesmo vídeo: com `android`, as alturas disponíveis eram 144/180/**360**; sem forçar cliente, 144/240/360/480/720/**1080**. Agora a primeira tentativa não força cliente nenhum e o `android` ficou como segunda chance (ele responde quando o outro falha, só que em 360p). Acima de 360p, vídeo e áudio vêm em streams separados e o ffmpeg junta os dois. O seletor **não** prende o codec: o H.264 do YouTube para em 1080p, e pedi-lo primeiro jogaria fora o 1440p e o 4K, que só existem em VP9 e AV1 — como o trecho é recodificado de qualquer jeito, a resolução importa mais que o codec de origem.

O YouTube às vezes recusa uma url recém-emitida com **403**, de forma intermitente (as urls são assinadas e ligadas ao cliente que as gerou). Nesse caso o corte é refeito uma vez com uma extração nova, que traz assinatura nova; só depois disso o erro sobe para a tela.

O corte é recodificado (`-ss` antes do `-i`, que é busca rápida, e depois libx264 com CRF 16) para começar no segundo pedido, e não no keyframe anterior. Falha de rede, vídeo restrito ou erro do ffmpeg viram uma mensagem em português na tela, não um traceback.

### Vídeo pronto para postar (na aba Roteiro)

A aba entregava o roteiro em texto. Agora ela monta a peça: **o corte tratado em 9:16 + um cartão final convidando a seguir a conta**, num `.mp4` só, mais o título e a descrição da publicação ([editor_reels.py](editor_reels.py), [publicacao.py](publicacao.py)).

**O vídeo inteiro sobre fundo desfocado** é o padrão, e por causa da definição: assim a imagem é *reduzida* (um 16:9 vira 1080x607), e reduzir é sempre nítido. O fundo é o próprio vídeo ampliado, desfocado e escurecido — sem tarja preta e sem contorno colorido em volta: quem separa a imagem do fundo é o desfoque, e uma borda só marcaria a peça como template. O modo *tela cheia* existe para quem fala na câmera, mas cobra o preço descrito abaixo.

Sem nada escrito em cima, o vídeo sobe e ocupa a largura inteira — 1080x607 em vez de 1000x562, 8% a mais de imagem e de resolução. Com título ou etiqueta, ele desce para não encostar.

**Por padrão, só imagem e legenda.** Título, etiqueta, marca, caixa atrás da legenda, barra de progresso, cartão de abertura e cartão final existem, mas todos vêm desligados — no uso real, uma caixa preta sobre o vídeo e uma etiqueta fixa atrapalharam mais do que ajudaram. A legenda fica direto sobre a imagem, com contorno de 7 px nas letras, que é o que a mantém legível sobre qualquer fundo sem cobrir o vídeo. Uma camada de arte vazia nem vira entrada do ffmpeg.

### A legenda ([legendas.py](legendas.py))

O arquivo de legenda do YouTube vem em pedaços de ~3 s que não têm relação nenhuma com as frases. A primeira versão usava esses pedaços como estão, e o resultado tinha três defeitos, todos medidos no mesmo trecho:

- **a legenda ficava na tela depois de a fala acabar** — "e baixar o código…" é dito de 0,00 a 3,77 s, e aparecia até 5,07 s, porque cada bloco era esticado até o seguinte para não piscar;
- **pedaço grande não era partido** — o limite de palavras só impedia *juntar*, então um pedaço de 12 palavras virava uma legenda de 12 palavras;
- **blocos começavam no meio da oração e em minúscula**, porque a quebra era a do arquivo, não a da frase.

Agora **cada palavra ganha um instante próprio**: a duração do pedaço é repartida entre as palavras dele na proporção do tamanho de cada uma. Erra por décimos, e não pelos 2 s que um pedaço inteiro errava. Pedaços que se sobrepõem (a legenda automática faz isso o tempo todo) são aparados no começo do seguinte, e uma palavra entra pelo meio dela — quem fala em cima do corte não perde a frase.

Com o tempo por palavra, os blocos quebram onde a fala quebra: fim de frase, silêncio maior que 0,7 s, ou os limites de 12 palavras e 4 s. O que sobra grande é repartido em partes **iguais** (10 palavras saem 5+5, não 8+2). Cada bloco sai da tela 0,5 s depois da última palavra, sem nunca alcançar o seguinte — então o silêncio fica sem legenda, como deve.

Os limites foram escolhidos medindo: com 8 palavras/3 s o trecho de teste virava 16 blocos de 1,8 s em média, rápido demais para ler; com 12/4 s viraram 9 blocos de 3,2 s.

**Depois, alinhados ao padrão profissional** ([guia da Netflix para português do Brasil](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215600497-Brazilian-Portuguese-Timed-Text-Style-Guide) e [requisitos gerais](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)): no máximo **2 linhas**, cada legenda entre **5/6 s e 7 s** na tela, e quebra depois de pontuação ou antes de conjunção/preposição — nunca separando artigo do nome, nem negação ou pronome do verbo. O que mudou, e o que cada mudança consertou no uso real:

- **Frase grande é partida no melhor ponto dela**, e não onde o limite de tempo caía. Antes: "tá na hora da gente ter uma última" num bloco e "conversa." sozinha no seguinte. Agora: "Senhor Rengoku, / tá na hora da gente ter uma última conversa.". O limite de tempo por bloco subiu de 4 para 6 s: com 4, "enquanto você se afoga em tristeza." (fala lenta, 5 s) virava "enquanto você / se afoga", separando o sujeito do verbo.
- **Quebra de linha com a mesma regra.** Nas 84 legendas reais que existiam aqui, a primeira linha terminando em artigo, preposição ou conjunção caiu de 29 para 3 ("Entre o céu e a terra, / sou o mais honrado.").
- **Bloco esticado sai no tempo de leitura.** Um pedaço da legenda automática que atravessou 8 s de música deixou "Está me superestimando." 8,8 s na tela; agora, quando a "fala" é mais lenta do que alguém fala de verdade (menos de 6 caracteres por segundo), o bloco sai no tempo de ler com folga — 4,1 s nesse caso. Fala lenta de verdade não é cortada.
- **Texto curto não é picado por tempo** ("Está / me / superestimando." em três blocos) e **o começo de frase cortado pelo fim do clipe some** ("Se" sozinho na tela).
- **Marcações da legenda automática saem** ("[Música]", "[Aplausos]", notas musicais), e caracteres sem fonte também (o lixo em coreano no meio do português).

**O tempo foi medido contra a voz**, filtrando o áudio na faixa da fala: na cena de diálogo limpo (despedida do Rengoku), o início dos blocos bate com o começo da voz com erro abaixo de 0,15 s na maioria deles. Onde a medida não serve é debaixo de música alta, que ocupa a mesma faixa. O limite que sobrava era o do **destaque palavra a palavra**: o tempo de cada palavra dentro do bloco era estimado pelo tamanho dela — resolvido pelo reconhecimento de fala local, abaixo.

### Reconhecimento de fala no computador ([fala_local.py](fala_local.py))

O [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelo `small`, ~480 MB, baixado no primeiro uso para a pasta do Hugging Face do usuário) roda no processador, sem custo por uso. Três usos:

**1. O tempo de cada palavra, medido no áudio.** Medido contra um gabarito — a voz neural do app (edge-tts) informa o instante exato de cada palavra; 55 palavras em 4 frases, a "legenda" em pedaços de 3 s como os do YouTube:

| | erro médio | 90% das palavras até | pior |
|---|---|---|---|
| estimativa pelo tamanho da palavra | 0,118 s | 0,230 s | 0,952 s |
| whisper, áudio limpo | 0,048 s | 0,090 s | 0,303 s |
| whisper, com ruído de fundo forte | 0,050 s | 0,102 s | 0,316 s |

A voz de gabarito fala num ritmo uniforme, o caso mais favorável à estimativa; em fala real, com pausa no meio da frase, a diferença tende a ser maior.

**Mas o texto não vem do whisper.** Nos clipes dublados, ele errou o que a legenda do YouTube acerta: "Lengoku", "Chugue as lágrimas", "Está-me superestido", "rio Harabara" no lugar de Yhwach. Então o texto continua o da transcrição (ou do `.srt`, ou da IA), e do whisper vem só o relógio: as duas sequências são **alinhadas** palavra a palavra (em japonês e chinês, letra a letra). Palavra que bate herda o tempo ouvido; palavra trocada ("Ele" no texto, "Leng" no ouvido) herda o tempo da ouvida no mesmo lugar; palavra que o whisper não ouviu fica colada na vizinha com duração natural. Três versões do alinhamento foram medidas nos clipes reais até acertar: a primeira espalhava a palavra não ouvida pelo silêncio ("Mamãe" foi parar 8 s antes de ser dita), a segunda deixava uma palavra trocada atravessar um silêncio de 3 s ("superestimando" com 4,3 s). Nos clipes do Rengoku, do Aizen e do Ichigo (japonês), 86%, 92% e 82% das palavras acharam par; abaixo de 40%, o texto e o áudio não falam a mesma coisa e o tempo estimado fica. A tela diz a porcentagem depois de montar.

Nas três telas há a caixa "Sincronizar a legenda pelo áudio", ligada por padrão. Custa tempo, não dinheiro: ~metade da duração do trecho (43 s de fala em 15 a 24 s, num processador de 12 núcleos). O resultado fica guardado por clipe: montar de novo não ouve de novo.

**2. Vídeo com a legenda desativada no YouTube.** Um botão transcreve o vídeo inteiro no computador e a análise segue normalmente. Medido num vídeo real: 4,4 min de áudio baixados em 4 s, o primeiro minuto reconhecido em 23 s — o vídeo inteiro em ~1,7 min. O tempo de cada palavra fica guardado junto, e a legenda dos cortes nem precisa ouvir de novo.

**3. Fonte de legenda no editor local**, grátis, ao lado do `.srt` e da transcrição pela IA — que também podem ser sincronizados pelo áudio. O idioma detectado pelo whisper decide se precisa traduzir.

Japonês e chinês não separam palavras com espaço: a legenda japonesa inteira de um pedaço era uma "palavra" só, com 13 s. Agora cada oração (até 、。！？) é uma unidade, e a pontuação de largura cheia fecha frase.

**Com chave, a IA repontua e reparte melhor** — e devolve, para cada bloco, o índice da primeira e da última palavra que ele cobre. A marcação de tempo continua sendo a do áudio, não um palpite do modelo. Se os índices não cobrirem todas as palavras, em ordem e sem repetir, a revisão inteira é recusada e vale a divisão mecânica: índice errado deslocaria a legenda do vídeo todo. O prompt proíbe resumir ou trocar palavras por sinônimos — é a fala da pessoa — e a transcrição entra sem `<` nem `>`, para não conseguir fechar o delimitador.

**Sobre a definição da imagem.** Na tela cheia, um vídeo 16:9 perde 68% da largura e o terço central é esticado **1,78x** para virar 1080x1920 — é matemática do enquadramento, não ajuste de codec, e foi o que deixou a primeira versão mole. O que dá para fazer, e foi feito: pedir a maior resolução de origem possível (a 1440p a ampliação cai para 1,33x; a 4K vira redução), ampliar com **lanczos** em vez do bicúbico padrão, devolver contorno com **unsharp** — aplicado só quando há ampliação, senão criaria artefato — e cortar a perda de geração, gravando o corte em CRF 16 e a peça final em CRF 18 no preset `medium`. Num clipe de 6 s isso custou 3 s a mais de processamento.

**Nada de importante depois de y=1500.** O Instagram e o TikTok desenham a conta, a legenda do post e os botões por cima do último quinto do vídeo. A legenda termina em 1500 e a barra de progresso fica logo abaixo, recuada na margem dos cartões — atravessando a tela inteira, ela lia como uma borda.

**O arquivo sai com o nome do vídeo**, não com o id do YouTube: `como_a_rede_neural_enxerga_um_numero_corte1_20260920_143022.mp4` em vez de `reels_aircAruvnKk_1_pt_20260920_143022.mp4`. O nome vem do título da postagem — que, sem chave, é o próprio título do vídeo analisado. O número do corte separa os três do mesmo vídeo, o carimbo de tempo evita sobrescrever uma montagem anterior, e o idioma só entra quando há mais de um. O `.srt` acompanha com o mesmo nome.

**Publicação**: um campo diz qual conta mencionar, e a IA escreve título, descrição, hashtags e a frase do cartão final a partir do resumo do vídeo e da fala do trecho escolhido — a chamada para seguir sai ligada ao assunto, não é uma frase pronta. Sem chave, o título é o do vídeo, a descrição é o começo do resumo, e o convite fica no modelo mais simples ("Siga @conta para mais"); hashtag nenhuma é inventada.

**Vários idiomas**: cada idioma escolhido gera um vídeo próprio, com título, chamada final e legendas traduzidos numa única chamada ao modelo, mais um `.srt`. Por que um vídeo por idioma, e não uma faixa de legenda que o espectador troca: **Instagram e TikTok descartam faixas de legenda embutidas** — lá, legenda tem que estar queimada na imagem, e variar por região significa publicar um vídeo por idioma. YouTube e Facebook aceitam o `.srt` e escolhem sozinhos pelo idioma de quem assiste. Só idiomas de escrita latina (pt, en, es, fr, de, it): as fontes empacotadas não desenham japonês, chinês, coreano, árabe nem hebraico — sairia um retângulo vazio por caractere. Tradução com quantidade diferente de textos é recusada inteira, e o vídeo sai no original com aviso: meio traduzido deslocaria a legenda do vídeo todo.

Os cartões de abertura e de fechamento são opcionais e **vêm desligados**: cada um custa uma renderização quadro a quadro, locução e uma junção a mais, e no uso real não se pagaram. Sem nenhum dos dois, o clipe tratado já é o vídeo final — nem passa pela junção. Sem texto de botão, o cartão final fica só com a frase, em vez de repeti-la dentro de um botão. Todos os textos são editáveis antes de gerar.

**Roteiro em modo degradado não entra no vídeo.** Sem chave (ou se a IA falhar só nessa etapa), `gerar_roteiro_viral` devolve o roteiro-modelo fixo da TACTO Studio. Na aba ele aparece como texto, com aviso ao lado dizendo que não é sobre o vídeo analisado; no vídeo, seria propaganda de outra empresa queimada em cima do conteúdo de quem publica — aconteceu em uso real. O cartão de abertura, que é o único que o usaria, começa com o título do corte e o resto em branco.

Como foi feito: o que não muda a cada quadro é desenhado **uma vez** com o Pillow e entra no ffmpeg como PNG transparente (a legenda, como uma faixa de PNGs com tempo — veja Direção de arte). Desenhar quadro a quadro custaria ~9 MB de RGBA por quadro no cano, para o mesmo resultado. O desfoque do fundo é feito em 1/4 do tamanho e depois ampliado — mesmo borrão, e o clipe de 15 s caiu de 23 s para 5 s de processamento. As partes saem do mesmo encoder, então a junção é cópia direta, sem recompressão (com recodificação como reserva, se algum parâmetro divergir).

Verificado: 128 testes automáticos (montagens de ponta a ponta com ffmpeg de verdade, clipe mudo, os dois enquadramentos, o `.srt`, a recusa do roteiro degradado e cada caminho da tradução) e montagens reais — corte de 45 s em 1080p do YouTube, 13 blocos de legenda vindos da transcrição real, locução neural no cartão final, e a mesma peça saindo em inglês com os textos trocados.

### Aba "Edição": vários trechos numa peça só

O fatiador pega um pedaço contínuo e torce para o assunto caber ali. A edição faz o que um editor faz: a IA lê o vídeo inteiro e escolhe de 2 a 6 trechos de **lugares diferentes** — o gancho de um ponto, o exemplo de outro, o fecho de um terceiro — e eles são emendados sem o caminho entre eles ([edicao.py](edicao.py), [ui_edicao.py](ui_edicao.py)).

O prompt pede o que define se a peça funciona: os trechos juntos precisam contar **uma ideia do começo ao fim**, sem depender de nada que ficou de fora — nada de um "como eu disse" apontando para o que não entrou. Você pode dar um ângulo ("só a parte prática, sem a introdução teórica") e a duração alvo.

**O plano vem para revisar, não para executar.** A tela mostra cada trecho com a fala que está nele, os tempos editáveis e uma caixa para descartar. Montar é um segundo clique — a decisão de qual pedaço entra é a que decide a peça, e ela é sua.

Depois de escolhidos, os trechos passam pelo mesmo encaixe em fronteiras de frase do fatiador, com uma diferença: cada um estica no máximo meia vez a mais do que foi pedido. Num corte único, esticar 15 s para fechar a frase é barato; numa edição de quatro trechos, isso dobraria a peça inteira — foi o que aconteceu na primeira medição (45 s pedidos viraram 72 s). Trechos que se encostam depois do encaixe viram um só, porque senão repetiriam a mesma fala.

Cada trecho é reenquadrado e legendado por conta própria, e o `.srt` final soma os deslocamentos: a legenda do terceiro trecho conta o tempo dos dois primeiros.

**Sem chave, os trechos saem da minutagem**, espalhados pela duração, e a tela diz isso: não há leitura de conteúdo, e fingir que houve seria pior. O valor real desta aba depende da chave.

Entre os trechos, corte seco (o padrão) ou uma transição animada — veja Direção de arte. O que ela **não** faz: música, efeito sonoro e corte de silêncio dentro da fala. Cada um é um problema próprio, e nenhum deles muda o resultado tanto quanto escolher bem os trechos.

Verificado com vídeo real: 3 trechos (4s, 519s e 1071s do mesmo vídeo) viraram uma peça de 51 s em 22 s de montagem, com a legenda atravessando as emendas na marcação certa.

### Marca d'água do vídeo de origem

O app **não adiciona marca nenhuma**: a marca do cabeçalho é opcional e vem desligada. O que existe é a marca que já vem queimada no vídeo de origem, e o padrão agora é **procurar e, se houver, apagar** ([marca_dagua.py](marca_dagua.py)). O resultado aparece na tela depois de montar: onde apagou, ou que não achou nada.

**Como acha.** O contorno da marca é o mesmo em todo quadro; o do conteúdo, não. São amostrados 40 quadros espalhados pelo clipe, e em cada um se calcula a diferença entre pixels vizinhos, com sinal. Tirando a mediana no tempo, o que muda some e a borda fixa sobrevive (o método é de Dekel e outros, CVPR 2017). Das manchas que sobram, fica a de mais força entre as que têm cara de marca: nem linha comprida (borda de tarja), nem enorme, nem no meio da tela, e com desenho dentro. Peças vizinhas — ícone, texto, separador — viram uma caixa só.

**A primeira versão errou no primeiro vídeo real**, e o motivo mudou o método. Ela procurava pixels *parados*; a marca "YOUTUBE | BLEACH BRASILEIRO" era semitransparente, o fundo mudando por baixo a fazia variar tanto quanto o resto, e ela estava recuada do canto — onde a caixa por canto também não chegava. A mediana do gradiente não depende de o pixel ficar parado, só de a borda ficar no lugar.

**Medido em 17 clipes reais de 5 vídeos:** a marca foi achada nos 6 clipes que a tinham, com a mesma caixa em todos, e nos 11 sem marca nada foi acusado. A caixa passou por dois acertos medidos: num clipe curto e parado, um contorno do conteúdo encostou na marca e a caixa dobrou de altura (as pontas fracas e compridas agora são aparadas); aparando demais, o traço vertical da marca, que passa alguns pixels das letras, ficou na borda e o `delogo` o esticou por cima de tudo (ponta curta agora fica). A busca leva 2 a 4 s por clipe.

**Limites.** É uma amostra pequena, de um tipo de conteúdo (anime). Num fundo sintético mais "ruidoso" que vídeo real, o método já dá alarme falso — está registrado nos testes. Vídeo parado demais (a mesma imagem o tempo todo) não tem como separar marca de conteúdo, e a busca desiste em vez de chutar. Marca que muda de lugar no meio do vídeo (a do TikTok faz isso) não foi testada. E o `delogo` **não reconstrói** o que estava embaixo: em fundo liso a marca some, em fundo detalhado fica um borrão.

Por isso a tela tem **prévia de um quadro**: mostra o quadro original com a caixa em vermelho e o quadro final ao lado, em segundos. Se a caixa errar, "Eu marco onde está" abre quatro controles já posicionados onde a busca achou.

### Direção de arte ([efeitos.py](efeitos.py))

Nas três telas de montagem (vídeo pronto, Edição e editor local):

- **Filtro de cor**: vívido, neon, cinema (sombra azul, luz laranja), quente, frio, dramático, vintage, preto e branco. Escolhidos olhando uma folha de contato com o mesmo quadro em cada um, em dois vídeos reais; nenhum vem ligado.
- **Zoom de ênfase**: a imagem aproxima numa troca de frase e volta na seguinte (sutil 8%, forte 18%). Sem legenda, alterna a cada 3 s. A versão ampliada é posta por cima só na janela — a legenda e a moldura não aproximam junto.
- **Vinheta** (bordas escurecidas).
- **Estilo da legenda**: clássica (a frase inteira), palavra em destaque (karaokê, na cor do tema) e impacto (até 3 palavras, grandes, em caixa alta, trocando no ritmo da fala).
- **Transição entre trechos** (só na Edição): esmaecer, flash branco, piscar no preto, deslizar, zoom, círculo, desfoque — o `xfade` do ffmpeg, com o som cruzado junto. A legenda e o `.srt` descontam o tempo que cada passagem sobrepõe.

**O custo foi medido, e mudou o desenho.** Em 12 s de um clipe 1080p a 50 quadros/s (só o vídeo, sem nada, levava 3,7 s): granulação de filme somava 33 a 41 s — triplicava a montagem, e ficou de fora; o filtro "cinema" com `colorbalance` somava 11 s; a vinheta do ffmpeg, 5 s. Três mudanças: o vídeo cai para a taxa da saída (24 quadros/s) logo no começo, em vez de todo filtro processar 50 quadros para a saída jogar metade fora; a cor é aplicada **depois** de reduzir o vídeo (frente em 1080x607, fundo em 270x480) e com curvas por canal, que são uma tabela e não uma conta por pixel; a vinheta virou um PNG desenhado uma vez. Com **tudo ligado** — marca apagada, cinema, vinheta, zoom e karaokê — os mesmos 12 s levam 6,3 s. O clipe de 50 s inteiro foi de 90 s para 40 s, com a busca da marca incluída.

**A legenda virou uma faixa.** Cada estado da legenda (um bloco, ou o bloco com a palavra N em destaque) é um PNG, e uma lista do demuxer `concat` diz quanto tempo cada um fica na tela. Para o ffmpeg é um vídeo só, com um overlay só. Antes, cada bloco era uma entrada e um overlay próprios — serve para 15 blocos, mas o karaokê tem um estado por palavra (uns 150 num minuto).

### Receitas por situação de anime ([efeitos.py](efeitos.py), [momentos.py](momentos.py))

A primeira linha da direção de arte é a **receita**: luta, aura/entrada de personagem, emoção/despedida, comédia/reação e diálogo — ou "personalizada", que abre os controles um a um. Cada receita junta o que um editor faria naquele tipo de cena:

| Receita | O que faz |
|---|---|
| Luta | quadro invertido no golpe, flash branco, tremida com separação RGB e aproximação; o golpe mais forte em câmera lenta; legenda de impacto; transição com flash |
| Aura | imagem escura puxada para o vermelho, halo nas luzes, faixa de cinema, vinheta; poucos golpes com quadro vermelho; câmera lenta no mais forte |
| Emoção | cor fria e lavada, halo suave, faixa de cinema, vinheta; nenhum golpe, tremida ou zoom; legenda clássica; transição esmaecendo |
| Comédia | aproximação forte e rápida nos picos de som (a reação), tremida leve, cor saturada |
| Diálogo | cor viva, zoom sutil a cada frase, palavra dita em destaque |

**Referências** (pesquisadas em setembro de 2026): guias de ritmo de vídeo curto — troca a cada 1,5–3 s no TikTok e 2,5–4 s no Reels, gancho nos 3 primeiros segundos ([Shortzly](https://shortzly.com/blog/short-form-video-pacing-editing-guide)); ritmo de cena de ação contra cena de emoção — cortes rápidos para tensão, planos longos para peso ([Inside the Edit](https://www.insidetheedit.com/blog/pacing-in-video-editing)); os efeitos das edições de anime no CapCut — velocity, flash, shake, reverse ([CapCut](https://www.capcut.com/explore/velocity-x-flash-x-shake-x-reverse)), separação RGB e borrão de movimento em luta ([Toolify, tutorial de edição de anime no CapCut](https://www.toolify.ai/ai-news/capcut-tutorial-creating-stunning-animestyle-video-edits-3634198)); a câmera lenta presa ao golpe, e não a um tempo qualquer ([Northwest Media Systems](https://northwestmediasystems.com/blog/speed-ramping-time-remapping-corporate-video/)); e o "impact frame" — o quadro monocromático ou invertido de uma fração de segundo que o próprio anime usa no auge do golpe ([Sakugabooru](https://blog.sakugabooru.com/glossary/impact-frames/)). Os números das receitas (golpes por minuto, amplitude da tremida, 2 quadros de impacto, meia velocidade) foram acertados olhando o resultado nos clipes reais, não tirados das referências.

**Os efeitos caem nos golpes, não num relógio.** [momentos.py](momentos.py) mede, sem IA, onde o som estoura (subida de 8 dB em 100 ms até -20 dBFS) e onde o plano troca (diferença grande entre quadros seguidos); golpe que coincide com troca de plano pesa mais. A primeira versão comparava o volume com a mediana do próprio clipe, e a despedida do Rengoku — quase sussurrada — deu 50 "golpes" por minuto: cada começo de fala contava. Com o limite absoluto, zero. Funciona porque o YouTube normaliza o volume dos vídeos.

**Medido em 14 clipes reais de 5 vídeos:** as lutas tiveram 36 a 59 trocas de plano por minuto (menos um trecho mais lento, com 13); o monólogo do Aizen, 16 a 30; a despedida do Rengoku, 24, e volume bem mais baixo. A prévia usa isso para **sugerir** uma receita — lutas viram "Luta" (5 de 6), a despedida vira "Emoção", o Aizen vira "Diálogo, experimente Aura". É palpite de 14 clipes, e a tela diz que é palpite.

**Câmera lenta**: pouco mais de 1 s em volta do golpe mais forte, em meia velocidade; o som estica junto com `atempo`, que não engrossa a voz. Tudo que tem tempo — legenda, palavras, golpes, janelas de zoom, o `.srt` — é remapeado para a nova linha do tempo, e o vídeo fica 1,2 s mais longo. Anime é animado a 8–12 desenhos por segundo, então a meia velocidade repete quadros; interpolar (`minterpolate`) seria muito mais lento.

**Três defeitos achados olhando os quadros, e corrigidos**: o brilho somado em RGB deixava uma coluna roxa de 8 px na borda direita quando havia filtro de cor antes (a soma agora é só na luminância); a separação RGB aplicada no quadro final deixava um fio azul na borda (agora ela é feita na imagem ampliada, antes do recorte, e a borda fica fora); e a prévia quebrava com câmera lenta ligada, porque o som esticado ficava sem saída (a prévia não tem som).

**Custo**: com a receita de luta, 25 s de um clipe 1440p montam em ~25 s; aura em ~32 s para 40 s; emoção ~30 s para 43 s — a análise de golpes (2 a 7 s por clipe) incluída.

O que ficou de fora: **zoom lento contínuo** — o `zoompan` do ffmpeg treme (arredonda a posição para o pixel inteiro a cada quadro) e o `scale` com expressão por quadro desliza para um lado (o `crop` seguinte calcula o centro uma vez só); os dois foram testados. Também granulação (custo), tremida, velocidade variável e música.

### Editor de vídeo local e outras redes ([ui_local.py](ui_local.py), [fonte_local.py](fonte_local.py))

Um quarto modo, que não passa pela análise: **arquivo do computador** (mp4, mov, mkv, webm, m4v, avi, até 2 GB — o limite do Streamlit foi aumentado em `.streamlit/config.toml`) ou **link de outra rede**. Mesmo compositor, mesma direção de arte, mesma busca de marca d'água e mesma prévia. Do link, só o trecho escolhido é baixado; do arquivo, ele é recortado no ponto exato. Os arquivos ficam em `videos_locais/`, fora do git, com um pedaço do hash no nome (enviar o mesmo vídeo de novo não duplica).

**Quais redes abrem**, testado em 21/09/2026 só lendo título e duração, com vídeos públicos que o próprio yt-dlp usa nos testes dele (versão 2026.08.19, 1.751 extratores): **abriram** Dailymotion, Reddit, clipes da Twitch e vídeo público do Facebook; **pediram login** Vimeo e Instagram; o **TikTok** respondeu "seu IP está bloqueado para este post" nos 2 posts testados, desta conexão. O yt-dlp consegue usar os cookies do navegador para os que pedem login, mas isso entrega a sessão da sua conta a um programa — não está ligado de propósito. Para esses, o caminho é baixar pelo app da rede e enviar como arquivo. Download de verdade só foi testado com o YouTube.

**A legenda é desligada por padrão aqui** (vídeo de outra rede quase sempre já chega legendado) e tem duas fontes: um **`.srt`** (os tempos do vídeo inteiro são cortados no trecho; aceita BOM, CRLF, ponto ou vírgula nos milissegundos e tira `<i>` e `{\an8}`) ou a **transcrição do áudio pela IA** — o áudio do trecho vai em mono e taxa baixa (1 minuto ≈ 360 KB) e volta em pedaços com início e fim. Tempo fora do clipe é descartado, não consertado. **Não verificado com chave de verdade**: o tempo de cada pedaço é o que o modelo diz ter ouvido; se a legenda sair adiantada ou atrasada, o próximo passo é um reconhecedor de fala local com tempo por palavra (faster-whisper), preciso e gratuito, mas com ~500 MB de modelo.

**A legenda é uma escolha visível nas três telas, com o custo escrito nela:**

| A fala é em... | Opções |
|---|---|
| português | revisada pela IA (1 chamada) · como está, sem IA (custo zero) · não gerar |
| outro idioma | traduzida para português (1 chamada) · no idioma da fala, sem IA (se a fonte desenhar a escrita) · não gerar |

"Como está" usa o texto do YouTube sem mexer — sem chave, é o padrão. Para traduzir, a legenda **não** passa pela revisão antes: a tradução já sai pontuada, e revisar seria pagar duas vezes. "Não gerar" é para o vídeo que já traz legenda queimada na imagem: nada é desenhado por cima, e a **faixa de cinema é desligada**, porque o recorte para 2,39:1 tira justamente a parte de baixo, onde essa legenda fica.

Havia um erro que impedia isso: a tradução pulava tudo quando o destino era português, porque supunha que a fala já era português. O clipe do Ichigo, com a transcrição em japonês, sairia com a legenda em japonês — e a fonte do vídeo não desenha japonês: seria uma fileira de quadradinhos. Agora o idioma da fala é guardado na análise, a opção "no idioma da fala" some quando a escrita não tem fonte, e, se a tradução falhar, a legenda sai de fora com aviso em vez de sair em quadradinhos. No mesmo levantamento apareceu outro caso: a legenda automática do YouTube da luta do Rengoku, em português, trazia um pedaço de lixo em coreano ("가사주"), que também virava quadradinho; caracteres sem fonte agora são limpos antes de desenhar.

No editor local não há sigla de idioma (a fala vem de um `.srt` ou da transcrição): um palpite por palavras que só o português usa evita traduzir português para português. Reconheceu os 16 `.srt` em português que existiam aqui e recusou inglês, espanhol, francês, alemão e italiano de teste. Também no editor local, nem o `.srt` nem a transcrição passam pela revisão: o primeiro já é legenda pronta, a segunda já vem pontuada.

**Vídeo com a legenda desativada no YouTube.** A análise (resumo, cortes, roteiro) lê o texto da fala; sem legenda, não tem o que ler. Antes o erro saía em inglês, com o texto cru da biblioteca. Agora cada caso tem mensagem própria — legenda desativada, vídeo indisponível, restrição de idade, YouTube recusando pedidos em sequência — e, quando é falta de legenda, dois caminhos: transcrever o vídeo no computador e analisar normalmente, ou levar o link para o editor, que funciona sem a análise.

### Quanto custa cada coisa

Preços do Gemini 3.6 Flash no nível pago, conferidos em 21/09/2026 na [tabela oficial](https://ai.google.dev/gemini-api/docs/pricing): US$ 0,75 por milhão de tokens de entrada e US$ 3,75 por milhão de saída — **os dois dobram em 01/01/2027**. Áudio entra pelo mesmo preço do texto e conta [32 tokens por segundo](https://ai.google.dev/gemini-api/docs/audio). O "pensamento" do modelo é cobrado como saída e não dá para prever; as faixas abaixo supõem de 300 a 1.500 tokens de pensamento por chamada. Tamanhos medidos num trecho real de 50 s (74 palavras), com tokens estimados em ~4 caracteres cada.

| O quê | Chamadas | Custo aproximado |
|---|---|---|
| Baixar, cortar, marca d'água, receitas, efeitos, prévia, montar, locução dos cartões | 0 | zero (roda no computador; a voz é o edge-tts, gratuito) |
| Legenda "como está", `.srt`, "não gerar" | 0 | zero |
| Revisar a legenda de um trecho de 50 s | 1 | US$ 0,003 a 0,007 |
| Traduzir a legenda de um trecho de 50 s | 1 | US$ 0,002 a 0,006 |
| Reconhecer a fala no computador (sincronizar, editor local, vídeo sem legenda) | 0 | zero — custa tempo: ~metade da duração do áudio |
| Transcrever o áudio de um trecho de 50 s pela IA (editor local) | 1 | US$ 0,003 a 0,008 |
| "Escrever com IA" (título, descrição, hashtags) | 1 | US$ 0,002 a 0,007 |
| Planejar a Edição (vídeo de ~10 min) | 1 | US$ 0,004 a 0,009 |
| Analisar um vídeo de até ~15 min (resumo, quiz, cortes, roteiro) | ~5 | medido na sua conta: US$ 0,0323 |

A barra lateral do app mostra o gasto real da sessão (tokens de entrada, saída e pensamento). Repetir o mesmo pedido de texto não gasta de novo (cache); a transcrição de áudio não entra no cache, mas fica guardada na sessão para a prévia e a montagem do mesmo trecho não pagarem duas vezes.



## Direitos autorais

O fatiador baixa trechos de vídeos de terceiros para reutilizá-los. Use com conteúdo seu ou licenciado.

## Limitações conhecidas

O reconhecimento local (modelo `small`) erra nomes próprios e palavras incomuns — por isso ele só dá o tempo quando existe outro texto; no vídeo sem legenda nenhuma, o texto é o dele. A transcrição pela IA não foi verificada com chave. Legenda automática vem sem pontuação e não é limpa antes de resumir. Nos cartões, a legenda é o texto da cena em blocos, não sincronizada palavra a palavra. Sem a sincronia pelo áudio (desligada, ou o texto e o áudio não batem), o tempo de cada palavra é **estimado** pelo tamanho dela — e o destaque palavra a palavra pode andar alguns décimos fora da voz. O corte para preencher a tela é sempre central (não segue quem está falando). A tradução é do texto de tela e da legenda, não do áudio: a fala do clipe continua no idioma original (o cartão final, esse sim, é narrado por uma voz do idioma escolhido). As hashtags são as mesmas em todos os idiomas. O renderizador oficial da TACTO tem 4 cenas fixas (não é orientado a dados).
