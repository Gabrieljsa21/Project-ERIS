# -*- coding: utf-8 -*-
"""Entry point standalone do ERIS (`python -m eris.main`) - extraído da GAIA
em 2026-08-24 (ver `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`
-> "Project ERIS"). Diferente do HESTIA (sem loop próprio) e igual ao
MOIRAI: o ERIS tem um loop de vida própria de verdade (a conexão com o
Discord), continua rodando/respondendo moderação e exportação mesmo se a
GAIA estiver fechada - só a conversa/comandos que dependem de conteúdo
ficam indisponíveis nesse caso (ver `eris/bot.py`)."""
import asyncio
import datetime
import logging
import os
import socket
import subprocess
import sys
import threading

from dotenv import load_dotenv

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 🔥 Papel desta instância - "completo" (padrão, bot único de sempre) ou
# "musica" (2ª instância, bot Discord PRÓPRIO dedicado só ao Modo Música -
# 2026-08-26, pedido do usuário: "esse novo bot devo fazer p ERIS? O primeiro
# é da GAIA" -> sim, 2ª instância do MESMO projeto ERIS, token diferente).
# Detectado por argv (`python -m eris.main musica`) em vez de variável de
# ambiente - evita colidir com o `override=True` do load_dotenv abaixo (ver
# `.env.musica.example`).
PAPEL = "musica" if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "musica" else "completo"
_ARQUIVO_ENV = ".env.musica" if PAPEL == "musica" else ".env"

# 🔥 override=True (mesmo motivo já documentado no HESTIA/MOIRAI e corrigido
# na GAIA no mesmo dia, 2026-08-24) - sem isso, uma variável de ambiente
# herdada do processo que lançou o ERIS venceria o `.env`/`.env.musica` local
# em silêncio.
load_dotenv(os.path.join(PASTA_PROJETO, _ARQUIVO_ENV), override=True)

from eris import bot, db, tray  # noqa: E402
from eris.api_bridge import iniciar_servidor_api  # noqa: E402
from eris.config import PORTA_INSTANCIA_UNICA, PORTA_INSTANCIA_UNICA_MUSICA  # noqa: E402
from eris.watchdog import EXIT_CODE_FECHAR  # noqa: E402

_socket_instancia_unica = None


class _RedirecionadorLog:
    """Espelha stdout/stderr pra `logs/AAAA-MM-DD.log` (reabre sozinho se o
    processo atravessar a meia-noite) - achado real 2026-08-25, depurando por
    que o Modo Conversa não respondia numa call: `pythonw.exe` (sem console,
    como o ERIS sempre roda em produção) descarta todo `print()` no vazio, e
    não sobra NENHUM registro pra diagnosticar o que deu errado aqui (do lado
    da GAIA só se vê o efeito - "não chegou pedido nenhum" - nunca a causa).
    Mesmo espírito do `LogRedirector` da GAIA (`ui/qt_painel.py`), bem mais
    simples - sem widget de Painel pra espelhar (o ERIS não tem GUI)."""

    def __init__(self, stream_original):
        self._stream_original = stream_original
        self._arquivo = None
        self._data_arquivo = None

    def _garantir_arquivo(self):
        hoje = datetime.date.today().isoformat()
        if self._arquivo is not None and self._data_arquivo == hoje:
            return
        if self._arquivo is not None:
            try:
                self._arquivo.close()
            except Exception:
                pass
        try:
            pasta_logs = os.path.join(PASTA_PROJETO, "logs")
            os.makedirs(pasta_logs, exist_ok=True)
            self._arquivo = open(os.path.join(pasta_logs, f"{hoje}.log"), "a", encoding="utf-8")
            self._data_arquivo = hoje
        except Exception:
            self._arquivo = None

    def write(self, texto):
        if self._stream_original:
            try:
                self._stream_original.write(texto)
            except Exception:
                pass
        self._garantir_arquivo()
        if self._arquivo:
            try:
                self._arquivo.write(texto)
                self._arquivo.flush()
            except Exception:
                pass

    def flush(self):
        for destino in (self._stream_original, self._arquivo):
            if destino:
                try:
                    destino.flush()
                except Exception:
                    pass


def _ativar_log_em_disco():
    sys.stdout = _RedirecionadorLog(sys.stdout)
    sys.stderr = _RedirecionadorLog(sys.stderr)


