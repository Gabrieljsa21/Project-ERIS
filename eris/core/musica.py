# -*- coding: utf-8 -*-
"""Modo Música - toca áudio de verdade numa call de voz do Discord (substitui o
Jockie Music, pedido do usuário 2026-08-25: "quero q alguem seja meu dj
exclusivo, q conheça meus gostos e q qnd eu pedir uma musica, ele continue
tocando outras em sequencia na mesma vibe"). Busca/streaming via YouTube
(`yt-dlp` - mesma abordagem que praticamente todo bot de música de Discord
usa, já que não existe forma oficial/de graça de tocar áudio arbitrário numa
call a partir só de nome de artista/música). A "continuação na mesma vibe"
delega pro motor determinístico do Project ECHO (via webhook reverso pra
GAIA, `eris.integrations.gaia_webhook`) - o ERIS nunca decide sozinho o que é
"parecido", só busca/toca o que o ECHO sugere.

⚠️ Zona cinzenta de ToS do YouTube (avisado ao usuário antes de implementar,
2026-08-25) - extrair áudio via yt-dlp não é um uso oficialmente suportado,
mas é a mesma técnica usada por praticamente todo bot de música de Discord
(incluindo o Jockie que isso substitui). Usa `player_client=android` (não
exige token de origem/cookie, ao contrário do client "web" padrão desde 2024)
- se o YouTube endurecer e isso parar de funcionar, o próximo passo é
configurar `YOUTUBE_COOKIES_FILE` no `.env` (cookies exportados do navegador).

Diferente de `voz_call.SessaoVoz` (Intérprete/Tutora/Conversa - captura fala do
usuário e toca resposta curta), aqui não existe captura nenhuma - é uma
transmissão contínua disparada por slash command (`/musica tocar` etc.,
`eris/bot.py`), sem envolver STT/LLM/TTS da GAIA no caminho crítico.

🔥 Buffer em 3 camadas + por pessoa (2026-08-26, pedido do usuário: "espera
perceptível entre músicas é fallback/falha de pré-carregamento, nunca
comportamento normal do /caos") - o ECHO já mantém a camada 1 (pool pessoal,
100-300, do lado dele). Aqui dentro:
- Camada 2, `fila_logica` (20-50): IDENTIDADE da faixa (artista/título) já
  puxada do pool do ECHO, ainda SEM stream resolvido no YouTube.
- Camada 3, `fila` (5-10): streams JÁ resolvidos (`url_stream` pronto pra
  tocar), com `resolvido_em` pra detectar link velho antes de usar.
`_avancar()` só CONSOME o topo da camada 3 - nenhuma chamada de rede no
caminho crítico entre uma faixa acabar e a próxima começar. As duas camadas
são reabastecidas em BACKGROUND (`asyncio.create_task`, nunca bloqueando a
reprodução atual) sempre que caem abaixo do mínimo."""
import asyncio
import json
import os
import time

import discord
import yt_dlp

from eris.integrations import gaia_webhook

_sessoes_musica = {}  # guild_id -> SessaoMusica

_HISTORICO_SESSAO_MAX = 50  # não cresce pra sempre numa call que fica ligada o dia todo

# 🔥 Anúncios do Modo Música viram Embed com borda colorida (2026-08-27,
# pedido do usuário: "queria q as mensagens do bot tivessem esse embed ou
# borda... pra ficar facil diferenciar" - mensagem de texto solta se
# confundia com o resto da conversa do canal). Mesmo azul-claro já usado no
# resto do ecossistema (ver `ui/qt_modais/argus.py` da GAIA, cor "#4bade8").
COR_EMBED_MUSICA = discord.Color(0x4BADE8)

_FILA_LOGICA_ALVO = 50
_FILA_LOGICA_MINIMO = 20
_STREAMS_ALVO = 10
_STREAMS_MINIMO = 5
_STREAM_MAX_IDADE_SEGUNDOS = 3600  # link do YouTube expira - re-resolve antes de tocar se passou disso

_PASTA_SESSOES_PERSISTIDAS = "data"

_YTDL_OPCOES_BASE = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch1",
    "quiet": True,
    "no_warnings": True,
    "extractor_args": {"youtube": {"player_client": ["android"]}},
}

_FFMPEG_OPCOES_ANTES = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
_FFMPEG_OPCOES = "-vn"


def _binario_ffmpeg():
    """Mesmo padrão de `eris/core/voz_nativa.py::_binario_ffmpeg` - usa
    `FFMPEG_BIN_DIR` se configurado, senão cai pro `ffmpeg` do PATH do
    sistema."""
    pasta = os.getenv("FFMPEG_BIN_DIR")
    caminho = os.path.join(pasta, "ffmpeg.exe") if pasta else None
    return caminho if caminho and os.path.exists(caminho) else "ffmpeg"


def _chave(faixa):
    return f"{faixa['artista'].strip().lower()}::{faixa['titulo'].strip().lower()}"


