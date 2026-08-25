# -*- coding: utf-8 -*-
"""Manda uma mensagem de VOZ NATIVA do Discord (a bolha com waveform, tipo
"voice message" gravada pelo app) via chamada HTTP CRUA na API REST -
`discord.py` não expõe os campos "duration_secs"/"waveform" nem a flag
IS_VOICE_MESSAGE que esse tipo especial de anexo exige, então não dá pra
fazer isso pelo client normal. Extraído de
`integrations/discord/discord_voz_nativa.py` (GAIA, antes da extração de
2026-08-24) - comportamento idêntico, só o módulo mudou de casa.

⚠️ RISCO CONHECIDO (avisado ao usuário antes de implementar, 2026-07-24):
esse recurso foi pensado pelo Discord pra usuários reais gravando pelo
próprio app - o comportamento via bot é pouco documentado oficialmente. Uma
chamada com HTTP 200/201 não garante que o cliente do Discord vai renderizar
como mensagem de voz de verdade; pode simplesmente aparecer como anexo de
áudio comum mesmo com a flag setada. Por isso a conversão pra OGG/Opus é
best-effort: se o ffmpeg não estiver disponível, cai pra mandar como anexo
de áudio comum em vez de falhar a mensagem inteira."""
import base64
import json
import os
import subprocess

import requests

API_BASE = "https://discord.com/api/v10"
IS_VOICE_MESSAGE = 1 << 13  # flag documentada de forma não-oficial (reverse engineering da comunidade)


def _binario_ffmpeg(nome):
    pasta = os.getenv("FFMPEG_BIN_DIR")
    caminho = os.path.join(pasta, f"{nome}.exe") if pasta else None
    return caminho if caminho and os.path.exists(caminho) else nome  # cai pro PATH do sistema se não configurado


def _converter_para_ogg_opus(caminho_origem):
    """Converte pra OGG/Opus via ffmpeg (formato que o cliente do Discord
    espera pra considerar uma mensagem de voz de verdade). Devolve o caminho
    do .ogg gerado, ou None se o ffmpeg não estiver disponível ou a
    conversão falhar - nesse caso quem chama (enviar_mensagem_voz) cai pro
    fallback de anexo de áudio comum."""
    caminho_ogg = os.path.splitext(caminho_origem)[0] + "_voz.ogg"
    try:
        resultado = subprocess.run(
            [_binario_ffmpeg("ffmpeg"), "-y", "-i", caminho_origem, "-c:a", "libopus", "-b:a", "32k", caminho_ogg],
            capture_output=True, timeout=20,
        )
        if resultado.returncode != 0 or not os.path.exists(caminho_ogg):
            return None
        return caminho_ogg
    except Exception:
        return None


def _duracao_segundos(caminho):
    """Via ffprobe (vem junto do ffmpeg) - funciona pra qualquer formato de
    áudio. duration_secs é só o número mostrado no player - uma estimativa
    aproximada não quebra o envio, então cai num valor fixo em vez de falhar
    a mensagem inteira."""
    try:
        resultado = subprocess.run(
            [_binario_ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
            capture_output=True, text=True, timeout=10,
        )
        return round(float(resultado.stdout.strip()), 2)
    except Exception:
        return 3.0


def _waveform_falso():
    """O Discord exige uma amostra de amplitude em base64 (campo
    "waveform") pra desenhar a barrinha visual da mensagem de voz - não faz
    análise real do áudio aqui; uma sequência fixa de valores médios já é
    aceita pelos clientes oficiais em relatos da comunidade."""
    return base64.b64encode(bytes([80] * 40)).decode("ascii")


def enviar_mensagem_voz(channel_id, token, caminho_audio):
    """Devolve (True, aviso_ou_None) em sucesso - `aviso` vem preenchido só
    quando caiu pro fallback de anexo comum (ffmpeg indisponível/conversão
    falhou), pra quem chamou (a GAIA, via webhook reverso) poder ser honesto
    na resposta sobre qual dos dois formatos foi enviado de verdade. Devolve
    (False, motivo) se nem o fallback conseguiu ser mandado."""
    if not token:
        return False, "DISCORD_BOT_TOKEN não configurado."
    if not os.path.exists(caminho_audio):
        return False, "Arquivo de áudio não encontrado."

    caminho_ogg = _converter_para_ogg_opus(caminho_audio)
    eh_mensagem_de_voz = caminho_ogg is not None
    caminho_final = caminho_ogg or caminho_audio
    nome_arquivo = os.path.basename(caminho_final)

    if caminho_final.lower().endswith(".ogg"):
        content_type = "audio/ogg"
    elif caminho_final.lower().endswith(".wav"):
        content_type = "audio/wav"
    else:
        content_type = "audio/mpeg"

    payload = {"attachments": [{"id": "0", "filename": nome_arquivo}]}
    if eh_mensagem_de_voz:
        payload["flags"] = IS_VOICE_MESSAGE
        payload["attachments"][0]["duration_secs"] = _duracao_segundos(caminho_final)
        payload["attachments"][0]["waveform"] = _waveform_falso()

    try:
        with open(caminho_final, "rb") as f:
            resp = requests.post(
                f"{API_BASE}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (nome_arquivo, f, content_type)},
                timeout=20,
            )
    except Exception as e:
        return False, f"Erro na chamada ao Discord: {e}"

    if resp.status_code not in (200, 201):
        return False, f"Discord recusou (status {resp.status_code}): {resp.text[:300]}"

    if eh_mensagem_de_voz:
        return True, None
    return True, "ffmpeg indisponível/conversão falhou - mandado como anexo de áudio comum, não como mensagem de voz nativa."
