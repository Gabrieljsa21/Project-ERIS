# -*- coding: utf-8 -*-
"""Detecção de fala por volume (RMS) - portado de `core/voice/vad.py::VoiceFilterRMS`
(GAIA) em 2026-08-25, na migração do Intérprete/Tutora por voz pro ERIS. Cópia
deliberada (não import cruzado entre repositórios) - o original na GAIA
continua existindo, usado lá pro fallback de VAD do microfone local; esta
cópia é só pra decidir onde uma fala capturada numa call do Discord termina
(ver `eris/core/voz_captura.py`)."""
import numpy as np


class VoiceFilterRMS:
    LIMIAR_RMS = 500

    def calcular_rms(self, audio_data):
        audio_int16 = np.frombuffer(audio_data, dtype=np.int16)
        return np.sqrt(np.mean(audio_int16.astype(np.float64) ** 2))

    def is_human_voice(self, audio_data, rate=16000):
        return self.calcular_rms(audio_data) > self.LIMIAR_RMS