def _titulo_com_link(faixa):
    """Título como link markdown pro vídeo do YouTube tocado (2026-08-27,
    pedido do usuário) - `url_pagina` vem de `_buscar_no_youtube`, sempre
    presente numa faixa resolvida; cai pro título em negrito puro (sem
    link) se faltar por algum motivo, nunca quebra o anúncio por causa
    disso."""
    url = faixa.get("url_pagina")
    if url:
        return f"**[{faixa['titulo']}]({url})**"
    return f"**{faixa['titulo']}**"


def _arquivo_fila_sessao(guild_id):
    return os.path.join(_PASTA_SESSOES_PERSISTIDAS, f"fila_sessao_{guild_id}.json")


def _carregar_fila_logica_persistida(guild_id):
    """Sobrevive a um restart do ERIS enquanto a call continua ativa
    (2026-08-26, pedido do usuário) - evita perder identidades já puxadas do
    pool do ECHO (cada consumo do pool é definitivo lá, não tem como pedir
    de volta)."""
    caminho = _arquivo_fila_sessao(guild_id)
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _salvar_fila_logica_persistida(guild_id, fila_logica):
    os.makedirs(_PASTA_SESSOES_PERSISTIDAS, exist_ok=True)
    with open(_arquivo_fila_sessao(guild_id), "w", encoding="utf-8") as f:
        json.dump(fila_logica, f, ensure_ascii=False, indent=2)


def _remover_fila_logica_persistida(guild_id):
    caminho = _arquivo_fila_sessao(guild_id)
    if os.path.exists(caminho):
        try:
            os.remove(caminho)
        except Exception:
            pass


