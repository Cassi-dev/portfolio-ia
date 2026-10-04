import os
import sys
import subprocess
import yt_dlp

from core.midia import localizar_ffmpeg

ffmpeg_exe = localizar_ffmpeg()

def extrair_frames_storyboard(url_video, cenas, pasta_destino, video_id="video"):
    """
    Tira um snapshot em alta definição (JPG) de cada cena do roteiro
    direto da transmissão do vídeo, sem precisar baixar o arquivo inteiro.
    Custo: R$ 0,00!
    """
    os.makedirs(pasta_destino, exist_ok=True)
    
    # 1. Obtém a URL direta de transmissão em resolução média/boa (360p/480p)
    ydl_opts = {
        'format': '18/best',
        'extractor_args': {'youtube': {'player_client': ['android']}},
        'quiet': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url_video, download=False)
        stream_url = info['url']
        
    frames_gerados = []
    
    # Mapeamento aproximado de segundos para cada cena
    segundos_cenas = [5, 12, 30, 50]
    
    for i, cena in enumerate(cenas):
        seg = segundos_cenas[i] if i < len(segundos_cenas) else (i * 15)
        arquivo_frame = os.path.join(pasta_destino, f"frame_{video_id}_cena_{i+1}.jpg")
        
        cmd = [
            ffmpeg_exe,
            '-y',
            '-ss', str(seg),
            '-i', stream_url,
            '-vframes', '1',
            '-q:v', '2',
            arquivo_frame
        ]
        
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(arquivo_frame):
                cena["frame_path"] = arquivo_frame
                frames_gerados.append(arquivo_frame)
        except Exception as e:
            print(f"Erro ao extrair frame {i+1}: {e}")
            
    return cenas
