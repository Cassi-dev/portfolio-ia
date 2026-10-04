"""Schemas Pydantic das respostas do LLM neste projeto (enviados ao Gemini como response_schema)."""
import re

from pydantic import BaseModel, Field, field_validator, model_validator


class Topico(BaseModel):
    timestamp: str = Field(description="Minutagem de início do tópico, no formato MM:SS ou HH:MM:SS")
    titulo: str
    descricao: str = Field(description="Explicação sucinta do tópico em uma ou duas frases")

    @field_validator("timestamp")
    @classmethod
    def _formato_do_tempo(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{1,2}(:\d{2}){1,2}", v):
            raise ValueError("timestamp deve ser MM:SS ou HH:MM:SS")
        return v


class SinteseVideo(BaseModel):
    resumo_executivo: str = Field(description="Dois parágrafos fluidos com o conceito central e a relevância do vídeo")
    topicos_com_minutagem: list[Topico] = Field(min_length=1)
    conclusao: str = Field(description="Uma frase com o maior aprendizado prático do vídeo")


class PerguntaQuiz(BaseModel):
    pergunta: str
    opcoes: list[str] = Field(min_length=4, max_length=4, description="Quatro alternativas: A), B), C) e D)")
    resposta_correta: int = Field(ge=0, le=3, description="Índice (começando em 0) da alternativa correta")
    explicacao: str = Field(description="Justificativa de uma frase")


class Quiz(BaseModel):
    perguntas: list[PerguntaQuiz] = Field(min_length=5, max_length=5)


class CorteViral(BaseModel):
    titulo: str = Field(description="Título chamativo para o Reels")
    inicio_segundos: int = Field(ge=0)
    fim_segundos: int
    motivo_viral: str = Field(description="Por que esse trecho prende a atenção nos primeiros 3 segundos")

    @model_validator(mode="after")
    def _intervalo(self):
        if not 0 < self.fim_segundos - self.inicio_segundos <= 180:
            raise ValueError("o corte deve durar entre 1 e 180 segundos (ideal: 30 a 60)")
        return self


class SugestaoCortes(BaseModel):
    cortes: list[CorteViral] = Field(min_length=1, max_length=5)


class CenaRoteiro(BaseModel):
    tempo: str = Field(description='Faixa de tempo, por exemplo "0s a 3s"')
    bloco: str = Field(description="Gancho, Dor, Valor ou CTA")
    fala: str
    direcao_visual: str


class RoteiroViral(BaseModel):
    titulos_capa: list[str] = Field(min_length=1, max_length=5)
    cenas: list[CenaRoteiro] = Field(min_length=3, max_length=6)
    legenda_instagram: str
    hashtags: str = Field(description="Hashtags separadas por espaço")
