# -*- coding: utf-8 -*-
"""Moderação/administração do servidor - domínio 100% novo do ERIS (não
existia na GAIA antes da extração, pedido do usuário em 2026-08-24 ao
planejar o ERIS). Zero decisão de IA - toda função aqui é mecânica pura de
Discord, chamada pelos slash commands nativos do próprio ERIS
(`eris/bot.py`), nunca pela GAIA.

Toda ação aqui é restrita a DONOS da Galateia (`eris.db.ids_donos_ativos`),
independente de cargo de administrador no servidor - mesma régua de
autorização já usada pro resto do bot (autorização por `id` numérico, não
por cargo/nome). A checagem de autorização é feita por quem chama
(`eris/bot.py`, antes de invocar qualquer função daqui) - este módulo assume
que quem chegou até aqui já foi autorizado.

**Limpar canal** tem uma limitação real da API do Discord: `bulk delete` só
cobre mensagens de até 14 dias; mais antigas exigem exclusão uma a uma (mais
lenta, sujeita a rate limit). É irreversível, então exige `confirmar=True`
explícito - sem isso, só devolve o aviso, sem apagar nada."""
import datetime

import discord

from eris import db
from eris.core import mensagens

LIMITE_BULK_DELETE_DIAS = 14


def _registrar(ator_id, acao, alvo=None, guild_id=None, detalhe=None):
    db.registrar_auditoria(datetime.datetime.now(datetime.timezone.utc).isoformat(), ator_id, acao, alvo, guild_id, detalhe)


# --------------------------------------------------------------------------
# Moderação de membros
# --------------------------------------------------------------------------

async def kick_membro(guild, membro_id, motivo, ator_id):
    try:
        membro = await guild.fetch_member(int(membro_id))
    except discord.NotFound:
        return False, "Membro não encontrado nesse servidor."
    try:
        await membro.kick(reason=motivo or None)
    except discord.Forbidden:
        return False, "Sem permissão \"Expulsar Membros\" (ou o cargo do membro é mais alto que o do bot)."
    except Exception as e:
        return False, f"Erro ao expulsar: {e}"
    _registrar(ator_id, "kick", str(membro_id), guild.id, motivo)
    return True, f"{membro.display_name} expulso."


async def ban_membro(guild, membro_id, motivo, ator_id, dias_apagar_mensagens=0):
    try:
        await guild.ban(discord.Object(id=int(membro_id)), reason=motivo or None, delete_message_days=max(0, min(7, dias_apagar_mensagens)))
    except discord.Forbidden:
        return False, "Sem permissão \"Banir Membros\" (ou o cargo do membro é mais alto que o do bot)."
    except Exception as e:
        return False, f"Erro ao banir: {e}"
    _registrar(ator_id, "ban", str(membro_id), guild.id, motivo)
    return True, "Membro banido."


async def desbanir_membro(guild, membro_id, ator_id):
    try:
        await guild.unban(discord.Object(id=int(membro_id)))
    except discord.NotFound:
        return False, "Esse ID não está banido nesse servidor."
    except Exception as e:
        return False, f"Erro ao desbanir: {e}"
    _registrar(ator_id, "unban", str(membro_id), guild.id)
    return True, "Membro desbanido."


async def timeout_membro(guild, membro_id, minutos, motivo, ator_id):
    try:
        membro = await guild.fetch_member(int(membro_id))
    except discord.NotFound:
        return False, "Membro não encontrado nesse servidor."
    ate = discord.utils.utcnow() + datetime.timedelta(minutes=max(1, minutos))
    try:
        await membro.timeout(ate, reason=motivo or None)
    except discord.Forbidden:
        return False, "Sem permissão \"Silenciar Membros\" (Moderate Members)."
    except Exception as e:
        return False, f"Erro ao aplicar timeout: {e}"
    _registrar(ator_id, "timeout", str(membro_id), guild.id, f"{minutos}min - {motivo or ''}")
    return True, f"{membro.display_name} em timeout por {minutos} minuto(s)."


