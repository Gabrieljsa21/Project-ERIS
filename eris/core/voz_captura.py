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


INTERVALO_DIAGNOSTICO_SEGUNDOS = 2.0  # 🔥 ver docstring de _logar_diagnostico abaixo


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
        # 🔥 Diagnóstico (2026-08-25) - achado real: nem ERIS nem GAIA logavam
        # NADA quando a call não respondia, sem dar pra saber se o pacote de
        # áudio sequer chegava até aqui, ou se chegava mas o RMS nunca passava
        # do limiar (LIMIAR_RMS). Log inicial (1x, confirma que o SSRC resolveu
        # pra este usuário e pacotes estão chegando de verdade) + throttle
        # periódico com o RMS de verdade, pra dar pra calibrar LIMIAR_RMS sem
        # florar o log a cada pacote (~50/s por participante).
        print(f" [ERIS] Recebendo áudio de {getattr(user, 'display_name', user)} (SSRC resolvido, começando a capturar).")
        self._ultimo_log_diagnostico = 0.0

    def receber(self, pcm_48k_estereo):
        mono_16k = self._converter(pcm_48k_estereo)
        rms = self._voice_filter.calcular_rms(mono_16k)
        eh_voz = rms > VoiceFilterRMS.LIMIAR_RMS
        agora = time.monotonic()
        self._logar_diagnostico(agora, rms, eh_voz)
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

    def _logar_diagnostico(self, agora, rms, eh_voz):
        if agora - self._ultimo_log_diagnostico < INTERVALO_DIAGNOSTICO_SEGUNDOS:
            return
        self._ultimo_log_diagnostico = agora
        print(f" [ERIS] Diagnóstico voz: RMS={rms:.0f} (limiar {VoiceFilterRMS.LIMIAR_RMS}) - {'detectando fala' if eh_voz else 'silêncio/ruído'}.")

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
            print(f" [ERIS] Fala fechada ({duracao_segundos:.1f}s) - mandando pra GAIA processar.")
            self._ao_fechar_fala(self.user, frames)
        else:
            print(f" [ERIS] Fala fechada curta demais ({duracao_segundos:.1f}s < {DURACAO_MINIMA_FALA_SEGUNDOS}s) - descartada.")


class SinkVoz(voice_recv.AudioSink):
    """1 instância por sessão/call (ver eris/core/voz_call.py) - `write` é
    chamado pela extensão de voz pra CADA pacote decodificado de CADA
    participante que está falando na call."""

    def __init__(self, ao_fechar_fala):
        super().__init__()
        self._ao_fechar_fala = ao_fechar_fala
        self._buffers = {}
        self._ja_avisou_user_none = False

    def wants_opus(self):
        return False  # PCM já decodificado - a extensão faz o decode de Opus pra gente

    def write(self, user, data):
        if user is None:
            # 🔥 Diagnóstico (2026-08-25) - log 1x por sessão (não por pacote,
            # senão floraria o log) pra saber se ESTE é o motivo de nunca
            # capturar nada: SSRC nunca resolvido pra um Member de verdade
            # (precisa do member já em cache - intents.members, ver eris/bot.py).
            if not self._ja_avisou_user_none:
                self._ja_avisou_user_none = True
                print(" [ERIS] Pacote de áudio recebido, mas SSRC ainda não resolveu pra nenhum usuário (descartando) - se isso persistir, o problema é resolução de SSRC, não VAD.")
            return
        buffer = self._buffers.get(user.id)
        if buffer is None:
            buffer = BufferParticipante(user, self._ao_fechar_fala)
            self._buffers[user.id] = buffer
        buffer.receber(data.pcm)

    def cleanup(self):
        self._buffers.clear()
