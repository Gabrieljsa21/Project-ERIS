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
import importlib
import re

import discord
from discord import app_commands

from eris import db
from eris.core import mensagens, moderacao, musica, seguranca, thoth, voz_call
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
_scheduler_worldboss = None
_scheduler_batalha = None
_musica_retomada = False


def _carregar_pandora(papel):
    """Módulos do PANDORA usados pelo bot (2026-11-12). Importados aqui, não
    no topo: o papel "musica" só usa o auto-colecionador (a conta do bot de
    música também joga) e não pode cair junto se o PANDORA estiver quebrado ou
    no meio de uma atualização. No "principal" o PANDORA é obrigatório, então
    o erro sobe normalmente. Devolve um dict nome -> módulo, ou None."""
    nomes = ["auto_colecionador"]
    if papel == "principal":
        nomes += ["gacha", "paineis", "sincronizador", "worldboss"]
    try:
        return {nome: importlib.import_module(f"pandora.{nome}") for nome in nomes}
    except Exception as e:
        if papel == "principal":
            raise
        print(f" [ERIS] PANDORA indisponível ({e}) - papel \"{papel}\" segue sem o auto-colecionador.")
        return None


def cliente_conectado():
    return _client_atual


def esta_conectado():
    """Estado de agora (2026-11-12): `cliente_conectado()` continua valendo
    para sempre depois do 1º `on_ready`, mesmo com o gateway caído; o
    `/status` da ponte HTTP precisa saber se a sessão está de pé neste
    momento."""
    client = _client_atual
    return client is not None and client.is_ready() and not client.is_closed()


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


def _registrar_slash_comandos_gaia(tree, metadados):
    """Slash commands de ação que a GAIA expõe via `core/agent/comandos.py`
    (2026-09-17, completa a extração do Discord - ver docs/ARQUITETURA.md e
    docs/TODO.md). Proxy fino: `metadados` (nome/descrição/argumento de cada
    comando) vem de `GET /eris/comandos`, buscado 1x no boot do bot
    (`iniciar_bot` abaixo) - registra o slash NATIVO aqui e encaminha
    (comando, argumento, eh_dono, remetente_id) pro webhook reverso na hora
    de executar; quem decide o que fazer e o texto de resposta é sempre a
    GAIA, o ERIS nunca roda o handler de verdade.

    Parâmetro sempre chamado "argumento" (mesmo raciocínio da versão que
    rodava dentro da própria GAIA antes da extração, ver histórico de
    `discord_bot.py`): evita gerar 1 assinatura de função Python por
    comando, a descrição do parâmetro (visível ao passar o mouse no
    Discord) usa o nome mais específico de cada um
    (`info["argumento"]`).

    Sem sincronização automática de comando novo - só pega a lista atual no
    boot; um comando adicionado do lado da GAIA só aparece aqui depois de
    reiniciar o ERIS (mesmo padrão de qualquer satélite que depende de
    metadados buscados 1x da GAIA)."""

    async def _executar(interaction, comando, argumento):
        if not await _somente_dono(interaction):
            return
        await interaction.response.defer()
        try:
            resposta = await asyncio.to_thread(
                gaia_webhook.pedir_resposta_comando, comando, argumento, True, interaction.user.id,
            )
        except Exception as e:
            print(f" [ERIS] Erro pedindo \"/{comando}\" pra GAIA: {e}")
            resposta = None
        if resposta is None:
            await interaction.followup.send("A Galateia está desligada agora (ou não respondeu) - tenta de novo depois.")
            return
        for bloco in mensagens.fatiar_mensagem(resposta):
            await interaction.followup.send(bloco)

    def _com_argumento(nome, descricao_argumento):
        async def _callback(interaction: discord.Interaction, argumento: str):
            await _executar(interaction, nome, argumento)
        _callback.__name__ = f"slash_{nome}"
        app_commands.describe(argumento=descricao_argumento.capitalize())(_callback)
        return _callback

    def _sem_argumento(nome):
        async def _callback(interaction: discord.Interaction):
            await _executar(interaction, nome, "")
        _callback.__name__ = f"slash_{nome}"
        return _callback

    for info in list(metadados.get("sincronos", [])) + list(metadados.get("assincronos", [])):
        nome = info.get("nome")
        if not nome:
            continue
        callback = _com_argumento(nome, info["argumento"]) if info.get("argumento") else _sem_argumento(nome)
        tree.add_command(app_commands.Command(name=nome, description=info.get("descricao") or nome, callback=callback))


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
        """Mesma régua de `/pandora_admin` (permissão de administrador NAQUELE
        servidor, não `_somente_dono` - conteúdo/config do jogo varia por
        servidor) - repetida aqui (não importada de `_registrar_slash_colecao`)
        porque só a instância "musica" registra `/musica_admin` (papel
        "principal" nunca tem `/musica`/`/caos`, ver `iniciar_bot`)."""
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


