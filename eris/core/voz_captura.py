# -*- coding: utf-8 -*-
"""Captura de áudio por participante numa call do Discord - portado de
`features/interprete/audio.py::SinkInterprete`/`BufferParticipante` (GAIA)
em 2026-08-25, na migração do Intérprete/Tutora por voz pro ERIS. Ponte
entre a extensão `discord-ext-voice-recv` (voice receive, que discord.py não
tem nativamente) e o resto do pipeline - decide só ONDE cada fala individual
termina (por volume, RMS) e entrega os frames PCM 16kHz mono já prontos pro
Whisper (que continua do lado da GAIA, chamado via webhook reverso).

Genérico o bastante pra servir Intérprete (qualquer participante pode falar)
e Tutora por voz (quem filtra "só o dono pode falar" é quem registra o
callback, ver `eris/core/voz_call.py`) - esta camada não sabe nada sobre
quem tem permissão de falar, só entrega cada fala fechada."""
import audioop
import time

from discord.ext import voice_recv

from eris.core.vad import VoiceFilterRMS

TAXA_ENTRADA = 48000
TAXA_SAIDA = 16000
SILENCIO_MAXIMO_SEGUNDOS = 0.8
DURACAO_MINIMA_FALA_SEGUNDOS = 0.3


class BufferParticipante:
    """Recebe PCM 48kHz estéreo (Discord) aos poucos, converte pra 16kHz mono
    (formato que o Whisper da GAIA já espera) e decide onde a fala termina
    por VOLUME (VoiceFilterRMS, não VAD neural - já se sabe que é voz humana
    de um canal de voz de verdade, o problema é só marcar o fim da fala, não
    filtrar ruído ambiente)."""

    def __init__(self, user, ao_fechar_fala):
        self.user = user
        self._ao_fechar_fala = ao_fechar_fala
        self._estado_ratecv = None
        self._voice_filter = VoiceFilterRMS()
        self._falando = False
        self._ultimo_chunk_com_voz = None
        self._frames_16k_da_fala = []

    def receber(self, pcm_48k_estereo):
        mono_16k = self._converter(pcm_48k_estereo)
        eh_voz = self._voice_filter.is_human_voice(mono_16k, rate=TAXA_SAIDA)
        agora = time.monotonic()
        if eh_voz:
            self._frames_16k_da_fala.append(mono_16k)
            self._falando = True
            self._ultimo_chunk_com_voz = agora
        elif self._falando:
            # 🔥 Mantém a cauda de silêncio na própria fala (não descarta) - cortar
            # seco no último frame com voz soa robótico/cortado quando o Whisper
            # transcreve.
            self._frames_16k_da_fala.append(mono_16k)
            if agora - self._ultimo_chunk_com_voz > SILENCIO_MAXIMO_SEGUNDOS:
                self._fechar_fala()

    def _converter(self, pcm_48k_estereo):
        mono_48k = audioop.tomono(pcm_48k_estereo, 2, 0.5, 0.5)
        mono_16k, self._estado_ratecv = audioop.ratecv(
            mono_48k, 2, 1, TAXA_ENTRADA, TAXA_SAIDA, self._estado_ratecv
        )
        return mono_16k

    def _fechar_fala(self):
        frames = self._frames_16k_da_fala
        self._frames_16k_da_fala = []
        self._falando = False
        duracao_segundos = sum(len(f) for f in frames) / 2 / TAXA_SAIDA
        if duracao_segundos >= DURACAO_MINIMA_FALA_SEGUNDOS:
            self._ao_fechar_fala(self.user, frames)


class SinkVoz(voice_recv.AudioSink):
    """1 instância por sessão/call (ver eris/core/voz_call.py) - `write` é
    chamado pela extensão de voz pra CADA pacote decodificado de CADA
    participante que está falando na call."""

    def __init__(self, ao_fechar_fala):
        super().__init__()
        self._ao_fechar_fala = ao_fechar_fala
        self._buffers = {}

    def wants_opus(self):
        return False  # PCM já decodificado - a extensão faz o decode de Opus pra gente

    def write(self, user, data):
        if user is None:
            return  # SSRC ainda não resolvido pra um membro de verdade - descarta
        buffer = self._buffers.get(user.id)
        if buffer is None:
            buffer = BufferParticipante(user, self._ao_fechar_fala)
            self._buffers[user.id] = buffer
        buffer.receber(data.pcm)

    def cleanup(self):
        self._buffers.clear()
