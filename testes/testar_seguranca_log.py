"""Teste isolado do scrubber, sem ler logs ou dados reais."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eris import seguranca_log


def testar_valor_configurado(monkeypatch=None):
    segredo = "token-super-secreto-123"
    anterior = os.environ.get("DISCORD_BOT_TOKEN")
    os.environ["DISCORD_BOT_TOKEN"] = segredo
    try:
        limpo = seguranca_log.limpar_segredos(f"Falha usando {segredo}")
        assert segredo not in limpo
        assert seguranca_log.MASCARA in limpo
    finally:
        if anterior is None:
            os.environ.pop("DISCORD_BOT_TOKEN", None)
        else:
            os.environ["DISCORD_BOT_TOKEN"] = anterior


def testar_formato_discord_sem_variavel():
    token = "A" * 24 + "." + "B" * 6 + "." + "C" * 27
    limpo = seguranca_log.limpar_segredos(token)
    assert token not in limpo
    assert limpo == seguranca_log.MASCARA


if __name__ == "__main__":
    testar_valor_configurado()
    testar_formato_discord_sem_variavel()
    print("PASS: segredos mascarados no log")
