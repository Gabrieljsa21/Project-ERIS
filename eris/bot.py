# -*- coding: utf-8 -*-
"""Conexão/gateway do ERIS - extraído de
`features/discord_presence/discord_bot.py::iniciar_bot` (GAIA, antes da
extração de 2026-08-24). Diferença central em relação ao original: aqui
NUNCA se chama `processar_ia`/qualquer handler de ação direto - toda
mensagem que passa pelo filtro de roteamento (`eris.core.seguranca`) é
encaminhada pro webhook reverso da GAIA (`eris.integrations.gaia_webhook`),
que devolve o texto de resposta. O ERIS decide SE vale perguntar; a GAIA
decide O QUE responder. Mesmo princípio vale pro Modo Intérprete/Tutora por
voz (migrados em 2026-08-25, ver `eris/core/voz_call.py`): o ERIS entra na
call e captura/toca áudio, a GAIA transcreve/traduz/sintetiza."""
import asyncio
import re
import time

import discord
from discord import app_commands

from eris import db
from eris.core import mensagens, moderacao, seguranca, voz_call
from eris.integrations import gaia_webhook

# 🔥 Gatilho por menção pros 3 modos de voz (portado de discord_bot.py,
# Conversa adicionada em 2026-08-25) - "@Gala entra"/"@Gala conversa" pra
# bate-papo comum, "@Gala traduz" especificamente pro Intérprete, "@Gala sai"
# pra sair (de qualquer um dos 3, ver voz_call.sair_qualquer). Casa em
# qualquer lugar da frase - não precisa ser a frase inteira. Só o dono aciona
# (mesma trava de segurança de qualquer ação real do sistema), e roda ANTES do
# filtro normal de roteamento - entrar/sair da call não é "conversa livre", é
# comando, então funciona mesmo com "Responder livremente"/"menções" desligado.
# 🔥 ORDEM IMPORTA: Intérprete exige palavra EXPLÍCITA de tradução - "entra"
# sozinho (sem "traduz") NÃO é mais Intérprete (bug real 2026-08-25: "@Gala
# entra na call" sempre acionava o Intérprete, mesmo quem só queria bater um
# papo comum) - checado primeiro pra vencer se as duas palavras aparecerem
# juntas ("entra e traduz"). "entra"/"entrar" bem genérico agora vira Conversa,
# que é o comportamento que a maioria espera de um "entra" sem qualificação.
_PADRAO_INTERPRETE_ENTRAR = re.compile(r'\b(traduz|traduzir|tradução|tradutor|intérprete|interprete)\b', re.IGNORECASE)
_PADRAO_CONVERSA_ENTRAR = re.compile(r'\b(entra|entrar|conversa|conversar|bate.?papo)\b', re.IGNORECASE)
_PADRAO_SAIR = re.compile(r'\bsai(r)?\b', re.IGNORECASE)

_client_atual = None
_loop_atual = None
_slash_ja_sincronizado = False


def cliente_conectado():
    return _client_atual


def loop_atual():
    """Loop asyncio do bot - usado por `eris/api_bridge.py` (rodando numa
    THREAD separada) pra despachar uma coroutine (ex.: `notificar_donos`) de
    fora do loop assíncrono, via `asyncio.run_coroutine_threadsafe`."""
    return _loop_atual


def _guilds_para_cache(client):
    return [{"id": str(g.id), "name": g.name} for g in client.guilds]


async def _somente_dono(interaction):
    """Devolve True se autorizado (e já respondeu ephemeral + False se não).
    Toda ação de moderação do ERIS passa por aqui - régua fixa de sempre:
    dono da Galateia, nunca cargo de administrador do servidor."""
    if not seguranca.eh_dono(interaction.user.id):
        await interaction.response.send_message("Esse comando é só pra dono da Galateia.", ephemeral=True)
        return False
    return True


async def _responder_resultado(interaction, ok, mensagem):
    if not interaction.response.is_done():
        await interaction.response.send_message(mensagem, ephemeral=not ok)
    else:
        await interaction.followup.send(mensagem, ephemeral=not ok)


