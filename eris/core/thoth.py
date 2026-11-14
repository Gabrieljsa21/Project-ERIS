# -*- coding: utf-8 -*-
"""Aprovação das respostas de WhatsApp sugeridas pelo THOTH (2026-11-13).

A GAIA recebe do THOTH um rascunho de resposta e pede ao ERIS uma DM para cada
dono (`POST /notificar_donos_com_botoes`, ver `eris/api_bridge.py`) com três
botões: Enviar, Editar e Descartar. O ERIS só desenha os botões e repassa a
decisão; quem envia pelo WhatsApp (ou descarta) é a GAIA, pelo webhook reverso
`gaia_webhook.pedir_acao_thoth`.

Botões persistentes no mesmo padrão de `musica.BotaoMusica`: `custom_id`
`thoth:<acao>:<id>` e `BotaoThoth` registrado com `client.add_dynamic_items`
no papel "principal" (`eris/bot.py`). O texto sugerido não cabe no
`custom_id` (100 caracteres), então fica em `data/thoth_rascunhos.json` pelo
ID do rascunho, para o "Editar" abrir já preenchido mesmo depois de um
reinício. Entradas com mais de 7 dias são podadas a cada gravação."""
import asyncio
import os
import re
import time

import discord

from eris.config import LIMITE_CARACTERES_MENSAGEM, PASTA_DADOS
from eris.core import seguranca
from eris.integrations import gaia_webhook
from eris.persistencia import ler_json, salvar_json_atomico

PADRAO_ID_RASCUNHO = r"[0-9a-f]{6,32}"
_BOTOES_THOTH = {
    "enviar": ("Enviar", discord.ButtonStyle.success),
    "editar": ("Editar", discord.ButtonStyle.secondary),
    "descartar": ("Descartar", discord.ButtonStyle.danger),
}
_STATUS_POR_ACAO = {"enviar": "✅ Enviado", "descartar": "🗑️ Descartado"}
_ARQUIVO_RASCUNHOS = os.path.join(PASTA_DADOS, "thoth_rascunhos.json")
_IDADE_MAX_SEGUNDOS = 7 * 24 * 3600
_TEXTO_EDITAVEL_MAX = 4000  # teto do TextInput do Discord


def id_rascunho_valido(rascunho_id):
    return isinstance(rascunho_id, str) and re.fullmatch(PADRAO_ID_RASCUNHO, rascunho_id) is not None


def podar_rascunhos(rascunhos, agora=None):
    """Devolve só as entradas com menos de 7 dias (entrada sem data sai)."""
    agora = time.time() if agora is None else agora
    return {
        rid: dados for rid, dados in rascunhos.items()
        if isinstance(dados, dict) and agora - dados.get("criado_em", 0) <= _IDADE_MAX_SEGUNDOS
    }


def registrar_rascunho(rascunho_id, texto, agora=None):
    agora = time.time() if agora is None else agora
    rascunhos = podar_rascunhos(ler_json(_ARQUIVO_RASCUNHOS, {}), agora)
    rascunhos[rascunho_id] = {"texto": texto, "criado_em": agora}
    salvar_json_atomico(_ARQUIVO_RASCUNHOS, rascunhos)


def texto_do_rascunho(rascunho_id):
    dados = ler_json(_ARQUIVO_RASCUNHOS, {}).get(rascunho_id)
    return dados.get("texto", "") if isinstance(dados, dict) else ""


def esquecer_rascunho(rascunho_id):
    rascunhos = podar_rascunhos(ler_json(_ARQUIVO_RASCUNHOS, {}))
    rascunhos.pop(rascunho_id, None)
    salvar_json_atomico(_ARQUIVO_RASCUNHOS, rascunhos)


def conteudo_com_status(conteudo, status, limite=LIMITE_CARACTERES_MENSAGEM):
    """Acrescenta a linha de status no fim, encurtando o texto se a soma
    passar do limite do Discord."""
    sufixo = f"\n\n{status}"
    conteudo = conteudo or ""
    if len(conteudo) + len(sufixo) > limite:
        conteudo = conteudo[:limite - len(sufixo) - 1].rstrip() + "…"
    return conteudo + sufixo


