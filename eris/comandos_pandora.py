# -*- coding: utf-8 -*-
"""Slash commands e painéis do Colecionador (Project PANDORA) registrados pelo
ERIS - separados de `eris/bot.py` em 2026-11-12. O bot.py tinha 2.079 linhas,
cerca de 1.300 delas deste domínio, que foi extraído pro PANDORA em
2026-08-29 mas continuava sendo registrado daqui.

Só o papel "principal" importa este módulo (ver `eris/bot.py::iniciar_bot`): o
papel "musica" não depende do PANDORA para subir. Próximo passo natural é o
próprio PANDORA expor `registrar(tree)` e este arquivo sumir do ERIS.

Os 17 subcomandos de `pandora_admin_legacy` e a view `_ViewFerramentasAdminPandora`
foram removidos na mesma mudança: nunca eram registrados nem usados, o painel
`/pandora_admin` cobre tudo."""
import asyncio

import discord
from discord import app_commands

from pandora import consulta, economia, gacha, paineis
from pandora import db as colecao_db


def _texto_configuracao_pandora(guild):
    config = colecao_db.obter_configuracao_colecao(guild.id)
    canal = f"<#{config['canal_anuncio_id']}>" if config["canal_anuncio_id"] else "canal padrão"
    return (
        f"**Administração — {guild.name}**\n"
        f"Rolls: {config['rolls_por_ciclo']}/{config['ciclo_rolls_minutos']} min · "
        f"Claims: {config['claims_por_ciclo']}/{config['ciclo_claims_minutos']} min\n"
        f"Progressão: até +{config['teto_bonus_rolls_progressao']} Rolls · "
        f"+{config['teto_bonus_claims_progressao']} Claims\n"
        f"Card: {config['duracao_card_segundos']}s · Puxada: {config['max_rolls_por_comando']} · "
        f"Wish: {round(config['chance_wish_roll'] * 100)}%\n"
        f"NSFW: {'ligado' if config['nsfw_permitido'] else 'desligado'} · "
        f"Canal automático: {canal}"
    )


class _ModalLimitesPandora(discord.ui.Modal, title="Limites do ciclo"):
    def __init__(self, guild_id, config):
        super().__init__()
        self.guild_id = guild_id
        self.rolls = discord.ui.TextInput(label="Rolls por ciclo", default=str(config["rolls_por_ciclo"]), max_length=4)
        self.minutos_rolls = discord.ui.TextInput(label="Minutos entre Rolls", default=str(config["ciclo_rolls_minutos"]), max_length=4)
        self.claims = discord.ui.TextInput(label="Claims por ciclo", default=str(config["claims_por_ciclo"]), max_length=3)
        self.minutos_claims = discord.ui.TextInput(label="Minutos entre Claims", default=str(config["ciclo_claims_minutos"]), max_length=4)
        for campo in (self.rolls, self.minutos_rolls, self.claims, self.minutos_claims):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            rolls, min_rolls, claims, min_claims = (int(campo.value.strip()) for campo in (self.rolls, self.minutos_rolls, self.claims, self.minutos_claims))
            if not 1 <= rolls <= 1000 or not 1 <= claims <= 100 or not 1 <= min_rolls <= 1440 or not 1 <= min_claims <= 1440:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Use números válidos: Rolls 1–1000, Claims 1–100 e ciclos 1–1440 min.", ephemeral=True)
            return
        for campo, valor in (("rolls_por_ciclo", rolls), ("ciclo_rolls_minutos", min_rolls), ("claims_por_ciclo", claims), ("ciclo_claims_minutos", min_claims)):
            colecao_db.definir_configuracao_colecao(self.guild_id, campo, valor)
        await interaction.response.send_message("Limites do ciclo atualizados.", ephemeral=True)


