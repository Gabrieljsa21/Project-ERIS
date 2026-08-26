# -*- coding: utf-8 -*-
"""Webhook reverso ERIS -> GAIA - único lugar do ERIS que pede CONTEÚDO pra
alguém (a persona). Mesmo padrão já usado pelo Project-MOIRAI
(`POST /moirai/episodio_assistido`) e Project-HESTIA
(`POST /hestia/sincronizar_lancamento`), só que aqui a direção pede uma
RESPOSTA de volta no corpo (síncrono), não só "aviso e sigo minha vida" - uma
mensagem recebida precisa de resposta dentro de um tempo razoável pra
parecer conversa de verdade.

Se a GAIA não estiver rodando, devolve None (silencioso) - quem chama
(`eris/bot.py`) decide o que fazer (hoje: responder um recado padrão
avisando que a persona está offline, em vez de deixar a pessoa sem
resposta nenhuma - diferente do padrão "silencioso" dos outros satélites,
que fazem sentido pra poll, não pra uma mensagem que já chegou esperando
reply)."""
import base64
import json
import urllib.request

from eris.config import URL_BASE_GAIA

TIMEOUT_SEGUNDOS = 30  # generoso de propósito - a GAIA pode estar processando LLM/ferramenta
# 🔥 Turno de voz (2026-08-25, Intérprete/Tutora/Conversa) - encadeia Whisper +
# LLM (tradução ou persona) + TTS do lado da GAIA, bem mais lento que uma
# mensagem de texto comum. 120s (não 60s) - achado real 2026-08-25: o lado da
# GAIA (`integrations/iris_bridge.py`) espera até 90s pelo próprio turno
# (`future.result(timeout=90)`); com o timeout DAQUI menor que o de LÁ, o ERIS
# desistia (fechando a conexão) ANTES da GAIA terminar de responder sob carga
# pesada (várias contas do Groq esgotadas em sequência, caindo pro fallback
# NVIDIA) - a GAIA gerava a resposta certinho, mas o `ConnectionAbortedError`
# ao tentar escrever a resposta no socket já fechado jogava tudo fora,
# silenciosamente (usuário via "às vezes dá erro e ela não responde").
TIMEOUT_TURNO_VOZ_SEGUNDOS = 120


