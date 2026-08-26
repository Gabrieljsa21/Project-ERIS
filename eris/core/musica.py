# -*- coding: utf-8 -*-
"""Modo Música - toca áudio de verdade numa call de voz do Discord (substitui o
Jockie Music, pedido do usuário 2026-08-25: "quero q alguem seja meu dj
exclusivo, q conheça meus gostos e q qnd eu pedir uma musica, ele continue
tocando outras em sequencia na mesma vibe"). Busca/streaming via YouTube
(`yt-dlp` - mesma abordagem que praticamente todo bot de música de Discord usa,
já que não existe forma oficial/de graça de tocar áudio arbitrário numa call a
partir só de nome de artista/música). A "continuação na mesma vibe" delega pro
motor determinístico do Project ECHO (via webhook reverso pra GAIA, `eris.
integrations.gaia_webhook.pedir_proxima_musica`) - o ERIS nunca decide sozinho
o que é "parecido", só busca/toca o que o ECHO sugere.

⚠️ Zona cinzenta de ToS do YouTube (avisado ao usuário antes de implementar,
2026-08-25) - extrair áudio via yt-dlp não é um uso oficialmente suportado,
mas é a mesma técnica usada por praticamente todo bot de música de Discord
(incluindo o Jockie que isso substitui). Usa `player_client=android` (não
exige token de origem/cookie, ao contrário do client "web" padrão desde 2024)
- se o YouTube endurecer e isso parar de funcionar, o próximo passo é
configurar `YOUTUBE_COOKIES_FILE` no `.env` (cookies exportados do navegador).

Diferente de `voz_call.SessaoVoz` (Intérprete/Tutora/Conversa - captura fala do
usuário e toca resposta curta), aqui não existe captura nenhuma - é uma
transmissão contínua disparada por slash command (`/musica tocar` etc.,
`eris/bot.py`), sem envolver STT/LLM/TTS da GAIA no caminho crítico."""
import asyncio
import os

import discord
import yt_dlp

from eris.integrations import gaia_webhook

_sessoes_musica = {}  # guild_id -> SessaoMusica

_HISTORICO_SESSAO_MAX = 50  # não cresce pra sempre numa call que fica ligada o dia todo

_YTDL_OPCOES_BASE = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch1",
    "quiet": True,
    "no_warnings": True,
    "extractor_args": {"youtube": {"player_client": ["android"]}},
}

_FFMPEG_OPCOES_ANTES = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
_FFMPEG_OPCOES = "-vn"


def _binario_ffmpeg():
    """Mesmo padrão de `eris/core/voz_nativa.py::_binario_ffmpeg` - usa
    `FFMPEG_BIN_DIR` se configurado, senão cai pro `ffmpeg` do PATH do
    sistema."""
    pasta = os.getenv("FFMPEG_BIN_DIR")
    caminho = os.path.join(pasta, "ffmpeg.exe") if pasta else None
    return caminho if caminho and os.path.exists(caminho) else "ffmpeg"