class _ModalProgressaoPandora(discord.ui.Modal, title="Tetos da Progressão"):
    def __init__(self, guild_id, config):
        super().__init__()
        self.guild_id = guild_id
        self.rolls = discord.ui.TextInput(label="Teto extra de Rolls", default=str(config["teto_bonus_rolls_progressao"]), max_length=4)
        self.claims = discord.ui.TextInput(label="Teto extra de Claims", default=str(config["teto_bonus_claims_progressao"]), max_length=3)
        self.add_item(self.rolls)
        self.add_item(self.claims)

    async def on_submit(self, interaction):
        try:
            rolls, claims = int(self.rolls.value.strip()), int(self.claims.value.strip())
            if not 0 <= rolls <= 1000 or not 0 <= claims <= 100:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Use valores entre 0–1000 Rolls e 0–100 Claims.", ephemeral=True)
            return
        colecao_db.definir_configuracao_colecao(self.guild_id, "teto_bonus_rolls_progressao", rolls)
        colecao_db.definir_configuracao_colecao(self.guild_id, "teto_bonus_claims_progressao", claims)
        await interaction.response.send_message(f"Tetos atualizados: +{rolls} Rolls e +{claims} Claims.", ephemeral=True)


class _ModalCardsPandora(discord.ui.Modal, title="Cards e puxadas"):
    def __init__(self, guild_id, config):
        super().__init__()
        self.guild_id = guild_id
        self.duracao = discord.ui.TextInput(label="Duração do card (segundos)", default=str(config["duracao_card_segundos"]), max_length=5)
        self.puxada = discord.ui.TextInput(label="Máximo por puxada", default=str(config["max_rolls_por_comando"]), max_length=4)
        self.wish = discord.ui.TextInput(label="Chance de wishlist (%)", default=str(round(config["chance_wish_roll"] * 100)), max_length=3)
        self.canal = discord.ui.TextInput(label="ID do canal automático (vazio = padrão)", default=config["canal_anuncio_id"] or "", required=False, max_length=25)
        for campo in (self.duracao, self.puxada, self.wish, self.canal):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            duracao, puxada, wish = int(self.duracao.value.strip()), int(self.puxada.value.strip()), int(self.wish.value.strip())
            canal = self.canal.value.strip()
            if not 10 <= duracao <= 86400 or not 1 <= puxada <= 1000 or not 0 <= wish <= 100 or (canal and not canal.isdigit()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Confira os valores: duração 10–86400, puxada 1–1000, wishlist 0–100 e ID numérico de canal.", ephemeral=True)
            return
        for campo, valor in (("duracao_card_segundos", duracao), ("max_rolls_por_comando", puxada), ("chance_wish_roll", wish / 100), ("canal_anuncio_id", canal or None)):
            colecao_db.definir_configuracao_colecao(self.guild_id, campo, valor)
        await interaction.response.send_message("Configuração de cards e puxadas atualizada.", ephemeral=True)


class _ModalCooldownBatalhaPandora(discord.ui.Modal, title="Cooldown de batalha"):
    def __init__(self, guild_id, config):
        super().__init__()
        self.guild_id = guild_id
        self.horas = discord.ui.TextInput(label="Horas (0 = desativado)", default=str(config["cooldown_batalha_horas"]), max_length=4)
        self.add_item(self.horas)

    async def on_submit(self, interaction):
        try:
            horas = int(self.horas.value.strip())
            if not 0 <= horas <= 720:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Use um número de 0 a 720 horas.", ephemeral=True)
            return
        colecao_db.definir_configuracao_colecao(self.guild_id, "cooldown_batalha_horas", horas)
        colecao_db.definir_configuracao_colecao(self.guild_id, "cooldown_batalha_ativo", 1 if horas else 0)
        await interaction.response.send_message("Cooldown de batalha " + (f"definido em {horas}h." if horas else "desativado."), ephemeral=True)


class _ModalWorldBossPandora(discord.ui.Modal, title="World Boss"):
    def __init__(self, guild_id, config):
        super().__init__()
        self.guild_id = guild_id
        self.ativo = discord.ui.TextInput(label="Ativo? (sim/não)", default="sim" if config["worldboss_ativo"] else "não", max_length=4)
        self.horarios = discord.ui.TextInput(label="Horários Brasília (ex.: 10,14,18,22)", default=config["worldboss_horarios"], max_length=50)
        self.inscricao = discord.ui.TextInput(label="Minutos de inscrição", default=str(config["worldboss_inscricao_minutos"]), max_length=3)
        self.turno = discord.ui.TextInput(label="Segundos por turno", default=str(config["worldboss_turno_segundos"]), max_length=4)
        self.limite = discord.ui.TextInput(label="Máximo de turnos", default=str(config["worldboss_limite_turnos"]), max_length=4)
        for campo in (self.ativo, self.horarios, self.inscricao, self.turno, self.limite):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            ativo = self.ativo.value.strip().lower() in {"sim", "s", "true", "1"}
            horarios = sorted({int(valor.strip()) for valor in self.horarios.value.split(",")})
            inscricao, turno, limite = int(self.inscricao.value), int(self.turno.value), int(self.limite.value)
            if not horarios or any(hora < 0 or hora > 23 for hora in horarios) or not 1 <= inscricao <= 120 or not 10 <= turno <= 3600 or not 1 <= limite <= 1000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Confira: horários 0–23 separados por vírgula, inscrição 1–120, turno 10–3600 e limite 1–1000.", ephemeral=True)
            return
        valores = (("worldboss_ativo", 1 if ativo else 0), ("worldboss_horarios", ",".join(map(str, horarios))), ("worldboss_inscricao_minutos", inscricao), ("worldboss_turno_segundos", turno), ("worldboss_limite_turnos", limite))
        for campo, valor in valores:
            colecao_db.definir_configuracao_colecao(self.guild_id, campo, valor)
        await interaction.response.send_message("World Boss configurado. As mudanças valem para os próximos eventos.", ephemeral=True)


class _ModalSeriePandora(discord.ui.Modal):
    def __init__(self, guild_id, bloquear):
        super().__init__(title="Bloquear série" if bloquear else "Desbloquear série")
        self.guild_id = guild_id
        self.bloquear = bloquear
        self.serie = discord.ui.TextInput(label="Nome da série/obra", max_length=100)
        self.add_item(self.serie)

    async def on_submit(self, interaction):
        serie = self.serie.value.strip()
        if not serie:
            await interaction.response.send_message("Informe uma série.", ephemeral=True)
            return
        canonica = colecao_db.encontrar_serie_por_nome(serie)
        if canonica:
            _aplicar_serie_admin(self.guild_id, canonica, self.bloquear)
            await interaction.response.send_message(f'Série "{canonica}" {"bloqueada" if self.bloquear else "desbloqueada"}.', ephemeral=True)
            return
        candidatas = colecao_db.series_do_catalogo(serie, 25)
        if not candidatas:
            await interaction.response.send_message(f'Nenhuma série parecida com "{serie}".', ephemeral=True)
            return
        await interaction.response.send_message("Escolha a série:", view=_ViewEscolherSerieAdmin(self.guild_id, self.bloquear, candidatas), ephemeral=True)


def _aplicar_serie_admin(guild_id, serie, bloquear):
    (colecao_db.bloquear_serie if bloquear else colecao_db.desbloquear_serie)(guild_id, serie)


class _ViewEscolherSerieAdmin(discord.ui.View):
    def __init__(self, guild_id, bloquear, series):
        super().__init__(timeout=120)
        self.guild_id, self.bloquear = guild_id, bloquear
        select = discord.ui.Select(placeholder="Escolha a série", options=[discord.SelectOption(label=serie[:100], value=str(i)) for i, serie in enumerate(series)])
        async def escolher(interaction):
            serie = series[int(interaction.data["values"][0])]
            _aplicar_serie_admin(self.guild_id, serie, self.bloquear)
            await interaction.response.edit_message(content=f'Série "{serie}" {"bloqueada" if self.bloquear else "desbloqueada"}.', view=None)
        select.callback = escolher
        self.add_item(select)


class _ModalResetarAcoesPandora(discord.ui.Modal, title="Resetar ações de jogador"):
    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id
        self.membro = discord.ui.TextInput(label="ID do jogador")
        self.acao = discord.ui.TextInput(label="Ação: rolls, claims ou ambos", default="ambos", max_length=10)
        self.add_item(self.membro)
        self.add_item(self.acao)

    async def on_submit(self, interaction):
        try:
            membro_id = int(self.membro.value.strip())
        except ValueError:
            await interaction.response.send_message("O ID do jogador precisa ser numérico.", ephemeral=True)
            return
        acao = self.acao.value.strip().lower()
        if acao not in {"rolls", "claims", "ambos"}:
            await interaction.response.send_message("Use rolls, claims ou ambos.", ephemeral=True)
            return
        resultados = []
        if acao in {"rolls", "ambos"}:
            resultados.append(f"{colecao_db.resetar_rolls_admin(self.guild_id, membro_id)} Rolls")
        if acao in {"claims", "ambos"}:
            resultados.append(f"{colecao_db.resetar_claims_admin(self.guild_id, membro_id)} Claims")
        await interaction.response.send_message("Reset concluído: " + " · ".join(resultados) + ".", ephemeral=True)


class _ModalPersonagemAdminPandora(discord.ui.Modal, title="Ação em personagem"):
    def __init__(self, guild_id, acao_inicial="afinidade"):
        super().__init__()
        self.guild_id = guild_id
        self.acao = discord.ui.TextInput(label="Ação: dar ou afinidade", default=acao_inicial, max_length=10)
        self.membro = discord.ui.TextInput(label="ID do jogador")
        self.personagem = discord.ui.TextInput(label="ID da personagem")
        self.valor = discord.ui.TextInput(label="Afinidade (somente para afinidade)", required=False, max_length=2)
        for campo in (self.acao, self.membro, self.personagem, self.valor):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            acao = self.acao.value.strip().lower()
            membro_id = int(self.membro.value.strip())
            if acao not in {"dar", "afinidade"}:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Use ação dar/afinidade e IDs numéricos.", ephemeral=True)
            return
        texto_personagem = self.personagem.value.strip()
        if not texto_personagem.isdigit():
            candidatas = colecao_db.buscar_personagens(texto_personagem, 25)
            if not candidatas:
                await interaction.response.send_message(f'Nenhuma personagem parecida com "{texto_personagem}".', ephemeral=True)
                return
            await interaction.response.send_message("Escolha a personagem:", view=_ViewEscolherPersonagemAdmin(self.guild_id, membro_id, acao, self.valor.value.strip(), candidatas), ephemeral=True)
            return
        personagem_id = int(texto_personagem)
        if acao == "afinidade":
            try:
                valor = int(self.valor.value.strip())
                if not 0 <= valor <= 10:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message("A Afinidade deve estar entre 0 e 10.", ephemeral=True)
                return
            if colecao_db.dono_do_personagem(self.guild_id, personagem_id) != str(membro_id):
                await interaction.response.send_message("Esse jogador não possui essa personagem.", ephemeral=True)
                return
            novo = colecao_db.definir_afinidade_admin(self.guild_id, membro_id, personagem_id, valor)
            personagem = colecao_db.personagem_por_id(personagem_id)
            await interaction.response.send_message(f"Afinidade de {personagem['nome']} definida em {novo}.", ephemeral=True)
            return
        membro = interaction.guild.get_member(membro_id)
        if membro is None:
            await interaction.response.send_message("Jogador não encontrado neste servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok, erro, embed = await gacha.atribuir_personagem_admin(self.guild_id, personagem_id, membro)
        if not ok:
            await interaction.followup.send(erro, ephemeral=True)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)


class _ViewEscolherPersonagemAdmin(discord.ui.View):
    def __init__(self, guild_id, membro_id, acao, valor, candidatas):
        super().__init__(timeout=120)
        select = discord.ui.Select(placeholder="Escolha a personagem", options=[discord.SelectOption(label=f"{p['nome']} · #{p['id']}"[:100], value=str(p['id'])) for p in candidatas])
        async def escolher(interaction):
            personagem_id = int(interaction.data["values"][0])
            if acao == "afinidade":
                try: valor_int = int(valor)
                except ValueError: valor_int = -1
                if not 0 <= valor_int <= 10 or colecao_db.dono_do_personagem(guild_id, personagem_id) != str(membro_id):
                    await interaction.response.edit_message(content="Afinidade inválida ou a personagem não pertence ao jogador.", view=None); return
                novo = colecao_db.definir_afinidade_admin(guild_id, membro_id, personagem_id, valor_int)
                await interaction.response.edit_message(content=f"Afinidade definida em {novo}.", view=None); return
            membro = interaction.guild.get_member(membro_id)
            if membro is None:
                await interaction.response.edit_message(content="Jogador não encontrado.", view=None); return
            await interaction.response.defer()
            ok, erro, _embed = await gacha.atribuir_personagem_admin(guild_id, personagem_id, membro)
            await interaction.edit_original_response(content=erro if not ok else "Personagem entregue.", view=None)
        select.callback = escolher
        self.add_item(select)


class _ModalBuscarPersonagemParaDar(discord.ui.Modal, title="Buscar personagem"):
    def __init__(self, guild_id, membro_id):
        super().__init__()
        self.guild_id, self.membro_id = guild_id, membro_id
        self.nome = discord.ui.TextInput(label="Nome da personagem", placeholder="Digite parte do nome", max_length=100)
        self.add_item(self.nome)

    async def on_submit(self, interaction):
        candidatas = colecao_db.buscar_personagens(self.nome.value.strip(), 25)
        if not candidatas:
            await interaction.response.send_message("Nenhuma personagem encontrada.", ephemeral=True)
            return
        await interaction.response.send_message("Escolha a personagem:", view=_ViewDarPersonagem(interaction.guild, self.membro_id, candidatas), ephemeral=True)


class _ViewDarPersonagem(discord.ui.View):
    def __init__(self, guild, membro_id=None, candidatas=None):
        super().__init__(timeout=180)
        self.guild, self.guild_id, self.membro_id = guild, guild.id, membro_id
        if membro_id is None:
            seletor = discord.ui.UserSelect(placeholder="Escolha quem vai receber")
            async def escolher_membro(interaction):
                self.membro_id = int(interaction.data["values"][0])
                await interaction.response.send_modal(_ModalBuscarPersonagemParaDar(self.guild_id, self.membro_id))
            seletor.callback = escolher_membro
            self.add_item(seletor)
        else:
            opcoes = []
            for personagem in candidatas:
                dono_id = colecao_db.dono_do_personagem(self.guild_id, personagem["id"])
                dono = self.guild.get_member(int(dono_id)) if dono_id else None
                dono_txt = dono.display_name if dono else (f"ID {dono_id}" if dono_id else "Livre")
                opcoes.append(discord.SelectOption(
                    label=f"{personagem['nome']} · #{personagem['id']}"[:100], value=str(personagem["id"]),
                    description=(f"Já pertence a: {dono_txt}" if dono_id else "Livre para entregar")[:100],
                    emoji="👤" if dono_id else "✨",
                ))
            seletor = discord.ui.Select(placeholder="Escolha a personagem", options=opcoes)
            async def entregar(interaction):
                membro = interaction.guild.get_member(self.membro_id)
                if membro is None:
                    await interaction.response.edit_message(content="Jogador não encontrado.", view=None)
                    return
                await interaction.response.defer()
                ok, erro, _embed = await gacha.atribuir_personagem_admin(self.guild_id, int(interaction.data["values"][0]), membro)
                await interaction.edit_original_response(content=erro if not ok else f"Personagem entregue para {membro.display_name}.", view=None)
            seletor.callback = entregar
            self.add_item(seletor)


class _ViewAdminPandora(discord.ui.View):
    def __init__(self, guild_id, autor_id):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.autor_id = str(autor_id)

    async def _autor(self, interaction):
        if str(interaction.user.id) != self.autor_id:
            await interaction.response.send_message("Este painel pertence a outro administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Limites do ciclo", emoji="🎲", style=discord.ButtonStyle.primary, row=0)
    async def limites(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalLimitesPandora(self.guild_id, colecao_db.obter_configuracao_colecao(self.guild_id)))

    @discord.ui.button(label="Progressão", emoji="📈", style=discord.ButtonStyle.success, row=0)
    async def progressao(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalProgressaoPandora(self.guild_id, colecao_db.obter_configuracao_colecao(self.guild_id)))

    @discord.ui.button(label="Cards e puxadas", emoji="🃏", style=discord.ButtonStyle.primary, row=0)
    async def cards(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalCardsPandora(self.guild_id, colecao_db.obter_configuracao_colecao(self.guild_id)))

    @discord.ui.button(label="Alternar NSFW", emoji="🔞", style=discord.ButtonStyle.secondary, row=1)
    async def nsfw(self, interaction, _button):
        if not await self._autor(interaction):
            return
        config = colecao_db.obter_configuracao_colecao(self.guild_id)
        ativo = not config["nsfw_permitido"]
        colecao_db.definir_nsfw_permitido(self.guild_id, ativo)
        await interaction.response.send_message(f"Conteúdo NSFW {'ligado' if ativo else 'desligado'}.", ephemeral=True)

    @discord.ui.button(label="Cooldown de batalha", emoji="⚔️", style=discord.ButtonStyle.secondary, row=1)
    async def cooldown_batalha(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalCooldownBatalhaPandora(self.guild_id, colecao_db.obter_configuracao_colecao(self.guild_id)))

    @discord.ui.button(label="World Boss", emoji="🐉", style=discord.ButtonStyle.primary, row=1)
    async def worldboss(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalWorldBossPandora(self.guild_id, colecao_db.obter_configuracao_colecao(self.guild_id)))

    @discord.ui.button(label="Bloquear série", emoji="🚫", style=discord.ButtonStyle.secondary, row=2)
    async def bloquear_serie(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalSeriePandora(self.guild_id, True))

    @discord.ui.button(label="Desbloquear série", emoji="✅", style=discord.ButtonStyle.secondary, row=2)
    async def desbloquear_serie(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalSeriePandora(self.guild_id, False))

    @discord.ui.button(label="Resetar ações", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def resetar_acoes(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalResetarAcoesPandora(self.guild_id))

    @discord.ui.button(label="Dar personagem", emoji="🎁", style=discord.ButtonStyle.secondary, row=2)
    async def dar_personagem(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_message("Escolha quem vai receber:", view=_ViewDarPersonagem(interaction.guild), ephemeral=True)

    @discord.ui.button(label="Definir Afinidade", emoji="💞", style=discord.ButtonStyle.secondary, row=2)
    async def definir_afinidade(self, interaction, _button):
        if await self._autor(interaction):
            await interaction.response.send_modal(_ModalPersonagemAdminPandora(self.guild_id))

    async def _abrir_validacao(self, interaction, fila):
        total = await asyncio.to_thread(_contar_fila_classes, fila)
        if not total:
            await interaction.response.send_message("Nada pendente nessa fila.", ephemeral=True)
            return
        await interaction.response.send_modal(_ModalValidarClassesPandora(fila, total))

    @discord.ui.button(label="Validar sem classe", emoji="🔎", style=discord.ButtonStyle.secondary, row=3)
    async def validar_normais(self, interaction, _button):
        if await self._autor(interaction): await self._abrir_validacao(interaction, "possuidas")

    @discord.ui.button(label="Revalidar falhas", emoji="⚠️", style=discord.ButtonStyle.secondary, row=3)
    async def validar_falhas(self, interaction, _button):
        if await self._autor(interaction): await self._abrir_validacao(interaction, "falhas")

    @discord.ui.button(label="Validar não adquiridas", emoji="📚", style=discord.ButtonStyle.secondary, row=3)
    async def validar_catalogo(self, interaction, _button):
        if await self._autor(interaction): await self._abrir_validacao(interaction, "catalogo")


# Filas de classificação do painel admin (2026-10-14, pedido do usuário:
# "deixa a pessoa informar a quantidade, e tem de informar quantas tem").
# "falhas" junta as falhas das possuídas e as do catálogo não adquirido.
_TITULOS_FILA_CLASSES = {"possuidas": "Validar sem classe", "falhas": "Revalidar falhas", "catalogo": "Validar não adquiridas"}
_MAX_VALIDACAO_CLASSES = 2000


def _contar_fila_classes(fila):
    if fila == "catalogo":
        return colecao_db.contar_personagens_nao_adquiridos_sem_classe()
    if fila == "falhas":
        return colecao_db.contar_personagens_possuidos_sem_classe(True) + colecao_db.contar_personagens_nao_adquiridos_sem_classe(True)
    return colecao_db.contar_personagens_possuidos_sem_classe(False)


def _buscar_fila_classes(fila, limite):
    if fila == "catalogo":
        return colecao_db.personagens_nao_adquiridos_sem_classe(limite)
    if fila == "falhas":
        possuidas = colecao_db.personagens_possuidos_sem_classe(limite, True)
        return possuidas + colecao_db.personagens_nao_adquiridos_sem_classe(limite - len(possuidas), True) if len(possuidas) < limite else possuidas
    return colecao_db.personagens_possuidos_sem_classe(limite, False)


class _ModalValidarClassesPandora(discord.ui.Modal):
    def __init__(self, fila, total):
        super().__init__(title=_TITULOS_FILA_CLASSES[fila])
        self.fila = fila
        self.total = total
        maximo = min(total, _MAX_VALIDACAO_CLASSES)
        self.quantidade = discord.ui.TextInput(
            label=f"Quantidade (na fila: {colecao_db.fmt_numero(total)})"[:45],
            placeholder=f"1 a {maximo}",
            default=str(min(100, maximo)),
            max_length=5,
        )
        self.add_item(self.quantidade)

    async def on_submit(self, interaction):
        maximo = min(self.total, _MAX_VALIDACAO_CLASSES)
        try:
            quantidade = int(self.quantidade.value.strip())
            if not 1 <= quantidade <= maximo:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(f"Informe um número de 1 a {maximo}.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        pendentes = await asyncio.to_thread(_buscar_fila_classes, self.fila, quantidade)
        sucesso = falhas = 0
        for personagem in pendentes:
            if (await gacha.revelar_classe(personagem))[0]: sucesso += 1
            else:
                falhas += 1
                await asyncio.to_thread(colecao_db.marcar_falha_classificacao, personagem["id"])
        restantes = await asyncio.to_thread(_contar_fila_classes, self.fila)
        texto = (
            f"{_TITULOS_FILA_CLASSES[self.fila]}: {colecao_db.fmt_numero(len(pendentes))} verificadas, "
            f"{colecao_db.fmt_numero(sucesso)} classificadas, {colecao_db.fmt_numero(falhas)} falharam. "
            f"Restam {colecao_db.fmt_numero(restantes)} na fila."
        )
        try:
            await interaction.followup.send(texto, ephemeral=True)
        except discord.HTTPException:
            # O token da interação vale 15 min; rodadas grandes passam disso.
            await interaction.user.send(texto)


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

    @app_commands.command(name="pandora", description="Abre o painel do Colecionador (rolar, coleção e mais)")
    async def _pandora(interaction: discord.Interaction):
        """Painel-raiz (2026-08-29, pedido do usuário: "os bots estão
        ficando muito poluídos"/"e se fizermos um painel com botões, assim
        como foi feito com o legends awaken?") - Fase 1 (ver plano da
        sessão que criou isto): só Rolar/Coleção por enquanto, os comandos
        antigos equivalentes continuam existindo até cada botão ser
        validado ao vivo. Lógica de verdade em `eris/colecao/paineis.py`.
        🔥 Renomeado de `/waifu` pra `/pandora` (2026-09-02, pedido do
        usuário)."""
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
        if colecao_db.esta_na_wishlist(interaction.guild.id, interaction.user.id, id_personagem) and not confirmar:
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
            ok, mensagem = colecao_db.wishlist_adicionar(interaction.guild.id, interaction.user.id, id_personagem)
            await interaction.response.send_message(f"{'⭐' if ok else '⚠️'} {mensagem}", ephemeral=True)
        else:
            colecao_db.wishlist_remover(interaction.guild.id, interaction.user.id, id_personagem)
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
        ok, mensagem = colecao_db.wishlist_adicionar(interaction.guild.id, interaction.user.id, id_personagem)
        await interaction.response.send_message(
            f"{'⭐' if ok else '⚠️'} {mensagem if not ok else personagem['nome'] + ' adicionada à sua Wishlist.'}",
            ephemeral=True,
        )

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

    async def _somente_admin_do_servidor_colecao(interaction: discord.Interaction):
        """Mesma régua de `/pandora_admin nsfw` original (renomeado de
        `/colecao_admin` em 2026-09-02), agora compartilhada
        por todos os subcomandos de configuração - permissão de administrador
        NAQUELE servidor (não `_somente_dono`, que é dono da Galateia; aqui é
        conteúdo/dificuldade do jogo, faz sentido variar por servidor)."""
        eh_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if interaction.guild is None or not eh_admin:
            await interaction.response.send_message("Só administradores do servidor podem mudar essa configuração.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="pandora_admin", description="Abre o painel de administração do Pandora")
    async def _pandora_admin(interaction: discord.Interaction):
        if not await _somente_admin_do_servidor_colecao(interaction):
            return
        await interaction.response.send_message(
            _texto_configuracao_pandora(interaction.guild),
            view=_ViewAdminPandora(interaction.guild.id, interaction.user.id),
            ephemeral=True,
        )

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

    @grupo_loja.command(name="upgrade", description="Compra o próximo nível de rolls máximos (+5 permanente por nível, sem teto)")
    async def _loja_upgrade(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # 🔥 `comprar_upgrade_rolls_ate` (2026-09-03) - o upgrade perdeu o
        # teto de nível 5; este comando antigo (1 nível por clique) agora
        # só passa "nível atual + 1" como alvo pra manter o mesmo
        # comportamento de antes - o botão "Upgrade de rolls" da Loja
        # (`/pandora` -> 🛒 Loja) é quem ganhou o dropdown de pular vários
        # níveis de uma vez.
        proximo_nivel = colecao_db.nivel_upgrade_rolls(interaction.guild.id, interaction.user.id) + 1
        ok, mensagem = colecao_db.comprar_upgrade_rolls_ate(interaction.guild.id, interaction.user.id, proximo_nivel)
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    @grupo_loja.command(name="upgrade_claims", description="Compra o próximo nível de claims máximos (+1 permanente por nível, sem teto)")
    async def _loja_upgrade_claims(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        proximo_nivel = colecao_db.nivel_upgrade_claims(interaction.guild.id, interaction.user.id) + 1
        ok, mensagem = colecao_db.comprar_upgrade_claims_ate(interaction.guild.id, interaction.user.id, proximo_nivel)
        await interaction.response.send_message(mensagem, ephemeral=not ok)

    @app_commands.command(name="merge", description="Abre a Fusão: sacrifica 5 personagens da mesma raridade por 1 à sua escolha")
    async def _merge(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Isso só funciona dentro de um servidor.", ephemeral=True)
            return
        # Mesmo painel do botão "🧬 Fusão" do `/pandora` (escolher as 5,
        # depois o alvo). A versão antiga, por #id, chamava
        # `economia.executar_merge` com a assinatura de antes de 2026-09-02
        # e quebrava com TypeError.
        await paineis.abrir_fusao(interaction)

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
        # (2026-08-29) - compartilhado com o botão 🔄 Trocas do painel
        # `/pandora`, pra nunca duplicar essa lógica em 2 lugares.
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
    tree.add_command(_pandora)
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
    tree.add_command(_pandora_admin)
    tree.add_command(grupo_loja)
    tree.add_command(grupo_trocar)
    tree.add_command(grupo_party)


def registrar(tree):
    _registrar_slash_colecao(tree)
