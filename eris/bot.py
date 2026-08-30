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
# 🔥 Colecionador EXTRAÍDO pro Project-PANDORA (2026-08-29, biblioteca Python
# local por path, ver pyproject.toml/ARQUITETURA.md) - `colecao_db` é um
# ALIAS de propósito (não reaproveita o nome `db` de cima, que continua
# sendo o `eris.db` de sempre - donos/roteamento/auditoria/cache de guilds,
# ver `db.salvar_guilds_cache` mais abaixo) - dois bancos SQLite distintos
# agora (`data/eris.db` e `Project-PANDORA/data/pandora.db`), nunca confundir.
from pandora import auto_colecionador, consulta, economia, gacha, paineis, sincronizador
from pandora import db as colecao_db
from eris.core import mensagens, moderacao, musica, seguranca, voz_call
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
_auto_colecionador = None
_auto_colecionador_usuarios = None
_sincronizador_catalogo = None


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


def _registrar_slash_lista_desejo(tree):
    @app_commands.command(name="ideia", description="Pede uma ideia nova de animação/reação pra Galateia, na hora")
    async def _ideia(interaction: discord.Interaction):
        # 🔥 2026-08-29, pedido do usuário: "tem como forcar isso com
        # /ideia?" - gera fora do gatilho aleatório da Lista de Desejo (ver
        # `run.py::_monitorar_lista_desejo_loop` do lado da GAIA). Resposta
        # PÚBLICA (não ephemeral) - é uma ideia solta, o espírito é
        # compartilhar, não é uma ação administrativa.
        await interaction.response.defer()
        try:
            ideia = await asyncio.to_thread(gaia_webhook.pedir_ideia_lista_desejo)
        except Exception as e:
            # 🔥 achado real (2026-08-29): sem isso, qualquer exceção aqui
            # (ex.: erro de rede/encoding do lado da GAIA) deixava a
            # interação SEM NENHUMA resposta - o Discord mostra "O
            # aplicativo não respondeu" só depois de expirar de vez, em vez
            # da mensagem de erro de verdade.
            print(f" [ERIS] Erro pedindo ideia da Lista de Desejo: {e}")
            ideia = None
        if ideia is None:
            await interaction.followup.send("A Galateia está desligada agora (ou não veio nada) - tenta de novo depois.")
            return
        await interaction.followup.send(ideia)

    tree.add_command(_ideia)


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


def _quem_iniciou_pode(interaction):
    """Controles de reprodução (pular/pausar/continuar/parar/dj_automatico)
    restritos a quem INICIOU a sessão (decisão do usuário 2026-08-26,
    resolvendo a contradição real com "aberto a qualquer membro" - Modo
    Música virou social por pessoa, então o CONTROLE de estado precisa de
    dono, mas adicionar/avaliar continua livre). Sem sessão ativa, deixa
    passar (`musica.pular` etc. já respondem "não tava tocando" sozinhos)."""
    iniciador = musica.obter_iniciador(interaction.guild.id)
    return iniciador is None or str(interaction.user.id) == iniciador


async def _responder_negado_por_dono_da_sessao(interaction):
    await interaction.response.send_message(
        "Só quem iniciou a sessão de música pode fazer isso - \"/musica tocar\" pra adicionar e 👍/👎 continuam liberados.",
        ephemeral=True,
    )


def _canal_anuncio_musica(interaction):
    """Canal onde toda resposta PÚBLICA de música aparece (2026-08-30,
    pedido do usuário: "quero q tudo relacionado a musica so seja
    respondido no canal de musica definido, independente se mandar o
    comando em outro canal") - SUBSTITUI a restrição antiga (`/musica
    <ação>` só FUNCIONAVA dentro de um canal configurado, recusando os
    demais - `_no_canal_certo_de_musica`, removida). Agora QUALQUER canal
    pode disparar o comando; a resposta pública (Tocando/pular/pausar/
    etc.) sempre aparece no canal configurado via `/musica canal`, nunca
    no de onde foi digitado. Sem configuração (`obter_canal_restrito`
    devolve None), cai no canal da própria interação - comportamento de
    sempre."""
    canal_id = musica.obter_canal_restrito(interaction.guild.id)
    if canal_id:
        canal = interaction.guild.get_channel(int(canal_id))
        if canal is not None:
            return canal
    return interaction.channel


async def _responder_no_canal_de_musica(interaction, texto):
    """Manda `texto` pro canal resolvido por `_canal_anuncio_musica` - se
    for o MESMO canal de onde veio o comando, responde a interação
    normalmente (sem overhead); se for OUTRO (redirecionamento
    configurado), a interação recebe só um ack ephemeral silencioso
    (apagado em seguida) e o texto de verdade vai como mensagem comum no
    canal configurado - não dá pra fazer uma resposta de interação
    aparecer num canal diferente de onde ela nasceu, limitação da própria
    API do Discord, por isso o desvio."""
    canal = _canal_anuncio_musica(interaction)
    if canal.id == interaction.channel.id:
        await interaction.response.send_message(texto)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await canal.send(texto)
    except discord.HTTPException:
        pass
    await interaction.delete_original_response()


