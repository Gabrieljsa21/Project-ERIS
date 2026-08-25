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
import json
import urllib.request

from eris.config import URL_BASE_GAIA

TIMEOUT_SEGUNDOS = 30  # generoso de propósito - a GAIA pode estar processando LLM/ferramenta


def _post(caminho, corpo):
    try:
        dados = json.dumps(corpo).encode("utf-8")
        req = urllib.request.Request(f"{URL_BASE_GAIA}{caminho}", data=dados, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read())
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
