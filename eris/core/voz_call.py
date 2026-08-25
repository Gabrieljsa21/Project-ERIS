# -*- coding: utf-8 -*-
"""Sessão de voz numa call do Discord - Intérprete (tradução ao vivo entre
dois humanos) e Tutora (o dono pratica idioma sozinho com a persona)
compartilham a mesma mecânica de conexão/captura/playback, só divergem em
quem pode falar e qual endpoint do webhook reverso é chamado por turno.
Extraído de `features/interprete/sessao.py` + `features/tutora/
sessao_discord.py` (GAIA, antes da migração de 2026-08-25) - a decisão de
TRADUÇÃO/RESPOSTA continua 100% na GAIA (Whisper/LLM/TTS, "fica no core"
desde antes da extração do ERIS); aqui só entra/sai da call, captura a fala
até o silêncio e toca o áudio que a GAIA devolve.

Só 1 sessão de voz por servidor (Discord só permite 1 conexão de voz por
guild de qualquer forma) - `_sessoes` guarda por `guild_id`, sem separar por
modo."""
import asyncio

import discord
from discord.ext import voice_recv

from eris.core import seguranca
from eris.core.voz_captura import SinkVoz
from eris.integrations import gaia_webhook

_sessoes = {}  # guild_id -> SessaoVoz


class SessaoVoz:
    def __init__(self, guild_id, modo):
        self.guild_id = guild_id
        self.modo = modo  # "interprete" | "tutora"
        self._vc = None
        self._loop = asyncio.get_running_loop()
        self._fila = asyncio.Queue()
        self._worker_task = None

    @property
    def canal_atual(self):
        return self._vc.channel if self._vc else None

    async def entrar(self, voice_channel):
        self._vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        self._vc.listen(SinkVoz(self._on_fala_fechada_thread_externa))
        self._worker_task = asyncio.create_task(self._worker())

    async def sair(self):
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
        if self._vc:
            self._vc.stop_listening()
            await self._vc.disconnect()
            self._vc = None

    def _on_fala_fechada_thread_externa(self, user, frames_pcm_16k_mono):
        """Chamado pela extensão de voz numa thread própria (decodificação de
        rede) - nunca mexe direto na fila asyncio, só agenda com segurança de
        thread (mesmo cuidado do código original antes da extração)."""
        self._loop.call_soon_threadsafe(self._fila.put_nowait, (user, frames_pcm_16k_mono))

    async def _worker(self):
        while True:
            user, frames = await self._fila.get()
            try:
                await self._processar_fala(user, frames)
            except Exception as e:
                print(f" [ERIS] Erro processando fala ({self.modo}) de {getattr(user, 'display_name', user)}: {e}")

    async def _processar_fala(self, user, frames):
        audio_bytes = b"".join(frames)
        if self.modo == "interprete":
            eh_dono = seguranca.eh_dono(user.id)
            resultado = await asyncio.to_thread(
                gaia_webhook.pedir_turno_interprete, self.guild_id, user.id, user.display_name, eh_dono, audio_bytes,
            )
            if resultado is None:
                return
            await self._tocar(resultado["caminho_audio"])
        else:  # tutora - só o dono alimenta essa conversa
            if not seguranca.eh_dono(user.id):
                return
            caminho_audio = await asyncio.to_thread(gaia_webhook.pedir_turno_tutora, self.guild_id, audio_bytes)
            if caminho_audio is None:
                return
            await self._tocar(caminho_audio)

    async def _tocar(self, caminho_audio):
        concluido = asyncio.Event()

        def _ao_terminar(erro):
            self._loop.call_soon_threadsafe(concluido.set)

        self._vc.play(discord.FFmpegPCMAudio(caminho_audio), after=_ao_terminar)
        await concluido.wait()


def canal_ativo(guild_id):
    sessao = _sessoes.get(guild_id)
    return sessao.canal_atual if sessao else None


async def entrar_interprete(voice_channel):
    guild_id = voice_channel.guild.id
    if guild_id in _sessoes:
        return False, "Eu já tô numa call de voz nesse servidor - sai primeiro se quiser trocar de canal/modo."
    ok, mensagem = await asyncio.to_thread(gaia_webhook.iniciar_interprete, guild_id)
    if not ok:
        return False, mensagem
    sessao = SessaoVoz(guild_id, "interprete")
    try:
        await sessao.entrar(voice_channel)
    except Exception as e:
        await asyncio.to_thread(gaia_webhook.encerrar_interprete, guild_id)
        return False, f"Não consegui entrar na call: {e}"
    _sessoes[guild_id] = sessao
    return True, mensagem or f"Entrei em **{voice_channel.name}** e já tô ouvindo - fala à vontade."


async def sair_interprete(guild_id):
    sessao = _sessoes.get(guild_id)
    if not sessao or sessao.modo != "interprete":
        return "Eu não tava em nenhuma call de intérprete nesse servidor."
    del _sessoes[guild_id]
    await sessao.sair()
    mensagem = await asyncio.to_thread(gaia_webhook.encerrar_interprete, guild_id)
    return mensagem or "Saí da call e parei de traduzir."


async def entrar_tutora(voice_channel):
    guild_id = voice_channel.guild.id
    if guild_id in _sessoes:
        return False, "Eu já tô numa call de voz nesse servidor - sai primeiro se quiser trocar de canal/modo."
    ativo = await asyncio.to_thread(gaia_webhook.tutora_sessao_ativa)
    if not ativo:
        return False, "Não tem sessão de Tutora ativa ainda - manda \"/iniciar_tutora <idioma>\" primeiro (por DM ou menção)."
    sessao = SessaoVoz(guild_id, "tutora")
    try:
        await sessao.entrar(voice_channel)
    except Exception as e:
        return False, f"Não consegui entrar na call: {e}"
    _sessoes[guild_id] = sessao
    return True, f"Entrei em **{voice_channel.name}** também."


async def sair_tutora(guild_id):
    sessao = _sessoes.get(guild_id)
    if not sessao or sessao.modo != "tutora":
        return ""
    del _sessoes[guild_id]
    await sessao.sair()
    return "Saí da call."


async def sair_qualquer(guild_id):
    """Usado pelo auto-leave (canal ficou sem nenhum humano, ver
    eris/bot.py::on_voice_state_update) - não precisa saber o modo de
    antemão."""
    sessao = _sessoes.get(guild_id)
    if not sessao:
        return
    if sessao.modo == "interprete":
        await sair_interprete(guild_id)
    else:
        await sair_tutora(guild_id)
