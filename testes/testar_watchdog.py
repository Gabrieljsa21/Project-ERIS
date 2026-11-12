from eris import watchdog


class _ProcessoFalso:
    def __init__(self, codigo):
        self.codigo = codigo

    def wait(self):
        return self.codigo


def _rodar(monkeypatch, codigos, duracoes):
    codigos, duracoes, esperas, argvs = list(codigos), list(duracoes), [], []
    relogio = [0.0]

    def popen(argv, **_):
        argvs.append(argv)
        relogio[0] += duracoes.pop(0)
        return _ProcessoFalso(codigos.pop(0))

    monkeypatch.setattr(watchdog.subprocess, "Popen", popen)
    monkeypatch.setattr(watchdog.time, "time", lambda: relogio[0])
    watchdog.supervisionar("musica", dormir=esperas.append)
    return esperas, argvs


def testar_crash_seguido_aumenta_backoff_e_fechar_encerra(monkeypatch):
    esperas, argvs = _rodar(monkeypatch, [1, 1, 1, watchdog.EXIT_CODE_FECHAR], [1, 1, 1, 1])
    assert esperas == [5, 15, 45]
    assert argvs[0][-1] == "musica"


def testar_reiniciar_nao_espera(monkeypatch):
    esperas, _ = _rodar(monkeypatch, [watchdog.EXIT_CODE_REINICIAR, watchdog.EXIT_CODE_FECHAR], [1, 1])
    assert esperas == []


def testar_rodar_muito_tempo_reseta_backoff(monkeypatch):
    longo = watchdog.DURACAO_MINIMA_PARA_RESETAR_BACKOFF_SEGUNDOS
    esperas, _ = _rodar(monkeypatch, [1, 1, 1, watchdog.EXIT_CODE_FECHAR], [1, 1, longo, 1])
    assert esperas == [5, 15, 5]