def _post(caminho, corpo, timeout=TIMEOUT_SEGUNDOS):
    try:
        dados = json.dumps(corpo).encode("utf-8")
        req = urllib.request.Request(f"{URL_BASE_GAIA}{caminho}", data=dados, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            corpo_resposta = resp.read()
            return json.loads(corpo_resposta) if corpo_resposta else {}
    except Exception as e:
        print(f" [ERIS] GAIA não respondeu ({caminho}): {e}")
        return None


def _get(caminho, timeout=TIMEOUT_SEGUNDOS):
    try:
        with urllib.request.urlopen(f"{URL_BASE_GAIA}{caminho}", timeout=timeout) as resp:
            corpo_resposta = resp.read()
            return json.loads(corpo_resposta) if corpo_resposta else {}
    except Exception as e:
        print(f" [ERIS] GAIA não respondeu ({caminho}): {e}")
        return None


def pedir_resposta_persona(texto, eh_dono, remetente_id, remetente_nome, channel_id):
    """Pede a resposta da persona pra uma mensagem recebida (DM ou menção/
    servidor, já filtrada por `eris.core.seguranca.deve_processar_mensagem`).
    Devolve o texto de resposta, ou None se a GAIA não respondeu/está fora do
    ar (quem chama decide a mensagem de fallback)."""
    resultado = _post("/eris/mensagem", {
        "texto": texto, "eh_dono": eh_dono, "remetente_id": str(remetente_id),
        "remetente_nome": remetente_nome, "channel_id": str(channel_id),
    })
    if resultado is None:
        return None
    return resultado.get("resposta")


# --------------------------------------------------------------------------
# Modo Conversa (bate-papo comum por voz numa call do Discord - sem tradução,
# sem prática de idioma, sem sessão prévia nenhuma)
# --------------------------------------------------------------------------

def pedir_turno_conversa(guild_id, speaker_id, speaker_nome, eh_dono, audio_pcm_16k_mono):
    """Mesma ideia de `pedir_turno_tutora`, mas sem exigir sessão prévia -
    qualquer participante pode falar (a GAIA decide o tom da resposta a
    partir de `eh_dono`, mesmo raciocínio de `pedir_resposta_persona` pra
    mensagem de texto). Devolve o caminho local do áudio de resposta, ou
    None."""
    resultado = _post("/eris/conversa/turno", {
        "guild_id": str(guild_id), "speaker_id": str(speaker_id), "speaker_nome": speaker_nome,
        "eh_dono": bool(eh_dono), "audio_b64": base64.b64encode(audio_pcm_16k_mono).decode("ascii"),
    }, timeout=TIMEOUT_TURNO_VOZ_SEGUNDOS)
    if not resultado or not resultado.get("caminho_audio"):
        return None
    return resultado.get("caminho_audio")


# --------------------------------------------------------------------------
# Modo Intérprete (tradução de voz ao vivo numa call do Discord)
# --------------------------------------------------------------------------

def iniciar_interprete(guild_id):
    """Pede pra GAIA abrir uma sessão de tradução pra esse servidor (checa se
    o Modo Intérprete está ligado no Painel, inicializa o contexto/idioma
    estrangeiro atual). Devolve (ok: bool, mensagem: str)."""
    resultado = _post("/eris/interprete/iniciar", {"guild_id": str(guild_id)})
    if resultado is None:
        return False, "A Galateia está desligada agora - não consigo iniciar o Intérprete."
    return bool(resultado.get("ok")), resultado.get("mensagem", "")


def encerrar_interprete(guild_id):
    resultado = _post("/eris/interprete/encerrar", {"guild_id": str(guild_id)})
    if resultado is None:
        return "A Galateia está desligada agora."
    return resultado.get("mensagem", "")


def pedir_turno_interprete(guild_id, speaker_id, speaker_nome, eh_dono, audio_pcm_16k_mono):
    """Manda uma fala já fechada (PCM 16kHz mono, ver eris/core/voz_captura.py)
    pra GAIA transcrever/traduzir/sintetizar. Devolve um dict
    {"caminho_audio", "legenda_original", "legenda_traducao"} - `caminho_audio`
    é um caminho LOCAL (mesma máquina, ver ARQUITETURA.md) que o ERIS abre
    direto pra tocar na call, mesmo padrão já usado por `enviar_arquivo`/
    `enviar_audio_voz`. None se não houver nada pra falar (silêncio detectado
    como alucinação do Whisper, etc.) ou se a GAIA não respondeu."""
    resultado = _post("/eris/interprete/turno", {
        "guild_id": str(guild_id), "speaker_id": str(speaker_id), "speaker_nome": speaker_nome,
        "eh_dono": bool(eh_dono), "audio_b64": base64.b64encode(audio_pcm_16k_mono).decode("ascii"),
    }, timeout=TIMEOUT_TURNO_VOZ_SEGUNDOS)
    if not resultado or not resultado.get("caminho_audio"):
        return None
    return resultado


# --------------------------------------------------------------------------
# Modo Tutora por voz (o dono pratica sozinho com a persona numa call)
# --------------------------------------------------------------------------

def tutora_sessao_ativa():
    resultado = _get("/eris/tutora/status")
    return bool(resultado and resultado.get("ativo"))


def pedir_turno_tutora(guild_id, audio_pcm_16k_mono):
    """Mesma ideia de `pedir_turno_interprete`, mas pro Modo Tutora - só o
    dono alimenta essa conversa (filtro já aplicado por quem chama, ver
    eris/core/voz_call.py). Devolve o caminho local do áudio de resposta, ou
    None."""
    resultado = _post("/eris/tutora/turno", {
        "guild_id": str(guild_id), "audio_b64": base64.b64encode(audio_pcm_16k_mono).decode("ascii"),
    }, timeout=TIMEOUT_TURNO_VOZ_SEGUNDOS)
    if not resultado or not resultado.get("caminho_audio"):
        return None
    return resultado.get("caminho_audio")


# --------------------------------------------------------------------------
# Modo Música (fila com continuação "na mesma vibe", ver eris/core/musica.py)
# --------------------------------------------------------------------------

def pedir_proxima_musica(artista_atual, titulo_atual, excluir):
    """Pede pra GAIA (que consulta o Project ECHO) uma sugestão de próxima
    música na mesma vibe da que acabou de tocar - a GAIA decide QUAL música
    (motor determinístico do ECHO), o ERIS só busca/toca. `excluir`: lista de
    "artista::titulo" já tocados NESTA sessão (dedup de curto prazo). Devolve
    {"artista", "titulo"} ou None se não achou nada / GAIA fora do ar."""
    resultado = _post("/eris/proxima_musica", {
        "artista_atual": artista_atual, "titulo_atual": titulo_atual, "excluir": list(excluir),
    })
    if not resultado or not resultado.get("proxima"):
        return None
    proxima = resultado["proxima"]
    return {"artista": proxima.get("artista"), "titulo": proxima.get("titulo")}


def pedir_feedback_musica(artista, titulo, feedback):
    """Botões 👍/👎 na mensagem de "tocando agora" (2026-08-26, pedido do
    usuário: "quando ela toca uma musica, podia aparecer botoes de like,
    dislike e next") - `feedback`: "positivo" ou "negativo". Best-effort
    (não bloqueia a UI do Discord esperando resposta detalhada) - devolve
    True se a GAIA respondeu, False se estava fora do ar."""
    resultado = _post("/eris/musica_feedback", {"artista": artista, "titulo": titulo, "feedback": feedback})
    return resultado is not None


def pedir_semente_musica(excluir):
    """`/caos` (2026-08-26, pedido do usuário: "ERIS entra no canal de voz...
    sem exigir artista, gênero, música ou qualquer outra referência inicial")
    - pede uma sugestão de PARTIDA baseada só no perfil/histórico musical,
    sem faixa atual pra semear (diferente de `pedir_proxima_musica`). Mesmo
    contrato de retorno: {"artista", "titulo"} ou None."""
    resultado = _post("/eris/musica_caos", {"excluir": list(excluir)})
    if not resultado or not resultado.get("semente"):
        return None
    semente = resultado["semente"]
    return {"artista": semente.get("artista"), "titulo": semente.get("titulo")}
