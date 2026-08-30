# -*- coding: utf-8 -*-
"""Ícone de bandeja do sistema (`pystray`) - dá visibilidade/controle ao ERIS
quando ele roda escondido via `pythonw.exe` (ver `iniciar_eris.bat`/
`iniciar_eris_oculto.vbs`), sem precisar de um terminal aberto pra saber que
o processo está de pé nem pra derrubá-lo (2026-08-30, pedido do usuário: "n
quero terminais abertos p cd bot online, oculta isso").

**Só o papel "completo" mostra ícone (2026-08-30, correção do mesmo dia -
usuário: "Vc criou 2 eris, falei q era p criar apenas 1 contendo as 2")** -
os 2 papéis CONTINUAM processos separados (isolamento de crash preservado
de propósito: o papel "musica" tem histórico real de instabilidade recente,
extraindo o Colecionador pro Project PANDORA - juntar os 2 num processo só
arriscaria derrubar o "completo" junto numa queda do "musica"), mas o
"musica" agora sobe SEM ícone próprio - só um listener de controle remoto
(`PORTA_CONTROLE_MUSICA`) que o menu do "completo" usa pra Reiniciar/Fechar
a instância música à distância. "Ver logs" do "completo" já cobre as 2
(`eris/main.py::_RedirecionadorLog` escreve as 2 no MESMO
`logs/AAAA-MM-DD.log`).

Fechar/Reiniciar (local ou remoto) nunca derruba o processo sem re-erguer
sozinho - `eris/watchdog.py` supervisiona os 2 papéis e decide se reinicia
baseado no código de saída (ver docstring de lá)."""
import asyncio
import datetime
import os
import socket
import threading

from eris import bot
from eris.config import PASTA_PROJETO, PORTA_CONTROLE_MUSICA, PORTA_INSTANCIA_UNICA_MUSICA
from eris.watchdog import EXIT_CODE_FECHAR, EXIT_CODE_REINICIAR

try:
    import pystray
    from PIL import Image
    _TRAY_DISPONIVEL = True
except ImportError:
    _TRAY_DISPONIVEL = False

TIMEOUT_FECHAMENTO_FORCADO_SEGUNDOS = 5.0
TIMEOUT_COMANDO_REMOTO_SEGUNDOS = 3.0

# Ícone oficial do ERIS (a Maçã Dourada da Discórdia, ver README).
CAMINHO_ICONE = os.path.join(PASTA_PROJETO, "assets", "icone_eris.png")

# Código de saída que este processo deve usar quando `asyncio.run(bot.
# iniciar_bot(...))` (chamado por `eris/main.py`) retornar - `main.py` lê
# isso DEPOIS do run() encerrar e sai do processo com ele, pro watchdog
# saber se foi um pedido explícito (reiniciar/fechar) ou uma queda
# inesperada (crash - reinicia com backoff).
_codigo_saida = [0]


def codigo_saida():
    return _codigo_saida[0]


def _carregar_icone():
    try:
        return Image.open(CAMINHO_ICONE)
    except Exception:
        return Image.new("RGBA", (64, 64), (212, 175, 55, 255))


def _abrir_logs():
    caminho_hoje = os.path.join(PASTA_PROJETO, "logs", f"{datetime.date.today().isoformat()}.log")
    alvo = caminho_hoje if os.path.exists(caminho_hoje) else os.path.join(PASTA_PROJETO, "logs")
    try:
        os.startfile(alvo)
    except Exception:
        pass


def _encerrar(icon, codigo):
    """Fecha ESTE processo com `codigo` - usado tanto pelo clique local no
    menu (papel "completo") quanto pelo listener de controle remoto (papel
    "musica", `icon=None`, ver `_escutar_comandos_remotos` abaixo)."""
    _codigo_saida[0] = codigo
    if icon is not None:
        icon.stop()
    loop = bot.loop_atual()
    client = bot.cliente_conectado()
    if loop is not None and client is not None:
        try:
            asyncio.run_coroutine_threadsafe(client.close(), loop)
        except Exception:
            pass
    # Rede de segurança: se o loop do bot não encerrar sozinho a tempo
    # (travado, ou ainda nem conectou), força a saída mesmo assim, JÁ com o
    # código certo (o watchdog decide reiniciar ou não a partir dele).
    threading.Timer(TIMEOUT_FECHAMENTO_FORCADO_SEGUNDOS, lambda: os._exit(codigo)).start()