class BotaoThoth(discord.ui.DynamicItem[discord.ui.Button], template=rf"thoth:(?P<acao>enviar|editar|descartar):(?P<id>{PADRAO_ID_RASCUNHO})"):
    def __init__(self, acao, rascunho_id, desabilitado=False):
        rotulo, estilo = _BOTOES_THOTH[acao]
        super().__init__(discord.ui.Button(
            label=rotulo, style=estilo, custom_id=f"thoth:{acao}:{rascunho_id}", disabled=desabilitado,
        ))
        self.acao = acao
        self.rascunho_id = rascunho_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["acao"], match["id"])

    async def callback(self, interaction: discord.Interaction):
        if not seguranca.eh_dono(interaction.user.id):
            await interaction.response.send_message("Só o dono pode usar.", ephemeral=True)
            return
        if self.acao == "editar":
            texto = texto_do_rascunho(self.rascunho_id)
            await interaction.response.send_modal(_ModalEditarThoth(self.rascunho_id, texto, interaction.message))
            return
        await executar_acao(interaction, self.rascunho_id, self.acao, None, interaction.message)


class ViewThoth(discord.ui.View):
    """`timeout=None`: o rascunho pode esperar horas por uma decisão."""

    def __init__(self, rascunho_id, desabilitada=False):
        super().__init__(timeout=None)
        for acao in _BOTOES_THOTH:
            self.add_item(BotaoThoth(acao, rascunho_id, desabilitada))


class _ModalEditarThoth(discord.ui.Modal, title="Editar resposta"):
    def __init__(self, rascunho_id, texto, mensagem):
        super().__init__(timeout=None)
        self.rascunho_id = rascunho_id
        self.mensagem = mensagem
        self.resposta = discord.ui.TextInput(
            label="Resposta", style=discord.TextStyle.paragraph, max_length=_TEXTO_EDITAVEL_MAX,
            default=(texto or "")[:_TEXTO_EDITAVEL_MAX] or None,
        )
        self.add_item(self.resposta)

    async def on_submit(self, interaction: discord.Interaction):
        await executar_acao(interaction, self.rascunho_id, "enviar", self.resposta.value, self.mensagem)


async def executar_acao(interaction, rascunho_id, acao, texto, mensagem):
    """Repassa a decisão para a GAIA. Deu certo: desabilita os botões, põe a
    linha de status na DM e esquece o rascunho. Falhou: só avisa, e os botões
    continuam ativos para tentar de novo."""
    await interaction.response.defer(ephemeral=True)
    resultado = await asyncio.to_thread(gaia_webhook.pedir_acao_thoth, interaction.user.id, rascunho_id, acao, texto)
    if not resultado.get("ok"):
        await interaction.followup.send(f"Falhou: {resultado.get('mensagem') or 'sem detalhe'}", ephemeral=True)
        return
    if mensagem is not None:
        try:
            await mensagem.edit(
                content=conteudo_com_status(mensagem.content, _STATUS_POR_ACAO[acao]),
                view=ViewThoth(rascunho_id, desabilitada=True),
            )
        except discord.HTTPException as e:
            print(f" [ERIS] THOTH: não consegui atualizar a DM do rascunho {rascunho_id}: {e}")
    await asyncio.to_thread(esquecer_rascunho, rascunho_id)
    await interaction.followup.send(resultado.get("mensagem") or _STATUS_POR_ACAO[acao], ephemeral=True)


# ---------- Perguntas de confirmação do cofre do THOTH (2026-11-14) ----------
# O THOTH pergunta o que o Claude deduziu ("Maurício é cônjuge de Ana?"); cada
# opção vira um botão `thothp:<id>:<índice>`. Os rótulos ficam em
# `data/thoth_perguntas.json` para a mensagem ser redesenhada (botões
# desligados) mesmo depois de um reinício. A resposta vai para a GAIA, que
# repassa ao THOTH (`gaia_webhook.responder_pergunta_thoth`).

