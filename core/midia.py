import shutil


def localizar_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        caminho = shutil.which("ffmpeg")
        if caminho:
            return caminho
        raise RuntimeError("ffmpeg não encontrado: instale `imageio-ffmpeg` ou coloque o ffmpeg no PATH.")