def _musica_rodando():
    """Sonda `PORTA_INSTANCIA_UNICA_MUSICA` (mesmo truque de `eris/main.py::
    _garantir_instancia_unica` e do `voz_local_supervisor.py` da GAIA) -
    bind falha == já tem alguém escutando == "musica" está de pé."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORTA_INSTANCIA_UNICA_MUSICA))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _enviar_comando_musica(comando):
    try:
        with socket.create_connection(("127.0.0.1", PORTA_CONTROLE_MUSICA), timeout=TIMEOUT_COMANDO_REMOTO_SEGUNDOS) as s:
            s.sendall(f"{comando}\n".encode("utf-8"))
    except OSError:
        pass  # "musica" não está rodando (ou não escutando ainda) - nada a fazer


def _escutar_comandos_remotos():
    """Só o papel "musica" chama isso (ver `iniciar` abaixo) - aceita
    conexões locais de `_enviar_comando_musica` (rodando no processo
    "completo") com uma linha de texto ("FECHAR"/"REINICIAR")."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        servidor.bind(("127.0.0.1", PORTA_CONTROLE_MUSICA))
        servidor.listen(1)
    except OSError:
        print(f" [SISTEMA] Não consegui abrir a porta de controle remoto ({PORTA_CONTROLE_MUSICA}) - Reiniciar/Fechar remoto desabilitado pra esta instância.")
        return

    def _rodar():
        while True:
            try:
                conexao, _ = servidor.accept()
            except OSError:
                return
            with conexao:
                try:
                    comando = conexao.recv(64).decode("utf-8", errors="ignore").strip().upper()
                except OSError:
                    continue
            if comando == "FECHAR":
                _encerrar(None, EXIT_CODE_FECHAR)
            elif comando == "REINICIAR":
                _encerrar(None, EXIT_CODE_REINICIAR)

    threading.Thread(target=_rodar, daemon=True, name="eris-controle-remoto-musica").start()


def _montar_menu():
    status_musica = lambda item: f"Música: {'rodando' if _musica_rodando() else 'parada'}"  # noqa: E731
    return pystray.Menu(
        pystray.MenuItem("ERIS (completo) - rodando", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ver logs (completo + música)", lambda icon, item: _abrir_logs()),
        pystray.MenuItem("Reiniciar", lambda icon, item: _encerrar(icon, EXIT_CODE_REINICIAR)),
        pystray.MenuItem("Fechar", lambda icon, item: _encerrar(icon, EXIT_CODE_FECHAR)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(status_musica, None, enabled=False),
        pystray.MenuItem("Reiniciar música", lambda icon, item: _enviar_comando_musica("REINICIAR")),
        pystray.MenuItem("Fechar música", lambda icon, item: _enviar_comando_musica("FECHAR")),
    )


def iniciar(papel):
    """Chamado por `eris/main.py` pras 2 instâncias - só o papel "completo"
    sobe um ícone de verdade (ver docstring do módulo pro motivo); o
    "musica" só sobe o listener de controle remoto, sem UI nenhuma."""
    if papel != "completo":
        _escutar_comandos_remotos()
        return

    if not _TRAY_DISPONIVEL:
        print(" [SISTEMA] pystray/Pillow não instalados - ícone de bandeja desabilitado (bot continua normal).")
        return

    def _rodar():
        icon = pystray.Icon("eris_completo", _carregar_icone(), "ERIS", _montar_menu())
        icon.run()

    threading.Thread(target=_rodar, daemon=True, name="tray-eris-completo").start()