def _buscar_no_youtube(query):
    """BLOQUEANTE (chamar via `asyncio.to_thread`) - busca 1 resultado no
    YouTube (aceita nome de música/artista OU link direto) e devolve
    `{"titulo", "artista", "url_stream", "url_pagina", "duracao_segundos"}`,
    ou None se não achou nada/a extração falhou. "artista" é o nome do canal
    do YouTube - uma aproximação razoável pra clipe oficial, mas não é
    garantido (nunca é tratado como dado 100% confiável pra scoring do ECHO,
    só como texto de exibição e semente de busca)."""
    opcoes = dict(_YTDL_OPCOES_BASE)
    cookies = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        opcoes["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(query, download=False)
            if info is None:
                return None
            if "entries" in info:
                entradas = [e for e in info["entries"] if e]
                if not entradas:
                    return None
                info = entradas[0]
            if not info.get("url"):
                return None
            return {
                "titulo": info.get("title") or query,
                "artista": info.get("uploader") or info.get("channel") or "Desconhecido",
                "url_stream": info["url"],
                "url_pagina": info.get("webpage_url"),
                "duracao_segundos": info.get("duration"),
            }
    except Exception as e:
        print(f" [ERIS] Falha na busca do YouTube (\"{query}\"): {e}")
        return None


async def _buscar_sugestao_no_youtube(sugestao):
    """Busca no YouTube uma sugestão do ECHO (`{"artista", "titulo"}`) e
    SOBRESCREVE o artista/título da faixa resultante pro valor LIMPO que o
    ECHO devolveu - achado real (2026-08-26, "caos... esta repetindo sempre
    a msm musica"): usar o título/canal cru do YouTube (cheio de "(Official
    Video)"/variações de remaster/feat.) pro dedup de sessão E pra semear o
    pedido da PRÓXIMA sugestão pro ECHO quebrava a comparação de string -
    "Payphone ft. Wiz Khalifa (Explicit) (Official Music Video)" nunca batia
    com o "Payphone" limpo que o próprio ECHO usa nos candidatos dele, então
    a mesma faixa nunca era excluída de verdade e voltava a ser sugerida
    (confirmado em log: mesma música tocando 3x seguidas)."""
    faixa = await asyncio.to_thread(_buscar_no_youtube, f"{sugestao['artista']} {sugestao['titulo']}")
    if faixa is None:
        return None
    faixa["artista"] = sugestao["artista"]
    faixa["titulo"] = sugestao["titulo"]
    faixa["resolvido_em"] = time.time()
    return faixa


class _ViewControlesMusica(discord.ui.View):
    """⏯️/⏭️/👍/👎/▶️/📋 na mensagem de "tocando agora" (2026-08-26/27,
    pedido do usuário: "quando ela toca uma musica, podia aparecer botoes
    de like, dislike e next", depois expandido com pausar/retomar, replay e
    fila). `timeout=None` - a música pode tocar por horas, os botões
    continuam válidos até uma faixa nova substituir a mensagem.

    🔥 like/dislike/replay/fila continuam abertos a QUALQUER membro
    (like/dislike alimentam só o perfil de quem clicou, ver `gaia_webhook.
    pedir_feedback_musica`; replay/fila não mudam nada, só consultam ou
    reenfileiram) - só ⏯️/⏭️ (controle de ESTADO da reprodução) exigem ser
    quem iniciou a sessão (decisão do usuário 2026-08-26)."""

    def __init__(self, guild_id, artista, titulo):
        super().__init__(timeout=None)
        self._guild_id = guild_id
        self._artista = artista
        self._titulo = titulo

    async def _feedback(self, interaction, valor, resposta):
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(gaia_webhook.pedir_feedback_musica, interaction.user.id, self._artista, self._titulo, valor)
        # 🔥 👎 também limpa a fila LÓGICA local (2026-08-27, achado pelo
        # usuário: "deveria ir tirando as votadas da lista das 50 e
        # completar com novas") - o ECHO já invalida o artista inteiro no
        # POOL dele (`pool.invalidar_relacionados`), mas isso nunca
        # alcançava candidatos JÁ PUXADOS pro buffer local do ERIS antes
        # do dislike (requisito do plano original, nunca conectado no
        # código final). Só a camada 2 (sem stream ainda) - streams JÁ
        # resolvidos na camada 3 continuam, pra não desperdiçar trabalho.
        if valor == "negativo":
            sessao = _sessoes_musica.get(self._guild_id)
            if sessao is not None:
                sessao.remover_artista_da_fila_logica(self._artista)
        await interaction.followup.send(resposta, ephemeral=True)

    async def _somente_iniciador(self, interaction):
        """Devolve True se autorizado; senão já respondeu ephemeral e devolve
        False. Mesma régua de `/musica pular`/`pausar`/etc. em `eris/bot.py`,
        só que pros botões (⏯️/⏭️) - like/dislike/replay não passam por aqui."""
        sessao = _sessoes_musica.get(self._guild_id)
        if sessao is not None and str(interaction.user.id) != sessao.iniciado_por:
            await interaction.response.send_message(
                "Só quem iniciou a sessão pode fazer isso - mas 👍/👎/▶️ é liberado pra você.", ephemeral=True,
            )
            return False
        return True

    # 🔥 Ordem pedida pelo usuário (2026-08-27): pausar/retomar, pular,
    # like, dislike - replay (▶️) e fila (📋) vêm depois, são utilitários
    # secundários, não controle de reprodução em si.

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary)
    async def _pausar_retomar(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle único (2026-08-27, pedido do usuário) - emoji ⏸️/▶️
        trocando dinamicamente colidiria visualmente com o botão de replay
        (▶️, sempre presente na mesma mensagem), por isso um símbolo
        combinado fixo em vez de trocar de cara. Restrito a quem iniciou a
        sessão, mesma régua de `/musica pausar`/`continuar`."""
        if not await self._somente_iniciador(interaction):
            return
        sessao = _sessoes_musica.get(self._guild_id)
        pausado = sessao is not None and sessao._vc is not None and sessao._vc.is_paused()
        mensagem = retomar(self._guild_id) if pausado else pausar(self._guild_id)
        await interaction.response.send_message(mensagem, ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def _pular(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._somente_iniciador(interaction):
            return
        mensagem = pular(self._guild_id)
        await interaction.response.send_message(mensagem, ephemeral=True)

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.green)
    async def _like(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._feedback(interaction, "positivo", "Anotado - mais disso.")

    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.red)
    async def _dislike(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._feedback(interaction, "negativo", "Anotado - menos disso.")

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.blurple)
    async def _tocar_de_novo(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Replay (2026-08-26, pedido do usuário: "Adicionar botão de play,
        para caso queira voltar em alguma musica que tocou") - a mensagem
        de "tocando agora" de uma faixa antiga continua no canal com seus
        próprios botões (`timeout=None`), já sabendo artista/título - basta
        rolar até ela e clicar. Aberto a qualquer membro, mesmo espírito de
        "adicionar à fila" (`/musica tocar`), não é um controle de estado."""
        await interaction.response.defer(ephemeral=True)
        ok, mensagem = await adicionar_por_identidade(self._guild_id, self._artista, self._titulo)
        if mensagem is None:
            await interaction.delete_original_response()
            return
        await interaction.followup.send(mensagem, ephemeral=True)

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary)
    async def _mostrar_fila(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        estado = obter_fila(self._guild_id)
        if estado is None:
            await interaction.followup.send("Não tô tocando nada nesse servidor agora.", ephemeral=True)
            return
        await interaction.followup.send(formatar_estado_fila(estado), ephemeral=True)


class SessaoMusica:
    def __init__(self, guild_id, iniciado_por):
        self.guild_id = guild_id
        self.iniciado_por = str(iniciado_por)
        self._vc = None
        self._loop = asyncio.get_running_loop()
        self.fila = []  # camada 3: streams pré-resolvidos (alvo 5-10)
        self.fila_logica = _carregar_fila_logica_persistida(guild_id)  # camada 2: identidade, sem stream (alvo 20-50)
        self.tocando_agora = None
        self.modo_continuo = True
        self._modo_aprovadas = False  # True quando a sessão veio de `tocar_aprovadas` - não cai pro pool ao esgotar
        self._historico_sessao = []
        self._contagem_artistas_sessao = {}
        self.text_channel = None
        self._repondo_fila_logica = False
        self._resolvendo_streams = False
        self._pulado_manualmente = False
        self._inicio_atual = None

    @property
    def canal_atual(self):
        return self._vc.channel if self._vc else None

    @property
    def historico_sessao(self):
        return list(self._historico_sessao)

    async def entrar(self, voice_channel, text_channel):
        self._vc = await voice_channel.connect()
        self.text_channel = text_channel
        print(f" [ERIS] Sessão de música conectada em \"{voice_channel.name}\".")

    async def sair(self):
        self.fila.clear()
        self.fila_logica.clear()
        self.tocando_agora = None
        _remover_fila_logica_persistida(self.guild_id)
        if self._vc:
            if self._vc.is_playing() or self._vc.is_paused():
                self._vc.stop()
            await self._vc.disconnect()
            self._vc = None

    def _registrar_historico(self, faixa):
        self._historico_sessao.append(_chave(faixa))
        self._historico_sessao = self._historico_sessao[-_HISTORICO_SESSAO_MAX:]

    def _contar_artista_sessao(self, artista):
        chave = artista.strip().lower()
        self._contagem_artistas_sessao[chave] = self._contagem_artistas_sessao.get(chave, 0) + 1

    def _excluidos_atual(self):
        """Dedup de CURTO prazo (nunca repetir NESTA sessão) - une o que já
        tocou com o que já tá reservado nas 2 camadas de buffer, senão o
        reabastecimento em background podia pedir pro ECHO uma faixa que já
        tá esperando na própria fila."""
        excluidos = set(self._historico_sessao)
        excluidos |= {_chave(f) for f in self.fila_logica}
        excluidos |= {_chave(f) for f in self.fila}
        return list(excluidos)

    def _penalidades_sessao(self):
        """Só no nível de ARTISTA (o ERIS não conhece gênero - isso é
        conhecimento exclusivo do ECHO) - ainda assim cobre a queixa central
        de "evitar repetição excessiva de artista... durante uma mesma
        sessão" sem precisar expor gênero através da fronteira ERIS/ECHO."""
        return {f"artista::{artista}": contagem for artista, contagem in self._contagem_artistas_sessao.items()}

    def _ao_terminar_thread_externa(self, erro):
        """Chamado pelo discord.py numa thread PRÓPRIA do player de áudio
        (nunca a do loop asyncio) - mesmo cuidado de thread-safety de
        `voz_call.SessaoVoz._on_fala_fechada_thread_externa`."""
        if erro:
            print(f" [ERIS] Erro tocando música: {erro}")
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._avancar()))

    def _agendar_feedback_passivo(self, faixa, inicio_monotonic, pulado):
        """Sinal fraco/acumulativo (2026-08-26) - fração tocada + se foi
        pulada manualmente, mandado pro ECHO (via GAIA) em background; nunca
        atrasa a próxima faixa. Atribuído a quem INICIOU a sessão (o sinal é
        sobre a vibe da sessão dela, não dá pra saber quem na call de fato
        ouviu)."""
        if inicio_monotonic is None:
            return
        tempo_tocado = time.monotonic() - inicio_monotonic
        duracao_total = faixa.get("duracao_segundos")
        fracao_tocada = (tempo_tocado / duracao_total) if duracao_total else None
        asyncio.create_task(asyncio.to_thread(
            gaia_webhook.pedir_feedback_passivo_musica, self.iniciado_por, faixa["artista"], faixa["titulo"],
            fracao_tocada, pulado, int(tempo_tocado) if pulado else None,
        ))

    async def _tocar(self, faixa):
        self.tocando_agora = faixa
        self._inicio_atual = time.monotonic()
        self._pulado_manualmente = False
        self._registrar_historico(faixa)
        fonte = discord.FFmpegPCMAudio(
            faixa["url_stream"], executable=_binario_ffmpeg(),
            before_options=_FFMPEG_OPCOES_ANTES, options=_FFMPEG_OPCOES,
        )
        try:
            self._vc.play(fonte, after=self._ao_terminar_thread_externa)
        except Exception as e:
            print(f" [ERIS] Erro ao INICIAR reprodução de música: {e}")
            self.tocando_agora = None
            return
        print(f" [ERIS] Tocando: {faixa['titulo']} - {faixa['artista']}")
        # 🔥 ÚNICO lugar que anuncia "tocando agora" com botões - cobre tanto o
        # play imediato (/musica tocar, /caos) quanto a continuação automática
        # (_avancar, sem interaction nenhuma pra responder) de forma uniforme.
        if self.text_channel is not None:
            sufixo_voto = await self._sufixo_voto(faixa)
            view = _ViewControlesMusica(self.guild_id, faixa["artista"], faixa["titulo"])
            embed = discord.Embed(
                title="🎵 Tocando agora",
                description=f"{_titulo_com_link(faixa)} - {faixa['artista']}{sufixo_voto}",
                color=COR_EMBED_MUSICA,
            )
            try:
                await self.text_channel.send(embed=embed, view=view)
            except Exception as e:
                print(f" [ERIS] Não consegui anunciar a música no canal: {e}")

    async def _sufixo_voto(self, faixa):
        """"(👍)"/"(👎)" no fim da linha de anúncio (2026-08-27, pedido do
        usuário) - se essa faixa já foi avaliada antes por quem INICIOU a
        sessão (Discord não permite "reação pré-marcada" numa mensagem nova
        pra ninguém - texto é a única forma honesta de comunicar isso).
        Roda DEPOIS de `self._vc.play()` já ter começado (ver `_tocar`) -
        atrasa só o anúncio, nunca o áudio."""
        try:
            voto = await asyncio.to_thread(gaia_webhook.pedir_voto_musica, self.iniciado_por, faixa["artista"], faixa["titulo"])
        except Exception:
            return ""
        if voto == "positivo":
            return " (👍)"
        if voto == "negativo":
            return " (👎)"
        return ""

    @staticmethod
    def _stream_expirado(faixa):
        resolvido_em = faixa.get("resolvido_em")
        return resolvido_em is None or (time.time() - resolvido_em) > _STREAM_MAX_IDADE_SEGUNDOS

    async def _avancar(self):
        """Chamado quando uma faixa termina. Caminho NORMAL só consome o topo
        já pronto da camada 3 (`fila`) - nenhuma rede no meio. Cai pra camada
        2 (`fila_logica`, resolve na hora) só se a 3 já tiver secado, e só
        pede uma sugestão nova ao vivo (mesmo caminho de antes desta
        reescrita) se as duas primeiras camadas estiverem vazias - isso é o
        fallback raro, não o normal."""
        if self._vc is None:  # sair() já rodou antes do callback disparar
            return

        # 🔥 Captura e LIMPA antes de qualquer branch/recursão (achado ao
        # revisar: sem isso, o fallback de stream expirado/YouTube sem
        # resultado recursava em `_avancar()` com `tocando_agora` ainda
        # apontando pra faixa antiga, mandando feedback passivo duplicado
        # da MESMA faixa que já tinha acabado de tocar).
        faixa_que_terminou = self.tocando_agora
        inicio_da_faixa_anterior = self._inicio_atual
        pulado_da_faixa_anterior = self._pulado_manualmente
        self.tocando_agora = None
        if faixa_que_terminou is not None:
            self._agendar_feedback_passivo(faixa_que_terminou, inicio_da_faixa_anterior, pulado_da_faixa_anterior)

        if self.fila:
            proxima = self.fila.pop(0)
            if self._stream_expirado(proxima):
                reresolvida = await _buscar_sugestao_no_youtube({"artista": proxima["artista"], "titulo": proxima["titulo"]})
                if reresolvida is None:
                    await self._avancar()  # essa não deu - tenta a próxima do buffer
                    return
                proxima = reresolvida
            await self._tocar(proxima)
            self._agendar_reabastecimento()
            return

        if self.fila_logica:
            identidade = self.fila_logica.pop(0)
            _salvar_fila_logica_persistida(self.guild_id, self.fila_logica)
            faixa = await _buscar_sugestao_no_youtube(identidade)
            if faixa is None:
                await self._avancar()  # não achou no YouTube - tenta a próxima identidade
                return
            await self._tocar(faixa)
            self._agendar_reabastecimento()
            return

        if self._modo_aprovadas:
            print(" [ERIS] Lista de aprovadas esgotada nesta sessão.")
            if self.text_channel is not None:
                embed = discord.Embed(
                    description="🎵 Todas as suas músicas aprovadas já tocaram nesta sessão - use `/caos` pra continuar com novas sugestões.",
                    color=COR_EMBED_MUSICA,
                )
                try:
                    await self.text_channel.send(embed=embed)
                except Exception:
                    pass
            return
        if not self.modo_continuo or faixa_que_terminou is None:
            return

        # 🔥 Fallback raro - os buffers deveriam manter isso sempre cheio; só
        # chega aqui se o pool/aprovadas do ECHO secaram de vez (usuário novo
        # ou já ouviu tudo que existe pra ele).
        sugestao = await asyncio.to_thread(
            gaia_webhook.pedir_proxima_musica, self.iniciado_por, faixa_que_terminou["artista"], faixa_que_terminou["titulo"],
            self._excluidos_atual(), self._penalidades_sessao(),
        )
        if not sugestao:
            print(" [ERIS] Modo contínuo: ECHO não tem mais nenhum candidato - fila esvaziada.")
            return
        faixa = await _buscar_sugestao_no_youtube(sugestao)
        if not faixa:
            print(f" [ERIS] Modo contínuo: não achei \"{sugestao['artista']} - {sugestao['titulo']}\" no YouTube.")
            return
        await self._tocar(faixa)

    async def _repor_fila_logica(self):
        """Reabastece a camada 2 puxando do pool do ECHO (via GAIA) - cada
        chamada é praticamente instantânea do lado do ECHO (só consome o
        pool pré-calculado), mas ainda assim roda em background, nunca no
        caminho crítico entre uma faixa acabar e a próxima começar."""
        if self._repondo_fila_logica or self._modo_aprovadas:
            return
        self._repondo_fila_logica = True
        try:
            while len(self.fila_logica) < _FILA_LOGICA_ALVO and self.modo_continuo:
                semente = self.fila_logica[-1] if self.fila_logica else self.tocando_agora
                if semente:
                    sugestao = await asyncio.to_thread(
                        gaia_webhook.pedir_proxima_musica, self.iniciado_por, semente["artista"], semente["titulo"],
                        self._excluidos_atual(), self._penalidades_sessao(),
                    )
                else:
                    sugestao = await asyncio.to_thread(gaia_webhook.pedir_semente_musica, self.iniciado_por, self._excluidos_atual())
                if not sugestao:
                    break  # ECHO não tem mais candidato agora - não adianta insistir
                self.fila_logica.append(sugestao)
                self._contar_artista_sessao(sugestao["artista"])
            _salvar_fila_logica_persistida(self.guild_id, self.fila_logica)
        finally:
            self._repondo_fila_logica = False
        if len(self.fila) < _STREAMS_ALVO and self.fila_logica:
            asyncio.create_task(self._resolver_streams())

    async def _resolver_streams(self):
        """Reabastece a camada 3 (streams JÁ tocáveis) puxando identidades
        já esperando na camada 2 - essa sim envolve rede de verdade
        (yt-dlp), por isso fica adiantada, nunca disparada só quando a
        faixa atual termina."""
        if self._resolvendo_streams:
            return
        self._resolvendo_streams = True
        try:
            while len(self.fila) < _STREAMS_ALVO and self.fila_logica:
                identidade = self.fila_logica.pop(0)
                _salvar_fila_logica_persistida(self.guild_id, self.fila_logica)
                faixa = await _buscar_sugestao_no_youtube(identidade)
                if faixa:
                    self.fila.append(faixa)
                # não achou no YouTube - só perde essa candidata, segue pra próxima
        finally:
            self._resolvendo_streams = False

    def _agendar_reabastecimento(self):
        if not self._modo_aprovadas and len(self.fila_logica) < _FILA_LOGICA_MINIMO:
            asyncio.create_task(self._repor_fila_logica())
        if len(self.fila) < _STREAMS_MINIMO and self.fila_logica:
            asyncio.create_task(self._resolver_streams())

    def remover_artista_da_fila_logica(self, artista):
        """👎 forte (2026-08-27, achado pelo usuário: "deveria ir tirando as
        votadas da lista das 50 e completar com novas") - remove da fila
        LÓGICA (camada 2, ainda sem stream) tudo do mesmo artista e dispara
        reabastecimento na hora (não espera cair abaixo do mínimo de 20 -
        "completar com novas" é imediato, não só eventual). Streams JÁ
        resolvidos (camada 3) não são tocados - preserva trabalho de
        resolução do YouTube já feito, mesmo raciocínio de sempre."""
        artista_normalizado = artista.strip().lower()
        tamanho_antes = len(self.fila_logica)
        self.fila_logica = [f for f in self.fila_logica if f["artista"].strip().lower() != artista_normalizado]
        if len(self.fila_logica) == tamanho_antes:
            return  # nada desse artista esperando na fila lógica - nada a fazer
        _salvar_fila_logica_persistida(self.guild_id, self.fila_logica)
        if not self._modo_aprovadas:
            asyncio.create_task(self._repor_fila_logica())

    async def _tocar_ou_enfileirar(self, faixa):
        """Toca IMEDIATAMENTE se nada estiver tocando/na fila, senão
        enfileira na camada 3 (streams - já chega aqui resolvida) - decisão
        compartilhada por `adicionar` (busca livre), `iniciar_caos` e
        `tocar_aprovadas`.

        🔥 `mensagem=None` no play imediato (2026-08-27, pedido do usuário:
        "essa resposta privada pode ser removida" - o card público "tocando
        agora" já confirma sozinho) - quem chama (`eris/bot.py`) apaga a
        resposta adiada em vez de mandar um followup vazio de propósito."""
        if self.tocando_agora is None and not self.fila:
            await self._tocar(faixa)
            return True, None
        self.fila.append(faixa)
        return True, f"Adicionado à fila (posição {len(self.fila)}): **{faixa['titulo']}** - {faixa['artista']}"

    async def adicionar(self, query):
        """Busca livre e adiciona - toca IMEDIATAMENTE se nada estiver
        tocando/na fila. Devolve (ok, mensagem). O anúncio detalhado
        ("tocando agora" + botões) sai à parte via `_tocar` -> `text_
        channel.send` - aqui é só a confirmação curta da interação."""
        faixa = await asyncio.to_thread(_buscar_no_youtube, query)
        if not faixa:
            return False, f"Não achei nada pra \"{query}\" no YouTube."
        faixa["resolvido_em"] = time.time()
        return await self._tocar_ou_enfileirar(faixa)

    def pular(self):
        if self._vc is None or not (self._vc.is_playing() or self._vc.is_paused()):
            return "Não tem nada tocando agora."
        self._pulado_manualmente = True
        self._vc.stop()  # dispara o callback `after`, que avança sozinho
        return "Pulei pra próxima."

    def pausar(self):
        if self._vc is None or not self._vc.is_playing():
            return "Não tem nada tocando agora."
        self._vc.pause()
        return "Pausei."

    def retomar(self):
        if self._vc is None or not self._vc.is_paused():
            return "Não tem nada pausado agora."
        self._vc.resume()
        return "Retomei."

    def obter_fila(self):
        return {
            "tocando_agora": self.tocando_agora,
            "fila": list(self.fila),
            "fila_logica_tamanho": len(self.fila_logica),
            "modo_continuo": self.modo_continuo,
        }


