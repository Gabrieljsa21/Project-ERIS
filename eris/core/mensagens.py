# -*- coding: utf-8 -*-
"""Mecânica de mensagens do ERIS - fatiamento de texto acima do limite do
Discord, lotes de anexo, entrega em DM/canal, canal dentro de categoria e
perfil via REST. Extraído de `features/discord_presence/discord_bot.py`
(GAIA, antes da extração de 2026-08-24) - mesmo comportamento de sempre, só
reorganizado: aqui é só ENTREGA, nunca decide o que mandar (isso é sempre um
parâmetro de quem chama - a GAIA, via `eris/api_bridge.py`, ou o próprio
`eris/bot.py` respondendo um comando local)."""
import io
import re

import discord
import requests

from eris.config import (
    ANEXOS_MAX_BYTES_POR_MENSAGEM, ANEXOS_MAX_POR_MENSAGEM, LIMITE_CARACTERES_MENSAGEM,
)

# 🔥 Guardado quando o bot conecta (ver eris/bot.py::on_ready) - permite
# entregar mensagem PROATIVA (não é resposta a nada, é a GAIA pedindo pra
# avisar algo) de qualquer lugar do código sem precisar passar o client
# inteiro através de todas as chamadas.
_client_atual = None


def definir_client(client):
    global _client_atual
    _client_atual = client


def cliente_conectado():
    return _client_atual


def fatiar_mensagem(texto, limite=LIMITE_CARACTERES_MENSAGEM):
    """Corta `texto` em blocos de até `limite` caracteres, preferindo cortar
    numa quebra de linha (nunca no meio de uma palavra). Só corta no meio de
    verdade se não achar nenhuma quebra de linha dentro do bloco."""
    blocos = []
    restante = texto
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = limite
        blocos.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    if restante:
        blocos.append(restante)
    return blocos


def lotes_arquivos(arquivos):
    """Agrupa `[(nome, bytes), ...]` em lotes de até ANEXOS_MAX_POR_MENSAGEM
    arquivos E até ANEXOS_MAX_BYTES_POR_MENSAGEM somados - o que fechar
    primeiro. Um anexo sozinho já maior que o limite ainda vai (sozinho, no
    seu próprio lote)."""
    lotes = []
    lote_atual, bytes_atual = [], 0
    for nome, dado in (arquivos or []):
        if lote_atual and (len(lote_atual) >= ANEXOS_MAX_POR_MENSAGEM or bytes_atual + len(dado) > ANEXOS_MAX_BYTES_POR_MENSAGEM):
            lotes.append(lote_atual)
            lote_atual, bytes_atual = [], 0
        lote_atual.append((nome, dado))
        bytes_atual += len(dado)
    if lote_atual:
        lotes.append(lote_atual)
    return lotes


async def _enviar_blocos_e_arquivos(enviar, blocos, lotes):
    """Manda `blocos` de texto e `lotes` de arquivos através de `enviar`
    (`usuario.send`/`canal.send`) - o PRIMEIRO lote de arquivos vai JUNTO do
    ÚLTIMO bloco de texto, na MESMA mensagem, em vez de virar uma mensagem
    exclusiva só pro anexo."""
    if blocos and lotes:
        for bloco in blocos[:-1]:
            await enviar(bloco)
        primeiro_lote = [discord.File(io.BytesIO(dado), filename=nome) for nome, dado in lotes[0]]
        await enviar(blocos[-1], files=primeiro_lote)
        lotes = lotes[1:]
    else:
        for bloco in blocos:
            await enviar(bloco)
    for lote in lotes:
        arquivos_discord = [discord.File(io.BytesIO(dado), filename=nome) for nome, dado in lote]
        await enviar(files=arquivos_discord)


async def notificar_donos(donos_ids, texto, arquivos=None):
    """Manda uma DM PROATIVA pra cada ID de dono. Silencioso se o bot ainda
    não conectou. Cada dono é tentado independente - um falhar (bloqueou o
    bot, ID errado) não impede os outros."""
    if _client_atual is None:
        return
    blocos = fatiar_mensagem(texto)
    lotes = lotes_arquivos(arquivos)
    for id_ in donos_ids:
        try:
            usuario = await _client_atual.fetch_user(int(id_))
            await _enviar_blocos_e_arquivos(usuario.send, blocos, lotes)
        except Exception as e:
            print(f" [ERIS] Falha ao notificar dono {id_} proativamente: {e}")


async def enviar_para_canal(channel_id, texto, arquivos=None):
    """Entrega direta por ID de canal (usado pela GAIA quando ela já sabe o
    canal de destino - ex.: resposta a uma DM em andamento, ver
    `eris/api_bridge.py`)."""
    if _client_atual is None:
        return False
    canal = _client_atual.get_channel(int(channel_id))
    if canal is None:
        try:
            canal = await _client_atual.fetch_channel(int(channel_id))
        except Exception:
            return False
    try:
        await _enviar_blocos_e_arquivos(canal.send, fatiar_mensagem(texto), lotes_arquivos(arquivos))
        return True
    except Exception as e:
        print(f" [ERIS] Falha ao entregar mensagem no canal {channel_id}: {e}")
        return False


def nome_canal_valido(texto):
    """Sanitiza um texto qualquer pro formato de nome de canal do Discord -
    minúsculo, espaço/barra/pontuação viram hífen, até 90 caracteres (limite
    real é 100, folga de propósito). Preserva acento/letra unicode."""
    nome = re.sub(r"[^\w-]+", "-", texto.strip(), flags=re.UNICODE).lower()
    nome = re.sub(r"-+", "-", nome).strip("-_")
    return nome[:90] or "geral"


