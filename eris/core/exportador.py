# -*- coding: utf-8 -*-
"""Exporta o histórico de um canal do Discord pra JSON - funcionalidade
equivalente ao DiscordChatExporter (github.com/Tyrrrz/DiscordChatExporter),
reimplementada em Python puro usando a API REST oficial do Discord direto
(mesmo padrão de `eris/core/mensagens.py::buscar_perfil_discord`) - não
precisa da conexão de Gateway (WebSocket) do bot pra isso, só o token já
basta pra ler mensagens de um canal. Extraído de
`integrations/discord/discord_exportador.py` (GAIA, antes da extração de
2026-08-24) - função administrativa do ERIS agora (ver ARQUITETURA.md),
comportamento idêntico.

Exige que o bot já esteja no servidor de onde quer exportar, com permissão
de "Ver Canal" e "Ler Histórico de Mensagens" no canal específico."""
import json
import os
import time
from datetime import datetime

import requests

from eris.config import PASTA_EXPORTACOES

API_BASE = "https://discord.com/api/v10"
LIMITE_POR_PAGINA = 100  # máximo permitido pela própria API por chamada


def _headers(token):
    return {"Authorization": f"Bot {token}"}


def _autor_para_dict(autor):
    return {
        "id": autor.get("id"),
        "username": autor.get("username"),
        "nome_exibicao": autor.get("global_name") or autor.get("username"),
        "bot": autor.get("bot", False),
    }


def _mensagem_para_dict(msg):
    return {
        "id": msg.get("id"),
        "timestamp": msg.get("timestamp"),
        "timestamp_editado": msg.get("edited_timestamp"),
        "autor": _autor_para_dict(msg.get("author", {})),
        "conteudo": msg.get("content", ""),
        "anexos": [
            {"nome": a.get("filename"), "url": a.get("url"), "tamanho_bytes": a.get("size")}
            for a in msg.get("attachments", [])
        ],
        "embeds": [
            {"titulo": e.get("title"), "descricao": e.get("description"), "url": e.get("url")}
            for e in msg.get("embeds", [])
        ],
        "reacoes": [
            {"emoji": (r.get("emoji") or {}).get("name"), "quantidade": r.get("count")}
            for r in msg.get("reactions", [])
        ],
    }


def obter_info_canal(channel_id, token):
    """Devolve (ok, dados_ou_erro) - usado tanto pela exportação em si quanto
    pra validar rapidamente um ID de canal antes de disparar a exportação
    completa (que pode demorar em canais grandes)."""
    try:
        resp = requests.get(f"{API_BASE}/channels/{channel_id}", headers=_headers(token), timeout=15)
    except Exception as e:
        return False, f"Erro ao consultar o canal: {e}"
    if resp.status_code != 200:
        return False, (
            f"Não consegui acessar o canal (status {resp.status_code}) - confirme que "
            f"o bot está nesse servidor com permissão de ver o canal e ler o "
            f"histórico. Resposta: {resp.text[:200]}"
        )
    return True, resp.json()


def exportar_canal(channel_id, token, limite_mensagens=None, pasta_destino=PASTA_EXPORTACOES):
    """Exporta o histórico de um canal pra um arquivo JSON. `limite_mensagens`:
    None = exporta tudo (pode demorar em canais grandes, por causa do rate
    limit da própria API); um número = para depois de coletar essa
    quantidade (as mais recentes). Devolve (ok: bool, caminho_ou_erro: str) -
    nunca levanta exceção."""
    if not token:
        return False, "DISCORD_BOT_TOKEN não configurado."

    ok, info_canal = obter_info_canal(channel_id, token)
    if not ok:
        return False, info_canal

    mensagens = []
    before = None
    try:
        while True:
            params = {"limit": LIMITE_POR_PAGINA}
            if before:
                params["before"] = before
            resp = requests.get(f"{API_BASE}/channels/{channel_id}/messages", headers=_headers(token), params=params, timeout=15)

            if resp.status_code == 429:
                espera = resp.json().get("retry_after", 2)
                time.sleep(espera + 0.5)
                continue
            if resp.status_code != 200:
                return False, f"Erro ao buscar mensagens (status {resp.status_code}): {resp.text[:200]}"

            pagina = resp.json()
            if not pagina:
                break
            mensagens.extend(pagina)
            before = pagina[-1]["id"]
            if limite_mensagens and len(mensagens) >= limite_mensagens:
                mensagens = mensagens[:limite_mensagens]
                break
            time.sleep(0.5)  # margem extra além do rate limit
    except Exception as e:
        return False, f"Erro durante a exportação: {e}"

    mensagens_ordenadas = list(reversed(mensagens))

    dados_exportados = {
        "canal": {"id": info_canal.get("id"), "nome": info_canal.get("name"), "tipo": info_canal.get("type")},
        "total_mensagens": len(mensagens_ordenadas),
        "exportado_em": datetime.now().isoformat(),
        "mensagens": [_mensagem_para_dict(m) for m in mensagens_ordenadas],
    }

    os.makedirs(pasta_destino, exist_ok=True)
    nome_canal_seguro = "".join(c for c in (info_canal.get("name") or str(channel_id)) if c.isalnum() or c in "-_")
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"discord_{nome_canal_seguro}_{carimbo}.json"
    caminho = os.path.join(pasta_destino, nome_arquivo)

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados_exportados, f, ensure_ascii=False, indent=2)

    return True, caminho
