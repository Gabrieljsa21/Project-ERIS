# -*- coding: utf-8 -*-
"""Segurança e filtro de roteamento do ERIS - extraído de
`features/discord_presence/discord_bot.py` (GAIA, antes da extração de
2026-08-24). Duas responsabilidades que ficam SEMPRE no ERIS, nunca na GAIA:

1. **Autorização** - quem é dono (acesso total), rate limit genérico contra
   flood/abuso de quem não é dono, bloqueio de bot/webhook. Autorização é
   sempre por `message.author.id` (snowflake numérico, não falsificável via
   API oficial) - nome/nickname/avatar nunca decidem permissão.
2. **Filtro de "vale a pena chamar a persona?"** - decide se uma mensagem
   deveria virar uma pergunta pro webhook reverso da GAIA, ANTES de gastar
   uma chamada de rede. Sem isso, toda mensagem de todo servidor onde o bot
   está (inclusive os desativados) viajaria até a GAIA só pra ela dizer
   "ignora essa" - desperdício e um problema de escopo (a GAIA não devia
   nem VER mensagem de servidor desativado)."""
import time
from collections import deque

from eris import db
from eris.config import RATE_LIMIT_JANELA_SEGUNDOS, RATE_LIMIT_MAX_MENSAGENS

_mensagens_por_remetente = {}
_ultimo_aviso_limite = {}


def limite_excedido(remetente_id):
    """Registra a mensagem atual de `remetente_id` e devolve True se ele
    passou de RATE_LIMIT_MAX_MENSAGENS na última janela de
    RATE_LIMIT_JANELA_SEGUNDOS. NUNCA vale pro dono (checar `eh_dono` antes
    de chamar) - a intenção é limitar gente de fora, nunca travar o próprio
    controle remoto."""
    agora = time.monotonic()
    fila = _mensagens_por_remetente.setdefault(remetente_id, deque())
    fila.append(agora)
    while fila and agora - fila[0] > RATE_LIMIT_JANELA_SEGUNDOS:
        fila.popleft()
    return len(fila) > RATE_LIMIT_MAX_MENSAGENS


def deveria_avisar_limite(remetente_id):
    """True só a 1ª vez que o limite é excedido dentro da janela - evita
    mandar o aviso de novo a cada mensagem excedente enquanto quem está
    floodando continua mandando."""
    agora = time.monotonic()
    if agora - _ultimo_aviso_limite.get(remetente_id, 0) > RATE_LIMIT_JANELA_SEGUNDOS:
        _ultimo_aviso_limite[remetente_id] = agora
        return True
    return False


def eh_dono(remetente_id):
    return str(remetente_id) in db.ids_donos_ativos()


def nome_bate_alvo(nome_configurado, nome_exibicao, nome_usuario):
    nome_configurado = (nome_configurado or "").strip().lstrip("@").lower()
    if not nome_configurado:
        return False
    return nome_configurado in (nome_exibicao or "").lower() or nome_configurado in (nome_usuario or "").lower()


def deve_processar_mensagem(*, eh_bot_ou_webhook, em_dm, guild_id, mencionada, nome_exibicao, nome_usuario):
    """Decide se uma mensagem (já filtrada por rate limit) deveria virar uma
    chamada ao webhook reverso da GAIA. Mensagem de bot/webhook nunca passa -
    `message.author.bot` já cobre webhook disfarçado (webhook só existe em
    canal de servidor, sempre chega com `author.bot=True` ou `webhook_id`).
    Em DM, sempre processa (mesmo padrão de sempre - controle remoto e
    conversa por DM não têm toggle de servidor). Em servidor, só processa se
    o master switch (`discord_active`) estiver ligado, o servidor não estiver
    na lista de desativados, e (mencionada OU "responder livremente" OU bate
    o nome do usuário em foco)."""
    if eh_bot_ou_webhook:
        return False
    cfg = db.obter_config_roteamento()
    if not cfg["discord_active"]:
        return False
    if em_dm:
        return True
    if guild_id is not None and str(guild_id) in set(cfg["disabled_guilds"]):
        return False
    return bool(
        cfg["server_active"]
        or (cfg["mentions"] and mencionada)
        or (cfg["target_user_active"] and nome_bate_alvo(cfg["target_user_name"], nome_exibicao, nome_usuario))
    )