def _registrar_slash_moderacao(tree):
    grupo_mod = app_commands.Group(name="moderacao", description="Moderação de membros")
    grupo_msg = app_commands.Group(name="mensagem", description="Moderação de mensagens")
    grupo_canal = app_commands.Group(name="canal", description="Controle de canal")
    grupo_cargo = app_commands.Group(name="cargo", description="Atribuir/remover cargo")

    @grupo_mod.command(name="kick", description="Expulsa um membro do servidor")
    async def _kick(interaction: discord.Interaction, membro: discord.Member, motivo: str = ""):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.kick_membro(interaction.guild, membro.id, motivo, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_mod.command(name="ban", description="Bane um membro do servidor")
    async def _ban(interaction: discord.Interaction, membro: discord.Member, motivo: str = "", apagar_mensagens_dias: int = 0):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.ban_membro(interaction.guild, membro.id, motivo, interaction.user.id, apagar_mensagens_dias)
        await _responder_resultado(interaction, ok, msg)

    @grupo_mod.command(name="desbanir", description="Remove o banimento de um ID de usuário")
    async def _unban(interaction: discord.Interaction, id_usuario: str):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.desbanir_membro(interaction.guild, id_usuario, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_mod.command(name="timeout", description="Silencia um membro por N minutos")
    async def _timeout(interaction: discord.Interaction, membro: discord.Member, minutos: int, motivo: str = ""):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.timeout_membro(interaction.guild, membro.id, minutos, motivo, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_mod.command(name="remover_timeout", description="Remove o timeout de um membro")
    async def _remover_timeout(interaction: discord.Interaction, membro: discord.Member):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.remover_timeout(interaction.guild, membro.id, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_mod.command(name="advertir", description="Registra uma advertência (avisa o membro por DM, best-effort)")
    async def _advertir(interaction: discord.Interaction, membro: discord.Member, motivo: str = ""):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.advertir_membro(interaction.guild, membro.id, motivo, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_msg.command(name="fixar", description="Fixa uma mensagem pelo ID")
    async def _fixar(interaction: discord.Interaction, id_mensagem: str):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.fixar_mensagem(interaction.channel, id_mensagem, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_msg.command(name="desfixar", description="Desfixa uma mensagem pelo ID")
    async def _desfixar(interaction: discord.Interaction, id_mensagem: str):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.desfixar_mensagem(interaction.channel, id_mensagem, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_msg.command(name="deletar", description="Deleta uma mensagem pelo ID")
    async def _deletar(interaction: discord.Interaction, id_mensagem: str):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.deletar_mensagem(interaction.channel, id_mensagem, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_msg.command(name="modolento", description="Define o modo lento do canal atual (0 = desliga)")
    async def _modolento(interaction: discord.Interaction, segundos: int):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.definir_modo_lento(interaction.channel, segundos, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_msg.command(name="limpar", description="Apaga as últimas N mensagens do canal atual (IRREVERSÍVEL)")
    async def _limpar(interaction: discord.Interaction, quantidade: int, confirmar: bool = False):
        if not await _somente_dono(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        ok, msg = await moderacao.limpar_canal(interaction.channel, quantidade, interaction.user.id, confirmar)
        await interaction.followup.send(msg, ephemeral=True)

    @grupo_canal.command(name="bloquear", description="Impede @everyone de mandar mensagem no canal atual")
    async def _bloquear(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.bloquear_canal(interaction.channel, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_canal.command(name="desbloquear", description="Libera @everyone pra mandar mensagem no canal atual")
    async def _desbloquear(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.desbloquear_canal(interaction.channel, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_canal.command(name="criar", description="Cria um canal de texto novo")
    async def _criar(interaction: discord.Interaction, nome: str, categoria: discord.CategoryChannel = None):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.criar_canal(interaction.guild, nome, categoria.id if categoria else None, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_canal.command(name="renomear", description="Renomeia o canal atual")
    async def _renomear(interaction: discord.Interaction, novo_nome: str):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.renomear_canal(interaction.channel, novo_nome, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_canal.command(name="arquivar", description="Move o canal atual pra categoria \"📦 Arquivados\" e bloqueia envio")
    async def _arquivar(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.arquivar_canal(interaction.channel, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_cargo.command(name="atribuir", description="Atribui um cargo a um membro")
    async def _cargo_atribuir(interaction: discord.Interaction, membro: discord.Member, cargo: discord.Role):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.atribuir_cargo(interaction.guild, membro.id, cargo.id, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    @grupo_cargo.command(name="remover", description="Remove um cargo de um membro")
    async def _cargo_remover(interaction: discord.Interaction, membro: discord.Member, cargo: discord.Role):
        if not await _somente_dono(interaction):
            return
        ok, msg = await moderacao.remover_cargo(interaction.guild, membro.id, cargo.id, interaction.user.id)
        await _responder_resultado(interaction, ok, msg)

    tree.add_command(grupo_mod)
    tree.add_command(grupo_msg)
    tree.add_command(grupo_canal)
    tree.add_command(grupo_cargo)


def _registrar_slash_exportar(tree, token):
    @app_commands.command(name="exportar", description="Exporta o histórico de um canal pra JSON")
    async def _exportar(interaction: discord.Interaction, id_canal: str, limite_mensagens: int = 0):
        if not await _somente_dono(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        from eris.core import exportador
        ok, resultado = await asyncio.to_thread(exportador.exportar_canal, id_canal, token, limite_mensagens or None)
        if ok:
            await interaction.followup.send(f"Exportado com sucesso: `{resultado}`", ephemeral=True)
        else:
            await interaction.followup.send(f"Falha ao exportar: {resultado}", ephemeral=True)

    tree.add_command(_exportar)


def _voice_channel_do_autor(interaction):
    """`interaction.user.voice` só existe de verdade quando o autor é um
    `discord.Member` (dentro de um servidor) E está numa call agora."""
    voice_state = getattr(interaction.user, "voice", None)
    return voice_state.channel if voice_state else None


async def _somente_dono_em_call(interaction):
    """Mesma trava de `_somente_dono`, mais a checagem de estar numa call de
    voz de verdade (entrar/sair de call não faz sentido em DM)."""
    if not await _somente_dono(interaction):
        return None
    if interaction.guild is None:
        await interaction.response.send_message("Isso só funciona dentro de um servidor (não numa DM).", ephemeral=True)
        return None
    canal = _voice_channel_do_autor(interaction)
    if canal is None:
        await interaction.response.send_message("Você precisa estar numa call de voz do servidor pra eu entrar.", ephemeral=True)
        return None
    return canal


def _registrar_slash_voz(tree):
    """Modo Conversa, Modo Intérprete e Modo Tutora por voz - migrados pro
    ERIS em 2026-08-25 (ver `eris/core/voz_call.py`). A GAIA continua
    decidindo todo conteúdo (transcrição/tradução/resposta/síntese); aqui só
    entra/sai da call."""
    grupo_conversar = app_commands.Group(name="conversar", description="Bate-papo comum por voz com a Galateia (sem tradução, sem prática de idioma)")
    grupo_interprete = app_commands.Group(name="interprete", description="Modo Intérprete - tradução de voz ao vivo numa call")
    grupo_tutora = app_commands.Group(name="tutora", description="Modo Tutora - pratique um idioma por voz com a Galateia")

    @grupo_conversar.command(name="entrar", description="A Gala entra na sua call de voz atual pra bater um papo comum")
    async def _conversar_entrar(interaction: discord.Interaction):
        canal = await _somente_dono_em_call(interaction)
        if canal is None:
            return
        await interaction.response.defer()
        ok, mensagem = await voz_call.entrar_conversa(canal)
        await interaction.followup.send(mensagem, ephemeral=not ok)

    @grupo_conversar.command(name="sair", description="A Gala sai da call de voz")
    async def _conversar_sair(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor (não numa DM).", ephemeral=True)
            return
        mensagem = await voz_call.sair_conversa(interaction.guild.id)
        await interaction.response.send_message(mensagem)

    @grupo_interprete.command(name="entrar", description="A Gala entra na sua call de voz atual e começa a traduzir")
    async def _interprete_entrar(interaction: discord.Interaction):
        canal = await _somente_dono_em_call(interaction)
        if canal is None:
            return
        await interaction.response.defer()
        ok, mensagem = await voz_call.entrar_interprete(canal)
        await interaction.followup.send(mensagem, ephemeral=not ok)

    @grupo_interprete.command(name="sair", description="A Gala sai da call de voz e para de traduzir")
    async def _interprete_sair(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor (não numa DM).", ephemeral=True)
            return
        mensagem = await voz_call.sair_interprete(interaction.guild.id)
        await interaction.response.send_message(mensagem)

    @grupo_tutora.command(name="entrar", description="A Gala entra na sua call de voz atual pra praticar Tutora (precisa de sessão de texto já iniciada)")
    async def _tutora_entrar(interaction: discord.Interaction):
        canal = await _somente_dono_em_call(interaction)
        if canal is None:
            return
        await interaction.response.defer()
        ok, mensagem = await voz_call.entrar_tutora(canal)
        await interaction.followup.send(mensagem, ephemeral=not ok)

    @grupo_tutora.command(name="sair", description="A Gala sai da call de voz da Tutora (a sessão de texto continua ativa)")
    async def _tutora_sair(interaction: discord.Interaction):
        if not await _somente_dono(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor (não numa DM).", ephemeral=True)
            return
        mensagem = await voz_call.sair_tutora(interaction.guild.id)
        await interaction.response.send_message(mensagem or "Eu não tava na call da Tutora nesse servidor.")

    tree.add_command(grupo_conversar)
    tree.add_command(grupo_interprete)
    tree.add_command(grupo_tutora)


async def iniciar_bot(token):
    """Sobe o bot e fica ouvindo DMs e canais de servidor até o processo
    encerrar. Não bloqueia quem chamou além do próprio `await` - use
    `asyncio.create_task` pra rodar em paralelo com o servidor HTTP
    (`eris/api_bridge.py`)."""
    global _client_atual, _loop_atual, _slash_ja_sincronizado
    _loop_atual = asyncio.get_running_loop()

    # 🔥 2026-08-25 - achado real (ela entrava na call mas não ouvia nem falava
    # nada): discord.py EMBUTE o DLL do libopus (`discord/bin/libopus-0.x64.dll`),
    # mas não carrega ele sozinho no import (isso só existia em versões bem
    # antigas da lib) - sem isso, tanto a decodificação de áudio recebido
    # (discord-ext-voice-recv, ver eris/core/voz_captura.py) quanto o encode do
    # que a GAIA manda de volta (`SessaoVoz._tocar`) falham em silêncio (excessão
    # engolida pelo try/except do worker, sem nenhum aviso visível no Discord).
    if not discord.opus.is_loaded():
        discord.opus._load_default()
        if discord.opus.is_loaded():
            print(" [SISTEMA] libopus carregado (voz na call habilitada).")
        else:
            print(" [SISTEMA] ATENÇÃO: não consegui carregar o libopus - Intérprete/Tutora por voz não vão funcionar (entra na call, mas não ouve nem fala nada).")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True  # 🔥 exigido pra moderação de membro (kick/ban/timeout/cargo) funcionar de forma confiável
    intents.voice_states = True  # 🔥 Intérprete/Tutora por voz - detectar canal esvaziando (on_voice_state_update)

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    _registrar_slash_moderacao(tree)
    _registrar_slash_exportar(tree, token)
    _registrar_slash_voz(tree)

    @client.event
    async def on_ready():
        global _client_atual, _slash_ja_sincronizado
        _client_atual = client
        mensagens.definir_client(client)
        print(f" [ERIS] Bot conectado como {client.user}.")
        db.salvar_guilds_cache(_guilds_para_cache(client))
        if not _slash_ja_sincronizado:
            try:
                sincronizados = await tree.sync()
                print(f" [ERIS] {len(sincronizados)} slash command(s) sincronizado(s) - pode levar até 1h pra propagar globalmente na 1ª vez.")
                _slash_ja_sincronizado = True
            except Exception as e:
                print(f" [ERIS] Erro ao sincronizar slash commands: {e}")

    @client.event
    async def on_guild_join(guild):
        db.salvar_guilds_cache(_guilds_para_cache(client))

    @client.event
    async def on_guild_remove(guild):
        db.salvar_guilds_cache(_guilds_para_cache(client))

    @client.event
    async def on_voice_state_update(member, before, after):
        # 🔥 Se o canal onde a Gala está numa call (Intérprete/Tutora) fica sem
        # NENHUM humano (só ela, ou vazio), ela sai sozinha e para de gastar
        # Whisper/LLM/TTS à toa numa call fantasma. Roda pra QUALQUER membro que
        # mude de estado de voz (não só ela mesma) - é o humano saindo que
        # normalmente esvazia o canal.
        canal_ativo = voz_call.canal_ativo(member.guild.id)
        if canal_ativo is not None and (before.channel == canal_ativo or after.channel == canal_ativo):
            if not any(not m.bot for m in canal_ativo.members):
                await voz_call.sair_qualquer(member.guild.id)

    async def _responder(message, eh_dono, remetente_id, texto):
        try:
            async with message.channel.typing():
                resposta = await asyncio.to_thread(
                    gaia_webhook.pedir_resposta_persona, texto, eh_dono, remetente_id, message.author.display_name, message.channel.id,
                )
            if resposta is None:
                resposta = "A Galateia está desligada agora - não consigo conversar, só executar comando de moderação/exportação."
            for bloco in mensagens.fatiar_mensagem(resposta):
                await message.channel.send(bloco)
        except Exception as e:
            print(f" [ERIS] Erro processando mensagem: {e}")
            try:
                await message.channel.send("Deu um erro aqui do meu lado, tenta de novo.")
            except Exception:
                pass

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        eh_bot_ou_webhook = message.author.bot
        remetente_id = str(message.author.id)
        eh_dono_flag = seguranca.eh_dono(remetente_id)

        if not eh_dono_flag and not eh_bot_ou_webhook and seguranca.limite_excedido(remetente_id):
            if seguranca.deveria_avisar_limite(remetente_id):
                try:
                    await message.channel.send("Calma aí, muitas mensagens rápido demais - espera um minuto e manda de novo.")
                except Exception:
                    pass
            return

        em_dm = isinstance(message.channel, discord.DMChannel)
        if not em_dm and message.guild is None:
            return  # nem DM nem servidor (ex.: group DM) - fora de escopo

        mencionada = client.user in message.mentions if not em_dm else False

        # 🔥 Gatilho por menção do Modo Intérprete (portado de discord_bot.py) -
        # só o dono aciona, e roda ANTES do filtro normal de roteamento: precisa
        # funcionar mesmo com "Responder livremente"/"menções" desligado -
        # entrar/sair da call não é conversa livre, é comando.
        if mencionada and eh_dono_flag and not em_dm:
            texto_sem_mencao = message.content
            if client.user is not None:
                texto_sem_mencao = texto_sem_mencao.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()
            if _PADRAO_INTERPRETE_ENTRAR.search(texto_sem_mencao):
                voice_state = getattr(message.author, "voice", None)
                if voice_state is None or voice_state.channel is None:
                    await message.channel.send("Você precisa estar numa call de voz do servidor pra eu entrar.")
                else:
                    ok, resposta = await voz_call.entrar_interprete(voice_state.channel)
                    await message.channel.send(resposta)
                return
            if _PADRAO_CONVERSA_ENTRAR.search(texto_sem_mencao):
                voice_state = getattr(message.author, "voice", None)
                if voice_state is None or voice_state.channel is None:
                    await message.channel.send("Você precisa estar numa call de voz do servidor pra eu entrar.")
                else:
                    ok, resposta = await voz_call.entrar_conversa(voice_state.channel)
                    await message.channel.send(resposta)
                return
            if _PADRAO_SAIR.search(texto_sem_mencao):
                resposta = await voz_call.sair_qualquer(message.guild.id)
                await message.channel.send(resposta)
                return

        if not seguranca.deve_processar_mensagem(
            eh_bot_ou_webhook=eh_bot_ou_webhook, em_dm=em_dm,
            guild_id=message.guild.id if message.guild else None, mencionada=mencionada,
            nome_exibicao=message.author.display_name, nome_usuario=message.author.name,
        ):
            return

        texto = message.content
        if client.user is not None:
            texto = texto.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()
        if not texto:
            return  # só a menção, sem nenhum conteúdo pra responder

        await _responder(message, eh_dono_flag, remetente_id, texto)

    await client.start(token)