async def obter_ou_criar_canal_em_categoria(guild_id, categoria_id, nome_canal):
    """Acha um canal de TEXTO com esse nome dentro da categoria `categoria_id`
    do servidor `guild_id` - cria um novo (na mesma categoria) se ainda não
    existir. Devolve o `discord.TextChannel`, ou None se o bot não conectou,
    o servidor/categoria não for encontrado, ou a criação falhar - nunca
    levanta exceção."""
    if _client_atual is None:
        return None
    guild = _client_atual.get_guild(int(guild_id))
    if guild is None:
        print(f" [ERIS] Servidor {guild_id} não encontrado (bot não está nele, ou id errado).")
        return None
    categoria = guild.get_channel(int(categoria_id))
    if not isinstance(categoria, discord.CategoryChannel):
        print(f" [ERIS] Categoria {categoria_id} não encontrada no servidor {guild_id}.")
        return None
    for canal in categoria.channels:
        if isinstance(canal, discord.TextChannel) and canal.name == nome_canal:
            return canal
    try:
        return await guild.create_text_channel(nome_canal, category=categoria)
    except Exception as e:
        print(f" [ERIS] Erro ao criar o canal '{nome_canal}' na categoria {categoria_id}: {e}")
        return None


async def notificar_canal_em_categoria(guild_id, categoria_id, nome_canal, texto, arquivos=None):
    """Manda uma mensagem PROATIVA num canal de texto (achando ou criando
    dentro da categoria)."""
    canal = await obter_ou_criar_canal_em_categoria(guild_id, categoria_id, nome_canal)
    if canal is None:
        return False
    try:
        await _enviar_blocos_e_arquivos(canal.send, fatiar_mensagem(texto), lotes_arquivos(arquivos))
        return True
    except Exception as e:
        print(f" [ERIS] Falha ao notificar o canal '{nome_canal}': {e}")
        return False


async def testar_canal_categoria(guild_id, categoria_id, nome_canal):
    """Testa achar/criar o canal e manda uma mensagem de teste, devolvendo
    `(sucesso, mensagem)` SEMPRE (nunca levanta exceção) com o motivo EXATO
    de uma falha - usado pelo botão "🧪 Testar canal" do modal de E-mail da
    GAIA."""
    if _client_atual is None:
        return False, "Bot do ERIS ainda não conectou."
    try:
        guild = _client_atual.get_guild(int(guild_id))
    except (TypeError, ValueError):
        return False, "ID do servidor inválido (precisa ser só números)."
    if guild is None:
        return False, "Servidor não encontrado - confira se o bot está nele e se o ID está certo."
    try:
        categoria = guild.get_channel(int(categoria_id))
    except (TypeError, ValueError):
        return False, "ID da categoria inválido (precisa ser só números)."
    if not isinstance(categoria, discord.CategoryChannel):
        return False, "Categoria não encontrada nesse servidor (confira o ID - tem que ser de uma CATEGORIA, não de um canal)."
    canal = await obter_ou_criar_canal_em_categoria(guild_id, categoria_id, nome_canal)
    if canal is None:
        return False, f"Servidor e categoria certos, mas não consegui achar/criar o canal \"{nome_canal}\" - confira a permissão \"Gerenciar Canais\" do bot nessa categoria."
    try:
        await canal.send(f"🧪 Teste de configuração - se você está vendo isso em #{canal.name}, servidor/categoria/canal estão certos.")
    except Exception as e:
        return False, f"Canal #{canal.name} encontrado, mas falhei ao mandar a mensagem de teste: {e}"
    return True, f"✅ Mensagem de teste enviada em #{canal.name}."


def buscar_perfil_discord(user_id, token):
    """Busca nome de exibição e URL do avatar de um usuário do Discord pelo
    ID, via REST direto com o token do bot - não precisa do bot estar
    conectado no gateway pra isso funcionar, é só uma chamada HTTP
    autenticada. Devolve {"nome": str, "avatar_url": str|None} ou None se
    falhar (ID inválido, token errado, sem internet, rate limit, etc.)."""
    if not token or not user_id:
        return None
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/users/{user_id}",
            headers={"Authorization": f"Bot {token}"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        dados = resp.json()
        nome = dados.get("global_name") or dados.get("username") or "(sem nome)"
        avatar_hash = dados.get("avatar")
        avatar_url = None
        if avatar_hash:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=64"
        return {"nome": nome, "avatar_url": avatar_url}
    except Exception:
        return None


def listar_emojis_aplicacao(token):
    """[{"id", "name", "animated"}, ...] - emojis próprios da aplicação
    (Portal de Desenvolvedores -> Applications -> Emojis), carregados uma
    vez quando o bot conecta (ver eris/bot.py::on_ready) e expostos pra GAIA
    injetar no prompt (ela precisa saber que emojis próprios existem e a
    sintaxe exata pra usar, <:nome:id> ou <a:nome:id> se animado)."""
    try:
        resp = requests.get(
            "https://discord.com/api/v10/applications/@me/emojis",
            headers={"Authorization": f"Bot {token}"}, timeout=10,
        )
        if resp.status_code != 200:
            return []
        return [
            {"id": e["id"], "name": e["name"], "animated": e.get("animated", False)}
            for e in resp.json().get("items", [])
        ]
    except Exception:
        return []


async def enviar_arquivo(channel_id, caminho):
    """Envia um arquivo real (ex.: print da tela, tag <PRINT> da GAIA) como
    anexo no canal/DM identificado por `channel_id`."""
    if _client_atual is None:
        return False
    canal = _client_atual.get_channel(int(channel_id)) or await _client_atual.fetch_channel(int(channel_id))
    await canal.send(file=discord.File(caminho))
    return True
