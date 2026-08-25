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
import os
import socket
import subprocess
import sys
import threading

from dotenv import load_dotenv

# 🔥 override=True (mesmo motivo já documentado no HESTIA/MOIRAI e corrigido
# na GAIA no mesmo dia, 2026-08-24) - sem isso, uma variável de ambiente
# herdada do processo que lançou o ERIS venceria o `.env` local em silêncio.
load_dotenv(override=True)

from eris import bot, db  # noqa: E402
from eris.api_bridge import iniciar_servidor_api  # noqa: E402
from eris.config import PORTA_INSTANCIA_UNICA  # noqa: E402

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _garantir_instancia_unica():
    global _socket_instancia_unica
    _socket_instancia_unica = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _socket_instancia_unica.bind(("127.0.0.1", PORTA_INSTANCIA_UNICA))
    except OSError:
        print(
            " [SISTEMA] Já existe uma instância do ERIS rodando "
            f"(porta {PORTA_INSTANCIA_UNICA} ocupada) - encerrando esta pra não conectar o mesmo token duas vezes."
        )
        sys.exit(1)


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
    _garantir_instancia_unica()
    _mostrar_versao_boot()

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(" [SISTEMA] DISCORD_BOT_TOKEN não configurado no .env - o ERIS não tem como conectar. Veja .env.example.")
        sys.exit(1)

    db.inicializar()
    ids_bootstrap = [i.strip() for i in os.getenv("DISCORD_OWNER_IDS", "").split(",") if i.strip()]
    db.importar_donos_bootstrap(ids_bootstrap)

    threading.Thread(target=iniciar_servidor_api, args=(token,), daemon=True).start()
    print(" [SISTEMA] ERIS pronto - ponte HTTP na porta 8772, conectando ao Discord...")

    asyncio.run(bot.iniciar_bot(token))


if __name__ == "__main__":
    main()