def _buscar_no_youtube(query):
    """BLOQUEANTE (chamar via `asyncio.to_thread`) - busca 1 resultado no
    YouTube (aceita nome de música/artista OU link direto) e devolve
    `{"titulo", "artista", "url_stream", "url_pagina"}`, ou None se não achou
    nada/a extração falhou. "artista" é o nome do canal do YouTube - uma
    aproximação razoável pra clipe oficial, mas não é garantido (nunca é
    tratado como dado 100% confiável pra scoring do ECHO, só como texto de
    exibição e semente de busca)."""
    opcoes = dict(_YTDL_OPCOES_BASE)
    cookies = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        opcoes["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(query, download=False)
            if info is None:
                return None
            if "entries" in info:
                entradas = [e for e in info["entries"] if e]
                if not entradas:
                    return None
                info = entradas[0]
            if not info.get("url"):
                return None
            return {
                "titulo": info.get("title") or query,
                "artista": info.get("uploader") or info.get("channel") or "Desconhecido",
                "url_stream": info["url"],
                "url_pagina": info.get("webpage_url"),
            }
    except Exception as e:
        print(f" [ERIS] Falha na busca do YouTube (\"{query}\"): {e}")
        return None


class SessaoMusica:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self._vc = None
        self._loop = asyncio.get_running_loop()
        self.fila = []
        self.tocando_agora = None
        self.modo_continuo = True
        self._historico_sessao = []

    @property
    def canal_atual(self):
        return self._vc.channel if self._vc else None

    @property
    def historico_sessao(self):
        return list(self._historico_sessao)

    async def entrar(self, voice_channel):
        self._vc = await voice_channel.connect()
        print(f" [ERIS] Sessão de música conectada em \"{voice_channel.name}\".")

    async def sair(self):
        self.fila.clear()
        self.tocando_agora = None
        if self._vc:
            if self._vc.is_playing() or self._vc.is_paused():
                self._vc.stop()
            await self._vc.disconnect()
            self._vc = None

    def _registrar_historico(self, faixa):
        chave = f"{faixa['artista'].strip().lower()}::{faixa['titulo'].strip().lower()}"
        self._historico_sessao.append(chave)
        self._historico_sessao = self._historico_sessao[-_HISTORICO_SESSAO_MAX:]

    def _ao_terminar_thread_externa(self, erro):
        """Chamado pelo discord.py numa thread PRÓPRIA do player de áudio
        (nunca a do loop asyncio) - mesmo cuidado de thread-safety de
        `voz_call.SessaoVoz._on_fala_fechada_thread_externa`."""
        if erro:
            print(f" [ERIS] Erro tocando música: {erro}")
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._avancar()))

    async def _tocar(self, faixa):
        self.tocando_agora = faixa
        self._registrar_historico(faixa)
        fonte = discord.FFmpegPCMAudio(
            faixa["url_stream"], executable=_binario_ffmpeg(),
            before_options=_FFMPEG_OPCOES_ANTES, options=_FFMPEG_OPCOES,
        )
        try:
            self._vc.play(fonte, after=self._ao_terminar_thread_externa)
        except Exception as e:
            print(f" [ERIS] Erro ao INICIAR reprodução de música: {e}")
            self.tocando_agora = None
            return
        print(f" [ERIS] Tocando: {faixa['titulo']} - {faixa['artista']}")

    async def _avancar(self):
        """Chamado quando uma faixa termina - toca a próxima da fila; se a
        fila estiver vazia e o modo contínuo ligado, pede uma sugestão pro
        ECHO (via GAIA) semeada pela faixa que acabou de tocar, buscando
        exclusão de tudo já tocado NESTA sessão (dedup de curto prazo -
        resolve a queixa real do usuário sobre o Jockie repetir depois de um
        tempo, diferente do dedup de 90 dias do Radar Musical semanal)."""
        if self._vc is None:  # sair() já rodou antes do callback disparar
            return
        if self.fila:
            proxima = self.fila.pop(0)
            await self._tocar(proxima)
            return
        anterior = self.tocando_agora
        self.tocando_agora = None
        if not self.modo_continuo or anterior is None:
            return
        sugestao = await asyncio.to_thread(
            gaia_webhook.pedir_proxima_musica, anterior["artista"], anterior["titulo"], self._historico_sessao,
        )
        if not sugestao:
            print(" [ERIS] Modo contínuo: ECHO não sugeriu nada (sem candidato ou indisponível) - fila esvaziada.")
            return
        faixa = await asyncio.to_thread(_buscar_no_youtube, f"{sugestao['artista']} {sugestao['titulo']}")
        if not faixa:
            print(f" [ERIS] Modo contínuo: não achei \"{sugestao['artista']} - {sugestao['titulo']}\" no YouTube.")
            return
        await self._tocar(faixa)

    async def adicionar(self, query):
        """Busca e adiciona - toca IMEDIATAMENTE se nada estiver tocando/na
        fila. Devolve (ok, mensagem)."""
        faixa = await asyncio.to_thread(_buscar_no_youtube, query)
        if not faixa:
            return False, f"Não achei nada pra \"{query}\" no YouTube."
        if self.tocando_agora is None and not self.fila:
            await self._tocar(faixa)
            return True, f"🎵 Tocando agora: **{faixa['titulo']}** - {faixa['artista']}"
        self.fila.append(faixa)
        return True, f"Adicionado à fila (posição {len(self.fila)}): **{faixa['titulo']}** - {faixa['artista']}"

    def pular(self):
        if self._vc is None or not (self._vc.is_playing() or self._vc.is_paused()):
            return "Não tem nada tocando agora."
        self._vc.stop()  # dispara o callback `after`, que avança sozinho
        return "Pulei pra próxima."

    def pausar(self):
        if self._vc is None or not self._vc.is_playing():
            return "Não tem nada tocando agora."
        self._vc.pause()
        return "Pausei."

    def retomar(self):
        if self._vc is None or not self._vc.is_paused():
            return "Não tem nada pausado agora."
        self._vc.resume()
        return "Retomei."

    def obter_fila(self):
        return {"tocando_agora": self.tocando_agora, "fila": list(self.fila), "modo_continuo": self.modo_continuo}