async def remover_timeout(guild, membro_id, ator_id):
    try:
        membro = await guild.fetch_member(int(membro_id))
        await membro.timeout(None)
    except discord.NotFound:
        return False, "Membro não encontrado nesse servidor."
    except Exception as e:
        return False, f"Erro ao remover timeout: {e}"
    _registrar(ator_id, "remover_timeout", str(membro_id), guild.id)
    return True, "Timeout removido."


async def advertir_membro(guild, membro_id, motivo, ator_id):
    """Sem API nativa de "warn" no Discord - fica só na nossa auditoria
    (`eris.db.listar_auditoria`) + DM opcional avisando a pessoa, best-effort
    (não falha a advertência se a DM não puder ser entregue - conta
    bloqueada/fechada pra DM de estranho é comum)."""
    _registrar(ator_id, "advertencia", str(membro_id), guild.id, motivo)
    try:
        membro = await guild.fetch_member(int(membro_id))
        await membro.send(f"Você recebeu uma advertência em {guild.name}. Motivo: {motivo or '(sem motivo informado)'}")
    except Exception:
        pass
    return True, "Advertência registrada."


# --------------------------------------------------------------------------
# Moderação de mensagens
# --------------------------------------------------------------------------

async def fixar_mensagem(channel, message_id, ator_id):
    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.pin()
    except Exception as e:
        return False, f"Erro ao fixar: {e}"
    _registrar(ator_id, "fixar_mensagem", str(message_id), channel.guild.id if channel.guild else None)
    return True, "Mensagem fixada."


async def desfixar_mensagem(channel, message_id, ator_id):
    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.unpin()
    except Exception as e:
        return False, f"Erro ao desfixar: {e}"
    _registrar(ator_id, "desfixar_mensagem", str(message_id), channel.guild.id if channel.guild else None)
    return True, "Mensagem desfixada."


async def deletar_mensagem(channel, message_id, ator_id):
    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.delete()
    except Exception as e:
        return False, f"Erro ao deletar: {e}"
    _registrar(ator_id, "deletar_mensagem", str(message_id), channel.guild.id if channel.guild else None)
    return True, "Mensagem deletada."


async def definir_modo_lento(channel, segundos, ator_id):
    try:
        await channel.edit(slowmode_delay=max(0, min(21600, segundos)))
    except Exception as e:
        return False, f"Erro ao definir modo lento: {e}"
    _registrar(ator_id, "modo_lento", detalhe=f"{segundos}s", guild_id=channel.guild.id if channel.guild else None)
    if segundos <= 0:
        return True, "Modo lento desligado."
    return True, f"Modo lento definido pra {segundos}s."


async def limpar_canal(channel, quantidade, ator_id, confirmar):
    """Bulk delete das `quantidade` mensagens mais recentes - **irreversível**,
    por isso exige `confirmar=True` explícito (o slash command em
    `eris/bot.py` só passa True se o usuário chamou o comando com o
    argumento de confirmação). Só cobre mensagens de até 14 dias (limite da
    própria API pra bulk delete) - mensagens mais antigas dentro da faixa
    pedida são silenciosamente ignoradas pelo Discord, não geram erro."""
    if not confirmar:
        return False, (
            f"Isso vai apagar até {quantidade} mensagem(ns) de #{channel.name} PRA SEMPRE - "
            "ação não pode ser desfeita. Rode o comando de novo com confirmar:true pra seguir."
        )
    limite_data = discord.utils.utcnow() - datetime.timedelta(days=LIMITE_BULK_DELETE_DIAS)
    try:
        apagadas = await channel.purge(limit=max(1, min(1000, quantidade)), after=limite_data)
    except discord.Forbidden:
        return False, "Sem permissão \"Gerenciar Mensagens\" nesse canal."
    except Exception as e:
        return False, f"Erro ao limpar o canal: {e}"
    _registrar(ator_id, "limpar_canal", guild_id=channel.guild.id if channel.guild else None, detalhe=f"{len(apagadas)} mensagens")
    aviso_idade = "" if quantidade <= len(apagadas) else " (mensagens com mais de 14 dias não são apagadas em massa pela API do Discord)"
    return True, f"{len(apagadas)} mensagem(ns) apagada(s) em #{channel.name}.{aviso_idade}"


# --------------------------------------------------------------------------
# Controle de canal
# --------------------------------------------------------------------------

