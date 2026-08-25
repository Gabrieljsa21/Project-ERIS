# -*- coding: utf-8 -*-
"""Entry point standalone do ERIS (`python -m eris.main`) - extraído da GAIA
em 2026-08-24 (ver `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`
-> "Project ERIS"). Diferente do HESTIA (sem loop próprio) e igual ao
MOIRAI: o ERIS tem um loop de vida própria de verdade (a conexão com o
Discord), continua rodando/respondendo moderação e exportação mesmo se a
GAIA estiver fechada - só a conversa/comandos que dependem de conteúdo
ficam indisponíveis nesse caso (ver `eris/bot.py`)."""
import asyncio
import os
import socket
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

_socket_instancia_unica = None


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


def main():
    _garantir_instancia_unica()

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