def formatar_estado_fila(estado):
    """Texto de `/musica fila` e do botão 📋 (2026-08-27) - compartilhado
    pelos dois pra não duplicar a formatação."""
    linhas = []
    if estado["tocando_agora"]:
        f = estado["tocando_agora"]
        linhas.append(f"🎵 Tocando agora: **{f['titulo']}** - {f['artista']}")
    else:
        linhas.append("Nada tocando agora.")
    if estado["fila"]:
        linhas.append("\n**Fila:**")
        linhas.extend(f"{i}. {f['titulo']} - {f['artista']}" for i, f in enumerate(estado["fila"], 1))
    if estado["fila_logica_tamanho"]:
        linhas.append(f"\n(+{estado['fila_logica_tamanho']} já reservadas, resolvendo em background)")
    linhas.append(f"\nModo contínuo (DJ automático): {'ligado' if estado['modo_continuo'] else 'desligado'}")
    return "\n".join(linhas)


def canal_ativo(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.canal_atual if sessao else None


def obter_iniciador(guild_id):
    """Quem iniciou a sessão nesse servidor (dono dos controles de
    reprodução - `eris/bot.py` checa contra `interaction.user.id`), ou None
    se não tem sessão ativa."""
    sessao = _sessoes_musica.get(guild_id)
    return sessao.iniciado_por if sessao else None


async def _obter_ou_criar_sessao(voice_channel, text_channel, discord_user_id):
    from eris.core import voz_call  # 🔥 import tardio - evita ciclo (voz_call também checa musica.canal_ativo)
    guild_id = voice_channel.guild.id
    if voz_call.canal_ativo(guild_id) is not None:
        return None, "Já tô numa call de voz (Conversa/Intérprete/Tutora) nesse servidor - sai de lá primeiro (\"@Gala sai\") se quiser música."
    sessao = _sessoes_musica.get(guild_id)
    if sessao is None:
        sessao = SessaoMusica(guild_id, discord_user_id)
        try:
            await sessao.entrar(voice_channel, text_channel)
        except Exception as e:
            return None, f"Não consegui entrar na call: {e}"
        _sessoes_musica[guild_id] = sessao
    return sessao, None


async def tocar(voice_channel, text_channel, query, discord_user_id):
    """`/musica tocar <busca>` - aberto a QUALQUER membro (decisão do
    usuário 2026-08-26: só os controles de estado ficam restritos a quem
    iniciou, adicionar à fila continua livre)."""
    sessao, erro = await _obter_ou_criar_sessao(voice_channel, text_channel, discord_user_id)
    if sessao is None:
        return False, erro
    return await sessao.adicionar(query)


async def adicionar_por_identidade(guild_id, artista, titulo):
    """Botão ▶️ (2026-08-26, pedido do usuário: "Adicionar botão de play,
    para caso queira voltar em alguma musica que tocou") - reaproveita a
    MESMA busca/enfileiramento de `tocar`, mas a partir de uma identidade
    já conhecida (artista/título de uma mensagem "tocando agora" anterior
    no canal, ainda com os botões válidos). Precisa de uma sessão JÁ ativa
    nesse servidor (o botão não sabe de qual call de voz o clique veio, só
    a slash command sabe) - se a Gala já saiu, devolve erro pedindo pra
    começar de novo."""
    sessao = _sessoes_musica.get(guild_id)
    if sessao is None:
        return False, "Não tô mais tocando nesse servidor - use `/musica tocar` ou `/caos` pra começar de novo."
    return await sessao.adicionar(f"{artista} {titulo}")


async def tocar_aprovadas(voice_channel, text_channel, discord_user_id):
    """`/musica tocar` SEM parâmetro (2026-08-26, pedido do usuário: "o
    musica tocar, se n passar parametro, começa a tocar as musicas q
    aprovei, ate terminar todas") - puxa a lista de aprovadas de QUEM
    CHAMOU, não emenda no pool/`/caos` ao esgotar (diferente do modo
    contínuo normal - aqui é uma lista fechada, avisa e para)."""
    sessao, erro = await _obter_ou_criar_sessao(voice_channel, text_channel, discord_user_id)
    if sessao is None:
        return False, erro
    aprovadas = await asyncio.to_thread(gaia_webhook.pedir_aprovadas_musica, discord_user_id)
    if not aprovadas:
        return False, "Você ainda não tem nenhuma música aprovada (dá 👍 numa faixa tocando pra ela entrar nessa lista)."
    excluidos = set(sessao._excluidos_atual())
    candidatas = [
        {"artista": a["artista"], "titulo": a["titulo"]} for a in aprovadas
        if _chave({"artista": a["artista"], "titulo": a["titulo"]}) not in excluidos
    ]
    if not candidatas:
        return False, "Todas as suas músicas aprovadas já tocaram nesta sessão."
    sessao._modo_aprovadas = True
    primeira = candidatas[0]
    sessao.fila_logica.extend(candidatas[1:])
    _salvar_fila_logica_persistida(sessao.guild_id, sessao.fila_logica)
    faixa = await _buscar_sugestao_no_youtube(primeira)
    if not faixa:
        return False, f"Não achei \"{primeira['artista']} - {primeira['titulo']}\" no YouTube."
    resultado = await sessao._tocar_ou_enfileirar(faixa)
    if len(sessao.fila) < _STREAMS_MINIMO and sessao.fila_logica:
        asyncio.create_task(sessao._resolver_streams())
    return resultado


async def iniciar_caos(voice_channel, text_channel, discord_user_id):
    """`/caos` (2026-08-26, pedido do usuário: "ERIS entra no canal de voz do
    usuário e inicia uma sessão musical contínua... sem exigir artista,
    gênero, música ou qualquer outra referência inicial") - pede pro ECHO
    (via GAIA) uma sugestão de PARTIDA baseada só no perfil/pool de
    `discord_user_id` (sem faixa atual pra semear, diferente de `_avancar`)
    e entra igual um `/musica tocar` normal a partir daí. `modo_continuo` já
    nasce ligado (`SessaoMusica.__init__`), então o motor de continuação de
    sempre assume sozinho - nenhum mecanismo novo além de arranjar a
    PRIMEIRA busca sem pedir nada ao usuário, e disparar o reabastecimento
    das 2 camadas de buffer em background logo em seguida.

    🔥 Reseta `_modo_aprovadas` (2026-08-27, bug relatado pelo usuário:
    "assim q eu uso o /caos, ele tem de ignorar tudo p tras e seguir a
    logica do /caos... o caos so ta tocando 1 musica") - `_obter_ou_criar_
    sessao` reaproveita a sessão já ativa se ela veio de um `/musica tocar`
    (aprovadas) anterior; sem resetar essa flag aqui, `_avancar()`
    continuava tratando a sessão como "lista fechada de aprovadas" (parava
    e repetia o aviso de esgotado) mesmo depois do usuário pedir `/caos`
    explicitamente, e `_agendar_reabastecimento` nunca enchia a fila lógica
    de novo (só reabastece quando `_modo_aprovadas` é False)."""
    sessao, erro = await _obter_ou_criar_sessao(voice_channel, text_channel, discord_user_id)
    if sessao is None:
        return False, erro
    sessao._modo_aprovadas = False
    sugestao = await asyncio.to_thread(gaia_webhook.pedir_semente_musica, discord_user_id, sessao._excluidos_atual())
    if not sugestao:
        return False, "Não consegui pensar em nada pra começar agora (ECHO indisponível ou sem candidato) - tenta \"/musica tocar\" com algo específico."
    faixa = await _buscar_sugestao_no_youtube(sugestao)
    if not faixa:
        return False, f"Não achei \"{sugestao['artista']} - {sugestao['titulo']}\" no YouTube - tenta de novo."
    resultado = await sessao._tocar_ou_enfileirar(faixa)
    sessao._agendar_reabastecimento()
    return resultado


async def sair_musica(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    if not sessao:
        return "Eu não tava tocando música nesse servidor."
    del _sessoes_musica[guild_id]
    await sessao.sair()
    return "Parei e saí da call."


def pular(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.pular() if sessao else "Eu não tava tocando música nesse servidor."


def pausar(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.pausar() if sessao else "Eu não tava tocando música nesse servidor."


def retomar(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.retomar() if sessao else "Eu não tava tocando música nesse servidor."


def obter_fila(guild_id):
    sessao = _sessoes_musica.get(guild_id)
    return sessao.obter_fila() if sessao else None


def definir_modo_continuo(guild_id, ativo):
    sessao = _sessoes_musica.get(guild_id)
    if not sessao:
        return "Eu não tava tocando música nesse servidor."
    sessao.modo_continuo = ativo
    return f"Modo contínuo (DJ automático) {'ativado' if ativo else 'desativado'}."


async def listar_aprovadas(discord_user_id):
    return await asyncio.to_thread(gaia_webhook.pedir_aprovadas_musica, discord_user_id)


async def listar_desaprovadas(discord_user_id):
    return await asyncio.to_thread(gaia_webhook.pedir_desaprovadas_musica, discord_user_id)
