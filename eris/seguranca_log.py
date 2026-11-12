"""Mascara credenciais antes de qualquer texto chegar ao console ou log."""
import os
import re


VARIAVEIS_SEGREDO = (
    "DISCORD_BOT_TOKEN",
    "GROQ_API_KEY_LLM",
    "GROQ_API_KEY_LLM_EXTRAS",
)
PADROES_FORMATO = (
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    # Token de bot do Discord: ID em base64 (24 a 28 caracteres, cresce com o
    # ID), carimbo de 6 e HMAC de 27 (formato antigo) a 38 (atual). O padrão
    # de antes só aceitava 24.6.27 e mascarava os tokens novos pela metade.
    re.compile(r"[A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}"),
)
MASCARA = "[SEGREDO REMOVIDO]"
_TAMANHO_MINIMO_VALOR = 8


def _valores_configurados():
    valores = []
    for nome in VARIAVEIS_SEGREDO:
        bruto = os.environ.get(nome, "")
        valores.extend(valor.strip() for valor in bruto.split(",") if valor.strip())
    return valores


def limpar_segredos(texto):
    if not texto:
        return texto
    for valor in _valores_configurados():
        if len(valor) >= _TAMANHO_MINIMO_VALOR:
            texto = texto.replace(valor, MASCARA)
    for padrao in PADROES_FORMATO:
        texto = padrao.sub(MASCARA, texto)
    return texto