def _ativar_log_debug_voice_recv():
    """DEBUG só do `discord.ext.voice_recv` (não do discord.py inteiro - o
    gateway de texto sozinho já loga heartbeat a cada ~40s, ruído demais pra
    esse fim) - achado real 2026-08-25: os logs pontuais de `voz_captura.py`
    (RMS/fala fechada) confirmaram que a call conecta e ativa a escuta sem
    erro nenhum, mas NENHUM pacote chega no nosso Sink - nem o aviso de "SSRC
    não resolvido" dispara. A própria lib loga em DEBUG se um pacote chegou e
    foi IGNORADO (`PacketRouter.feed_rtp`: "Ignoring packet from dropped ssrc
    %s") - sem ligar isso, não dá pra distinguir "pacote nunca chegou no
    soquete" (rede/firewall) de "chegou mas foi descartado antes do Sink"
    (bug na própria lib/versão). Chamado SÓ depois de _ativar_log_em_disco -
    precisa que sys.stdout já seja o _RedirecionadorLog, pra este handler
    escrever no mesmo lugar."""
    logger = logging.getLogger("discord.ext.voice_recv")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [voice_recv debug] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)


def _garantir_instancia_unica():
    global _socket_instancia_unica
    porta = PORTA_INSTANCIA_UNICA_MUSICA if PAPEL == "musica" else PORTA_INSTANCIA_UNICA
    _socket_instancia_unica = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _socket_instancia_unica.bind(("127.0.0.1", porta))
    except OSError:
        print(
            f" [SISTEMA] Já existe uma instância do ERIS (papel \"{PAPEL}\") rodando "
            f"(porta {porta} ocupada) - encerrando esta pra não conectar o mesmo token duas vezes."
        )
        # 🔥 EXIT_CODE_FECHAR (não 1) - sob eris/watchdog.py (2026-08-30), um
        # código de saída genérico faria o watchdog achar que foi um crash e
        # tentar de novo pra sempre (com backoff), perdendo a corrida contra
        # a instância real de novo a cada vez. Isso NÃO foi uma falha
        # transitória - watchdog não deve reinicar.
        sys.exit(EXIT_CODE_FECHAR)


def _mostrar_versao_boot():
    """Mesmo raciocínio do `run.py` da GAIA (2026-08-25) - Python nunca
    recarrega código sozinho, então um ERIS de pé pode estar rodando uma
    versão bem mais antiga do que o código no disco agora, sem nenhum
    aviso visual óbvio. Falha em silêncio se `git` não estiver disponível."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PASTA_PROJETO,
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        resumo = subprocess.run(
            ["git", "log", "-1", "--format=%cd %s", "--date=format:%d/%m %H:%M"], cwd=PASTA_PROJETO,
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if commit:
            print(f" [SISTEMA] Código carregado: commit {commit} - {resumo}")
    except Exception:
        pass


def main():
    _ativar_log_em_disco()
    _ativar_log_debug_voice_recv()
    _garantir_instancia_unica()
    _mostrar_versao_boot()

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(f" [SISTEMA] DISCORD_BOT_TOKEN não configurado no {_ARQUIVO_ENV} - o ERIS não tem como conectar. Veja .env.example/.env.musica.example.")
        # 🔥 EXIT_CODE_FECHAR - mesmo motivo do _garantir_instancia_unica
        # acima: token ausente é erro de configuração, não crash transitório;
        # o watchdog não deve ficar tentando de novo pra sempre.
        sys.exit(EXIT_CODE_FECHAR)

    if PAPEL == "completo":
        db.inicializar()
        ids_bootstrap = [i.strip() for i in os.getenv("DISCORD_OWNER_IDS", "").split(",") if i.strip()]
        db.importar_donos_bootstrap(ids_bootstrap)
        threading.Thread(target=iniciar_servidor_api, args=(token,), daemon=True).start()
        print(" [SISTEMA] ERIS pronto - ponte HTTP na porta 8772, conectando ao Discord...")
    else:
        # 🔥 Papel "musica" não precisa de `db` (sem moderação/donos) nem da
        # ponte HTTP (`api_bridge.py`, porta 8772 já em uso pela instância
        # "completo") - a GAIA nunca chama DENTRO dessa instância, só ela
        # chamando a GAIA (`gaia_webhook.pedir_proxima_musica`).
        print(" [SISTEMA] ERIS (papel música) pronto - conectando ao Discord...")

    # 🔥 Ícone de bandeja (2026-08-30) - o ERIS roda em produção via
    # pythonw.exe (sem console, ver iniciar_eris.bat/iniciar_eris_oculto.vbs).
    # Só o papel "completo" mostra ícone de verdade (usuário: "falei q era p
    # criar apenas 1 [icone] contendo as 2") - "musica" só sobe o listener de
    # controle remoto que esse ícone usa pra Reiniciar/Fechar à distância,
    # ver eris/tray.py.
    tray.iniciar(PAPEL)

    asyncio.run(bot.iniciar_bot(token, papel=PAPEL))
    # 🔥 `run()` só retorna depois de `client.close()` (pedido local pelo tray
    # ou remoto via socket) - `tray.codigo_saida()` diz ao watchdog externo
    # (`eris/watchdog.py`) se foi um pedido explícito (reiniciar/fechar) ou
    # uma queda inesperada (0 == nenhum dos dois pediu, trata como crash).
    sys.exit(tray.codigo_saida())


if __name__ == "__main__":
    main()