async def iniciar_bot(token, papel="principal"):
    """Sobe o bot e fica ouvindo DMs e canais de servidor até o processo
    encerrar. Não bloqueia quem chamou além do próprio `await` - use
    `asyncio.create_task` pra rodar em paralelo com o servidor HTTP
    (`eris/api_bridge.py`).

    `papel="musica"` (2026-08-26, 2ª instância dedicada ao Modo Música, ver
    `eris/main.py`) registra só o grupo `/musica` - sem moderação, exportar,
    voz (Conversa/Intérprete/Tutora) nem o pipeline de texto livre (`on_
    message`/webhook pra GAIA) - essa instância só toca música, não tem
    conta de "dono"/DM pra proteger."""
    global _loop_atual
    _loop_atual = asyncio.get_running_loop()
    principal = papel == "principal"
    pandora = _carregar_pandora(papel)

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
    if principal:
        intents.message_content = True  # 🔥 texto livre/webhook pra GAIA - papel "musica" não conversa, não precisa
        intents.members = True  # 🔥 exigido pra moderação de membro (kick/ban/timeout/cargo) funcionar de forma confiável
    intents.voice_states = True  # 🔥 Intérprete/Tutora/Música - detectar canal esvaziando (on_voice_state_update), vale pros dois papéis

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    if principal:
        _registrar_slash_moderacao(tree)
        _registrar_slash_exportar(tree, token)
        _registrar_slash_voz(tree)
        from eris import comandos_pandora
        comandos_pandora.registrar(tree)
        _registrar_slash_lista_desejo(tree)
        # 🔥 Busca síncrona de boot (2026-09-17) - se a GAIA estiver fora do
        # ar agora, sobe sem esses slash commands nessa sessão (reiniciar o
        # ERIS depois dela subir resolve, ver gaia_webhook.obter_comandos_gaia).
        metadados_comandos_gaia = await asyncio.to_thread(gaia_webhook.obter_comandos_gaia)
        _registrar_slash_comandos_gaia(tree, metadados_comandos_gaia)
        # Botões de aprovação do THOTH nas DMs dos donos respondem mesmo
        # depois de um reinício (2026-11-13, ver `thoth.BotaoThoth`).
        client.add_dynamic_items(thoth.BotaoThoth)
    else:
        # 🔥 Exclusivo do papel "musica" (2026-08-26, achado pelo usuário: "pq
        # a gaia e a eris tem /caos? N deveria ser apenas da eris?") - antes
        # registrava sem checar papel nenhum, então a instância "principal"
        # também tinha /musica/caos: um usuário podia acidentalmente tocar
        # música NELA (ocupando o único slot de voz que ela tem) e perder
        # Conversa/Intérprete/Tutora até parar a música - exatamente o
        # problema que a 2ª instância existe pra evitar.
        _registrar_slash_musica(tree)
        _registrar_slash_caos(tree)
        # Botões de "Tocando agora" respondem mesmo depois de um reinício
        # (2026-11-12, ver `musica.BotaoMusica`).
        client.add_dynamic_items(musica.BotaoMusica)

    @client.event
    async def on_ready():
        global _client_atual, _slash_ja_sincronizado, _auto_colecionador, _auto_colecionador_usuarios, _sincronizador_catalogo, _scheduler_worldboss, _scheduler_batalha, _musica_retomada
        _client_atual = client
        mensagens.definir_client(client)
        print(f" [ERIS] Bot conectado como {client.user} (papel \"{papel}\").")
        if principal:
            db.salvar_guilds_cache(_guilds_para_cache(client))  # 🔥 papel "musica" não usa `db` (sem moderação/donos, ver eris/main.py)
        # 🔥 Resume sozinha a música que estava tocando quando o processo
        # caiu/reiniciou (2026-09-04, pedido do usuário: "qnd vc reinicia,
        # a eris para de tocar musica, e n volta mais... tem como pelo
        # menos fazer ela voltar a tocar musica q estava tocando qnd
        # voltar?") - só no papel "musica" (onde vivem as sessões de
        # verdade), 1x por processo (`on_ready` pode disparar de novo numa
        # reconexão do discord.py - não repetir isso a cada reconexão).
        if not principal and not _musica_retomada:
            _musica_retomada = True
            asyncio.create_task(musica.retomar_sessoes_persistidas(client))
        # 🔥 Auto-colecionador (2026-08-29) - só inicia UMA vez por processo,
        # `on_ready` pode disparar de novo numa reconexão do discord.py.
        if _auto_colecionador is None and pandora is not None:
            _auto_colecionador = pandora["auto_colecionador"].AutoColecionador(client, papel)
        # 🔥 Modo Auto-coleta POR USUÁRIO (2026-08-30) - só na instância
        # "principal" (onde vive o toggle em `paineis.ViewPerfilAcoes`), roda
        # em horário PRÓPRIO (:50/:55), independente do da conta de bot.
        if principal and _auto_colecionador_usuarios is None:
            _auto_colecionador_usuarios = pandora["auto_colecionador"].AutoColecionadorUsuarios(client)
        # 🔥 Sincronização contínua do catálogo (2026-08-29) - só na instância
        # "principal", rodar nas duas seria download/reimportação duplicados
        # à toa (upsert já deixaria seguro, mas sem ganho nenhum).
        if principal and _sincronizador_catalogo is None:
            _sincronizador_catalogo = pandora["sincronizador"].SincronizadorCatalogo(client)
        # 🔥 World Boss (2026-09-01) - só na instância "principal" (mesmo
        # critério de `AutoColecionadorUsuarios` - é onde vive o painel
        # `/pandora` -> 🐉 World Boss); spawna nos 4 horários fixos e conduz
        # inscrições/turnos sozinho, sem depender de nenhum comando.
        if principal and _scheduler_worldboss is None:
            _scheduler_worldboss = pandora["worldboss"].SchedulerWorldBoss(client)
        # 🔥 Auto-Defesa de Batalha por timeout (2026-09-02, pedido do
        # usuário: "Se o desafiado n responder em 10min, considera essa
        # defesa automatica") - só na instância "principal" (mesmo critério
        # dos outros schedulers - é onde vive o hub "⚔️ PvP").
        if principal and _scheduler_batalha is None:
            _scheduler_batalha = pandora["paineis"].SchedulerBatalha(client)
        if not _slash_ja_sincronizado:
            try:
                sincronizados = await tree.sync()
                print(f" [ERIS] {len(sincronizados)} slash command(s) sincronizado(s) - pode levar até 1h pra propagar globalmente na 1ª vez.")
                _slash_ja_sincronizado = True
            except Exception as e:
                print(f" [ERIS] Erro ao sincronizar slash commands: {e}")

    if principal:
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
    # Como as duas instâncias (principal/música) ficam no MESMO servidor e
    # compartilham o mesmo `pandora.db`, as duas viam o card pendente e as
    # duas tentavam processar o claim - só uma vencia a corrida (`db.
    # reivindicar` é atômico), mas a outra (a de música, que nem deveria
    # participar disso) mandava uma mensagem de erro/duplicada mesmo assim.
    # Colecionador é feature só do papel "principal" - agora só registra
    # aqui dentro, igual `on_guild_join`/`on_guild_remove` acima.
    if principal:
        @client.event
        async def on_raw_reaction_add(payload):
            await pandora["gacha"].processar_reacao_claim(client, payload)

    # 🔥 Papel "musica" não registra `on_message`/o pipeline de texto livre -
    # bot dedicado só ao grupo `/musica`, sem webhook pra GAIA, sem DM/menção.
    if principal:
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