def _registrar_slash_musica(tree):
    """Modo Música - substitui o Jockie Music (pedido do usuário 2026-08-25).
    Diferente do Conversa/Intérprete/Tutora, aberto a QUALQUER membro do
    servidor (não só dono) - é uma feature social compartilhada, mesmo
    espírito de uso que o Jockie já tinha (qualquer um na call podia pedir
    música). 🔥 2026-08-26: controles de ESTADO (pular/pausar/continuar/
    parar/dj_automatico) passaram a exigir ser quem iniciou a sessão -
    adicionar à fila e like/dislike continuam abertos a todo mundo."""
    grupo_musica = app_commands.Group(name="musica", description="Toca música na call de voz (busca no YouTube)")

    @grupo_musica.command(name="tocar", description="Toca (ou adiciona à fila) uma música - vazio toca suas aprovadas")
    async def _musica_tocar(interaction: discord.Interaction, busca: str = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        canal = _voice_channel_do_autor(interaction)
        if canal is None:
            await interaction.response.send_message("Você precisa estar numa call de voz do servidor.", ephemeral=True)
            return
        # 🔥 Confirmação ephemeral só quando sobra algo pra dizer (2026-08-27,
        # pedido do usuário: "essa resposta privada pode ser removida" - o
        # anúncio público de verdade ("tocando agora" + botões) já confirma
        # sozinho via `_tocar` -> `text_channel.send`; play IMEDIATO devolve
        # `mensagem=None` e a resposta adiada é apagada em vez de mandar um
        # followup vazio). "Adicionado à fila" continua tendo followup - só
        # ela sabe informar a posição. `_canal_anuncio_musica` (2026-08-30) -
        # o "Tocando"/botões sempre saem no canal configurado, nunca no de
        # onde `/musica tocar` foi digitado.
        canal_anuncio = _canal_anuncio_musica(interaction)
        await interaction.response.defer(ephemeral=True)
        if busca:
            ok, mensagem = await musica.tocar(canal, canal_anuncio, busca, interaction.user.id)
        else:
            # 🔥 Sem parâmetro (2026-08-26, pedido do usuário: "o musica
            # tocar, se n passar parametro, começa a tocar as musicas q
            # aprovei, ate terminar todas").
            ok, mensagem = await musica.tocar_aprovadas(canal, canal_anuncio, interaction.user.id)
        if mensagem is None:
            await interaction.delete_original_response()
            return
        await interaction.followup.send(mensagem, ephemeral=True)

    @grupo_musica.command(name="pular", description="Pula pra próxima música da fila (só quem iniciou a sessão)")
    async def _musica_pular(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if not _quem_iniciou_pode(interaction):
            await _responder_negado_por_dono_da_sessao(interaction)
            return
        await _responder_no_canal_de_musica(interaction, musica.pular(interaction.guild.id, _canal_anuncio_musica(interaction)))

    @grupo_musica.command(name="pausar", description="Pausa a música atual (só quem iniciou a sessão)")
    async def _musica_pausar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if not _quem_iniciou_pode(interaction):
            await _responder_negado_por_dono_da_sessao(interaction)
            return
        await _responder_no_canal_de_musica(interaction, musica.pausar(interaction.guild.id))

    @grupo_musica.command(name="continuar", description="Retoma a música pausada (só quem iniciou a sessão)")
    async def _musica_continuar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if not _quem_iniciou_pode(interaction):
            await _responder_negado_por_dono_da_sessao(interaction)
            return
        await _responder_no_canal_de_musica(interaction, musica.retomar(interaction.guild.id))

    @grupo_musica.command(name="fila", description="Mostra o que está tocando agora e a fila")
    async def _musica_fila(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 defer primeiro (2026-08-28) - `obter_fila` agora busca o voto de
        # cada faixa (rede, uma chamada por item) antes de responder, pode
        # passar dos 3s que o Discord dá pra resposta imediata.
        canal_anuncio = _canal_anuncio_musica(interaction)
        await interaction.response.defer(ephemeral=canal_anuncio.id != interaction.channel.id)
        estado = await musica.obter_fila(interaction.guild.id)
        if estado is None:
            await interaction.followup.send("Não tô tocando nada nesse servidor agora.", ephemeral=True)
            return
        texto = musica.formatar_estado_fila(estado)
        if canal_anuncio.id == interaction.channel.id:
            await interaction.followup.send(texto)
        else:
            await canal_anuncio.send(texto)
            await interaction.delete_original_response()

    @grupo_musica.command(name="aprovadas", description="Lista suas músicas aprovadas (👍), com páginas e opção de trocar o voto")
    async def _musica_aprovadas(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        faixas = await musica.listar_aprovadas(interaction.user.id)
        if not faixas:
            await interaction.followup.send("Você ainda não aprovou nenhuma música.", ephemeral=True)
            return
        view = musica.ViewListaVotos(interaction.user.id, "positivo", faixas)
        await interaction.followup.send(view.formatar(), view=view, ephemeral=True)

    @grupo_musica.command(name="desaprovadas", description="Lista suas músicas desaprovadas (👎), com páginas e opção de trocar o voto")
    async def _musica_desaprovadas(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        faixas = await musica.listar_desaprovadas(interaction.user.id)
        if not faixas:
            await interaction.followup.send("Você ainda não desaprovou nenhuma música.", ephemeral=True)
            return
        view = musica.ViewListaVotos(interaction.user.id, "negativo", faixas)
        await interaction.followup.send(view.formatar(), view=view, ephemeral=True)

    @grupo_musica.command(name="parar", description="Para a música, limpa a fila e sai da call (só quem iniciou a sessão)")
    async def _musica_parar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if not _quem_iniciou_pode(interaction):
            await _responder_negado_por_dono_da_sessao(interaction)
            return
        await _responder_no_canal_de_musica(interaction, await musica.sair_musica(interaction.guild.id))

    @grupo_musica.command(name="dj_automatico", description="Liga/desliga a continuação automática quando a fila acabar (só quem iniciou a sessão)")
    async def _musica_dj(interaction: discord.Interaction, ativo: bool):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if not _quem_iniciou_pode(interaction):
            await _responder_negado_por_dono_da_sessao(interaction)
            return
        await _responder_no_canal_de_musica(interaction, musica.definir_modo_continuo(interaction.guild.id, ativo))

    grupo_musica_admin = app_commands.Group(name="musica_admin", description="Configuração do Modo Música nesse servidor")

    async def _somente_admin_do_servidor_musica(interaction: discord.Interaction):
        """Mesma régua de `/colecao_admin` (permissão de administrador NAQUELE
        servidor, não `_somente_dono` - conteúdo/config do jogo varia por
        servidor) - repetida aqui (não importada de `_registrar_slash_colecao`)
        porque só a instância "musica" registra `/musica_admin` (papel
        "completo" nunca tem `/musica`/`/caos`, ver `iniciar_bot`)."""
        eh_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if interaction.guild is None or not eh_admin:
            await interaction.response.send_message("Só administradores do servidor podem mudar essa configuração.", ephemeral=True)
            return False
        return True

    @grupo_musica_admin.command(name="canal", description="Restringe /musica e /caos a um canal (sem informar nenhum, remove a restrição)")
    async def _musica_admin_canal(interaction: discord.Interaction, canal: discord.TextChannel = None):
        if not await _somente_admin_do_servidor_musica(interaction):
            return
        musica.definir_canal_restrito(interaction.guild.id, canal.id if canal else None)
        resposta = f"Comandos de música restritos a {canal.mention} nesse servidor." if canal else "Restrição de canal removida - música volta a funcionar em qualquer canal de texto."
        await interaction.response.send_message(resposta, ephemeral=True)

    @grupo_musica_admin.command(name="ver", description="Mostra o canal configurado pra música nesse servidor")
    async def _musica_admin_ver(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        canal_restrito = musica.obter_canal_restrito(interaction.guild.id)
        resposta = f"Comandos de música restritos a <#{canal_restrito}>." if canal_restrito else "Sem restrição de canal - música funciona em qualquer canal de texto."
        await interaction.response.send_message(resposta, ephemeral=True)

    tree.add_command(grupo_musica)
    tree.add_command(grupo_musica_admin)


def _registrar_slash_colecao(tree):
    """Colecionador de personagens estilo Mudae (ver PLANO_COLECAO_WAIFUS.md)
    - aberto a qualquer membro do servidor, mesmo espírito social do Modo
    Música (não é moderação, não exige ser dono da Galateia). Lógica de roll/
    claim em `eris/colecao/gacha.py`, consulta/coleção/wishlist em
    `eris/colecao/consulta.py` - aqui só registra os comandos e traduz
    interação <-> chamada de função, mesmo padrão dos outros grupos."""

    async def _rolar_e_responder(interaction: discord.Interaction, comando, quantidade):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 defer ANTES de chamar `rolar_varios` (2026-08-29, achado real em
        # produção: usuário reportou "aplicativo não respondeu" numa puxada
        # grande, e o cooldown JÁ tinha sido consumido - o `defer()` antigo
        # vinha DEPOIS dessa chamada, então não protegia nada. `rolar_varios`
        # é síncrono e pode passar dos 3s de ACK do Discord numa puxada de
        # até 50 (uma busca sequencial no banco por personagem sorteada);
        # `colecao_db.consumir_rolls` acontece bem no INÍCIO dela, então o timeout
        # matava a interação DEPOIS do ciclo já ter sido gasto, sem
        # nenhum resultado visível pro usuário. `asyncio.to_thread` evita
        # travar o loop assíncrono inteiro enquanto isso roda.
        await interaction.response.defer()
        ok, resultado = await asyncio.to_thread(gacha.rolar_varios, interaction.guild.id, interaction.user.id, comando, quantidade)
        if not ok:
            await interaction.followup.send(resultado, ephemeral=True)
            return
        await gacha.enviar_resultados(interaction, resultado)

    # 🔥 0 = "máximo disponível" (2026-08-29, pedido do usuário: "com 1
    # unico clique, rodar os maximo de rolls disponiveis") - `rolar_varios`
    # trata <= 0 como sentinela. Teto de 1000 só pra não aceitar um número
    # absurdo no parâmetro do Discord; o que sobra de verdade no ciclo
    # sempre vence (ver `colecao_db.consumir_rolls`). Default do PARÂMETRO também é
    # 0 (mesmo pedido, complemento no mesmo dia: "esse quantidade tem q ser
    # opcional, se n colocar, manda tudo") - `/wa` sem nada já rola o
    # máximo, não precisa mais digitar `quantidade:0` à mão.
    _RangeQuantidade = app_commands.Range[int, 0, 1000]
    _DESCRICAO_QUANTIDADE = "Quantos rolls (vazio ou 0 = todos os que sobrarem no ciclo atual)"

    @app_commands.command(name="wa", description="Rola personagem(ns) feminina(s) de anime/mangá")
    @app_commands.describe(quantidade=_DESCRICAO_QUANTIDADE)
    async def _wa(interaction: discord.Interaction, quantidade: _RangeQuantidade = 0):
        await _rolar_e_responder(interaction, "wa", quantidade)

    @app_commands.command(name="ha", description="Rola personagem(ns) masculina(s) de anime/mangá")
    @app_commands.describe(quantidade=_DESCRICAO_QUANTIDADE)
    async def _ha(interaction: discord.Interaction, quantidade: _RangeQuantidade = 0):
        await _rolar_e_responder(interaction, "ha", quantidade)

    @app_commands.command(name="ma", description="Rola personagem(ns) de qualquer gênero de anime/mangá")
    @app_commands.describe(quantidade=_DESCRICAO_QUANTIDADE)
    async def _ma(interaction: discord.Interaction, quantidade: _RangeQuantidade = 0):
        await _rolar_e_responder(interaction, "ma", quantidade)

    @app_commands.command(name="waifu", description="Abre o painel do Colecionador (rolar, coleção e mais)")
    async def _waifu(interaction: discord.Interaction):
        """Painel-raiz (2026-08-29, pedido do usuário: "os bots estão
        ficando muito poluídos"/"e se fizermos um painel com botões, assim
        como foi feito com o legends awaken?") - Fase 1 (ver plano da
        sessão que criou isto): só Rolar/Coleção por enquanto, os comandos
        antigos equivalentes continuam existindo até cada botão ser
        validado ao vivo. Lógica de verdade em `eris/colecao/paineis.py`."""
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        embed = paineis.montar_embed_hub(interaction.guild, interaction.user)
        view = paineis.ViewHubWaifu(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="colecao", description="Mostra a coleção de personagens (sua ou de outro membro)")
    async def _colecao(interaction: discord.Interaction, membro: discord.Member = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        alvo = membro or interaction.user
        personagens = colecao_db.colecao_do_usuario(interaction.guild.id, alvo.id)
        view = consulta.ViewColecao(f"Coleção de {alvo.display_name}", personagens)
        await interaction.response.send_message(view.formatar(), view=view)

    @app_commands.command(name="carteira", description="Mostra seu saldo de WiShards nesse servidor")
    async def _carteira(interaction: discord.Interaction, membro: discord.Member = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        alvo = membro or interaction.user
        saldo = colecao_db.saldo_wishards(interaction.guild.id, alvo.id)
        await interaction.response.send_message(f"💰 {alvo.display_name} tem **{saldo} WiShards** nesse servidor.")

    @app_commands.command(name="personagem", description="Busca um personagem pelo nome")
    async def _personagem(interaction: discord.Interaction, nome: str):
        resultados = colecao_db.buscar_personagens(nome)
        await interaction.response.send_message(consulta.formatar_busca(nome, resultados))

    @app_commands.command(name="populares", description="Lista os personagens mais populares do catálogo inteiro")
    async def _populares(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 200] = 50):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        permitir_nsfw = colecao_db.obter_configuracao_colecao(interaction.guild.id)["nsfw_permitido"]
        personagens = colecao_db.personagens_por_popularidade(quantidade, permitir_nsfw)
        view = consulta.ViewColecao("🔥 Personagens mais populares do catálogo", personagens, formatador_linha=consulta.linha_populares)
        await interaction.response.send_message(view.formatar(), view=view)

    @app_commands.command(name="colecao_disponiveis", description="Lista os 10 personagens mais populares ainda disponíveis pra reivindicar (última hora)")
    @app_commands.describe(raridade="Filtra só essa raridade (1 a 5 estrelas) - vazio considera todas")
    async def _colecao_disponiveis(interaction: discord.Interaction, raridade: app_commands.Range[int, 1, 5] = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 defer + `asyncio.to_thread` (2026-08-29, pedido do usuário: "se
        # possivel, isso ser feito sem causar delay enquanto ta rodando
        # comando") - `personagens_pendentes` agora consulta o banco (antes
        # era só um dict em memória); a query em si é pequena/indexada, mas
        # depois do bug de timeout já corrigido em `/wa` (rolar_varios
        # síncrono ANTES do defer), o padrão certo é sempre deferir antes
        # de qualquer chamada que toque o banco, nunca depois.
        await interaction.response.defer()
        # 🔥 `limite=10` (2026-08-29, usuário: "eu pedi p retornar apenas os
        # 10 melhores") - `personagens_pendentes` já ordena por popularidade
        # e corta aqui na fonte, então `pendentes` nunca passa de 10 (evita
        # de vez o estouro de 2000 caracteres que já aconteceu antes).
        pendentes = await asyncio.to_thread(gacha.personagens_pendentes, interaction.guild.id, raridade, limite=10)
        texto = consulta.formatar_pendentes(pendentes, raridade)
        if not pendentes:
            await interaction.followup.send(texto, ephemeral=True)
            return
        view = gacha.ViewClaimPendentes(interaction.guild.id, pendentes)
        await interaction.followup.send(texto, view=view)

    @app_commands.command(name="divorciar", description="Libera uma personagem da sua coleção (use o #id de /colecao ou /personagem)")
    async def _divorciar(interaction: discord.Interaction, id_personagem: int, confirmar: bool = False):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 Favoritas protegem contra ação destrutiva ACIDENTAL (Seção 15) -
        # exige confirmação extra, mas nunca bloqueia de vez (é uma escolha
        # válida do dono, diferente do bloqueio duro do Merge).
        if colecao_db.eh_favorita(interaction.guild.id, interaction.user.id, id_personagem) and not confirmar:
            await interaction.response.send_message(
                "Essa personagem está marcada como favorita - use `confirmar:true` se realmente quer divorciar.", ephemeral=True,
            )
            return
        ok, recompensa = colecao_db.divorciar(interaction.guild.id, id_personagem, interaction.user.id)
        if ok:
            mensagem = f"Personagem liberada da sua coleção - +{recompensa} WiShards (Afinidade preservada, um resgate futuro continua com o vínculo)."
        else:
            mensagem = "Você não tem essa personagem nesse servidor."
        await interaction.response.send_message(mensagem, ephemeral=True)

    @app_commands.command(name="favoritar", description="Marca/desmarca uma personagem sua como favorita (protege contra divórcio acidental)")
    async def _favoritar(interaction: discord.Interaction, id_personagem: int, favoritar: bool = True):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if colecao_db.dono_do_personagem(interaction.guild.id, id_personagem) != str(interaction.user.id):
            await interaction.response.send_message("Você não tem essa personagem nesse servidor.", ephemeral=True)
            return
        if favoritar:
            colecao_db.favoritar(interaction.guild.id, interaction.user.id, id_personagem)
            await interaction.response.send_message("⭐ Marcada como favorita.", ephemeral=True)
        else:
            colecao_db.desfavoritar(interaction.guild.id, interaction.user.id, id_personagem)
            await interaction.response.send_message("Desmarcada como favorita.", ephemeral=True)

    @app_commands.command(name="ranking", description="Mostra quem tem mais personagens reivindicadas nesse servidor")
    async def _ranking(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        ranking = colecao_db.ranking_guild(interaction.guild.id)
        await interaction.response.send_message(consulta.formatar_ranking(interaction.guild, ranking))

    grupo_wishlist = app_commands.Group(name="wishlist", description="Personagens que você quer que apareçam com mais chance nos rolls")

    @grupo_wishlist.command(name="adicionar", description="Adiciona um personagem à sua wishlist (use o #id de /personagem)")
    async def _wishlist_adicionar(interaction: discord.Interaction, id_personagem: int):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        personagem = colecao_db.personagem_por_id(id_personagem)
        if personagem is None:
            await interaction.response.send_message("Não achei nenhum personagem com esse #id.", ephemeral=True)
            return
        colecao_db.wishlist_adicionar(interaction.guild.id, interaction.user.id, id_personagem)
        await interaction.response.send_message(f"{personagem['nome']} adicionada à sua wishlist.", ephemeral=True)

    @grupo_wishlist.command(name="remover", description="Remove um personagem da sua wishlist (use o #id)")
    async def _wishlist_remover(interaction: discord.Interaction, id_personagem: int):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        colecao_db.wishlist_remover(interaction.guild.id, interaction.user.id, id_personagem)
        await interaction.response.send_message("Removida da sua wishlist (se estava lá).", ephemeral=True)

    @grupo_wishlist.command(name="listar", description="Lista sua wishlist nesse servidor")
    async def _wishlist_listar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        personagens = colecao_db.wishlist_listar(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(consulta.formatar_wishlist(personagens), ephemeral=True)

    grupo_admin = app_commands.Group(name="colecao_admin", description="Configuração do colecionador nesse servidor")

    async def _somente_admin_do_servidor_colecao(interaction: discord.Interaction):
        """Mesma régua de `/colecao_admin nsfw` original, agora compartilhada
        por todos os subcomandos de configuração - permissão de administrador
        NAQUELE servidor (não `_somente_dono`, que é dono da Galateia; aqui é
        conteúdo/dificuldade do jogo, faz sentido variar por servidor)."""
        eh_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if interaction.guild is None or not eh_admin:
            await interaction.response.send_message("Só administradores do servidor podem mudar essa configuração.", ephemeral=True)
            return False
        return True

    @grupo_admin.command(name="nsfw", description="Liga/desliga personagens NSFW nos rolls desse servidor")
    async def _admin_nsfw(interaction: discord.Interaction, ativo: bool):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_nsfw_permitido(interaction.guild.id, ativo)
        estado = "liberado" if ativo else "desabilitado"
        await interaction.response.send_message(f"Conteúdo NSFW {estado} pros rolls desse servidor.", ephemeral=True)

    @grupo_admin.command(name="rolls", description="Define quantos rolls por jogador, a cada quantos minutos")
    async def _admin_rolls(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 1000], minutos: app_commands.Range[int, 1, 1440]):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "rolls_por_ciclo", quantidade)
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "ciclo_rolls_minutos", minutos)
        await interaction.response.send_message(f"Rolls ajustados: {quantidade} a cada {minutos} min por jogador.", ephemeral=True)

    @grupo_admin.command(name="claims", description="Define quantos claims por jogador, a cada quantos minutos")
    async def _admin_claims(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100], minutos: app_commands.Range[int, 1, 1440]):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "claims_por_ciclo", quantidade)
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "ciclo_claims_minutos", minutos)
        await interaction.response.send_message(f"Claims ajustados: {quantidade} a cada {minutos} min por jogador.", ephemeral=True)

    @grupo_admin.command(name="duracao_card", description="Define por quantos segundos o botão de Reivindicar fica ativo")
    async def _admin_duracao_card(interaction: discord.Interaction, segundos: app_commands.Range[int, 10, 86400]):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "duracao_card_segundos", segundos)
        await interaction.response.send_message(f"Card de Reivindicar agora fica ativo por {segundos}s.", ephemeral=True)

    @grupo_admin.command(name="max_puxada", description="Máximo por comando de roll com quantidade explícita (não afeta quantidade:0 = máximo)")
    async def _admin_max_puxada(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 1000]):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "max_rolls_por_comando", quantidade)
        await interaction.response.send_message(f"Máximo por puxada (`quantidade` de /wa, /ha, /ma) ajustado pra {quantidade}.", ephemeral=True)

    @grupo_admin.command(name="wishlist_chance", description="Define a chance (%) de um roll vir da wishlist de quem rolou")
    async def _admin_wishlist_chance(interaction: discord.Interaction, porcentagem: app_commands.Range[int, 0, 100]):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "chance_wish_roll", porcentagem / 100)
        await interaction.response.send_message(f"Chance de wish-roll ajustada pra {porcentagem}%.", ephemeral=True)

    @grupo_admin.command(name="canal", description="Define o canal onde o auto-colecionador (GAIA/ERIS) posta os próprios rolls")
    async def _admin_canal(interaction: discord.Interaction, canal: discord.TextChannel):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.definir_configuracao_colecao(interaction.guild.id, "canal_anuncio_id", str(canal.id))
        await interaction.response.send_message(f"Auto-colecionador vai rolar em {canal.mention} a partir de agora.", ephemeral=True)

    @grupo_admin.command(name="ver", description="Mostra a configuração atual do colecionador nesse servidor")
    async def _admin_ver(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        config = colecao_db.obter_configuracao_colecao(interaction.guild.id)
        rotulo_canal = f"<#{config['canal_anuncio_id']}>" if config["canal_anuncio_id"] else "(usa o canal padrão do servidor)"
        texto = (
            f"**Configuração do colecionador em {interaction.guild.name}:**\n"
            f"- NSFW: {'liberado' if config['nsfw_permitido'] else 'desabilitado'}\n"
            f"- Rolls: {config['rolls_por_ciclo']} a cada {config['ciclo_rolls_minutos']} min\n"
            f"- Claims: {config['claims_por_ciclo']} a cada {config['ciclo_claims_minutos']} min\n"
            f"- Duração do card pra reivindicar: {config['duracao_card_segundos']}s\n"
            f"- Máximo de personagens por puxada: {config['max_rolls_por_comando']}\n"
            f"- Chance de wish-roll: {round(config['chance_wish_roll'] * 100)}%\n"
            f"- Séries bloqueadas: {', '.join(colecao_db.series_bloqueadas(interaction.guild.id)) or '(nenhuma)'}\n"
            f"- Canal do auto-colecionador: {rotulo_canal}"
        )
        await interaction.response.send_message(texto, ephemeral=True)

    @grupo_admin.command(name="bloquear_serie", description="Impede personagens dessa série/obra de aparecerem nos rolls desse servidor")
    async def _admin_bloquear_serie(interaction: discord.Interaction, serie: str):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.bloquear_serie(interaction.guild.id, serie)
        await interaction.response.send_message(f'Série "{serie}" bloqueada nesse servidor.', ephemeral=True)

    @grupo_admin.command(name="desbloquear_serie", description="Libera de novo uma série/obra bloqueada")
    async def _admin_desbloquear_serie(interaction: discord.Interaction, serie: str):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        colecao_db.desbloquear_serie(interaction.guild.id, serie)
        await interaction.response.send_message(f'Série "{serie}" desbloqueada.', ephemeral=True)

    @grupo_admin.command(name="resetar_rolls", description="Força o ciclo de rolls de alguém a recarregar agora (não espera o horário fixo)")
    async def _admin_resetar_rolls(interaction: discord.Interaction, membro: discord.Member):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        limite = colecao_db.resetar_rolls_admin(interaction.guild.id, membro.id)
        await interaction.response.send_message(f"Rolls de {membro.display_name} resetados - {limite} disponíveis agora.", ephemeral=True)

    @grupo_admin.command(name="resetar_claims", description="Força o ciclo de claims de alguém a recarregar agora (não espera o horário fixo)")
    async def _admin_resetar_claims(interaction: discord.Interaction, membro: discord.Member):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        limite = colecao_db.resetar_claims_admin(interaction.guild.id, membro.id)
        await interaction.response.send_message(f"Claims de {membro.display_name} resetados - {limite} disponíveis agora.", ephemeral=True)

    @grupo_admin.command(name="dar_personagem", description="Dá uma personagem LIVRE pra alguém direto (sem passar por roll/claim)")
    async def _admin_dar_personagem(interaction: discord.Interaction, membro: discord.Member, id_personagem: int):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        # 🔥 defer ANTES (2026-08-29) - `gacha.atribuir_personagem_admin`
        # agora chama `revelar_classe` (pede a GAIA por HTTP, ~1-2s), mesmo
        # cuidado do bug de timeout já corrigido em `/wa`.
        await interaction.response.defer()
        ok, erro, embed = await gacha.atribuir_personagem_admin(interaction.guild.id, id_personagem, membro)
        if not ok:
            await interaction.followup.send(erro, ephemeral=True)
            return
        await interaction.followup.send(embed=embed)

    @grupo_admin.command(name="definir_afinidade", description="Define a Afinidade de alguém com uma personagem (0-10), sem esperar reencontros")
    async def _admin_definir_afinidade(interaction: discord.Interaction, membro: discord.Member, id_personagem: int, valor: int):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        if colecao_db.dono_do_personagem(interaction.guild.id, id_personagem) != str(membro.id):
            await interaction.response.send_message(f"{membro.display_name} não tem essa personagem nesse servidor.", ephemeral=True)
            return
        novo = colecao_db.definir_afinidade_admin(interaction.guild.id, membro.id, id_personagem, valor)
        personagem = colecao_db.personagem_por_id(id_personagem)
        await interaction.response.send_message(f"Afinidade de {membro.display_name} com {personagem['nome']} definida em {novo}.", ephemeral=True)

    async def _definir_slot_equipe(interaction: discord.Interaction, tipo, posicao, id_personagem, rotulo_sucesso):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        if colecao_db.dono_do_personagem(interaction.guild.id, id_personagem) != str(interaction.user.id):
            await interaction.response.send_message("Você não tem essa personagem nesse servidor.", ephemeral=True)
            return
        colecao_db.definir_posicao_equipe(interaction.guild.id, interaction.user.id, tipo, posicao, id_personagem)
        personagem = colecao_db.personagem_por_id(id_personagem)
        await interaction.response.send_message(f"{rotulo_sucesso}: slot {posicao} = {personagem['nome']}.", ephemeral=True)

    grupo_party = app_commands.Group(name="party", description="Sua equipe (protegida contra Merge) - ainda sem Torre pra jogar")

    @grupo_party.command(name="ver", description="Mostra sua party (ou de outro membro)")
    async def _party_ver(interaction: discord.Interaction, membro: discord.Member = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        alvo = membro or interaction.user
        equipe = colecao_db.obter_equipe(interaction.guild.id, alvo.id, "party")
        await interaction.response.send_message(consulta.formatar_equipe(f"Party de {alvo.display_name}", equipe, colecao_db.MAX_POSICOES_EQUIPE))

    @grupo_party.command(name="definir", description="Coloca uma personagem sua num slot da party (1-5) - protege ela contra Merge")
    async def _party_definir(interaction: discord.Interaction, slot: app_commands.Range[int, 1, 5], id_personagem: int):
        await _definir_slot_equipe(interaction, "party", slot, id_personagem, "Party atualizada")

    @grupo_party.command(name="remover", description="Esvazia um slot da sua party")
    async def _party_remover(interaction: discord.Interaction, slot: app_commands.Range[int, 1, 5]):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        colecao_db.remover_posicao_equipe(interaction.guild.id, interaction.user.id, "party", slot)
        await interaction.response.send_message(f"Slot {slot} da party esvaziado.", ephemeral=True)

    @grupo_party.command(name="limpar", description="Esvazia toda a sua party")
    async def _party_limpar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        colecao_db.limpar_equipe(interaction.guild.id, interaction.user.id, "party")
        await interaction.response.send_message("Party esvaziada.", ephemeral=True)

    grupo_vitrine = app_commands.Group(name="vitrine", description="Mostruário público da sua coleção")

    @grupo_vitrine.command(name="ver", description="Mostra a vitrine de você ou de outro membro")
    async def _vitrine_ver(interaction: discord.Interaction, membro: discord.Member = None):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        alvo = membro or interaction.user
        equipe = colecao_db.obter_equipe(interaction.guild.id, alvo.id, "vitrine")
        await interaction.response.send_message(consulta.formatar_equipe(f"Vitrine de {alvo.display_name}", equipe, colecao_db.MAX_POSICOES_EQUIPE))

    @grupo_vitrine.command(name="definir", description="Coloca uma personagem sua num slot da vitrine (1-5)")
    async def _vitrine_definir(interaction: discord.Interaction, slot: app_commands.Range[int, 1, 5], id_personagem: int):
        await _definir_slot_equipe(interaction, "vitrine", slot, id_personagem, "Vitrine atualizada")

    @grupo_vitrine.command(name="remover", description="Esvazia um slot da sua vitrine")
    async def _vitrine_remover(interaction: discord.Interaction, slot: app_commands.Range[int, 1, 5]):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        colecao_db.remover_posicao_equipe(interaction.guild.id, interaction.user.id, "vitrine", slot)
        await interaction.response.send_message(f"Slot {slot} da vitrine esvaziado.", ephemeral=True)

    @grupo_vitrine.command(name="limpar", description="Esvazia toda a sua vitrine")
    async def _vitrine_limpar(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        colecao_db.limpar_equipe(interaction.guild.id, interaction.user.id, "vitrine")
        await interaction.response.send_message("Vitrine esvaziada.", ephemeral=True)

    grupo_loja = app_commands.Group(name="loja", description="Compre personagens livres ou garanta a raridade do seu próximo roll")

    @grupo_loja.command(name="ver", description="Mostra uma amostra de personagens livres pra comprar numa raridade (1-5)")
    async def _loja_ver(interaction: discord.Interaction, raridade: app_commands.Range[int, 1, 5]):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        permitir_nsfw = colecao_db.obter_configuracao_colecao(interaction.guild.id)["nsfw_permitido"]
        personagens = colecao_db.personagens_livres_por_raridade(interaction.guild.id, raridade, permitir_nsfw)
        await interaction.response.send_message(economia.formatar_loja(raridade, personagens), ephemeral=True)

    @grupo_loja.command(name="comprar", description="Compra uma personagem livre da loja (use o #id de /loja ver)")
    async def _loja_comprar(interaction: discord.Interaction, id_personagem: int):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        ok, mensagem = colecao_db.comprar_personagem(interaction.guild.id, interaction.user.id, id_personagem)
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    @grupo_loja.command(name="garantir", description="Compra uma garantia de raridade mínima (3-5) pro seu PRÓXIMO roll")
    async def _loja_garantir(interaction: discord.Interaction, raridade: app_commands.Range[int, 3, 5]):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        preco = colecao_db.PRECOS_GARANTIA[raridade]
        if colecao_db.saldo_wishards(interaction.guild.id, interaction.user.id) < preco:
            await interaction.response.send_message(f"Custa {preco} WiShards e você não tem o suficiente.", ephemeral=True)
            return
        colecao_db.creditar_wishards(interaction.guild.id, interaction.user.id, -preco, "loja_garantia", f"garantia {raridade}estrelas")
        colecao_db.definir_garantia(interaction.guild.id, interaction.user.id, raridade)
        await interaction.response.send_message(
            f"Garantido: seu próximo roll vai ser {raridade}⭐ ou mais (custou {preco} WiShards).", ephemeral=True,
        )

    @grupo_loja.command(name="upgrade", description="Compra o próximo nível de rolls máximos (+5 permanente por nível, até 5 níveis)")
    async def _loja_upgrade(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        ok, mensagem = colecao_db.comprar_upgrade_rolls(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    @grupo_loja.command(name="upgrade_claims", description="Compra o próximo nível de claims máximos (+1 permanente por nível, até 5 níveis)")
    async def _loja_upgrade_claims(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        ok, mensagem = colecao_db.comprar_upgrade_claims(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    @app_commands.command(name="merge", description="Sacrifica 5 personagens da mesma raridade por 1 aleatória da raridade seguinte")
    async def _merge(interaction: discord.Interaction, id1: int, id2: int, id3: int, id4: int, id5: int, confirmar: bool = False):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 Regras de verdade vivem em `economia.executar_merge` (2026-08-29)
        # - compartilhado com o botão 🔀 Merge do painel `/waifu` (`👤
        # Perfil`), pra nunca duplicar essa validação em 2 lugares.
        ok, mensagem, precisa_confirmar = economia.executar_merge(
            interaction.guild.id, interaction.user.id, [id1, id2, id3, id4, id5], confirmar,
        )
        if precisa_confirmar:
            mensagem += " Use `confirmar:true` se realmente quer sacrificá-la(s)."
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    grupo_trocar = app_commands.Group(name="trocar", description="Propõe uma troca bilateral de personagens/WiShards com outro jogador")

    @grupo_trocar.command(name="propor", description="Propõe uma troca (IDs de personagem separados por vírgula, ex.: 12,45)")
    async def _trocar_propor(
        interaction: discord.Interaction, membro: discord.Member,
        oferecer_personagens: str = "", oferecer_wishards: app_commands.Range[int, 0, 1000000] = 0,
        pedir_personagens: str = "", pedir_wishards: app_commands.Range[int, 0, 1000000] = 0,
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 Regras de verdade vivem em `economia.criar_e_avaliar_troca`
        # (2026-08-29) - compartilhado com o botão 🔄 Trocar do painel
        # `/waifu`, pra nunca duplicar essa lógica em 2 lugares.
        status, mensagem, view = economia.criar_e_avaliar_troca(
            interaction.guild.id, interaction.user.id, membro,
            economia.parse_ids_personagens(oferecer_personagens), oferecer_wishards,
            economia.parse_ids_personagens(pedir_personagens), pedir_wishards,
        )
        # 🔥 `view=None` explícito faz o discord.py quebrar (`send_message`
        # chama `view.is_finished()` sem checar None) - só passa `view=`
        # quando existe de verdade.
        if view is not None:
            await interaction.response.send_message(mensagem, view=view, ephemeral=status in ("erro", "npc_recusada"))
        else:
            await interaction.response.send_message(mensagem, ephemeral=status in ("erro", "npc_recusada"))

    tree.add_command(_wa)
    tree.add_command(_ha)
    tree.add_command(_ma)
    tree.add_command(_waifu)
    tree.add_command(_colecao)
    tree.add_command(_carteira)
    tree.add_command(_personagem)
    tree.add_command(_populares)
    tree.add_command(_colecao_disponiveis)
    tree.add_command(_divorciar)
    tree.add_command(_favoritar)
    tree.add_command(_ranking)
    tree.add_command(_merge)
    tree.add_command(grupo_wishlist)
    tree.add_command(grupo_admin)
    tree.add_command(grupo_loja)
    tree.add_command(grupo_trocar)
    tree.add_command(grupo_party)
    tree.add_command(grupo_vitrine)


def _registrar_slash_caos(tree):
    """`/caos` (2026-08-26, pedido do usuário: "ERIS entra no canal de voz do
    usuário e inicia uma sessão musical contínua... sem exigir artista,
    gênero, música ou qualquer outra referência inicial") - standalone (não
    dentro do grupo `/musica`, pedido explícito), mesmo espírito aberto a
    qualquer membro do servidor do Modo Música."""
    @app_commands.command(name="caos", description="A Gala entra na call e começa a tocar sozinha, sem pedir referência nenhuma")
    async def _caos(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        canal = _voice_channel_do_autor(interaction)
        if canal is None:
            await interaction.response.send_message("Você precisa estar numa call de voz do servidor.", ephemeral=True)
            return
        # 🔥 Confirmação ephemeral só quando sobra algo pra dizer - mesmo
        # motivo de `_musica_tocar` (2026-08-27). `_canal_anuncio_musica`
        # (2026-08-30) - "Tocando"/botões sempre saem no canal configurado,
        # nunca no de onde `/caos` foi digitado.
        await interaction.response.defer(ephemeral=True)
        ok, mensagem = await musica.iniciar_caos(canal, _canal_anuncio_musica(interaction), interaction.user.id)
        if mensagem is None:
            await interaction.delete_original_response()
            return
        await interaction.followup.send(mensagem, ephemeral=True)

    tree.add_command(_caos)


async def iniciar_bot(token, papel="completo"):
    """Sobe o bot e fica ouvindo DMs e canais de servidor até o processo
    encerrar. Não bloqueia quem chamou além do próprio `await` - use
    `asyncio.create_task` pra rodar em paralelo com o servidor HTTP
    (`eris/api_bridge.py`).

    `papel="musica"` (2026-08-26, 2ª instância dedicada ao Modo Música, ver
    `eris/main.py`) registra só o grupo `/musica` - sem moderação, exportar,
    voz (Conversa/Intérprete/Tutora) nem o pipeline de texto livre (`on_
    message`/webhook pra GAIA) - essa instância só toca música, não tem
    conta de "dono"/DM pra proteger."""
    global _client_atual, _loop_atual, _slash_ja_sincronizado
    _loop_atual = asyncio.get_running_loop()
    completo = papel == "completo"

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
    if completo:
        intents.message_content = True  # 🔥 texto livre/webhook pra GAIA - papel "musica" não conversa, não precisa
        intents.members = True  # 🔥 exigido pra moderação de membro (kick/ban/timeout/cargo) funcionar de forma confiável
    intents.voice_states = True  # 🔥 Intérprete/Tutora/Música - detectar canal esvaziando (on_voice_state_update), vale pros dois papéis

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    if completo:
        _registrar_slash_moderacao(tree)
        _registrar_slash_exportar(tree, token)
        _registrar_slash_voz(tree)
        _registrar_slash_colecao(tree)
        _registrar_slash_lista_desejo(tree)
    else:
        # 🔥 Exclusivo do papel "musica" (2026-08-26, achado pelo usuário: "pq
        # a gaia e a eris tem /caos? N deveria ser apenas da eris?") - antes
        # registrava sem checar papel nenhum, então a instância "completo"
        # também tinha /musica/caos: um usuário podia acidentalmente tocar
        # música NELA (ocupando o único slot de voz que ela tem) e perder
        # Conversa/Intérprete/Tutora até parar a música - exatamente o
        # problema que a 2ª instância existe pra evitar.
        _registrar_slash_musica(tree)
        _registrar_slash_caos(tree)

    @client.event
    async def on_ready():
        global _client_atual, _slash_ja_sincronizado, _auto_colecionador, _auto_colecionador_usuarios, _sincronizador_catalogo
        _client_atual = client
        mensagens.definir_client(client)
        print(f" [ERIS] Bot conectado como {client.user} (papel \"{papel}\").")
        if completo:
            db.salvar_guilds_cache(_guilds_para_cache(client))  # 🔥 papel "musica" não usa `db` (sem moderação/donos, ver eris/main.py)
        # 🔥 Auto-colecionador (2026-08-29) - só inicia UMA vez por processo,
        # `on_ready` pode disparar de novo numa reconexão do discord.py.
        if _auto_colecionador is None:
            _auto_colecionador = auto_colecionador.AutoColecionador(client, papel)
        # 🔥 Modo Auto-coleta POR USUÁRIO (2026-08-30) - só na instância
        # "completo" (onde vive o toggle em `paineis.ViewPerfilAcoes`), roda
        # em horário PRÓPRIO (:50/:55), independente do da conta de bot.
        if completo and _auto_colecionador_usuarios is None:
            _auto_colecionador_usuarios = auto_colecionador.AutoColecionadorUsuarios(client)
        # 🔥 Sincronização contínua do catálogo (2026-08-29) - só na instância
        # "completo", rodar nas duas seria download/reimportação duplicados
        # à toa (upsert já deixaria seguro, mas sem ganho nenhum).
        if completo and _sincronizador_catalogo is None:
            _sincronizador_catalogo = sincronizador.SincronizadorCatalogo(client)
        if not _slash_ja_sincronizado:
            try:
                sincronizados = await tree.sync()
                print(f" [ERIS] {len(sincronizados)} slash command(s) sincronizado(s) - pode levar até 1h pra propagar globalmente na 1ª vez.")
                _slash_ja_sincronizado = True
            except Exception as e:
                print(f" [ERIS] Erro ao sincronizar slash commands: {e}")

    if completo:
        @client.event
        async def on_guild_join(guild):
            db.salvar_guilds_cache(_guilds_para_cache(client))

        @client.event
        async def on_guild_remove(guild):
            db.salvar_guilds_cache(_guilds_para_cache(client))

    @client.event
    async def on_voice_state_update(member, before, after):
        # 🔥 Se o canal onde a Gala está numa call (Intérprete/Tutora/Conversa
        # OU Música, 2026-08-25) fica sem NENHUM humano (só ela, ou vazio), ela
        # sai sozinha - pra voz, evita gastar Whisper/LLM/TTS à toa numa call
        # fantasma; pra música, evita ficar tocando/gastando yt-dlp sozinha
        # numa call vazia. Roda pra QUALQUER membro que mude de estado de voz
        # (não só ela mesma) - é o humano saindo que normalmente esvazia o canal.
        canal_ativo = voz_call.canal_ativo(member.guild.id) or musica.canal_ativo(member.guild.id)
        if canal_ativo is not None and (before.channel == canal_ativo or after.channel == canal_ativo):
            if not any(not m.bot for m in canal_ativo.members):
                await voz_call.sair_qualquer(member.guild.id)

    # 🔥 Corrigido (2026-08-30, achado do usuário: "Qnd coleto algum
    # personagem pelo emoji, ambas os bots respondem, tinha q ser so 1")
    # - a suposição antiga era ERRADA: "cada processo só recebe evento das
    # PRÓPRIAS mensagens" não é como o Discord funciona - `on_raw_reaction_
    # add` dispara pra QUALQUER bot conectado ao canal, reagindo em
    # QUALQUER mensagem dele, não só nas que aquele bot específico postou.
    # Como as duas instâncias (completo/música) ficam no MESMO servidor e
    # compartilham o mesmo `pandora.db`, as duas viam o card pendente e as
    # duas tentavam processar o claim - só uma vencia a corrida (`db.
    # reivindicar` é atômico), mas a outra (a de música, que nem deveria
    # participar disso) mandava uma mensagem de erro/duplicada mesmo assim.
    # Colecionador é feature só do papel "completo" - agora só registra
    # aqui dentro, igual `on_guild_join`/`on_guild_remove` acima.
    if completo:
        @client.event
        async def on_raw_reaction_add(payload):
            await gacha.processar_reacao_claim(client, payload)

    # 🔥 Papel "musica" não registra `on_message`/o pipeline de texto livre -
    # bot dedicado só ao grupo `/musica`, sem webhook pra GAIA, sem DM/menção.
    if completo:
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