async def bloquear_canal(channel, ator_id):
    try:
        await channel.set_permissions(channel.guild.default_role, send_messages=False)
    except Exception as e:
        return False, f"Erro ao bloquear o canal: {e}"
    _registrar(ator_id, "bloquear_canal", guild_id=channel.guild.id)
    return True, f"#{channel.name} bloqueado - ninguém sem permissão extra consegue mandar mensagem."


async def desbloquear_canal(channel, ator_id):
    try:
        await channel.set_permissions(channel.guild.default_role, send_messages=None)
    except Exception as e:
        return False, f"Erro ao desbloquear o canal: {e}"
    _registrar(ator_id, "desbloquear_canal", guild_id=channel.guild.id)
    return True, f"#{channel.name} desbloqueado."


async def criar_canal(guild, nome, categoria_id, ator_id):
    from eris.core.mensagens import nome_canal_valido
    categoria = guild.get_channel(int(categoria_id)) if categoria_id else None
    try:
        canal = await guild.create_text_channel(nome_canal_valido(nome), category=categoria)
    except Exception as e:
        return False, f"Erro ao criar o canal: {e}"
    _registrar(ator_id, "criar_canal", str(canal.id), guild.id, nome)
    return True, f"Canal #{canal.name} criado."


async def renomear_canal(channel, novo_nome, ator_id):
    from eris.core.mensagens import nome_canal_valido
    nome_antigo = channel.name
    try:
        await channel.edit(name=nome_canal_valido(novo_nome))
    except Exception as e:
        return False, f"Erro ao renomear: {e}"
    _registrar(ator_id, "renomear_canal", str(channel.id), channel.guild.id, f"{nome_antigo} -> {channel.name}")
    return True, f"Canal renomeado pra #{channel.name}."


async def arquivar_canal(channel, ator_id):
    """Discord não tem "arquivar" nativo pra canal de texto comum (só pra
    threads/fórum) - aqui significa mover pra uma categoria "📦 Arquivados"
    (criada se não existir) e bloquear envio de mensagem, mesma ideia de
    "guardar sem apagar"."""
    guild = channel.guild
    categoria_arquivo = discord.utils.find(lambda c: c.name == "📦 Arquivados", guild.categories)
    try:
        if categoria_arquivo is None:
            categoria_arquivo = await guild.create_category("📦 Arquivados")
        await channel.edit(category=categoria_arquivo)
        await channel.set_permissions(guild.default_role, send_messages=False)
    except Exception as e:
        return False, f"Erro ao arquivar: {e}"
    _registrar(ator_id, "arquivar_canal", str(channel.id), guild.id)
    return True, f"#{channel.name} movido pra \"📦 Arquivados\" e bloqueado."


# --------------------------------------------------------------------------
# Cargos
# --------------------------------------------------------------------------

async def atribuir_cargo(guild, membro_id, cargo_id, ator_id):
    try:
        membro = await guild.fetch_member(int(membro_id))
        cargo = guild.get_role(int(cargo_id))
        if cargo is None:
            return False, "Cargo não encontrado nesse servidor."
        await membro.add_roles(cargo)
    except discord.Forbidden:
        return False, "Sem permissão \"Gerenciar Cargos\" (ou o cargo é mais alto que o do bot)."
    except Exception as e:
        return False, f"Erro ao atribuir cargo: {e}"
    _registrar(ator_id, "atribuir_cargo", str(membro_id), guild.id, cargo.name)
    return True, f"Cargo \"{cargo.name}\" atribuído a {membro.display_name}."


async def remover_cargo(guild, membro_id, cargo_id, ator_id):
    try:
        membro = await guild.fetch_member(int(membro_id))
        cargo = guild.get_role(int(cargo_id))
        if cargo is None:
            return False, "Cargo não encontrado nesse servidor."
        await membro.remove_roles(cargo)
    except discord.Forbidden:
        return False, "Sem permissão \"Gerenciar Cargos\" (ou o cargo é mais alto que o do bot)."
    except Exception as e:
        return False, f"Erro ao remover cargo: {e}"
    _registrar(ator_id, "remover_cargo", str(membro_id), guild.id, cargo.name)
    return True, f"Cargo \"{cargo.name}\" removido de {membro.display_name}."
