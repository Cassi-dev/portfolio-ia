import sys
import subprocess

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado
from esquemas_video import RoteiroViral
from transcricao_youtube import texto_para_prompt

MAX_CHARS_ROTEIRO = 60_000

TEMAS_TACTO = {
    "1. CAC Zero vs iFood (Como Bares Perdem 25% de Margem)": {
        "titulo_sugerido": "O ralo invisível de 25% no seu restaurante",
        "hook": "Se você é dono de bar ou restaurante, você está pagando o equivalente a um sócio oculto todo mês sem perceber!",
        "dor": "Entregar 25% a 27% de cada pedido para marketplaces como o iFood em cima de clientes que JÁ são seus frequentadores é queimar margem de lucro líquido.",
        "valor": "Com a TACTO Studio, nós criamos infraestrutura digital de CAC Zero. Seu cliente abre o cardápio em 0.3 segundos, pede direto pelo WhatsApp ou PWA próprio e a margem de lucro fica 100% no seu caixa.",
        "cta": "Pare de queimar sua margem com intermediários. Clica no link da bio da TACTO Studio e conheça a nossa esteira de conversão direta!",
        "legenda": "Você já calculou quanto deixa na mesa todo mês em comissões de marketplaces? 📉\n\nA sua calçada e os seus clientes fiéis não deveriam custar 25% a cada pedido.\n\nNa TACTO Studio, desenhamos infraestrutura digital de CAC Zero: velocidade extrema, experiência sensorial e pedidos direto no seu canal oficial.\n\n👉 Clica no link da bio e fale com a nossa equipe.",
        "hashtags": "#tactostudio #gastronomia #restaurantes #bares #gestaofinanceira #caczero #foodservice"
    },
    "2. O Fim dos Apps Pesados (A Revolução do PWA em 0.3s)": {
        "titulo_sugerido": "Ninguém mais baixa aplicativo na App Store!",
        "hook": "Pare de gastar 50 mil reais tentando criar um aplicativo que nenhum cliente seu vai querer baixar!",
        "dor": "O cliente está na calçada ou no sofá e não tem espaço na memória do celular nem paciência para esperar o download na loja de apps só para ver um cardápio ou treinar.",
        "valor": "A solução da TACTO é o PWA de velocidade extrema: abre em menos de 0.5s no 4G, tem vídeos em loop contínuo e o cliente adiciona na tela inicial com apenas 1 toque, sem precisar de loja de aplicativos.",
        "cta": "Quer levar essa tecnologia para a sua marca? Acesse o link da bio da TACTO Studio!",
        "legenda": "A era dos aplicativos pesados e caros ficou para trás. ⚡\n\nHoje, quem converte mais é quem carrega mais rápido. Nossos Web Apps PWA entregam estética de alto padrão em menos de 0.5s no 4G móvel.\n\nPronto para transformar sua presença digital? Link na bio.",
        "hashtags": "#tactostudio #pwa #tecnologia #designsensorial #webperformance #negocioslocais"
    },
    "3. Cardápio em PDF de 15MB vs Carta Sensorial de Alta Conversão": {
        "titulo_sugerido": "O erro grotesco do cardápio em PDF",
        "hook": "Se o seu cliente senta na mesa e você manda ele baixar um PDF de 15MB, você acabou de destruir a experiência da sua casa!",
        "dor": "O 4G oscila, o PDF trava, a letra fica minúscula e o cliente desiste de pedir drinks autorais ou sobremesas mais caras.",
        "valor": "A TACTO cria cartas sensoriais imersivas com fotos em alta definição, histórias dos coquetéis e um painel no celular do gerente para alterar preços e pausar bebidas em tempo real no Firestore.",
        "cta": "Diga adeus ao amadorismo do PDF. Fale com a TACTO Studio pelo link na bio!",
        "legenda": "Cardápio em PDF quebra o encanto de qualquer bar ou restaurante autoral. 🍸\n\nExperiência gastronômica exige desejo, estética e velocidade. Criamos cartas digitais que despertam apetite imediato e facilitam a operação da sua equipe.\n\nConheça nossos cases no link da bio.",
        "hashtags": "#tactostudio #coquetelaria #baresautorais #altagastronomia #cardapiodigital #experienciadocliente"
    }
}

def gerar_roteiro_tacto_personalizado(tema_escolhido, client=None):
    """Gera um roteiro viral pronto sob medida para o posicionamento da TACTO Studio."""
    info = TEMAS_TACTO.get(tema_escolhido, list(TEMAS_TACTO.values())[0])
    
    cenas = [
        {
            "tempo": "0s a 3s",
            "bloco": "O Gancho Magnético (Hook)",
            "fala": info["hook"],
            "direcao_visual": "Corte rápido em close + texto em destaque neon 'CUIDADO COM ISSO!'"
        },
        {
            "tempo": "3s a 15s",
            "bloco": "A Agitação da Dor",
            "fala": info["dor"],
            "direcao_visual": "Corte dinâmico de ângulo + ícone de dinheiro voando / celular travado"
        },
        {
            "tempo": "15s a 45s",
            "bloco": "A Solução TACTO Studio",
            "fala": info["valor"],
            "direcao_visual": "Tela dividida mostrando o PWA da TACTO carregando instantaneamente em 0.3s"
        },
        {
            "tempo": "45s a 60s",
            "bloco": "Chamada para Ação (CTA)",
            "fala": info["cta"],
            "direcao_visual": "Aponta para o link da bio + logo oficial da TACTO Studio brilhando"
        }
    ]
    
    return {
        "titulos_capa": [
            info["titulo_sugerido"],
            "Como donos de negócios estão virando o jogo",
            "A estratégia de CAC Zero da TACTO Studio"
        ],
        "cenas": cenas,
        "legenda_instagram": info["legenda"],
        "hashtags": info["hashtags"]
    }

def gerar_roteiro_viral(dados_transcricao, client=None):
    blocos = dados_transcricao["blocos"]

    if client:
        texto, _ = texto_para_prompt(blocos, MAX_CHARS_ROTEIRO, lambda b: b["texto"])
        prompt = (
            "Você é o maior especialista em Copywriting e Roteiros Virais para Instagram Reels, TikTok e YouTube Shorts.\n"
            "Com base no conteúdo deste vídeo, crie um ROTEIRO COMPLETO DE 45 A 60 SEGUNDOS focado em altíssima retenção "
            "e engajamento, com estas cenas: Gancho (0s a 3s), Dor (3s a 15s), Valor (15s a 45s) e CTA (45s a 60s).\n\n"
            f"CONTEÚDO:\n{texto}"
        )
        try:
            roteiro = gerar_estruturado(client, prompt, RoteiroViral).model_dump()
            roteiro["degradado"] = False
            roteiro["motivo_degradado"] = None
            return roteiro
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)
    else:
        motivo = MOTIVO_SEM_CHAVE

    roteiro = gerar_roteiro_tacto_personalizado(list(TEMAS_TACTO.keys())[0])
    roteiro["degradado"] = True
    roteiro["motivo_degradado"] = f"{motivo}. Exibindo o roteiro-modelo da TACTO Studio, que NÃO é baseado no vídeo analisado"
    return roteiro

def sintetizar_audio_narracao(texto, arquivo_saida, voz="pt-BR-AntonioNeural"):
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--text", texto,
        "--voice", voz,
        "--write-media", arquivo_saida
    ]
    subprocess.run(cmd, check=True)
    return arquivo_saida