def canal_ativo(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.canal_atual if sessao else None


async def _obter_ou_criar_sessao(voice_channel):
    from eris.core import voz_call  # 🔥 import tardio - evita ciclo (voz_call também checa musica.canal_ativo)
    guild_id = voice_channel.guild.id
    if voz_call.canal_ativo(guild_id) is not None:
        return None, "Já tô numa call de voz (Conversa/Intérprete/Tutora) nesse servidor - sai de lá primeiro (\"@Gala sai\") se quiser música."
    sessao = _sessoes_musica.get(guild_id)
    if sessao is None:
        sessao = SessaoMusica(guild_id)
        try:
            await sessao.entrar(voice_channel)
        except Exception as e:
            return None, f"Não consegui entrar na call: {e}"
        _sessoes_musica[guild_id] = sessao
    return sessao, None


async def tocar(voice_channel, query):
    sessao, erro = await _obter_ou_criar_sessao(voice_channel)
    if sessao is None:
        return False, erro
    return await sessao.adicionar(query)


async def iniciar_caos(voice_channel):
    """`/caos` (2026-08-26, pedido do usuário: "ERIS entra no canal de voz do
    usuário e inicia uma sessão musical contínua... sem exigir artista,
    gênero, música ou qualquer outra referência inicial") - pede pro ECHO
    (via GAIA) uma sugestão de PARTIDA baseada só no perfil/histórico
    musical (`gaia_webhook.pedir_semente_musica`, sem faixa atual pra
    semear - diferente de `_avancar`) e entra igual um `/musica tocar`
    normal a partir daí. `modo_continuo` já nasce ligado (`SessaoMusica.
    __init__`), então o motor de continuação de sempre assume sozinho -
    nenhum mecanismo novo além de arranjar a PRIMEIRA busca sem pedir nada
    ao usuário."""
    sessao, erro = await _obter_ou_criar_sessao(voice_channel)
    if sessao is None:
        return False, erro
    sugestao = await asyncio.to_thread(gaia_webhook.pedir_semente_musica, sessao.historico_sessao)
    if not sugestao:
        return False, "Não consegui pensar em nada pra começar agora (ECHO indisponível ou sem candidato) - tenta \"/musica tocar\" com algo específico."
    return await sessao.adicionar(f"{sugestao['artista']} {sugestao['titulo']}")


async def sair_musica(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    if not sessao:
        return "Eu não tava tocando música nesse servidor."
    del _sessoes_musica[guild_id]
    await sessao.sair()
    return "Parei e saí da call."


def pular(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.pular() if sessao else "Eu não tava tocando música nesse servidor."


def pausar(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.pausar() if sessao else "Eu não tava tocando música nesse servidor."


def retomar(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.retomar() if sessao else "Eu não tava tocando música nesse servidor."


def obter_fila(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.obter_fila() if sessao else None


def definir_modo_continuo(guild_id, ativo):
    sessao = _sessoes_musica.get(guild_id)
    if not sessao:
        return "Eu não tava tocando música nesse servidor."
    sessao.modo_continuo = ativo
    return f"Modo contínuo (DJ automático) {'ativado' if ativo else 'desativado'}."