PADRAO_ID_PERGUNTA = r"[0-9a-f]{12}"
_ARQUIVO_PERGUNTAS = os.path.join(PASTA_DADOS, "thoth_perguntas.json")
_MAX_OPCOES = 5                 # uma fileira do Discord


def id_pergunta_valido(pergunta_id):
    return isinstance(pergunta_id, str) and re.fullmatch(PADRAO_ID_PERGUNTA, pergunta_id) is not None


def registrar_pergunta(pergunta_id, opcoes, agora=None):
    agora = time.time() if agora is None else agora
    perguntas = podar_rascunhos(ler_json(_ARQUIVO_PERGUNTAS, {}), agora)
    perguntas[pergunta_id] = {"opcoes": [str(o)[:80] for o in opcoes][:_MAX_OPCOES], "criado_em": agora}
    salvar_json_atomico(_ARQUIVO_PERGUNTAS, perguntas)


def opcoes_da_pergunta(pergunta_id):
    dados = ler_json(_ARQUIVO_PERGUNTAS, {}).get(pergunta_id)
    return dados.get("opcoes", []) if isinstance(dados, dict) else []


class BotaoPerguntaThoth(discord.ui.DynamicItem[discord.ui.Button],
                         template=rf"thothp:(?P<id>{PADRAO_ID_PERGUNTA}):(?P<opcao>[0-9])"):
    def __init__(self, pergunta_id, opcao, rotulo="?", desabilitado=False):
        super().__init__(discord.ui.Button(
            label=rotulo, style=discord.ButtonStyle.primary if opcao == 0 else discord.ButtonStyle.secondary,
            custom_id=f"thothp:{pergunta_id}:{opcao}", disabled=desabilitado,
        ))
        self.pergunta_id = pergunta_id
        self.opcao = opcao

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["id"], int(match["opcao"]), item.label or "?")

    async def callback(self, interaction: discord.Interaction):
        if not seguranca.eh_dono(interaction.user.id):
            await interaction.response.send_message("Só o dono pode usar.", ephemeral=True)
            return
        await responder_pergunta(interaction, self.pergunta_id, self.opcao, interaction.message)


class ViewPerguntaThoth(discord.ui.View):
    """Uma pergunta, um botão por opção; `timeout=None` porque a resposta pode vir dias depois."""

    def __init__(self, pergunta_id, opcoes, desabilitada=False):
        super().__init__(timeout=None)
        for indice, rotulo in enumerate(opcoes[:_MAX_OPCOES]):
            self.add_item(BotaoPerguntaThoth(pergunta_id, indice, rotulo, desabilitada))


async def responder_pergunta(interaction, pergunta_id, opcao, mensagem):
    """Repassa a escolha. Deu certo: desliga os botões e põe a resposta na DM."""
    await interaction.response.defer(ephemeral=True)
    resultado = await asyncio.to_thread(gaia_webhook.responder_pergunta_thoth, interaction.user.id, pergunta_id, opcao)
    if not resultado.get("ok"):
        await interaction.followup.send(f"Falhou: {resultado.get('mensagem') or 'sem detalhe'}", ephemeral=True)
        return
    if mensagem is not None:
        opcoes = opcoes_da_pergunta(pergunta_id) or [b.label for b in getattr(mensagem, "components", [])]
        try:
            await mensagem.edit(
                content=conteudo_com_status(mensagem.content, f"✅ {resultado.get('mensagem') or 'Respondido'}"),
                view=ViewPerguntaThoth(pergunta_id, opcoes, desabilitada=True),
            )
        except discord.HTTPException as e:
            print(f" [ERIS] THOTH: não consegui atualizar a DM da pergunta {pergunta_id}: {e}")
    await interaction.followup.send("Anotado.", ephemeral=True)
