# -*- coding: utf-8 -*-
"""Ponte HTTP do ERIS (porta 8772) - mesmo padrão de `hestia/api_bridge.py`/
`moirai/api_bridge.py` (`BaseHTTPRequestHandler` simples, sem framework).
Consumida pela GAIA (`integrations/eris_client.py`) - entrega de mensagem
proativa (Agendador Diário, monitoramentos), CRUD de donos/config de
roteamento (Painel -> Discord Setup) e exportação de canal. Moderação NÃO
tem rota aqui de propósito - é acionada só pelos slash commands do próprio
ERIS (`eris/bot.py`), nunca pela GAIA (ver ARQUITETURA.md).

Roda numa THREAD separada (não o loop asyncio do bot) - qualquer coroutine
precisa ser despachada via `asyncio.run_coroutine_threadsafe` contra o loop
do bot (`eris.bot.loop_atual()`), igual ao padrão já usado pela GAIA em
`PainelQt.enviar_chat`."""
import asyncio
import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from eris import bot, db
from eris.config import PORTA_API_ERIS
from eris.core import mensagens

LOCAL_API_HOST = "127.0.0.1"

TIMEOUT_CHAMADA_ASSINCRONA_SEGUNDOS = 30


def _rodar_no_loop_do_bot(coro):
    """Despacha `coro` pro loop do bot e espera o resultado (bloqueante,
    estamos numa thread separada do asyncio) - devolve None se o bot ainda
    não conectou (loop inexistente)."""
    loop = bot.loop_atual()
    if loop is None:
        return None
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=TIMEOUT_CHAMADA_ASSINCRONA_SEGUNDOS)


def _arquivos_de_json(bruto):
    return [(a["nome"], base64.b64decode(a["dados_b64"])) for a in (bruto or [])]


def _ler_corpo_json(handler):
    tamanho = int(handler.headers.get("Content-Length", 0))
    try:
        return json.loads(handler.rfile.read(tamanho)) if tamanho else {}
    except Exception:
        return {}


class _API(BaseHTTPRequestHandler):
    def _responder_json(self, dados, status=200):
        corpo = json.dumps(dados).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo)

    def _responder_ok(self):
        self.send_response(200)
        self.end_headers()

    def _responder_404(self):
        self.send_response(404)
        self.end_headers()

    # ----------------------------------------------------------------
    def do_GET(self):
        if self.path == "/status":
            self._responder_json({"conectado": bot.cliente_conectado() is not None})
        elif self.path == "/donos":
            self._responder_json(db.listar_donos())
        elif self.path == "/config_roteamento":
            self._responder_json(db.obter_config_roteamento())
        elif self.path == "/guilds":
            self._responder_json(db.obter_guilds_cache())
        elif self.path == "/auditoria":
            self._responder_json(db.listar_auditoria())
        elif self.path == "/emojis_aplicacao":
            self._responder_json(mensagens.listar_emojis_aplicacao(_token_atual()))
        elif self.path.startswith("/perfil/"):
            user_id = self.path[len("/perfil/"):]
            perfil = mensagens.buscar_perfil_discord(user_id, _token_atual())
            self._responder_json(perfil or {})
        else:
            self._responder_404()

    def do_POST(self):
        corpo = _ler_corpo_json(self)

        if self.path == "/donos":
            db.salvar_donos(corpo.get("donos", []))
            self._responder_ok()
        elif self.path == "/config_roteamento":
            db.salvar_config_roteamento(corpo.get("campo"), corpo.get("valor"))
            self._responder_ok()
        elif self.path == "/guild_desativado":
            db.definir_guild_desativado(corpo.get("guild_id"), bool(corpo.get("desativado")))
            self._responder_ok()
        elif self.path == "/notificar_donos":
            _rodar_no_loop_do_bot(mensagens.notificar_donos(
                corpo.get("donos_ids", []), corpo.get("texto", ""), _arquivos_de_json(corpo.get("arquivos")),
            ))
            self._responder_ok()
        elif self.path == "/notificar_canal":
            ok = _rodar_no_loop_do_bot(mensagens.enviar_para_canal(
                corpo.get("channel_id"), corpo.get("texto", ""), _arquivos_de_json(corpo.get("arquivos")),
            ))
            self._responder_json({"ok": bool(ok)})
        elif self.path == "/notificar_canal_categoria":
            ok = _rodar_no_loop_do_bot(mensagens.notificar_canal_em_categoria(
                corpo.get("guild_id"), corpo.get("categoria_id"), corpo.get("nome_canal"),
                corpo.get("texto", ""), _arquivos_de_json(corpo.get("arquivos")),
            ))
            self._responder_json({"ok": bool(ok)})
        elif self.path == "/testar_canal_categoria":
            resultado = _rodar_no_loop_do_bot(mensagens.testar_canal_categoria(
                corpo.get("guild_id"), corpo.get("categoria_id"), corpo.get("nome_canal"),
            ))
            ok, msg = resultado if resultado else (False, "Bot do ERIS ainda não conectou.")
            self._responder_json({"ok": ok, "mensagem": msg})
        elif self.path == "/enviar_arquivo":
            ok = _rodar_no_loop_do_bot(mensagens.enviar_arquivo(corpo.get("channel_id"), corpo.get("caminho")))
            self._responder_json({"ok": bool(ok)})
        elif self.path == "/enviar_audio_voz":
            from eris.core import voz_nativa
            ok, aviso = voz_nativa.enviar_mensagem_voz(corpo.get("channel_id"), _token_atual(), corpo.get("caminho"))
            self._responder_json({"ok": ok, "aviso": aviso})
        elif self.path == "/exportar":
            from eris.core import exportador
            ok, resultado = exportador.exportar_canal(corpo.get("channel_id"), _token_atual(), corpo.get("limite_mensagens"))
            self._responder_json({"ok": ok, "resultado": resultado})
        else:
            self._responder_404()

    def log_message(self, format, *args):
        return


_token_global = None


def _token_atual():
    return _token_global


def iniciar_servidor_api(token):
    """Bloqueia a thread que chamar - `eris/main.py` sobe isso numa thread
    própria, já que o loop principal do processo fica ocupado com
    `bot.iniciar_bot` (asyncio)."""
    global _token_global
    _token_global = token
    servidor = HTTPServer((LOCAL_API_HOST, PORTA_API_ERIS), _API)
    servidor.serve_forever()
