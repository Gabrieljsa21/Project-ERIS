# -*- coding: utf-8 -*-
"""Constantes compartilhadas do ERIS - extraído da GAIA em 2026-08-24 (ver
`Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md` -> "Project ERIS").

Fronteira do projeto: o ERIS executa tudo que exige conhecer a API/permissões/
funcionamento interno do Discord (conexão, segurança, mensagens, moderação,
exportação, voz como TRANSPORTE) - ele nunca decide conteúdo. Toda decisão de
persona (o que responder, se vale falar algo) continua na GAIA, consultada
por um webhook reverso (`eris/integrations/gaia_webhook.py`) só para as
mensagens que passam pelo filtro local de roteamento (ver
`eris/core/seguranca.py`)."""
import os

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(PASTA_PROJETO, "data")
CAMINHO_BANCO = os.path.join(PASTA_DADOS, "eris.db")
PASTA_EXPORTACOES = os.path.join(PASTA_DADOS, "exportacoes_discord")

PORTA_API_ERIS = 8772
# 🔥 Porta dummy só pra travar instância única (mesmo truque do HESTIA/MOIRAI) -
# checada ANTES de conectar no gateway do Discord, pra uma 2ª instância nem
# chegar a autenticar o MESMO token duas vezes.
PORTA_INSTANCIA_UNICA = 8773

# 🔥 Base do webhook reverso (ERIS -> GAIA) - mesma porta do servidor
# `integrations/iris_bridge.py` que já atende MOIRAI/HESTIA/IRIS (8766), só
# com rotas novas (`/eris/mensagem`, `/eris/comando`). Ajustável via .env pra
# quem roda a GAIA noutra máquina/porta.
URL_BASE_GAIA = os.environ.get("GAIA_WEBHOOK_URL", "http://127.0.0.1:8766")

LIMITE_CARACTERES_MENSAGEM = 2000
ANEXOS_MAX_POR_MENSAGEM = 5
ANEXOS_MAX_BYTES_POR_MENSAGEM = 8 * 1024 * 1024

RATE_LIMIT_JANELA_SEGUNDOS = 60
RATE_LIMIT_MAX_MENSAGENS = 15
