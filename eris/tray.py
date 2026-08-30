# -*- coding: utf-8 -*-
"""Ícone de bandeja do sistema (`pystray`) - dá visibilidade/controle ao ERIS
quando ele roda escondido via `pythonw.exe` (ver `iniciar_eris.bat`/
`iniciar_eris_oculto.vbs`), sem precisar de um terminal aberto pra saber que
o processo está de pé nem pra derrubá-lo (2026-08-30, pedido do usuário: "n
quero terminais abertos p cd bot online, oculta isso").

Cada instância (papel "completo" ou "musica", ver `eris/main.py`) sobe o
PRÓPRIO ícone, numa thread daemon separada do loop asyncio do bot - `pystray`
no Windows só precisa de uma mensagem de loop própria, não do event loop do
asyncio (mesmo motivo que o `api_bridge.py` roda em thread separada e
despacha pro loop do bot via `run_coroutine_threadsafe`)."""
import asyncio
import datetime
import os
import subprocess
import sys
import threading

from eris import bot
from eris.config import PASTA_PROJETO

try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_DISPONIVEL = True
except ImportError:
    _TRAY_DISPONIVEL = False

TIMEOUT_FECHAMENTO_FORCADO_SEGUNDOS = 5.0

# Dourado (Maçã Dourada da Discórdia, ver README) pro papel "completo" -
# roxo pro "musica", só pra diferenciar os 2 ícones de relance na bandeja.
_COR_POR_PAPEL = {
    "completo": (212, 175, 55, 255),
    "musica": (155, 89, 182, 255),
}


def _gerar_icone(papel):
    cor = _COR_POR_PAPEL.get(papel, (120, 120, 120, 255))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)
    desenho.ellipse((4, 4, 60, 60), fill=cor, outline=(30, 30, 30, 255), width=3)
    letra = "E"
    try:
        from PIL import ImageFont
        fonte = ImageFont.load_default(size=34)
    except Exception:
        fonte = None
    caixa = desenho.textbbox((0, 0), letra, font=fonte) if fonte else (0, 0, 20, 26)
    largura_letra, altura_letra = caixa[2] - caixa[0], caixa[3] - caixa[1]
    posicao = ((64 - largura_letra) / 2 - caixa[0], (64 - altura_letra) / 2 - caixa[1])
    desenho.text(posicao, letra, fill=(30, 30, 30, 255), font=fonte)
    return img


def _abrir_logs():
    caminho_hoje = os.path.join(PASTA_PROJETO, "logs", f"{datetime.date.today().isoformat()}.log")
    alvo = caminho_hoje if os.path.exists(caminho_hoje) else os.path.join(PASTA_PROJETO, "logs")
    try:
        os.startfile(alvo)
    except Exception:
        pass


def _fechar_processo(icon):
    icon.stop()
    loop = bot.loop_atual()
    client = bot.cliente_conectado()
    if loop is not None and client is not None:
        try:
            asyncio.run_coroutine_threadsafe(client.close(), loop)
        except Exception:
            pass
    # Rede de segurança: se o loop do bot não encerrar sozinho a tempo
    # (travado, ou ainda nem conectou), força a saída mesmo assim - o
    # usuário clicou "Fechar", o processo tem que morrer.
    threading.Timer(TIMEOUT_FECHAMENTO_FORCADO_SEGUNDOS, lambda: os._exit(0)).start()


def _reiniciar_processo(icon, papel):
    argv = [sys.executable, "-m", "eris.main"]
    if papel == "musica":
        argv.append("musica")
    try:
        subprocess.Popen(argv, cwd=PASTA_PROJETO, close_fds=True)
    except Exception:
        pass
    _fechar_processo(icon)


def iniciar_tray(papel):
    """Sobe o ícone de bandeja desta instância numa thread daemon - não
    bloqueia quem chamou. Silencioso (não derruba o bot) se `pystray`/`Pillow`
    não estiverem instalados - ver `pyproject.toml`."""
    if not _TRAY_DISPONIVEL:
        print(" [SISTEMA] pystray/Pillow não instalados - ícone de bandeja desabilitado (bot continua normal).")
        return

    def _rodar():
        rotulo = "completo" if papel == "completo" else "música"
        menu = pystray.Menu(
            pystray.MenuItem(f"ERIS ({rotulo}) - rodando", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ver logs", lambda icon, item: _abrir_logs()),
            pystray.MenuItem("Reiniciar", lambda icon, item: _reiniciar_processo(icon, papel)),
            pystray.MenuItem("Fechar", lambda icon, item: _fechar_processo(icon)),
        )
        icon = pystray.Icon(f"eris_{papel}", _gerar_icone(papel), f"ERIS ({rotulo})", menu)
        icon.run()

    threading.Thread(target=_rodar, daemon=True, name=f"tray-eris-{papel}").start()
