# Arquitetura do Project ERIS

Extraído da GAIA em 2026-08-24 (ver `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`
-> "Project ERIS" e `docs/TODO.md` -> "Arquitetura do ecossistema"). Diferente
de MOIRAI/HESTIA (extraídos no mesmo dia), o `discord_bot.py` original não
tinha uma separação limpa entre mecânica e persona - `iniciar_bot` recebia a
própria `processar_ia` da GAIA como parâmetro, e slash commands/Intérprete/
Tutora chamavam ações reais direto de dentro do mesmo arquivo. Esta extração
teve que desenhar essa fronteira do zero, não só mover código.

## Fronteira de responsabilidade

O ERIS executa tudo que exige conhecer a API/permissões/funcionamento
interno do Discord. **Nunca decide conteúdo** - o que dizer, se vale avisar,
o fraseio continua sendo persona, e fica com a GAIA.

| Domínio | Fica no ERIS | Fica na GAIA |
|---|---|---|
| Conexão/gateway | ✅ único dono do token | - |
| Donos (quem tem acesso total) | ✅ `eris.db` (SQLite) | Painel edita via HTTP |
| Filtro "vale chamar a persona?" | ✅ (`eris.core.seguranca`) | Painel edita via HTTP |
| Conteúdo da resposta | webhook reverso pede | ✅ decide sempre |
| Slash commands de ação (`/abrir` etc.) | **fora do escopo desta v1** | ver "Pendências" abaixo |
| Moderação/administração | ✅ 100% local, zero IA | - |
| Exportação de canal | ✅ | - |
| Voz (Conversa/Intérprete/Tutora) | ✅ conexão/captura/playback (`eris.core.voz_call`) | ✅ transcrição/tradução/resposta/síntese via webhook |
| Notificações proativas (Hidratação, Steam, etc.) | executa a entrega | ✅ decide se/quando/o quê |

## Os 4 pontos que precisaram de desenho novo

O `discord_bot.py` original emaranhava mecânica e persona em 4 lugares -
cada um foi decidido explicitamente antes de escrever código (conversa de
2026-08-24, antes da extração):

1. **Filtro de roteamento (on_message)** - `discord_active`/
   `server_active`/`mentions`/`target_user`/`disabled_guilds` eram config no
   `brain.json` da GAIA, lida a cada mensagem dentro do loop do bot. Agora
   vivem no `eris.db` (tabela `config_roteamento`/`guilds_desativados`) -
   o ERIS decide LOCALMENTE se uma mensagem merece virar uma chamada de
   rede, em vez de mandar toda mensagem de todo servidor (inclusive
   desativado) pra GAIA só pra ela dizer "ignora essa".
2. **Identificação de dono/autorização** - `discord_donos` migrou do
   `brain.json` pra `eris.db` (tabela `donos`). O ERIS calcula `eh_dono` e
   manda como metadado no webhook reverso - a GAIA não recalcula.
3. **Slash commands que executam ação real** (`/abrir`, `/jornalista` etc.)
   - **decisão: fora do escopo desta extração**. O desenho correto (ERIS
   registra o comando, encaminha pro webhook reverso, GAIA roda o handler
   de `core/agent/comandos.py` e devolve o texto) está fechado, mas exige
   expor `INFO_COMANDOS`/`INFO_COMANDOS_ASSINCRONOS` pra cá e um contrato de
   webhook próprio - não é mecânico o bastante pra entrar na mesma extração
   que o resto sem risco de regressão. Ver TODO.md.
4. **Intérprete/Tutora por voz em call** - **implementado em 2026-08-25**,
   turno-a-turno (ERIS captura áudio até o silêncio → manda pra GAIA → GAIA
   transcreve/decide/sintetiza → devolve o CAMINHO local do áudio → ERIS
   toca), não streaming contínuo - cabe no mesmo padrão de webhook reverso,
   só que com áudio em vez de só texto. `eris/core/voz_call.py` (sessão de
   voz por guild, só 1 por vez já que Discord só permite 1 conexão de voz
   por servidor) + `eris/core/voz_captura.py`/`vad.py` (captura por
   participante, portados de `features/interprete/audio.py`/`core/voice/
   vad.py::VoiceFilterRMS` na GAIA). Do lado da GAIA, `features/interprete/
   sessao.py` foi reescrito pra não depender mais de `discord.py` - só
   guarda o ESTADO da tradução (contexto, idioma estrangeiro atual),
   `features/tutora/sessao_discord.py` foi removido (a lógica de turno virou
   uma função simples em `run.py`, sem precisar de estado por guild).
   Endpoints novos: `POST /eris/interprete/{iniciar,encerrar,turno}`,
   `GET /eris/tutora/status`, `POST /eris/tutora/turno`.

   **Modo Conversa adicionado no mesmo dia** - achado do usuário testando na
   prática: pedir pra ela "entrar na call" acionava sempre o Intérprete
   (única palavra-gatilho genérica era "entra"), mesmo quando o pedido era
   só bate-papo comum, sem tradução nem prática de idioma. Terceiro modo,
   mesmo padrão dos outros dois (turno-a-turno, sem sessão prévia, qualquer
   participante pode falar) - `eris.core.voz_call.SessaoVoz` ganhou um 3º
   valor de `modo` ("conversa"), endpoint novo `POST /eris/conversa/turno`.
   O gatilho por menção foi reordenado: Intérprete agora exige palavra
   EXPLÍCITA de tradução ("traduz"/"tradução"/"intérprete"); "entra"/
   "entrar"/"conversa" sozinho vira Modo Conversa, que é o comportamento que
   a maioria espera de um "entra" sem qualificação.

## Por que processo próprio (padrão IRIS/MOIRAI/HESTIA), não padrão Argus

O usuário perguntou explicitamente se o ERIS seguiria o modelo do Argus
("funciona sozinho, ganha função nova com a GAIA"). A resposta é sim NO
CONTRATO, mas não no MECANISMO: o Argus é uma biblioteca Python importada
DENTRO da própria `QApplication` da GAIA - faz sentido porque ele é
fundamentalmente um widget de interface. O núcleo do ERIS é uma conexão
assíncrona (`discord.Client`) que precisa ficar viva o tempo todo, sem
relação nenhuma com Qt - por isso processo próprio, venv próprio, HTTP,
igual IRIS/MOIRAI/HESTIA.

Isso é uma vantagem real, não só uma diferença técnica: hoje (antes da
extração), se a GAIA cai, o bot cai junto - inclusive moderação/exportação,
que não precisam de IA nenhuma pra funcionar. Com o ERIS em processo
separado, ele continua respondendo moderação/exportação com a GAIA
desligada; só a conversa (que depende da persona) informa que está
indisponível em vez de simplesmente não responder nada.

## SQLite desde o início, não JSON solto

MOIRAI/HESTIA usam JSON solto em `data/` porque o dado deles é baixa
cardinalidade (uma lista de animes/jogos rastreados). O ERIS já nasce
pensando nos domínios futuros do roadmap (economia, níveis, canais
temporários, colecionáveis - inspirados em AmariBot/Loritta/TempVoice/Mudae,
ver TODO.md) - alta cardinalidade por usuário/servidor, escrita concorrente,
consultas tipo "top 10". `sqlite3` da própria stdlib, sem dependência nova,
evita reescrever a camada de persistência quando esses domínios chegarem.

## Modo Música (2026-08-25) - fronteira com o Project ECHO

Ao planejar o roadmap futuro, foi levantada a dúvida se o Modo DJ (Project
ECHO) teria alguma sobreposição com a conexão de voz do ERIS. Na
especificação original não tinha (ECHO não tocava call nenhuma) - mas o
usuário depois pediu pra substituir o Jockie Music de verdade ("quero q
alguem seja meu dj exclusivo... qnd eu pedir uma musica, ele continue
tocando outras em sequencia na mesma vibe"), o que EXIGE tocar áudio numa
call. Fronteira aplicada, sem sobreposição:

- **ECHO nunca toca áudio** - continua só metadado/ranking (`GET /radar/
  proxima`, `echo/core/continuacao.py`). Não sabe o que é YouTube, não sabe
  o que é Discord.
- **ERIS faz TUDO que é áudio** - busca/extração via `yt-dlp`
  (`eris/core/musica.py`), conexão de voz, fila, playback. Quando a fila
  esvazia com "DJ automático" ligado, pede pra GAIA (`eris.integrations.
  gaia_webhook.pedir_proxima_musica`) uma sugestão - a GAIA repassa pro ECHO
  (`POST /eris/proxima_musica` no bridge dela, que chama `echo_client.
  sugerir_proxima_musica`) e devolve `{"artista", "titulo"}`. O ERIS busca
  ESSE nome no YouTube e toca - nunca inventa por conta própria o que vem
  depois.
- **Dedup de 2 camadas, propósitos diferentes**: o ERIS manda a lista de
  "já tocado NESTA sessão de call" (`_historico_sessao`, em memória, reseta
  quando a sessão acaba) pro ECHO excluir - resolve a queixa real do
  usuário sobre o Jockie repetir depois de um tempo. O ECHO AINDA aplica
  por baixo o dedup de 90 dias do Radar semanal (`core.recomendador.
  ranquear` chama `historico.foi_recomendada_recentemente`) como segunda
  camada, mas o de sessão é o que resolve o problema relatado.
- **Mutuamente exclusivo com Conversa/Intérprete/Tutora** (não simultâneo)
  DENTRO de uma mesma instância do ERIS - Discord só permite 1 conexão de
  voz por conta de bot por servidor. Rodar Música e voz ao mesmo tempo no
  mesmo canal exige uma 2ª instância/token de bot - ver seção abaixo.

**`/caos` (2026-08-26)** - pedido do usuário: "ERIS entra no canal de voz do
usuário e inicia uma sessão musical contínua... sem exigir artista, gênero,
música ou qualquer outra referência inicial". Mesma fronteira de sempre, só
muda QUEM inicia a busca: em vez do usuário mandar uma `query` (`/musica
tocar`), o ERIS pede pra GAIA (`gaia_webhook.pedir_semente_musica`) uma
sugestão de PARTIDA - a GAIA repassa pro ECHO (`POST /eris/musica_caos` no
bridge dela, `echo_client.sugerir_semente_musical` -> `POST /radar/semente`
no ECHO) e devolve `{"artista", "titulo"}` baseado só no perfil/histórico,
sem precisar de faixa atual. `eris/core/musica.py::iniciar_caos` delega pro
mesmo `SessaoMusica.adicionar` de sempre a partir daí - nenhum mecanismo
novo de reprodução/continuação, só a primeira busca vem do ECHO em vez do
usuário.

**`/caos` só age se NÃO tem sessão ativa (2026-08-28)** - antes, chamar
`/caos` com o ERIS já na call (mesmo pausado) reaproveitava a sessão e
enfileirava mais uma sugestão do ECHO em silêncio; usuário relatou ter
esquecido que a música já tava pausada e usado `/caos` de novo achando que
ela ainda ia entrar na call. Como `modo_continuo` já reabastece a fila
sozinho (`_avancar`/`_agendar_reabastecimento`), uma 2ª sugestão nesse caso
nunca teve função real. `iniciar_caos` agora checa `_sessoes_musica` ANTES
de chamar `_obter_ou_criar_sessao`/pedir semente ao ECHO - se já existe
sessão pro `guild_id`, devolve só um aviso ("Já tô na call tocando música
nesse servidor.", com um complemento se `sessao._vc.is_paused()`) e não
mexe em mais nada. Isso torna o bug de `_modo_aprovadas` descrito abaixo
inatingível por essa rota (documentado como estava, pela história).

**Restrição a 1 canal por servidor (2026-08-29)** - pedido do usuário:
"assim como a coleção de waifu roda em 1 canal, quero q parte de musica
tbm fique so em 1 canal configuravel". Diferente do `canal_anuncio_id` do
Colecionador (que só direciona onde o AUTO-colecionador posta os PRÓPRIOS
rolls, nunca bloqueia `/wa`/`/ha`/`/ma` em outro canal), aqui a restrição
é de verdade: `musica.obter_canal_restrito(guild_id)` (via
`_no_canal_certo_de_musica`, `eris/bot.py`) barra `/musica tocar/pular/
pausar/continuar/fila/parar/dj_automatico` e `/caos` fora do canal
configurado, respondendo ephemeral com o canal certo. `/musica aprovadas`/
`desaprovadas` ficam de FORA de propósito - consulta pessoal ephemeral,
sem áudio nem anúncio, não fazem parte do "barulho" que a restrição existe
pra conter.

Guardado em `data/musica_canal_restrito.json` (`{guild_id: canal_id}`),
NÃO em `eris.db` - só a instância "musica" (papel dedicado, ver
"Múltiplas instâncias" abaixo) registra `/musica`/`/musica_admin`/`/caos`,
e essa instância NUNCA chama `db.inicializar()` (`eris/main.py` - `db`/
ponte HTTP são exclusivos do papel "completo"). Configurável por
`/musica_admin canal <#canal>` (permissão de administrador do servidor,
mesma régua de `/colecao_admin`, checada de novo aqui - não reaproveitada
de `_registrar_slash_colecao` porque só "musica" registra este grupo) -
sem informar canal, remove a restrição; `/musica_admin ver` mostra a
config atual. Seedado direto no JSON pro servidor real (`Taverna da
Última Rodada`, guild `1388541192806989834` -> canal
`1388915991223730377`) sem precisar rodar o slash command.

**Botões ⏯️/⏭️/👍/👎/▶️/📋 na mensagem de "tocando agora" (2026-08-26/27)** -
pedido do usuário: "quando ela toca uma musica, podia aparecer botoes de
like, dislike e next", depois expandido ("Além dos controles atuais,
adicionaria: pausar/retomar, exibir a fila, tocar diretamente..."). `_tocar()`
(`eris/core/musica.py`) virou o ÚNICO lugar que anuncia a faixa no canal de
TEXTO (`SessaoMusica.text_channel`, guardado na entrada da sessão) - cobre
tanto o play imediato quanto a continuação automática (`_avancar`, sem
interaction nenhuma pra responder) de forma uniforme, em vez de só o
retorno da slash command original. `_ViewControlesMusica` (discord.ui.View,
`timeout=None`) processa cada clique, NESSA ordem (pedido do usuário):
- ⏯️ (novo, 2026-08-27) - pausa se tocando, retoma se pausado (`_vc.
  is_paused()` decide qual). Símbolo COMBINADO fixo (não troca ⏸️↔️▶️ ao
  clicar) - um emoji dinâmico colidiria visualmente com o botão de replay
  (▶️, sempre presente na mesma mensagem). Restrito a quem iniciou a sessão.
- ⏭️ chama a mesma função `pular()` de sempre (`/musica pular`), restrito a
  quem iniciou a sessão.
- 👍/👎 chamam `gaia_webhook.pedir_feedback_musica` -> `POST /eris/
  musica_feedback` no bridge da GAIA -> `echo_client.enviar_feedback_
  musica` -> `POST /radar/feedback_ao_vivo` no ECHO (cria a entrada no
  histórico na hora se a faixa nunca passou pelo Radar, resolve o gênero
  sozinho, e agora tira a faixa exata do pool - "Musicas sem voto não saem
  do pool" no ECHO). Resposta ephemeral, não interrompe a reprodução.
  Aberto a QUALQUER membro (alimenta só o perfil de quem clicou).

  🔥 **👎 também pula a faixa, restrito a quem iniciou (2026-08-29)** -
  pedido do usuário: "qnd clico no dislike, pode ja pular a musica junto
  tbm", seguido de "pode restirngir o skip do dislike a quem iniciou"
  (efeito colateral do 1º pedido - qualquer membro conseguia pular
  indiretamente via dislike, não só via ⏭️). `_dislike` sempre registra o
  VOTO (`gaia_webhook.pedir_feedback_musica`, aberto a qualquer membro,
  como sempre foi), mas só chama `pular()` quando as DUAS condições valem:
  (a) `self._artista`/`self._titulo` (identidade capturada na CONSTRUÇÃO
  da mensagem) bate com `sessao.tocando_agora` - sem isso, 👎 numa
  mensagem antiga de "tocando agora" (rolando o histórico do canal, mesmo
  cenário do ▶️ replay) pularia a música ERRADA, já que `pular()` sempre
  age sobre o que está tocando agora na sessão, não sobre a faixa da
  mensagem clicada; (b) `str(interaction.user.id) == sessao.iniciado_por`
  - mesma régua de `_somente_iniciador`/`/musica pular`, mas aplicada só
  ao EFEITO de pular, não ao voto (quem não iniciou ainda consegue dar
  👎, só não força o skip).

  🔥 **Limpeza da fila lógica por artista - adicionada e revertida no
  mesmo dia (2026-08-27)** - o requisito original do plano ("feedback
  negativo reorganiza músicas ainda não preparadas... streams já
  resolvidos permanecem") nunca tinha sido conectado no código final;
  implementei `SessaoMusica.remover_artista_da_fila_logica` pra remover da
  fila lógica tudo do mesmo artista num 👎, espelhando o `pool.
  invalidar_relacionados` do ECHO. O usuário apontou o problema de fundo:
  "um 👎 em 1 musica n pode condenar todas desse artista. Assim como o
  like n aprova todas tbm, algumas eu gosto e outras nao" - o requisito
  original do plano JÁ estava errado nessa premissa. Revertido junto com
  `pool.invalidar_relacionados` no ECHO - voto agora fica estritamente por
  FAIXA, nunca por artista.
- ▶️ (pedido do usuário: "Adicionar botão de play, para caso queira voltar
  em alguma musica que tocou") - `adicionar_por_identidade` reusa a mesma
  busca/enfileiramento de `/musica tocar`, a partir do artista/título JÁ
  guardados na View (não precisa perguntar nada). Como cada mensagem de
  "tocando agora" antiga continua no canal com seus próprios botões válidos,
  voltar numa música é só rolar até a mensagem dela e clicar. Aberto a
  qualquer membro (mesmo espírito de "adicionar à fila", não é controle de
  estado). Exige uma sessão JÁ ativa nesse servidor.
- 📋 (novo, 2026-08-27) - mesmo texto de `/musica fila`
  (`formatar_estado_fila`, compartilhado pelos dois pra não duplicar
  formatação), ephemeral. Aberto a qualquer membro (só consulta).

🔥 **Avaliação de rodada de design (2026-08-27)** - o usuário propôs trocar
👍/👎 por REAÇÕES nativas do Discord (pré-adicionadas pela ERIS, com
"estado selecionado" visual e contagem). Avaliado e adiado: reação resolve
bem o estado "você reagiu NESTA mensagem" (nativo do cliente Discord), mas
NÃO resolve "essa música já foi avaliada antes, numa mensagem ANTERIOR" -
isso é impossível pela API (reação é sempre por mensagem, o bot não pode
marcar uma reação como "já clicada" por alguém que nunca clicou nela).
Mantido como botão por ora; o "já avaliada antes" virou texto simples (ver
"(👍)"/"(👎)" abaixo) em vez de tentar simular visualmente.

**Anúncios viram `discord.Embed` com borda colorida (2026-08-27, pedido do
usuário: "queria q as mensagens do bot tivessem esse embed ou borda...
pra ficar facil diferenciar")** - texto solto no canal se misturava com o
resto da conversa. `COR_EMBED_MUSICA = discord.Color(0x4BADE8)` (mesmo
azul-claro já usado no resto do ecossistema, `ui/qt_modais/argus.py` da
GAIA) aplicado tanto no anúncio de "tocando agora" (`title`+`description`,
View de botões continua funcionando junto do embed) quanto no aviso de
lista de aprovadas esgotada - as duas mensagens PROATIVAS do canal (não
respostas ephemeral de comando, essas continuam texto simples).

**Título com link pro vídeo (2026-08-27, pedido do usuário)** - `_titulo_
com_link` (`eris/core/musica.py`) transforma o título do anúncio num link
markdown pra `faixa["url_pagina"]` (já vem de `_buscar_no_youtube`, sempre
presente numa faixa resolvida) - cai pro título em negrito puro se faltar
por algum motivo, nunca quebra o anúncio. Só na linha de "tocando agora",
não na listagem de fila (`/musica fila`/📋) - fora do escopo do pedido.

**"(👍)"/"(👎)" no final da linha de anúncio (2026-08-27)** - se a faixa que
está tocando agora já foi avaliada antes por quem INICIOU a sessão
(`SessaoMusica._sufixo_voto`, `POST /eris/musica_voto` no bridge da GAIA ->
`echo_client.obter_voto_musica` -> `GET /perfil/voto` no ECHO). Roda DEPOIS
de `self._vc.play()` já ter começado - atrasa só o texto do anúncio, nunca
o áudio (mesma regra de zero-espera-perceptível de sempre).

**Mesmo sufixo agora também em `/musica fila`/📋 (2026-08-28, pedido do
usuário: "no listar tem q por o voto se tiver, igual tem os (👍) no final
de qnd toca")** - `SessaoMusica.obter_fila` virou async e busca o voto da
faixa atual + de cada item da camada 3 (`fila`, streams já resolvidos,
`asyncio.gather` pra não serializar as chamadas) antes de montar o estado;
`formatar_estado_fila` só concatena o sufixo já pronto. Fica de fora só a
camada 2 (`fila_logica`, sem stream) - continua aparecendo como contagem
("+N já reservadas"), nunca item a item, então não tem faixa individual pra
anexar sufixo. `/musica fila` (slash command) passou a `defer()`/
`followup.send()` em vez de responder direto - a busca de voto por item é
rede, pode passar dos 3s que o Discord dá pra resposta imediata.

Views não são persistidas entre reinícios do processo (mesma limitação já
aceita pro resto do estado da sessão, `_sessoes_musica` em memória) -
botões de uma call anterior ao restart simplesmente param de responder,
consistente com a sessão em si já não existir mais.

## Buffer em 3 camadas + dono da sessão + feedback passivo (2026-08-26)

Investigando "eu mandei varias playlists, ela n se baseia nelas como meu
gosto?", o usuário pediu um redesenho completo do Modo Música pra garantir
**zero espera perceptível entre músicas** ("espera perceptível entre
músicas é fallback/falha de pré-carregamento, nunca comportamento normal
do `/caos`"). O ECHO já resolve a camada 1 (pool pessoal, 100-300, lado
dele - ver `ARQUITETURA.md` do [Project ECHO](../../Project-ECHO)). Aqui
dentro, `SessaoMusica` (`eris/core/musica.py`) ganhou mais 2 camadas:

- **Camada 2, `fila_logica`** (alvo 20-50) - identidade da faixa (artista/
  título) já puxada do pool do ECHO via `gaia_webhook.pedir_proxima_musica`/
  `pedir_semente_musica`, ainda SEM stream resolvido no YouTube.
- **Camada 3, `fila`** (alvo 5-10) - streams JÁ resolvidos (`url_stream`
  pronto), com `resolvido_em` (timestamp) pra detectar link do YouTube
  velho demais (`_STREAM_MAX_IDADE_SEGUNDOS`, 1h) e re-resolver ANTES de
  tocar, em vez de tentar tocar um link expirado.

`_avancar()` (chamado quando uma faixa termina) só CONSOME o topo da
camada 3 - nenhuma chamada de rede no caminho crítico. As 2 camadas se
reabastecem em BACKGROUND (`_repor_fila_logica`/`_resolver_streams`, via
`asyncio.create_task`, guardadas contra execução concorrente duplicada)
sempre que caem abaixo do mínimo, nunca bloqueando a reprodução atual. Cai
pra resolver a camada 2 na hora (ainda sem bloquear indefinidamente) só se
a 3 já secou, e só pede uma sugestão nova SÍNCRONA ao ECHO (mesmo caminho
de antes desta reescrita) se as duas primeiras já estiverem vazias - esse
é o fallback raro, não o caminho normal.

**Diversidade de sessão sem conhecer gênero** - o ERIS não sabe gênero
(isso é conhecimento exclusivo do ECHO), então `_penalidades_sessao` só
penaliza por ARTISTA repetido demais NESTA sessão (`_contagem_artistas_
sessao`, incrementado quando uma identidade entra na camada 2), mandado
junto em toda chamada de continuação/semente pro ECHO aplicar.

**Fila lógica persistida** (`data/fila_sessao_<guild_id>.json`) - sobrevive
a um restart do ERIS enquanto a call continua ativa, pra não perder
identidades já consumidas do pool do ECHO (cada consumo de lá é definitivo,
não tem como "devolver"). Removida quando a sessão termina de verdade
(`sair_musica`).

**Dono da sessão** (`SessaoMusica.iniciado_por`, decisão do usuário
2026-08-26 resolvendo uma contradição real: Modo Música virou social por
pessoa, mas ainda precisava de UM dono pros controles de estado) - quem
chamou `/musica tocar`/`/caos` primeiro nesse servidor. Controles de
reprodução (`/musica pular/pausar/continuar/parar/dj_automatico`, e o
botão ⏭️) checam `interaction.user.id == sessao.iniciado_por`
(`eris/bot.py::_quem_iniciou_pode`) - **adicionar à fila (`/musica tocar
<busca>`) e like/dislike continuam abertos a qualquer membro**, só o
controle de ESTADO da sessão é restrito. Sem substituto pra "dono da
Galateia" (a instância "musica" não carrega `eris.db`/lista de donos,
papel sem moderação) - se quem iniciou sair e não voltar, ninguém mais
controla a sessão até ela ser reiniciada; aceito como limitação conhecida.

**`/musica tocar` sem parâmetro toca as aprovadas** (pedido do usuário:
"o musica tocar, se n passar parametro, começa a tocar as musicas q
aprovei, ate terminar todas") - `musica.tocar_aprovadas` puxa a lista de
👍 de quem chamou (`gaia_webhook.pedir_aprovadas_musica`), usa como seed
fixa da fila lógica (`_modo_aprovadas=True`) e AVISA + PARA ao esgotar, em
vez de cair pro pool/`/caos` como o modo contínuo normal faz - é uma lista
fechada, não uma sessão infinita. `/musica aprovadas`/`/musica
desaprovadas` listam o que cada pessoa já avaliou.

**Paginação + troca de voto na lista (2026-08-28)** - pedido do usuário: "a
lista de musicas com like e dislike supera muito 25, tem q criar paginas e
permitir alterar" (o ECHO nunca teve teto - `historico.obter_aprovadas`/
`obter_desaprovadas` sempre devolveram a lista inteira; o corte era só o
`faixas[:25]` do lado do ERIS, silencioso). `musica.ViewListaVotos` pagina
de verdade (25 por página, mesmo teto do `discord.ui.Select` - dá pra usar
a página inteira como opções) com botões ◀️/▶️ reconstruindo o select a
cada troca de página. Escolher uma faixa no select abre `_ViewTrocarVoto`
numa resposta ephemeral à parte, com botões Aprovar/Desaprovar (o que já
reflete o voto atual da faixa vem desabilitado) - reaproveita o MESMO
`gaia_webhook.pedir_feedback_musica` que os botões 👍/👎 de "tocando agora"
já usam, nenhuma rota nova na GAIA/ECHO. Diferente do 👎 de "tocando agora"
(ver acima), Desaprovar aqui NUNCA pula nada - a lista não sabe em qual
guild/sessão de voz a faixa está tocando (se estiver).

**Feedback passivo (sinal fraco)** - `SessaoMusica._tocar` guarda
`_inicio_atual` (`time.monotonic()`) e reseta `_pulado_manualmente`;
`pular()` marca esse flag ANTES de `.stop()` (distingue skip manual de fim
natural, já que o callback `after` do discord.py dispara igual nos dois
casos). No início de `_avancar()`, ANTES de qualquer branch/recursão,
captura e LIMPA `tocando_agora`/`_inicio_atual`/`_pulado_manualmente` da
faixa que acabou de terminar e manda `gaia_webhook.pedir_feedback_passivo_
musica` em background (fração tocada = tempo decorrido / `duracao_
segundos` do yt-dlp) - atribuído a `iniciado_por` (o sinal é sobre a vibe
da SESSÃO, não dá pra saber quem na call efetivamente ouviu). Achado ao
revisar: capturar DEPOIS de uma branch que recursa (`await self._avancar()`
de novo, quando um stream expirado não re-resolve ou uma identidade não
acha nada no YouTube) mandaria o MESMO evento passivo duplicado - corrigido
limpando o estado antes de qualquer recursão possível.

## Canal de anúncio de música sempre fixo no configurado (2026-08-30)

Pedido do usuário depois de reportar `/caos`/comandos do Colecionador
"sempre respondendo no canal definido" - na 1ª leitura pareceu bug
(`SessaoMusica.text_channel` gravado só na criação, nunca atualizado -
uma sessão antiga continuava anunciando "Tocando: X" pro canal de quando
começou, mesmo que `/musica tocar`/`/caos` fossem chamados de outro canal
depois), mas uma pergunta direta revelou que era o comportamento
DESEJADO, só faltava aplicar CONSISTENTEMENTE: "quero q tudo relacionado
a musica so seja respondido no canal de musica definido, independente se
mandar o comando em outro canal".

**Antes**: `_no_canal_certo_de_musica` BLOQUEAVA `/musica <ação>`/`/caos`
fora de 1 canal configurável (`/musica canal`), recusando com "só funciona
em #X". **Agora**: função removida, substituída por `_canal_anuncio_
musica(interaction)` (resolve o canal configurado, senão cai no de
onde veio o comando) + `_responder_no_canal_de_musica(interaction, texto)`
- comandos funcionam de QUALQUER canal; se o canal resolvido for
DIFERENTE de onde o comando saiu, a interação vira um ack ephemeral
silencioso (apagado em seguida) e o texto de verdade vai como mensagem
comum pro canal configurado (`canal.send(...)`) - não dá pra fazer uma
resposta de interação aparecer num canal diferente de onde ela nasceu,
limitação da própria API do Discord. `_obter_ou_criar_sessao` também
passou a reatribuir `sessao.text_channel` toda vez que um comando roda
numa sessão JÁ ativa (antes só gravava na criação).

Mesmo fix aplicado ao Colecionador (agora em
[Project-PANDORA](../Project-PANDORA), ver `ARQUITETURA.md` de lá,
`gacha.enviar_resultados`) - telas ephemeral (perfil, wishlist, trocas,
Prova de Soulmate) ficam de fora, Discord não permite redirecionar
mensagens ephemeral pra outro canal.

## Comportamento conhecido: sessão de música "fantasma" na call após "Reiniciar Ecossistema Completo" (2026-08-27)

Observado pelo usuário: "ela estava em call qnd reiniciei, ela parou a
musica mas continuou na sala". Investigado no lado da GAIA
(`scripts/reiniciar_ecossistema.py`) - o restart mata o processo do ERIS
com `psutil.proc.kill()` (`TerminateProcess`, término ABRUPTO, sem
handshake). Isso explica os dois sintomas juntos: o ÁUDIO para na hora
(processo morto, stream cortado), mas a PRESENÇA na call de voz do
Discord não - `SessaoMusica.sair()`/`self._vc.disconnect()` nunca chegam
a rodar (nenhum código de limpeza roda num kill duro), então o Discord só
derruba essa presença de voz quando o PRÓPRIO timeout dele expira
(minutos, não imediato) - diferente da presença de TEXTO (online/offline),
que cai rápido via perda de heartbeat do gateway. Confirmado via PID: os 4
processos do ERIS (completo + música, launcher uv + processo real) trocam
de PID a cada restart - o kill funciona de verdade, não é processo zumbi.
Estado da sessão (`_sessoes_musica`, em memória) também se perde no
restart - o ERIS novo não sabe que "estava" numa call, não reconecta
sozinho. Aceito como limitação conhecida por ora (mesma natureza do "views
não são persistidas entre reinícios" já documentado acima) - resolver de
verdade exigiria um desligamento GRACIOSO do ERIS antes do kill (endpoint
HTTP pra pedir shutdown limpo, com `sessao.sair()` em todas as sessões
ativas antes de sair do processo), não implementado ainda.

## Bug real: `/caos` depois de `/musica tocar` (aprovadas) ficava preso no modo errado (2026-08-27, rota removida em 2026-08-28)

Histórico - `/caos` não chega mais a reaproveitar uma sessão já ativa (ver
"`/caos` só age se NÃO tem sessão ativa" acima), então este cenário não
ocorre mais. Mantido pelo valor histórico do diagnóstico.

Usuário reportou: "assim q eu uso o /caos, ele tem de ignorar tudo p tras e
seguir a logica do /caos, atualmente ele ta repetindo a msg... O caos so ta
tocando 1 musica". Causa raiz: `iniciar_caos` chama `_obter_ou_criar_
sessao`, que REAPROVEITA a sessão já ativa se ela existir (em vez de criar
uma nova) - se essa sessão tinha começado antes por `/musica tocar` sem
parâmetro (`tocar_aprovadas`, que seta `SessaoMusica._modo_aprovadas =
True`), `iniciar_caos` nunca resetava essa flag. Duas consequências: (1)
`_avancar()` continuava tratando a sessão como "lista fechada de
aprovadas" - ao esvaziar os buffers, sempre caía no branch `if self.
_modo_aprovadas:` (aviso de esgotado + `return`), nunca no fallback de DJ
contínuo normal do `/caos`; (2) `_agendar_reabastecimento` pula
`_repor_fila_logica` inteiro quando `_modo_aprovadas` é True, então a fila
lógica nunca era reabastecida - por isso só 1 música tocava. Corrigido:
`iniciar_caos` agora seta `sessao._modo_aprovadas = False` logo depois de
obter/criar a sessão, antes de pedir a semente pro ECHO.

## Bug real: dedup de sessão nunca batia, mesma música repetia (2026-08-26)

Usuário reportou: "Caos esta demorando para iniciar e esta repetindo
sempre a msm musica, quando pulo para a proxima pelo botão tbm" - log de
produção confirmou "Maroon 5 - Payphone ft. Wiz Khalifa (Explicit)
(Official Music Video)" tocando 3x SEGUIDAS. Causa raiz: `_registrar_
historico`/o pedido de próxima sugestão usavam `faixa["artista"]`/
`faixa["titulo"]` como o YOUTUBE devolveu (uploader do canal + título cru
do vídeo, cheio de "(Official Video)"/"ft. Fulano"/variações de
remaster) - a lista de exclusão de sessão mandada pro ECHO nunca batia
com o "artista::título" LIMPO que o próprio ECHO usa nos candidatos dele
(ex.: `"maroon 5vevo::maroon 5 - payphone ft. wiz khalifa (explicit)
(official music video)"` no lugar de `"maroon 5::payphone"`) - a exclusão
de sessão inteira era, na prática, um no-op silencioso.

Corrigido: `_buscar_sugestao_no_youtube` (novo, `eris/core/musica.py`)
busca no YouTube mas SOBRESCREVE o artista/título da faixa resultante
pro valor limpo que o ECHO sugeriu, ANTES de tocar/registrar no
histórico de sessão. Usado tanto por `_avancar` (continuação automática)
quanto por `iniciar_caos` (`/caos`) - as duas únicas origens de faixa que
vêm de uma sugestão do ECHO (busca livre via `/musica tocar` continua
usando o texto cru do YouTube, não tem "valor limpo" alternativo pra
usar). Validado simulando o cenário exato do bug (YouTube devolvendo
título sujo, artista final confirmado como o limpo do ECHO).

## Múltiplas instâncias (2026-08-26) - Música e voz simultâneas no mesmo canal

Pergunta real do usuário ao ver o Modo Música pronto: dá pra ter um ERIS
tocando música e outro conversando/traduzindo AO MESMO TEMPO no MESMO
canal (mesmo espírito do Jockie, que usa 4 bots separados - Jockie Music/
Music 1/2/3)? Sim - o limite do Discord é 1 conexão de voz por CONTA de
bot por servidor, não por canal; duas contas diferentes podem estar no
mesmo canal ao mesmo tempo. O usuário criou uma 2ª aplicação/bot no
Developer Portal (`ERIS#0983`, token próprio) - o código ficou modular o
bastante (Música e voz já eram mutuamente exclusivas DENTRO de uma
instância) pra isso ser só um parâmetro de papel, não reescrita.

- **`eris/main.py`** detecta o papel por argv (`python -m eris.main` =
  "completo", `python -m eris.main musica` = "musica") - não por variável
  de ambiente, pra não colidir com o `override=True` do `load_dotenv` (uma
  variável setada no processo pai venceria o `.env` local em silêncio,
  mesmo bug já corrigido no HESTIA/MOIRAI/GAIA). Papel "musica" carrega
  `.env.musica` (token PRÓPRIO, template em `.env.musica.example`) em vez
  de `.env`, usa uma porta de instância única separada
  (`PORTA_INSTANCIA_UNICA_MUSICA = 8779`, `eris/config.py`) e PULA
  `db.inicializar()`/a ponte HTTP (`api_bridge.py`, porta 8772 já ocupada
  pela instância "completo") - sem moderação/donos, a GAIA nunca precisa
  chamar DENTRO dessa instância, só ela chamando a GAIA
  (`gaia_webhook.pedir_proxima_musica`).
- **`eris/bot.py::iniciar_bot(token, papel="completo")`** condiciona no
  papel: intents privilegiadas (`message_content`/`members`) e os grupos
  `/moderacao`, `/mensagem`, `/canal`, `/cargo`, `/exportar`,
  `/conversar`, `/interprete`, `/tutora`, além do handler `on_message`
  (texto livre/webhook pra GAIA) e `on_guild_join`/`on_guild_remove`
  (cache de guilds, usa `db`) só existem no papel "completo". `/musica`/
  `/caos` são o INVERSO - exclusivos do papel "musica" (achado pelo
  usuário 2026-08-26: "pq a gaia e a eris tem /caos? N deveria ser apenas
  da eris?" - antes registrava sem checar papel, então a instância
  "completo" também tinha os comandos, e um clique errado nela ocupava o
  único slot de voz dela com música, derrubando Conversa/Intérprete/Tutora
  até parar - exatamente o que a 2ª instância existe pra evitar).
  `on_voice_state_update` (sair sozinho de call vazia) é o único que vale
  pros dois papéis de propósito - já era agnóstico, checa `voz_call.
  canal_ativo` OU `musica.canal_ativo` (na instância "completo", `musica.
  canal_ativo` nunca é diferente de None, já que ela não cria sessão de
  música nenhuma - checagem inofensiva, não removida por simplicidade).
- **Validado numa call real (2026-08-26)**: as 2 instâncias JUNTAS no
  MESMO canal - `ERIS#0983` tocando música (`/musica tocar`) enquanto a
  instância "completo" respondia por voz no Modo Conversa ao mesmo tempo,
  confirmado pelo usuário ("consegui usar as 2 ao msm tempo, e gaia me
  respondeu... e a eris tocando musica"). GAIA sobe as duas sozinha no
  boot desde então (`garantir_eris_rodando`/`garantir_eris_musica_rodando`,
  `Project G.A.I.A/assistant/integrations/iris_bridge.py`).
- **Decisão de `data/eris.db`**: NÃO compartilhado - a instância "musica"
  nem chama `db.inicializar()`, então não tem tabela nenhuma. Donos/config
  de roteamento continuam só na instância "completo" (ela decide quem é
  dono pra fins de moderação/DM; `/musica` é aberto a qualquer membro em
  ambas, sem checar `db`).

## Bug real: timeout de 3s do Discord consumia rolls sem mostrar nada (2026-08-29)

Usuário relatou 2 vezes o mesmo sintoma: "meus rolls deveriam ter resetado,
mas n consigo rolar... foi a gaia q deu os rolls dela" - a 2ª vez, com mais
detalhe, deu a pista real: "na primeira vez q uso /wa ela deu como
aplicativo nao respondeu, na segunda deu o erro de q ja usei os 50". Não
tinha nada a ver com a conta da GAIA (auto-colecionador usa `gacha.
rolar_sem_cooldown`, que nunca toca em `colecao_estado_jogador` - só existe
UMA linha nessa tabela, a do próprio usuário humano).

**Causa raiz**: `_rolar_e_responder` (`eris/bot.py`) e `ViewHubWaifu._rolar`
(`eris/colecao/paineis.py`) chamavam `gacha.rolar_varios` (síncrono, um
`SELECT` no banco por personagem sorteada) ANTES de `interaction.response.
defer()` - um comentário já existente dizia que o defer protegia "puxadas
grandes" contra o timeout de 3s do Discord, mas ele vinha DEPOIS da chamada
lenta, então não protegia nada de verdade. Medido ao vivo: 50 chamadas
sozinhas de `db.candidatos_por_raridade` já levam **4.8s** - acima do
prazo. Como `db.consumir_rolls` roda bem no INÍCIO de `rolar_varios`
(antes do sorteio em si), o timeout matava a interação DEPOIS do ciclo
inteiro já ter sido descontado, sem nenhum card aparecer - exatamente o
padrão relatado (1ª tentativa "não respondeu" = consumiu e morreu em
silêncio; 2ª tentativa, já sem rolls, respondeu rápido = "já usei os 50").

**Corrigido**: `defer()` movido pra ANTES da chamada em ambos os lugares;
`rolar_varios` agora roda em `asyncio.to_thread` (evita travar o loop
assíncrono do bot inteiro numa puxada de 50); o caminho "sem rolls
sobrando" passou a usar `interaction.followup.send` (a resposta inicial
virou sempre um defer, não dá mais pra usar `response.send_message`
direto). Rolls do usuário resetados manualmente no banco depois do fix
pra compensar os 2 ciclos perdidos.

**Como aplicar**: qualquer código futuro que chame uma função SÍNCRONA
bloqueante de banco/rede a partir de um handler de interação do Discord
precisa deferir (ou já ter respondido) ANTES dessa chamada, nunca depois -
o prazo de 3s do Discord conta a partir do início da interação, não do
fim do processamento.

**2 achados relacionados, mesmo dia**:
1. `/colecao_disponiveis` tinha o MESMO risco de estourar 2000 caracteres
   (listava até ~150 pendentes com 3 pessoas rolando 50/hora cada) - e
   também não batia com o pedido original do usuário ("ordenado por
   popularidade... retornar apenas os 10 melhores", não por raridade,
   não a lista inteira). `gacha.personagens_pendentes` ganhou `limite`
   (corta na FONTE, não só na exibição) e passou a ordenar por
   popularidade; `/colecao_disponiveis` usa `limite=10`. `consulta.
   formatar_wishlist`/`formatar_ranking`/`formatar_busca` também
   ganharam a mesma rede de segurança (`_truncar_seguro`) contra o
   limite de 2000, mesmo sem terem estourado ainda de verdade.
2. A mensagem de botões do roll (`gacha.enviar_resultados`/`auto_
   colecionador.py`) repetia os MESMOS embeds dos cards individuais que
   acabaram de sair com reação (usuário: "ta repetindo os cards... eles
   ja foram enviados 1 por msg antes") - removidos, a mensagem de botões
   agora só tem o texto "👇 Ou reivindique por aqui:" + os botões.

## Colecionador de Personagens (2026-08-29) - MVP inspirado na Mudae/Fable

🔥 **EXTRAÍDO pro [Project PANDORA](../Project-PANDORA) (2026-08-29, mesmo
dia)** - todo o código descrito nesta seção e nas 3 seguintes (`eris/
colecao/*`, 14 tabelas `colecao_*` de `eris/db.py`) foi movido pra um repo
próprio, quando o Colecionador já era a MAIORIA do peso do ERIS (~2.780
linhas de `eris/colecao/*` + 14 de 19 tabelas do banco). Biblioteca Python
LOCAL (não satélite HTTP como MOIRAI/ECHO - decisão explícita, ver
`ARQUITETURA.md` do PANDORA pro porquê: todo clique de roll/claim/troca
cai no orçamento de 3s do Discord, um satélite HTTP arriscaria regredir 2
bugs de timeout já corrigidos). `eris/bot.py` importa o pacote novo via
dependência de path (`uv`, `pyproject.toml`); comandos/painéis continuam
idênticos do ponto de vista de quem usa o Discord. As 4 seções abaixo
(design original/WiShards/Loja/Categoria de combate/Prova de Soulmate)
ficam registradas aqui como HISTÓRICO de como o sistema foi desenhado -
consulte o `ARQUITETURA.md` do PANDORA pro estado atual do código.

Pedido do usuário: um colecionador de personagens (waifus/husbandos) igual
à Mudae, mas com código/catálogo/moeda/identidade próprios - ver
`PLANO_COLECAO_WAIFUS.md` (`C:\Workspace`) pro desenho original completo
(10 fases, Postgres/Redis/FastAPI/SQLAlchemy, catálogo AniList+Jikan+IGDB).
Esse plano original foi avaliado e **rejeitado quase todo**: superdimensionado
pra um bot de uso pessoal (escala confirmada pelo usuário) - nenhuma
infraestrutura nova, tudo dentro do `eris.db` (SQLite) já existente, mesmo
espírito do resto do ERIS.

**Referência de arquitetura, não de stack**: o usuário pesquisou bots de
colecionador abertos e escolheu o [Fable](https://github.com/ker0olos/fable)
(alternativa MIT a Mudae/Sofi/Karuta, TypeScript+MongoDB+Deno, arquivado em
2026-08-07) como referência de DIVISÃO CONCEITUAL - `db/schema.ts`,
`charactersPool.ts`, `getInventory.ts`, `src/gacha.ts` foram lidos e
resumidos antes de desenhar `eris/colecao/` (`gacha.py` = roll/claim,
`consulta.py` = coleção/busca/wishlist/ranking, `importar_get_waifu.py` =
carga do catálogo). A stack não foi copiada (nada de Mongo/Deno).

### Painel `/waifu` (2026-08-29) - reorganização de comandos inspirada no LegendsAwaken

O bot "completo" chegou a **25 comandos raiz** no seletor `/` do Discord - boa
parte (18) só do Colecionador (`/wa /ha /ma /colecao /carteira /personagem
/populares /colecao_disponiveis /divorciar /favoritar /ranking /merge`
soltos + `/wishlist /colecao_admin /party /vitrine /loja /trocar` como
grupos). Usuário: "os bots estão ficando muito poluídos... devo criar um
outro bot só p funcoes de colecao de waifu?" - GPT (consultado à parte)
sugeriu agrupar em subcomandos (`/waifu roll`, `/waifu colecao`...); o
usuário então apontou o próprio **LegendsAwaken** (`C:\Workspace\
LegendsAwaken`, C#/Discord.Net, projeto dele) como referência mais forte:
lá, cada sistema tem **1 comando raiz** (às vezes ZERO - `Grupos`/party só
é alcançado por botão de dentro do painel de `Herois`) e toda navegação
depois disso acontece via embed+botões editados na mesma mensagem
("painel"), não subcomando.

**O que foi adotado do LA**: 1 comando por sistema (`Commands/XxxCommand.cs`
só busca dado e chama `Panels/XxxPanel.cs`, que são funções puras
embed+componentes); estado por closure/re-derivação do banco a cada
clique, sem sessão em memória própria. **O que NÃO foi copiado**: o
`custom_id` roteado por prefixo do LA (`InteractionRouter` central) - o
discord.py já resolve melhor com `View`/`Item.callback = self._metodo`
fechando sobre variáveis Python, mesmo padrão que `ViewColecao`/
`ViewClaimMultiplo`/`ViewClaimPendentes`/`ViewTroca` (`eris/colecao/`) e
`musica.ViewListaVotos`/`_ViewTrocarVoto` já usavam ANTES desta leva; e a
paginação fraca do LA (corta em 25/agrupa em campos de embed, sem "próxima
página") - `ViewColecao` (10/página) já é melhor nisso.

Módulo novo `eris/colecao/paineis.py` (mirror do `Panels/` do LA) -
`gacha.py`/`consulta.py`/`economia.py` continuam sendo a camada de dado/
regra, SEM mudança de lógica interna. `/waifu` (comando novo, sem
argumento) abre `paineis.ViewHubWaifu` com botões que mandam uma resposta
NOVA (nunca editam a mensagem do hub - o hub continua clicável pra abrir
outro sub-painel, sem precisar de botão "◀️ Voltar" nesta 1ª leva):

- **🎲 Rolar** → `gacha.rolar_varios(guild_id, user_id, "ma", 0)` (mesmo
  "qualquer gênero, máximo disponível" que `/ma` sem parâmetro já faz) +
  `gacha.enviar_resultados` sem alteração nenhuma - `/wa`/`/ha`/`/ma`
  continuam sendo o caminho rápido pra gênero/quantidade específicos.
- **📚 Coleção** → `paineis.ViewColecaoHub`, SUBCLASSE de `consulta.
  ViewColecao` que acrescenta um `discord.ui.Select` de modo (linha 1,
  abaixo do pager ◀️/▶️ existente): "Minha coleção" (`db.colecao_do_
  usuario`, comportamento de `/colecao`), "🔥 Populares" (`db.personagens_
  por_popularidade`, comportamento de `/populares`) e "🎯 Disponíveis pra
  pegar" (`gacha.personagens_pendentes`, comportamento de `/colecao_
  disponiveis` - reaproveita `gacha.ViewClaimPendentes` como sub-view
  quando o botão de claim é clicado, sempre RE-BUSCANDO do banco na hora
  do clique, nunca reaproveitando a lista já achatada da página, pra não
  oferecer claim numa carta que expirou entre abrir e clicar). Trocar de
  modo reresolve os 4 campos (`_titulo`/`_personagens`/`_pagina`/
  `_formatador_linha`) via `_dados_do_modo()` e chama `_montar()` de novo -
  mesmo método (não um novo) que o `ViewColecao` pai já usa pro pager,
  então ◀️/▶️ continuam funcionando sem duplicar lógica de paginação.
  `consulta._linha_personagem` virou pública (`linha_personagem`, sem
  underscore) pra esse uso entre módulos deixar de ser um acesso a
  membro "privado".

**Fase 1 (aprovada) - COMPLETA nos passos 1-5, passo 6 pendente de
propósito.** Implementado, nesta ordem:
- **👤 Perfil** - painel NOVO (não existia comando equivalente) juntando
  `db.saldo_wishards` (`/carteira`) + posição no ranking (`db.ranking_
  guild(..., limite=1_000_000)`, pra achar a posição de QUALQUER um, não
  só o top 10 do `/ranking` de sempre) + `db.contar_favoritas` (novo, só
  fazia `eh_favorita` de UM personagem por vez antes). Botões Favoritar/
  Divorciar/Merge abrem `_ViewSelecionarPersonagem` (select genérico de
  até 25 personagens da própria coleção - reaproveitado depois pela
  Party) - Divorciar/Merge mostram `_ViewConfirmar` (Sim/Não genérico)
  quando a regra de sempre pede confirmação (favorita/Afinidade > 1).
- **⭐ Wishlist** - `ViewWishlistHub` (subclasse de `ViewColecao`, mesmo
  padrão de `ViewColecaoHub`) com botão "➕ Adicionar" abrindo um
  `discord.ui.Modal` (nome do personagem por texto - busca via `db.
  buscar_personagens`, pede pra especificar o #id se vier mais de 1
  resultado) e um select "🗑 Remover" na página atual. 🔥 "✨" à direita de
  quem já tem dono (2026-08-29, pedido do usuário) - `db.dono_do_
  personagem` checado por linha no `formatador_linha`; explica por que o
  item parou de sair em wish-roll (`db.wishlist_disponiveis_no_guild` já
  excluía quem tem dono, só nada avisava na listagem).
- **👥 Party** - `ViewEquipe`, SEM `/party` nem `/waifu party` (zero
  comando raiz, mesmo modelo do `Grupos` do LA). 🔥 **Redesenhado
  2026-08-29** - a versão original tinha 5 botões de slot numerado (cada
  um abrindo um select + "Esvaziar"); usuário perguntou "ter q selecionar
  1 por vez em cada slot tem alguma utilidade?" - conferi o `GruposPanel.
  cs` do LA de verdade e ele NÃO tem conceito de slot nenhum, só
  adiciona/remove de um conjunto de até 5 (`grupos_add_sel`/`grupos_
  rem_sel`). Como nada no ERIS hoje lê a POSIÇÃO da Party pra decidir
  algo (sem Torre/formação ainda), copiei o modelo do LA: 2 botões
  (➕ Adicionar - select multi-escolha até `vagas` livres; ➖ Remover -
  select multi-escolha dos membros atuais) + "🗑️ Limpar tudo". A coluna
  `posicao` do banco (`db.definir_posicao_equipe` exige um número)
  continua existindo por baixo - só parou de aparecer na UI, a próxima
  posição LIVRE é escolhida sozinha (`_adicionar_selecionados`).
  "Limpar tudo" edita a mensagem pública em vez de só confirmar ephemeral
  (pequena melhoria sobre `/party limpar`, painel já tinha a mensagem em
  mãos).
- **🛒 Loja** - `ViewLoja` com 3 ações (Comprar/Garantir/Upgrade), cada
  uma com seu próprio sub-fluxo de select(s)+confirmação, reaproveitando
  `db.comprar_personagem`/`db.definir_garantia`/`db.comprar_upgrade_
  rolls` sem mudança nenhuma. 🔥 Confirmação do Upgrade corrigida
  (2026-08-29, usuário: "n deixa claro oq faz, so o custo") - agora
  mostra o efeito (+5 rolls/ciclo PRA SEMPRE, acumulado) antes do preço,
  não só o preço sozinho.
- **🔄 Trocar** - a peça mais arriscada, como esperado. `economia.criar_e_
  avaliar_troca(guild_id, proponente_id, alvo, oferece_ids, oferece_
  wishards, pede_ids, pede_wishards)` foi EXTRAÍDO de `eris/bot.py::
  _trocar_propor` (mesmo padrão de `executar_merge`) - devolve `(status,
  mensagem, view_ou_None)`, status em "erro"/"npc_aceita"/"npc_recusada"/
  "pendente", compartilhado pelo comando antigo E pelo painel.
  🔥 **Redesenhado no mesmo dia** - a 1ª versão do painel pedia os IDs de
  personagem digitados num `discord.ui.Modal` (mesmos 4 campos de
  `/trocar propor`); usuário pediu pra trocar por dropdown ("prefiro q
  seja um dropdown q permita escrever nome para pesquisar doq passar id,
  n decoro ids" + "coloca apenas personagens possuidos no dropdwon").
  Fluxo final: `discord.ui.UserSelect` (escolher o alvo) → `_ViewEscolher
  PersonagensTroca` (select multi, `min_values=0`, populado com a coleção
  de quem PROPÕE) pro que se oferece → a MESMA classe de novo, agora
  populada com a coleção do ALVO, pro que se pede → só os 2 valores em
  WiShards continuam num Modal pequeno (`_ModalWishardsTroca`, só número -
  personagem nunca mais se digita nesse fluxo). O select nativo do
  Discord já deixa digitar pra filtrar as opções sozinho - não precisou
  nenhuma busca customizada. `Aceitar/Recusar` (`ViewTroca`) não mudou
  nada, já era botão.
  🔥 **Achado real ao testar** - `interaction.response.send_message(...,
  view=None)` QUEBRA no discord.py 2.7.1 (`view.is_finished()` chamado
  sem checar `None` primeiro) - todo caminho que pode devolver `view=None`
  (erro, NPC decidiu sozinho) precisa OMITIR o parâmetro `view`, nunca
  passar `None` explícito. Vale pra qualquer código futuro que reaproveite
  esse padrão de "função devolve view opcional".
- **🏆 Ranking** - top 25 (era top 10), sem paginação de verdade (`consulta.
  formatar_ranking` é membro+contagem, formato incompatível com
  `ViewColecao`) - 25 já cobre qualquer servidor pessoal real, não valeu a
  pena construir um pager novo só pra isso.
- `economia.executar_merge` também extraído de `eris/bot.py::_merge`,
  mesmo motivo do Trocar - devolve `(ok, mensagem, precisa_confirmar)`,
  compartilhado entre `/merge` e o botão Merge do Perfil.

Os comandos antigos equivalentes (`/colecao`, `/carteira`, `/ranking`,
`/favoritar`, `/divorciar`, `/merge`, `/wishlist`, `/party`, `/loja`,
`/trocar`, `/populares`, `/colecao_disponiveis`) **continuam existindo** -
passo 6 (removê-los) só acontece DEPOIS de validar cada botão equivalente
CLICANDO de verdade no Discord (isso exige um cliente Discord real - não
dá pra verificar clicando em botão só rodando Python). `/personagem`
(busca por texto) e `/colecao_admin` (admin-only) ficam de fora de
propósito - não são a poluição reclamada.

**Fase 2, deliberadamente NÃO nesta leva**: trazer mecânicas de JOGO novas
do LA (Torre/Arena/Bioma/Cidade/Contrato/Crafting/Treinar) - Torre
especificamente já está bloqueada por DESIGN, não por tempo (`TODO.md`:
o modelo de combate de `ERIS_sistema_colecao_wishards.md` está
subespecificado, "sem atributos individuais... sem fórmula"), e existe
uma sessão paralela com mais contexto acumulado da economia (WiShards/
Afinidade/NPCs) que devia ser coordenada antes de desenhar isso.

**3 decisões que DIVERGEM do Fable, todas explícitas do usuário:**
1. **Dono único por (guild, personagem)** - `UNIQUE` de fato via
   `colecao_propriedade`, mais perto da Mudae original. O Fable permite
   duplicatas configuráveis por guilda (`userId+characterId+guildId` como
   chave, não só `guildId+characterId`) - avaliado e rejeitado
   explicitamente pelo usuário por ser mais simples e mais fiel à Mudae.
2. **Raridade é uma característica FIXA do personagem**, não sorteada a
   cada roll. Calculada uma vez por `db.recalcular_raridade()` (percentil
   de popularidade dentro do catálogo ativo, mesmos cortes 50/30/15/4/1%
   que o `gacha.ts` do Fable usa como PROBABILIDADE de rating no momento do
   roll) - aqui o roll sorteia o TIER com esses pesos e escolhe um
   personagem já classificado nele (`eris.colecao.gacha._sortear_raridade_
   com_candidatos`), com fallback pro próximo tier mais comum se o
   sorteado não tiver candidato elegível no servidor (mesmo espírito do
   `fallbackPool()` do Fable).
3. **Catálogo de uma fonte só (get_waifu), carga única** - não AniList/
   Jikan/IGDB como o plano original queria. `github.com/JiachenRen/
   get_waifu` (`data/waifu_details.json`, Git LFS, ~94MB) tem 30.965
   personagens com nome/nome original/romanizado/imagem/descrição/série/
   popularidade (`likes`)/flag `nsfw`/tags - resolve de graça o campo
   `adult` que o plano original queria calcular por conta própria.
   Avaliado contra `anime-character-offline-database` (`arda-`, só 5.021
   personagens reais, conferido direto no `metadata.json` do repo - o
   README dele mostra um "12345" que é só exemplo ilustrativo, não o
   catálogo real) - rejeitado por ser 6x menor, apesar de ter licença
   ODbL/DbCL declarada (usuário decidiu não priorizar licença pra uso
   pessoal). **Import é upsert por `fonte_id`** (`db.importar_personagens`)
   - rodar de novo nunca duplica; não há job de sincronização contínua
   (diferente do job diário/semanal de AniList do plano original).

**NSFW ligado por padrão, desligável a qualquer momento por servidor**
(`colecao_configuracao_guild.nsfw_permitido`, default 1) - pedido explícito
do usuário ("pode incluir o NSFW mas permita desabilitar a qq momento").
Toggle é runtime (`/colecao_admin nsfw`, restrito a quem tem permissão de
administrador NAQUELE servidor - diferente de `_somente_dono`, que é dono
da Galateia; aqui faz sentido ser por servidor porque é conteúdo, não
mecânica do bot), sem precisar reiniciar o processo. 1.162 dos 30.965
personagens (3,75%) vêm marcados `nsfw=1` pela própria fonte.

**Claim atômico e cooldown preguiçoso, sem job/cron**: `db.reivindicar` usa
`INSERT ... ON CONFLICT(guild_id, personagem_id) DO NOTHING` + `rowcount`
pra decidir quem venceu a corrida (mesmo padrão do `PLANO_COLECAO_WAIFUS.md`
Seção 9). Cooldowns de roll e claim usam reset PREGUIÇOSO (`db._consumir_
recurso` - só recarrega o contador quando alguém tenta usar DEPOIS do ciclo
expirar), sem precisar de um scheduler varrendo jogador por jogador
(`PLANO_COLECAO_WAIFUS.md` Seção 10 já sugeria isso). **Claim só é
consumido se a reivindicação VENCER** (`db.claims_disponiveis` consulta sem
gastar; `db.consumir_claim` só roda depois do `INSERT` ganhar) - perder pra
outro clique não deveria gastar o único claim do ciclo de quem tentou.

**Ciclo FIXO ancorado na Época Unix, não relativo à última ação do jogador
(2026-08-29, correção pedida pelo usuário)**: a 1ª versão calculava o
próximo reset como `agora + janela_minutos` no momento em que o contador de
CADA jogador zerava - dava um horário de reset diferente pra cada um,
dependendo de quando cada um tinha rolado por último. Pedido do usuário:
"os resets tem de ser a cada hora, 1h, 2h, 3h... não 1h após interação do
usuário, vai ser fixo pra geral". `db._fim_ciclo_fixo(agora, janela_minutos)`
ancora o cálculo na meia-noite UTC de 1970-01-01 (`_EPOCA_UTC`) - como a
Época já cai em cheio, qualquer janela que divida 24h em partes iguais
(1h/2h/3h/4h/6h/8h/12h/24h) também cai em horários redondos em UTC (janela
de 1h reseta às XX:00 pra TODO MUNDO no mesmo instante). `db._consumir_
recurso` continua com o mesmo reset preguiçoso de sempre, só troca a FÓRMULA
do próximo reset - nenhuma migração de schema necessária (mesma coluna
`*_resetam_em`, só passa a guardar um valor calculado de forma diferente).

**Reconciliação de reset antigo/desalinhado (2026-08-29, mesmo dia, achado
em produção)**: reiniciar o processo com o fix acima NÃO corrige sozinho um
`*_resetam_em` que já estava salvo no banco de ANTES da correção (calculado
como "última ação + janela", quase nunca coincide com um horário redondo do
novo cronograma fixo) - reset preguiçoso só recarrega quando o valor salvo
já EXPIROU (`reset_salvo <= agora`), e um valor antigo desalinhado pode
muito bem ainda estar no futuro, só que num minuto arbitrário. Usuário
reportou exatamente isso: reiniciou esperando poder jogar "às 5h" (horário
redondo) e continuou vendo "tenta de novo em ~7 min" - o valor salvo antes
do fix apontava pra um horário que nunca ia bater com a grade nova.
`db._restantes_validos(linha, coluna_restante, coluna_reset, limite,
janela_minutos, agora)` centraliza a reconciliação: além de `reset_salvo <=
agora`, também trata como expirado quando `reset_salvo != _fim_ciclo_fixo(
agora, janela_minutos)` (ou seja, o valor salvo simplesmente não é o
horário fixo que estaria valendo agora) - recarrega o limite cheio na hora
em vez de esperar a data antiga passar sozinha. Extraído como função
compartilhada por `_consumir_recurso`, `claims_disponiveis` e
`tempo_restante` (as duas últimas ganharam `limite`/`janela_minutos` como
parâmetro novo) - antes cada uma checava a expiração à sua própria maneira,
o que deixava a mensagem de erro (`tempo_restante`) e o consumo de verdade
(`_consumir_recurso`) reconciliando o "não bate com o novo ciclo" cada uma
de um jeito (achado: só `_consumir_recurso` tinha sido corrigido na
1ª rodada, `tempo_restante`/`claims_disponiveis` continuavam usando a
checagem antiga, o que teria mascarado o self-heal com uma mensagem de
espera errada mesmo depois do roll já funcionar de novo). Sem migração de
dado nenhuma - é tudo recalculado na leitura, mesmo espírito de sempre do
reset preguiçoso.

**Cor do botão de claim condizendo com a raridade (2026-08-29, pedido do
usuário)**: o Discord só tem 4 estilos fixos de botão (`ButtonStyle.
secondary`/cinza, `.success`/verde, `.primary`/blurple, `.danger`/vermelho -
sem roxo nem dourado), então a cor exata de cada raridade (mesma paleta de
`_CORES_RARIDADE`, usada no embed) vem do EMOJI do botão
(`_EMOJI_RARIDADE = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣", 5: "🟡"}`), não só do
estilo - o estilo (`_ESTILO_BOTAO_RARIDADE`) só aproxima o mais perto
disponível (4 e 5 estrelas dividem o vermelho, mas continuam distinguíveis
pelo emoji dourado/roxo e pela contagem de estrelas no rótulo).

**Cards individuais com reação pra reivindicar, estilo Mudae (2026-08-29,
pedido do usuário)**: "quero que cada personagem seja enviada em uma
mensagem separada,e nela venha a opcao de reagir p pegar, igual no mudae,
a mensagem com os 10 botoes pode ficar numa mensagem separada no final
normalmente". `gacha.enviar_cards_individuais(canal, guild_id, resultados)`
(nova) - manda CADA personagem numa mensagem PRÓPRIA (mesmo embed de
`montar_embed`, sem view), e adiciona uma REAÇÃO (emoji colorido por
raridade, mesmo `_EMOJI_RARIDADE` do botão) só nas "livre" (`reencontro`/
`terceiro` só mostram o card, já foram resolvidos na hora do roll). A
mensagem combinada de sempre (N embeds + `ViewClaimMultiplo`, botões)
continua existindo IDÊNTICA, mandada por ÚLTIMO por quem chama - dá pros
dois jeitos de reivindicar (reação no card individual OU botão na mensagem
final) coexistirem, ambos passando pelo mesmo `db.reivindicar` atômico, o
que ganhar primeiro resolve a corrida.

🔥 **Correção (2026-08-30, achado do usuário: "Qnd coleto algum personagem
pelo emoji, ambas os bots respondem, tinha q ser so 1")** - o parágrafo
abaixo tinha uma suposição ERRADA ("cada processo só recebe evento das
próprias mensagens") - o Discord entrega `on_raw_reaction_add` pra
QUALQUER bot conectado ao canal, reagindo em QUALQUER mensagem dele, não
só nas que aquele bot específico postou. Como as instâncias "completo" e
"música" ficam no MESMO servidor (compartilhando o mesmo `pandora.db`),
as duas processavam o MESMO claim - `db.reivindicar` atômico garantia só
uma vencer a corrida, mas a instância "música" (que nem deveria participar
de Colecionador) ainda respondia com erro/duplicado mesmo perdendo.
Corrigido registrando `on_raw_reaction_add` só dentro do `if completo:`
de `eris/bot.py::iniciar_bot`, igual `on_guild_join`/`on_guild_remove`.

Registro em MEMÓRIA (`gacha._CARDS_REACAO_PENDENTES`, message_id -> {guild_
id, personagem, emoji, expira_em}) - `on_raw_reaction_add` (registrado em
`eris/bot.py::iniciar_bot`, nos DOIS papéis - GAIA e ERIS são contas de bot
SEPARADAS, cada processo só recebe evento das próprias mensagens) chama
`gacha.processar_reacao_claim(client, payload)`, que ignora silenciosamente:
reação do próprio bot, emoji que não é EXATAMENTE o de claim daquele card
específico, e card cuja `duracao_card_segundos` já expirou (limpo da
memória na hora). Reação válida chama o mesmo núcleo econômico do botão
(`_processar_claim`, extraído nesta mudança - claims_disponiveis/cooldown,
`db.reivindicar` atômico, WiShards, Afinidade, `revelar_classe`) e manda o
embed de confirmação no canal (reações não têm resposta ephemeral própria
como uma Interaction - erro de cooldown/corrida também vira mensagem
pública, `delete_after=10`).

**Confirmação de claim CONSOLIDADA numa única mensagem (mesmo pedido, 2ª
parte)**: antes eram 2 followups separados ("💰 +80 WiShards (saldo: 380)."
e "💫 A classe de X é Y!" em mensagens distintas) - usuário: "é bom deixar
claro que pegou, e a raridade da personagem. Tbm pode marcar a pessoa q
pegou e unificar tudo relevante p ela em 1 unica mensagem". `gacha.
_embed_confirmacao_claim(user, personagem, recompensa, novo_saldo, classe,
categoria_combate)` - 1 embed só, menciona quem reivindicou (`user.
mention`), raridade, WiShards (ganho + saldo) e classe/categoria (se já
revelada). `_processar_claim` recebe um hook opcional
`ao_confirmar_economia` (async) - roda logo depois da economia confirmar
(WiShards/Afinidade já creditados), ANTES de esperar `revelar_classe`
(~1-2s) - é onde o botão faz o ack visual instantâneo (desabilita/edita a
mensagem) sem esperar a GAIA responder; a reação não precisa desse hook
(não tem "visual" pra atualizar além do embed final). Testado (mocks): 7
cenários de reação (card vira pendente, emoji errado ignorado, reação do
próprio bot ignorada, reação válida reivindica de verdade + remove da
memória + manda 1 embed, card expirado ignorado e limpo) e o fluxo de
botão refatorado (ack instantâneo, embed consolidado mencionando quem
reivindicou, 2ª tentativa no botão já desabilitado continua bloqueada).

**Rolar o máximo disponível num único clique (2026-08-29, pedido do
usuário)**: "quero a opção de com 1 unico clique, rodar os maximo de
rolls disponiveis, q no caso é 50. N apenas os 10". `quantidade <= 0` em
`gacha.rolar_varios` agora é sentinela pra "tudo que sobrar no ciclo
atual" (`limite_rolls`, já soma o bônus de upgrade) - IGNORA `max_rolls_
por_comando` de propósito nesse caso, porque esse teto é uma dificuldade
POR COMANDO (evita puxada grande acidental) e pedir o máximo é uma ação
explícita, não devia ficar preso nele. `/wa`/`/ha`/`/ma quantidade:0`
expõe isso - e é o DEFAULT do parâmetro (2026-08-29, mesmo dia,
complemento do usuário: "esse quantidade tem q ser opcional, se n
colocar, manda tudo") - `/wa` sem nenhum argumento já rola o máximo, não
precisa mais digitar `quantidade:0` à mão. `quantidade` explícita (>0)
continua respeitando `max_rolls_por_comando` como sempre.
`LIMITE_TECNICO_EMBEDS_POR_MENSAGEM` (10) deixa de
ser um teto de COMANDO (não faz mais sentido - cada personagem já é uma
mensagem própria, ver "Cards individuais" acima) e vira só o tamanho de
cada LOTE: `gacha.enviar_resultados(interaction, resultados)` (nova,
substitui a lógica que estava direto em `_rolar_e_responder`) fatia
`resultados` em grupos de até 10 e manda cada grupo como cards
individuais + 1 mensagem combinada (mesmo padrão de sempre, já usado pelo
auto-colecionador) - a 1ª mensagem combinada fecha a interação
(`interaction.followup.send`, resolve o `defer()`); lotes seguintes vão
direto no canal. `/colecao_admin max_puxada` e o parâmetro `quantidade`
de `/wa`/`/ha`/`/ma` tiveram o teto duro de 10 elevado pra 1000 (só
proteção contra número absurdo - o que sobra de verdade no ciclo sempre
vence).

**`/colecao_disponiveis` - listar/filtrar/reivindicar cards ainda
pendentes (2026-08-29, pedido do usuário)**: "um comando q filtre todos
os personagens q ainda da p coletar (q no meu caso, esta configurado p
os gerados ate 1h atras n coletados) por raridade, ou ordenado por
raridade, com o botao de coletar dos 10 principais". `gacha.
personagens_pendentes(guild_id, raridade=None)` varre `_CARDS_REACAO_
PENDENTES` (mesmo registro dos cards com reação) filtrando por guild (e
por raridade, se pedido), descarta/limpa qualquer card já expirado que
encontrar no caminho, e ordena por raridade DESC. `ViewClaimPendentes`
(nova) - botão por item pros 10 PRIMEIROS da lista já ordenada/filtrada
(reaproveita `_processar_claim`, mesmo núcleo econômico do botão/reação
normais - claim daqui não rola nada novo, só resolve uma personagem que
já estava esperando). O texto da resposta lista TODAS as pendentes que
baterem o filtro (não só as 10 com botão) - útil pra ver o panorama
completo mesmo quando sobram mais de 10.
pedido do usuário)**: "coloca para a gaia e a eris tbm coletarem
personagens, cada uma roda seus 50 tiros, a gaia vai rodar sempre aos
XX:05, e apos 5min, vai escolher o de maior raridade, a eris fara o mesmo,
mas rodará aos XX:30 e escolhe aos XX:35". Módulo novo `eris/colecao/
auto_colecionador.py` - `AutoColecionador`, instanciado uma vez por
processo dentro de `on_ready` (`eris/bot.py`), usa `discord.ext.tasks.loop`
(30s, checando o minuto UTC atual contra `HORARIOS_POR_PAPEL[papel]`) pra
disparar rolar/decidir sem precisar de scheduler externo. `papel="completo"`
(conta GAIA) dispara aos `:05`/decide aos `:10`; `papel="musica"` (conta
ERIS) aos `:30`/`:35` - cada instância só sabe o horário do PRÓPRIO papel,
nunca do outro.

Roda por GUILDA (`client.guilds`). Primeira versão sorteava tudo em MEMÓRIA
e só anunciava o resultado final - **corrigido no mesmo dia** (pedido do
usuário: "os rolls q os bots fazem tem q mostrar as opcoes, igual os meus.
é literalmente rodar /wa 10 5x"): agora os 50 tiros viram **5 mensagens de
verdade** no `canal_anuncio_id` configurado (`/colecao_admin canal`) ou no
`guild.system_channel` se nenhum foi definido (sem canal nenhum disponível,
só loga no console e não rola nada) - cada lote de `TAMANHO_LOTE` (10,
mesmo `gacha.LIMITE_TECNICO_EMBEDS_POR_MENSAGEM` de sempre) manda os cards
individuais com reação (`gacha.enviar_cards_individuais`, ver "Cards
individuais com reação" acima) SEGUIDO da mesma mensagem combinada de
sempre (`gacha.montar_embed`/`gacha.ViewClaimMultiplo`) de um `/wa 10`
normal, com botão de Reivindicar de verdade - **qualquer humano pode
reagir/clicar e levar qualquer uma delas** nesse meio tempo, exatamente
como um roll comum.
`gacha.rolar_sem_cooldown` (função pública em `gacha.py`, ao lado de
`rolar_varios`) continua fazendo o sorteio em si - 50 tiros FIXOS (não
configurável, não é `max_rolls_por_comando`), sem tocar no cooldown de
ninguém (a conta do bot tem sua PRÓPRIA linha em `colecao_estado_jogador`,
mas essa linha nunca é lida/escrita por esse fluxo).

Só as personagens "livre" (têm botão) entram em `_pendentes_por_guild`
(MEMÓRIA, mesmo padrão de estado efêmero do resto do ERIS) junto com a
`view`/`índice` do card correspondente - "reencontro"/"terceiro" já foram
resolvidos na hora do roll, nunca são reivindicáveis. 5 minutos depois
(pedido do usuário: "ai da 5min p alguem tentar pegar algum, ele tira da
lista das escolhas os q ja foram pegos, e pega o mais popular"):
1. Reconsulta `db.dono_do_personagem` pra cada pendente - quem já foi
   clicado por um humano nesse meio tempo SAI da lista de escolhas.
2. Entre as que sobraram, escolhe a de MAIOR `popularidade` (não raridade -
   as duas normalmente andam juntas, mas não são a mesma coisa dentro de
   um lote de 50, e o pedido foi explicitamente por popularidade).
3. Reivindica com o mesmo `db.reivindicar` atômico de sempre (ainda
   protegido contra uma corrida de último segundo entre o passo 1 e este).
4. `ViewClaimMultiplo.marcar_reivindicada_externamente(índice, rótulo)`
   (método novo, público) desabilita/reetiqueta SÓ o botão daquela
   personagem e edita a mensagem daquele lote especificamente - os outros
   4 lotes continuam intocados, com seus botões ainda ativos pra qualquer
   humano até `duracao_card_segundos` vencer normalmente.
5. `gacha.revelar_classe` (extraído de `ViewClaimMultiplo._revelar_classe`
   antes, virou função de módulo justamente pra ser reaproveitado aqui)
   classifica se for a 1ª vez, anunciado como mensagem separada no mesmo
   canal (`view.mensagem.channel`, sem precisar reconsultar config).

Testado (mock de `discord.Client`/canal/mensagem, sem precisar de conexão
real): 5 mensagens postadas com embeds reais; um "humano" simulado
(`db.reivindicar` direto, sem passar pelo botão) rouba uma personagem antes
da decisão; a decisão automática corretamente a exclui e fica com a mais
POPULAR entre as 49 restantes; só o botão certo foi desabilitado, o resto
ficou intocado.

**`/populares` - ranking de popularidade do catálogo (2026-08-29, pedido do
usuário: "tem comando para listar personagens por popularidade?")**:
`db.personagens_por_popularidade(limite, permitir_nsfw)` - top N (padrão
50, até 200) do CATÁLOGO INTEIRO por `popularidade` (likes da fonte
get_waifu), não só quem já apareceu/foi reivindicado num servidor (decisão
explícita do usuário nas perguntas de esclarecimento), com o mesmo filtro
de NSFW dos rolls (`/colecao_admin nsfw`). Reaproveita `consulta.
ViewColecao` (paginação ◀️/▶️ já existente de `/colecao`) em vez de criar
uma view nova - `ViewColecao` ganhou um `formatador_linha` opcional
`(posição_global, personagem)` (default reaproveita `_linha_personagem`
ignorando a posição, mantém `/colecao`/wishlist idênticos a antes;
`/populares` passa `consulta.linha_populares`, que soma a posição no
ranking GLOBAL - não só da página atual - e o número de curtidas).

**Sincronização contínua do catálogo (2026-08-29)** - até aqui a importação
do get_waifu era carga ÚNICA (`eris/colecao/importar_get_waifu.py`,
precisava rodar na mão, ver TODO.md "Roadmap futuro"). Módulo novo `eris/
colecao/sincronizador.py::SincronizadorCatalogo` - `discord.ext.tasks.loop`
(1h, checando) só na instância `papel="completo"` (rodar nas duas seria
download/reimportação duplicados à toa - upsert por `fonte_id` já deixa
seguro, mas sem ganho nenhum). Frequência real é SEMANAL (pedido do
usuário: "Sincronização semanal"), decidida comparando `agora` com
`colecao_sincronizacao.ultimo_sucesso_em` (tabela nova, linha única) -
nunca dispara de novo só por causa de um restart do processo (comum nesse
ecossistema), só quando o prazo de 7 dias realmente já venceu.
`importar_get_waifu.baixar_catalogo` baixa o JSON (~94MB) em streaming pra
um arquivo `.tmp`, só troca pelo destino final (`os.replace`, atômico) se o
download inteiro funcionar - nunca deixa um catálogo pela metade no lugar
de um bom de uma sincronização anterior. Falha (rede fora, GitHub fora do
ar) é registrada em `ultimo_resultado` sem apagar `ultimo_sucesso_em` nem
derrubar o loop - só tenta de novo na próxima checagem.

**Trocas com conta de BOT são decididas na hora (mesmo pedido, 2ª parte)**:
"elas aceitam trocar se o valor oferecido for 10x oq pagaram, aceitam tanto
WiShards ou outros personagens, contanto q a soma seja superior ou igual a
10x". `eris/colecao/economia.py::avaliar_proposta_npc(proposta)` soma
`pede_wishards + valor_base das pede_personagens` (o "custo pra NPC") e
`oferece_wishards + valor_base das oferece_personagens` (o "valor
oferecido"), aceita se oferecido ≥ custo × `LIMIAR_TROCA_NPC` (10). `eris/
bot.py::_trocar_propor` detecta `membro.bot` logo depois de criar e
validar a proposta (a validação normal já garante que a conta de bot
realmente é dona do que está sendo pedido) e resolve na hora - aceita
executa `economia._executar_troca` direto (sem `ViewTroca`, sem esperar
clique - a conta de bot não ia poder clicar no próprio botão mesmo);
recusa marca a proposta como "recusada" e avisa o proponente por que. Vale
pra QUALQUER conta de bot no servidor (checagem é `membro.bot`, não uma
lista de IDs fixos) - evita hardcodar o ID de conta da GAIA/ERIS.

**Perfil "VIP fácil" (2026-08-29, pedido do usuário: "eu quero q seja tipo
um vip do mudae, ser mais fácil")** - os defaults do MVP original (10
rolls/hora, 1 claim/3h, card de 30s) eram cópia literal dos números da
Mudae free do `PLANO_COLECAO_WAIFUS.md` Seção 10, nunca uma escolha de
dificuldade. Ajustado pra:
- `rolls_por_ciclo = 50` (era 10) / `ciclo_rolls_minutos = 60` (igual).
- `claims_por_ciclo = 1` (igual) / `ciclo_claims_minutos = 60` (era 180 - 1
  claim por HORA em vez de a cada 3h).
- `duracao_card_segundos = 3600` (era 30) - o botão de Reivindicar fica
  ativo por 1h, não mais uma corrida contra o relógio.
- **"Puxada" de várias personagens num comando só** (pedido explícito:
  "permitir dar 10 pulls de 1x") - `/wa`/`/ha`/`/ma` ganharam o parâmetro
  `quantidade` (1 a `gacha.LIMITE_TECNICO_EMBEDS_POR_MENSAGEM = 10`, via
  `app_commands.Range`, mas na prática limitado ao `max_rolls_por_comando`
  configurado - ver abaixo). `gacha.rolar_varios` consome o LOTE inteiro de
  uma vez (`db.consumir_rolls`, generalização de `_consumir_recurso` com um
  parâmetro `quantidade` - nunca falha por pedir mais do que sobra no
  ciclo, entrega quantos der) e sorteia N personagens independentes (cada
  uma passa pelo próprio wish-roll/raridade, ver `_sortear_um`). A
  resposta vira UMA mensagem com até 10 embeds (limite do Discord) e
  `ViewClaimMultiplo` (um botão 💘 por personagem, numerado, até 2 linhas
  de 5) em vez da antiga `ViewClaim` de botão único.

**Toda essa dificuldade virou configurável por servidor (2026-08-29,
pedido do usuário: "o certo seria tudo q definimos ali ser configurável")**
- os números acima eram constantes fixas em `gacha.py` no commit anterior;
agora vivem em `colecao_configuracao_guild` (migração aditiva, `ALTER
TABLE ... ADD COLUMN ... DEFAULT` preenche servidores que já existiam) e são
lidos a cada roll/claim via `db.obter_configuracao_colecao(guild_id)` (com
fallback pros defaults em `db._CONFIG_COLECAO_PADRAO` quando o servidor
nunca configurou nada). Único número que CONTINUA fixo de propósito:
`gacha.LIMITE_TECNICO_EMBEDS_POR_MENSAGEM = 10` - é limite técnico do
Discord (máximo de embeds por mensagem), não dificuldade; o
`max_rolls_por_comando` configurável nunca pode passar disso.

Comandos novos em `/colecao_admin` (todos exigem permissão de administrador
NAQUELE servidor, mesma régua de `/colecao_admin nsfw`):
- `rolls <quantidade> <minutos>` / `claims <quantidade> <minutos>` -
  `db.definir_configuracao_colecao` grava os 2 campos relacionados.
- `duracao_card <segundos>` - `duracao_card_segundos`, lido de novo a cada
  `ViewClaimMultiplo.__init__` (um card aberto ANTES da mudança mantém o
  timeout com que nasceu - `discord.ui.View.timeout` é fixado na criação,
  não dá pra mudar um cronômetro já rodando).
- `max_puxada <quantidade>` - `max_rolls_por_comando`, aplicado no próximo
  `/wa`/`/ha`/`/ma` (o teto do PARÂMETRO do Discord continua sendo o
  técnico de 10; isso só reduz mais, nunca aumenta além do técnico).
- `wishlist_chance <porcentagem 0-100>` - grava `chance_wish_roll` como
  fração (`porcentagem / 100`).
- `ver` - mostra a config efetiva atual (útil justamente porque agora tem
  vários números por servidor, não um só global).

**Tela visual no Painel da GAIA (2026-08-29, pedido do usuário: "n tem uma
tela ou algo visual p configurar?")** - `/colecao_admin` continua existindo
(muda rápido de dentro do próprio Discord), mas agora também dá pra editar
pelo modal "🎴 Colecionador de Personagens" no Painel da GAIA (`ui/qt_
modais/colecao.py`, repo da GAIA), mesmo padrão do "💙 Painel Mestre do
Discord" - seletor de servidor + campos, carregamento em background com
retry. Exige 2 rotas HTTP novas em `eris/api_bridge.py` (config é POR
SERVIDOR, diferente de `/config_roteamento` que é global do bot):
- `GET /colecao_config/<guild_id>` -> `db.obter_configuracao_colecao`.
- `POST /colecao_config` (`{guild_id, campo, valor}`) -> `db.definir_
  configuracao_colecao`, devolve 400 com `{"ok": false, "erro": ...}` se
  `campo` não for um campo de config válido (mesma validação que já existia
  pra impedir SQL arbitrário via nome de coluna).
Do lado da GAIA, `integrations/eris_client.py` ganhou `obter_configuracao_
colecao(guild_id)`/`salvar_campo_configuracao_colecao(guild_id, campo,
valor)`, mesmo padrão de `obter_config_roteamento`/`salvar_campo_
roteamento` (fallback local quando o ERIS está inalcançável, nunca
confundido com "servidor respondeu isso de verdade" - mesma lição já
documentada no modal do Discord). Validado de ponta a ponta (offscreen,
`QT_QPA_PLATFORM=offscreen`): carregar servidor real, mudar 3 campos, salvar,
e confirmar direto no `eris.db` que persistiu.

**Classe da personagem - "secreta" até ser reivindicada, decidida pela GAIA
em tempo real (2026-08-29)** - pedido do usuário depois de perguntar sobre
raridade/classes: "consegue pegar 5 personagens e definir fácil classe e
raridade delas". Diferença central em relação à raridade: raridade é
PRÉ-CALCULADA em lote na importação (percentil de popularidade, sempre
existe); classe é NULL até a personagem ser reivindicada pela 1ª vez em
QUALQUER servidor (`colecao_personagens.classe`, migração aditiva) - nunca
aparece no card do roll (`gacha.montar_embed`), só depois de reivindicada
(`/colecao`, `/personagem`, `/wishlist listar`, ver `eris/colecao/
consulta.py::_linha_personagem`).

- **"O ideal não é você fazer isso, é a GAIA"** (pedido explícito do
  usuário) - o ERIS NUNCA classifica personagem sozinho. `ViewClaimMultiplo.
  _revelar_classe` (`eris/colecao/gacha.py`), chamado logo após um claim
  vencer, pede pra GAIA via webhook reverso novo (`eris.integrations.
  gaia_webhook.pedir_classe_personagem` -> `POST /eris/colecao_classificar`
  no bridge da GAIA, `integrations/iris_bridge.py`) - mesmo padrão de
  `pedir_resposta_persona`, só que síncrono/estruturado (JSON `{"classe":
  ...}`), não uma resposta de persona.
- **Taxonomia ABERTA, cresce sozinha** (pedido explícito: "não precisa
  limitar a só essas 10 classes... se tiver uma que combina mais do que as
  existentes, você adiciona na lista, tipo pirata") - `db.classes_
  existentes()` (todo o catálogo, não por servidor) é mandada junto no
  pedido; o prompt (`core.agent.turno.classificar_personagem_colecao`, repo
  da GAIA) pede pra REAPROVEITAR uma classe já usada quando encaixar, só
  inventar uma nova se nenhuma servir. Nomes CANÔNICOS sempre na forma
  masculina/genérica ("Guerreiro", nunca "Guerreira") - achado testando:
  sem essa instrução explícita, o LLM fragmentava a taxonomia por gênero
  gramatical da personagem, quebrando o reaproveitamento.
- **Classe deve ser arquétipo de RPG, não profissão/personalidade (achado
  em produção, 2026-08-29)** - usuário reportou 5 classificações erradas
  (ex.: "Maid" pra uma personagem espiã/infiltradora, "Comediante" pra uma
  carismática que anima o grupo) - profissão/cargo do dia a dia, não
  arquétipo de fantasia. Corrigido manualmente no banco (`classe`/`classe_
  exibicao`/`categoria_combate` das 5 personagens citadas) e o prompt
  ganhou uma seção "IMPORTANTE sobre o que É uma classe" com exemplos
  explícitos do que evitar ("Maid", "Atendente", "Líder", "Estudante",
  "Comediante") e como traduzir pro arquétipo certo (carismática/anima o
  grupo -> Barda; manipula/seduz -> Encantador(a); raciocínio/estratégia ->
  Sábio(a)).
- **Classe CANÔNICA x classe de EXIBIÇÃO (mesmo dia, 2ª correção)** - a
  regra "sempre forma masculina" (acima) deixava cards de personagem
  feminina artificiais ("Ai Hayasaka [Ladino]"). Usuário: "eu manteria a
  taxonomia internamente no masculino... mas separaria nome canônico de
  nome exibido... o nome exibido pode concordar com o gênero da
  personagem". Coluna nova `colecao_personagens.classe_exibicao` (migração
  aditiva) - `classe` continua canônica/masculina (usada em `classes_
  existentes()`/estatísticas, "Ladino" nunca vira duas entradas por
  gênero); `classe_exibicao` concorda com o gênero ("Ladina") e é o que
  aparece pro jogador (`consulta._linha_personagem`, mensagem de reveal em
  `gacha.revelar_classe`) - cai pra `classe` se vier vazia. O prompt da
  GAIA agora pede os DOIS nomes na mesma chamada JSON (`{"classe":
  "Ladino", "classe_exibicao": "Ladina", "categoria_combate": "Support"}`).
  Testado (LLM real): personagem feminina reaproveitando "Ladino" existente
  devolveu `classe_exibicao="Ladina"`; personagem masculina com a mesma
  classe devolveu `classe_exibicao="Ladino"` (igual à canônica, sem
  fragmentar).
- **Persistência é global e definitiva** - `db.definir_classe_personagem`
  só grava se `classe IS NULL` (1ª vez, em qualquer servidor); reivindicações
  seguintes da MESMA personagem (outro servidor, ou depois de um divórcio)
  reexibem a classe já decidida, nunca pedem de novo pra GAIA.
- **Nunca atrasa o claim** - o botão desabilita e a mensagem edita ANTES da
  chamada de LLM (1-2s); a classe chega como mensagem separada ("💫 A classe
  de X é Y!"), mesma regra de "zero espera perceptível" do resto do ERIS.
- **Achado real testando (2026-08-29)**: `MODELO_JUIZ`/`MODELO_GROQ_
  BARATO_PADRAO` (repo da GAIA, `brain_store.py`), hoje `"llama-3.1-8b-
  instant"`, está DESCOMISSIONADO pela Groq - 404 em qualquer chamada
  (confirmado via `client.models.list()`). Isso também quebra o juiz do
  Modo em Grupo (`core.agent.turno.decidir_quem_fala`, mesma constante) -
  bug PRÉ-EXISTENTE, não introduzido aqui. Decisão: `classificar_
  personagem_colecao` usa um modelo PRÓPRIO (`openai/gpt-oss-20b`, do
  catálogo atual da Groq, com `reasoning_format="hidden"` - é modelo de
  raciocínio, sem isso o `content` volta vazio), sem tocar em `MODELO_JUIZ`/
  `MODELO_GROQ_BARATO_PADRAO` - eles alimentam a cadeia de fallback da
  conversa principal também, e trocar esses às pressas sem revisar todos os
  call sites é risco desnecessário pra uma correção fora do escopo pedido.
  Registrado como pendência separada.

**Wishlist como leve viés, nunca garantia** (`PLANO_COLECAO_WAIFUS.md`
Seção 12): 20% dos rolls tentam primeiro um item da wishlist do próprio
jogador que ainda não tenha dono NESSE servidor; se não achar nada, cai pro
roll normal ponderado por raridade.

## WiShards, Afinidade e Reencontro (2026-08-29) - `ERIS_sistema_colecao_wishards.md`

Depois do MVP, o usuário trouxe um plano bem maior
(`ERIS_sistema_colecao_wishards.md`, `C:\Workspace`) cobrindo economia,
Afinidade/Soulmate, loja, upgrades, trocas, merge, classes/Party/Torre e
conquistas. Avaliado e a 1ª fatia (WiShards + claim + Afinidade/reencontro +
divórcio) foi implementada nesta mesma sessão - o resto (loja, upgrades,
trocas, merge, Torre, conquistas) fica pra depois, ver "Deliberadamente fora
do MVP" abaixo.

**Mudança de comportamento central: personagem já reivindicada volta a
poder aparecer no roll** (Seção 4 do plano - "continua podendo aparecer,
pois isso alimenta Afinidade e WiShards") - `db.candidatos_por_raridade` NÃO
exclui mais quem já tem dono nesse servidor (excluía até esta mudança).
Dono único continua valendo (`db.reivindicar` só deixa um vencer o claim),
só que agora rolar uma personagem já reivindicada é um resultado válido por
si só, resolvido logo após o sorteio por `gacha._resolver_resultado` em 3
tipos:
- **livre** - ninguém é dono ainda nesse servidor - fluxo de sempre
  (`ViewClaimMultiplo`, botão 💘 Reivindicar).
- **reencontro** - quem rolou É o dono - Afinidade **+1 até o teto de 10**
  (`db.incrementar_afinidade`), paga `valor_base × nova_afinidade` em
  WiShards NA HORA (`db.creditar_wishards`), sem precisar de nenhum clique.
- **terceiro** - outra pessoa é dona - o DONO (não quem rolou) recebe
  `valor_base × afinidade / 2` (divisão inteira), sem mudar a Afinidade;
  quem rolou não ganha nada além de ver de quem é (mostrado por menção
  `<@dono_id>`, sem precisar resolver nome de exibição via API - o cliente
  Discord já renderiza a menção sozinho).

Só personagens "livre" ganham botão em `ViewClaimMultiplo` - a View mapeia
ÍNDICE DO PERSONAGEM -> botão (`_botoes_por_indice`, não mais `self.
children[indice]`), porque numa puxada mista (algumas livres, outras já
resolvidas) os dois índices divergem assim que a 1ª personagem sem botão
aparece no meio da lista.

**Afinidade (0-10) por (guild, dono, personagem)** (`colecao_afinidade`,
Seção 7) - **0 é só o estado IMPLÍCITO** de "nunca foi sua" (sem linha na
tabela, nunca gravado), nasce em **1** no 1º claim (`db.definir_afinidade_
inicial`, `INSERT ... ON CONFLICT DO NOTHING`) e **sobrevive ao divórcio**
(só `colecao_propriedade` é apagada) - um resgate futuro da MESMA
personagem continua com o vínculo anterior, testado explicitamente
(divorciar com Afinidade 2, reivindicar nunca de novo, `definir_afinidade_
inicial` não reseta pra 1 por causa do `DO NOTHING`).

**WiShards** ("Wish Shards", nome do usuário - `colecao_wishards_saldo` +
`colecao_wishards_ledger`, Seção 6: "a economia deve usar preferencialmente
um ledger"). `db.creditar_wishards` grava os dois SEMPRE juntos, na mesma
transação - saldo é só leitura rápida, o ledger (`origem`: `claim`/
`reencontro`/`roll_terceiro`/`divorcio`, `motivo`: nome da personagem,
`referencia`: id dela) é a fonte de verdade contábil, mesmo espírito do
`currency_transactions` do `PLANO_COLECAO_WAIFUS.md` original (Seção 14).
`valor_base = raridade × 20` (`db.valor_base_wishards`, Seção 3) - não
armazenado, calculado na hora a partir da raridade (já existe, sem
redundância). Comando novo: `/carteira [membro]` mostra o saldo.

**Divórcio agora paga `valor_base × afinidade`** (Seção 9) e devolve
`(ok, recompensa)` em vez de só `bool` (`eris/bot.py::_divorciar` ajustado).

**`/colecao` mostra Afinidade** (`❤️N` ao lado de cada personagem, só quando
presente - `db.colecao_do_usuario` ganhou um `LEFT JOIN colecao_afinidade`,
`eris/colecao/consulta.py::_linha_personagem`).

**Decisão de classes revisada (2026-08-29, resolvendo a divergência com o
plano novo)**: a "classe" aberta/decidida pela GAIA (ver seção acima)
continua exatamente como estava - o plano novo queria uma lista fechada
(Tank/Fighter/Assassin/Mage/Ranger/Support) só porque a Torre precisa de
regras de restrição por andar (ex.: "máximo 1 Mage"), que não funcionam
bem contra uma taxonomia aberta. Resolvido em duas camadas, SEM
contradição: a "classe" (aberta, sabor/identidade) fica como está;
**"categoria de combate" fixa (DPS/Tank/Support)** é um atributo SEPARADO,
só usado pelas regras sistêmicas da Torre - ainda **não implementado**
(fica pra quando a fase Party/Torre chegar, ver "Deliberadamente fora do
MVP" abaixo). Restrições da Torre devem operar sobre categoria de combate
(e futuramente tags normalizadas), nunca sobre a lista de classes em si.

**Deliberadamente fora do MVP** (ver TODO.md, "Roadmap futuro" e
`ERIS_sistema_colecao_wishards.md`): categoria de combate fixa (DPS/Tank/
Support), upgrades permanentes (Seção 11 - loja/Guaranteed Roll JÁ
implementados, ver abaixo), Soulmate (moldura/título ao chegar em Afinidade
10 - hoje só fica "presa" no valor máximo de recompensa, sem nenhum efeito
cosmético), Party como equipe de gameplay, Torre PvE/auto-battler,
sinergias, Steal/roubo, conquistas, completismo/rankings avançados, eventos,
`/wg`/`/hg`/`/mg` (jogos via IGDB), séries bloqueadas por servidor
(cooldowns/duração do card/tamanho da puxada/chance de wish-roll JÁ são
configuráveis por servidor, ver acima - só séries continuam de fora).
Estado do roll/card (`gacha.ViewClaimMultiplo`) fica em MEMÓRIA, mesmo
padrão das sessões de música - não sobrevive a um restart do processo.

## Loja, Guaranteed Roll, Merge e Trocas (2026-08-29) - `ERIS_sistema_colecao_wishards.md` Seções 10-14

2ª fatia do plano maior (depois de WiShards/Afinidade/Reencontro/Divórcio
acima) - módulo novo `eris/colecao/economia.py` (loja/merge/trocas; roll/
claim continua em `gacha.py`, consulta em `consulta.py`).

**Loja (`/loja ver`/`comprar`)** - só vende personagens LIVRES nesse
servidor (`db.personagens_livres_por_raridade`, diferente de `candidatos_
por_raridade` que desde a fatia anterior NÃO filtra mais por dono - a loja
precisou de uma consulta própria). Preços fixos por raridade (`db.
PRECOS_LOJA`, Seção 10: 250/500/1.000/2.500/5.000) - "configuráveis pra
balanceamento" no plano, mas ainda não por servidor (diferente do resto da
dificuldade) - decisão consciente de escopo, não esquecimento.
`db.comprar_personagem` desconta ANTES de tentar `reivindicar`; se perder a
corrida (raro, mas testado: outra pessoa comprou/reivindicou no meio),
reembolsa na hora - nunca fica "cobrado sem receber".

**Guaranteed Roll (`/loja garantir`)** - Seção 12, preços iniciais
`db.PRECOS_GARANTIA` (500/2.000/8.000 pra ≥3★/≥4★/5★ - sem número oficial
no plano, escolhidos aqui bem acima do `valor_base` da raridade
correspondente, pra "comprar sorte" não virar atalho barato). Consumo
ÚNICO (`db.consumir_garantia`, `colecao_estado_jogador.garantia_raridade_
minima`) - vale só pro PRIMEIRO personagem sorteado no PRÓXIMO `/wa`/`/ha`/
`/ma` (mesmo numa puxada de vários, só o índice 0 recebe a garantia -
`gacha.rolar_varios`). `_sortear_raridade_com_candidatos` restringe o
sorteio do TIER aos tiers >= a garantia; se nenhum tiver candidato, cai pro
sorteio normal sem garantia (proteção contra "comprei e não aconteceu
nada"). Uma garantia PULA o wish-roll de propósito (Seção 12 não menciona
interação com wishlist - decisão: garantia paga não deveria virar uma
personagem de raridade baixa da wishlist só por sorte de 20%).

**Merge/Sacrifício (`/merge <id1..id5> [confirmar]`)** - Seção 14: 5
personagens da MESMA raridade (nunca 5⭐, não tem pra onde subir) → 1
aleatória da raridade seguinte. Simplificado em relação ao algoritmo
automático do Fable (`getSacrifices`, que escolhe sozinho quais sacrificar
entre chunks de 5) - aqui o JOGADOR escolhe os 5 IDs explicitamente, o que
já satisfaz sozinho o "nunca selecionar automaticamente" do plano (é uma
escolha explícita, não automática) e a exigência de "confirmação explícita"
pra Afinidade relevante: `confirmar:true` obrigatório se qualquer uma das 5
tiver Afinidade > 1. `db.remover_propriedade_sem_pagamento` (diferente de
`divorciar` - as 5 são CONSUMIDAS, não divorciadas, não pagam nada). A nova
personagem é sorteada entre as LIVRES da raridade seguinte (embaralha e
pega a 1ª livre - se todas estiverem ocupadas nesse servidor, avisa e não
cobra nada, já que nada foi sacrificado ainda nesse ponto do código).

**Trocas bilaterais (`/trocar propor`)** - Seção 13, `IDs separados por
vírgula` como parâmetro de texto (Discord não tem tipo nativo de lista).
**Sem reserva ativa de recursos durante a proposta** - simplificação
deliberada pra escala pessoal (o plano original sugeria reservar as
personagens ofertadas) - `economia.validar_proposta` roda TANTO na criação
QUANTO no aceite (`economia.ViewTroca`, botões Aceitar/Recusar restritos ao
`alvo_id`), nunca confiando no que a proposta dizia quando foi criada. Se a
validação falhar no aceite (ex.: uma das personagens foi divorciada nesse
meio-tempo), a proposta é cancelada com aviso, nada é executado.
`db.transferir_personagem` troca o dono direto (não é claim nem divórcio) -
**Afinidade nunca se transfere** (Seção 13): quem cede mantém o histórico
próprio intocado, quem recebe reaproveita o vínculo antigo se JÁ tinha sido
dono antes (mesma regra do resgate pós-divórcio), ou nasce em 1 se nunca
tinha sido. Testado explicitamente: A comprou uma personagem na loja
(Afinidade 1), trocou ela por outra com B, recebeu-a de volta depois - a
Afinidade permaneceu 1 (nem resetou, nem duplicou).

## Categoria de combate, Party, Vitrine, Favoritas e Upgrade de Rolls (2026-08-29)

3ª fatia do plano maior - fecha a maior parte do que era "bem especificado"
em `ERIS_sistema_colecao_wishards.md`. Deliberadamente FORA desta fatia:
Torre (combate subespecificado no próprio plano), Steal (opcional/futuro),
conquistas (sistema grande demais pra entrar de carona aqui), completismo/
rankings avançados, eventos, upgrades sem número no plano (wishlist,
claims armazenáveis, bônus de divórcio/reencontro/terceiro, desconto de
loja, "wishlist luck", rerolls, slots de vitrine extras) - ver TODO.md.

**Categoria de combate (Seção 16) - resolve a divergência de design já
registrada acima**: decidida pela GAIA JUNTO com a classe, mesma chamada de
LLM (`core.agent.turno.classificar_personagem_colecao`, repo da GAIA, agora
devolve `{"classe", "categoria_combate"}` em vez de só a classe) - evita um
2º round-trip de rede só pra decidir outra coisa sobre a mesma personagem.
Taxonomia FECHADA (DPS/Tank/Support) validada do lado da GAIA (normaliza
capitalização, cai pro default "DPS" se o LLM devolver algo fora das 3 -
testado: Makise Kurisu virou Support, Erza Scarlet virou DPS, ambos
coerentes). `eris.integrations.gaia_webhook.pedir_classe_personagem` e
`db.definir_classe_personagem` atualizados pro par completo.

**Favoritas (Seção 15)** - `colecao_favoritas`, protege contra AÇÃO
DESTRUTIVA ACIDENTAL: `/divorciar` passou a exigir `confirmar:true` se a
personagem for favorita (nunca bloqueia de vez - divorciar uma favorita é
uma escolha válida do dono, só não pode ser sem querer).

**Party e Vitrine (Seções 15/17) - mesma tabela, `tipo` distingue**
(`colecao_equipe`, até `MAX_POSICOES_EQUIPE = 5` posições cada) - evita 2
tabelas quase idênticas pra "5 slots por dono". Party ainda não tem Torre
pra jogar, mas **já protege contra Merge desde já** (`db.esta_na_party`,
bloqueio DURO em `/merge` - diferente de favorita/Afinidade alta, que só
pedem confirmação, uma personagem na Party nem passa pela checagem: "nunca
selecionar... Party" do plano é levado ao pé da letra, sem opção de
`confirmar:true` pra forçar). Vitrine é só mostruário (`/vitrine ver`
público, qualquer membro pode ver a de qualquer um).

**Upgrade permanente de rolls máximos (Seção 11)** - único upgrade do
plano com preços concretos (1.000/2.500/5.000/10.000/25.000 WiShards por
nível, `db.PRECOS_UPGRADE_ROLLS`), +5 rolls PERMANENTES por nível (até
nível 5, `db.NIVEL_MAXIMO_UPGRADE_ROLLS`) - bônus PESSOAL somado em cima do
`rolls_por_ciclo` do SERVIDOR (`eris/colecao/gacha.py::rolar_varios`),
nunca substitui a config dele. `/loja upgrade` compra o próximo nível.

**Séries bloqueadas por servidor (Seção 21, também a única pendência do
`PLANO_COLECAO_WAIFUS.md` original que faltava)** - `colecao_series_
bloqueadas`, filtro aplicado em `candidatos_por_raridade`. Comparação
case-insensitive nos dois sentidos (bloquear e desbloquear) - achado
durante o teste: sem isso, um admin digitando "one piece" não bloquearia
"One Piece" salvo no catálogo, e vice-versa. `/colecao_admin bloquear_
serie`/`desbloquear_serie`, e `/colecao_admin ver` agora lista as
bloqueadas.

**Soulmate cosmético (Seção 8) - SUBSTITUÍDO pela Prova de Soulmate de
verdade**, ver seção própria abaixo. Afinidade 10 sozinha não vira mais
Soulmate automaticamente.

## Prova de Soulmate (2026-08-29) - `ERIS_power_afinidade_soulmate_niveis.md`

Substitui o auto-flag "Afinidade 10 == Soulmate" (cosmético, seção acima)
por uma tentativa de verdade que o jogador precisa VENCER - decisão do
usuário depois de eu apontar a divergência entre o documento (Prova
explícita) e o que estava em produção (automático): "aplicar a regra nova
pra todo mundo... voltam pra 10, mas não tem nenhuma" - como nenhum
Soulmate real existia ainda em produção, não teve migração de dado, só
troca de comportamento.

**Chance/pity POR RARIDADE** (`gacha._PROVA_SOULMATE_POR_RARIDADE`,
números validados numa revisão do usuário sobre uma proposta do GPT - mais
granular que um rascunho anterior meu): chance INICIAL + incremento por
FALHA, crescendo até um pity que GARANTE sucesso:

| Raridade | Chance inicial | + por falha | Pity |
|---|---|---|---|
| ⭐ | 35% | +15pp | 5ª tentativa |
| ⭐⭐ | 25% | +10pp | 7ª |
| ⭐⭐⭐ | 15% | +7pp | 10ª |
| ⭐⭐⭐⭐ | 8% | +5pp | 14ª |
| ⭐⭐⭐⭐⭐ | 3% | +4pp | 20ª |

🔥 **O pity é um branch EXPLÍCITO** (`if tentativa_atual >= pity: sucesso
forçado`), não emerge sozinho da fórmula de chance (ex.: 5⭐ na 20ª
tentativa dá só 79% pela fórmula, não 100%) - é rede de segurança contra
azar extremo, não o caminho normal (média esperada ~2 tentativas pra 1⭐ até
~6,2 pra 5⭐). Cooldown fixo de 1h/personagem (`_PROVA_SOULMATE_COOLDOWN_
MINUTOS`, não configurável por servidor - é regra de balanceamento da
mecânica, diferente da dificuldade de roll/claim).

**Conteúdo gerado 1x pela GAIA, cacheado pra sempre** (`gacha.
obter_textos_prova_soulmate`, mesmo padrão de `revelar_classe`), via
webhook reverso `POST /eris/colecao_prova_soulmate` (espelha
`/eris/colecao_classificar` no lado da GAIA: `core.agent.turno.
gerar_prova_soulmate_personagem`, `temperature≈0.8` de propósito - mais
criativo que a classificação, que usa 0.3). Se a GAIA estiver fora do ar, a
função cai pra um texto GENÉRICO baseado no nome - a mecânica (chance/
pity/bônus) NUNCA depende da LLM responder, só a ambientação fica mais
simples.

**🔥 REDESENHO no mesmo dia, depois de testar ao vivo (feedback do usuário
sobre a Hyuga Hinata, revisando uma sugestão do GPT)**: a versão original
só tinha um "intro" narrativo seguido direto do botão "Enfrentar Prova" -
prometia "escolha a resposta que melhor demonstra compaixão", mas não
existia escolha nenhuma, só a % decidindo tudo ("faz o texto parecer
cenográfico, não uma prova de verdade"). Agora a GAIA gera uma SITUAÇÃO +
exatamente 3 OPÇÕES de resposta (`prova_soulmate_opcoes`, JSON - uma
marcada `correta` combinando com a personalidade da personagem, validado/
normalizado do lado da GAIA - taxonomia FECHADA, sempre 1 certa entre 3,
mesmo espírito de `categoria_combate`: a IA decide o CONTEÚDO, o código
garante o FORMATO). Escolher a certa dá um bônus FIXO de chance
(`gacha._BONUS_ESCOLHA_CORRETA_PROVA_SOULMATE = 0.10`) só NESSA tentativa -
nunca garante sucesso sozinho, nunca é persistido/somado à progressão base
(`tentar_prova_soulmate(..., bonus_escolha=0.0)`); o pity continua sendo um
branch separado, ignora o bônus. Isso separa 2 coisas: conhecer a
personagem influencia a tentativa, mas não elimina o elemento gacha - e
cada Soulmate testa um traço de personalidade DIFERENTE de verdade (a da
Hinata testa gentileza, por exemplo), em vez de um evento cosmético
disfarçado de escolha. `prova_soulmate_derrota` (mostrada toda tentativa
perdida) também foi encurtada no prompt - antes soava "resposta de
assistente genérico" de tanto se repetir ao longo de várias tentativas,
agora é 1 frase só, na voz da personagem, sem dar conselho.

**Schema**: `colecao_personagens` - `prova_soulmate_intro` REMOVIDA
(`ALTER TABLE ... DROP COLUMN`, SQLite 3.53 suporta desde a 3.35) e
substituída por `prova_soulmate_situacao`/`prova_soulmate_opcoes`
(JSON)/`prova_soulmate_reacao_acerto`/`prova_soulmate_reacao_erro` (+
`nome`/`descricao`/`derrota`/`vitoria`, mantidas). `db.definir_textos_
prova_soulmate` trocou o guard de cache de `WHERE prova_soulmate_nome IS
NULL` pra `WHERE prova_soulmate_opcoes IS NULL` - uma personagem testada
ANTES do redesenho (nome preenchido, opcoes NULA) se AUTO-CURA sozinha na
próxima vez que a Prova dela for aberta, sem precisar de UPDATE manual
(achado ao redesenhar: Hyuga Hinata já tinha sido testada com o schema
antigo). `colecao_afinidade` ganha `is_soulmate`/`soulmate_tentativas`/
`soulmate_ultima_tentativa_em` - `db.is_soulmate` substitui `afinidade >=
10` em TODO lugar que checava isso (`gacha._resolver_resultado`/
`montar_embed`, `consulta.linha_personagem`, `db.obter_equipe` - essa
última ganhou o JOIN com `colecao_afinidade` que não existia antes, então
Party/Vitrine nunca tinham mostrado o marcador de verdade). Emoji trocado
de `💍` pra `💞`; cor de embed EXCLUSIVA (`gacha._COR_SOULMATE =
0xFF69B4`) faz as vezes de "moldura" (ERIS usa embed puro, sem asset de
imagem renderizada pra ter uma moldura de verdade).

**UI, TUDO numa ÚNICA mensagem editada** (2026-08-29, feedback do mesmo
teste: "eu tentaria manter a Prova inteira em uma única interação/edit de
embed sempre que possível" - antes cada etapa criava uma mensagem "Só você
pode ver" nova): botão "💞 Prova de Soulmate" no painel `/waifu` -> Perfil
(`paineis.ViewPerfilAcoes`) abre um select das personagens elegíveis
(`db.personagens_prontas_para_prova` - Afinidade 10 E ainda não Soulmate,
até 25). Escolher uma EDITA essa mesma mensagem (`edit_original_response`)
pra mostrar a situação + `_ViewEscolherRespostaProva` (3 botões de
resposta); escolher uma resposta EDITA de novo (`response.edit_message`,
síncrono) pra mostrar chance base/bônus/chance final + tentativa/garantia
(ou "🌟 Garantido" se já bateu o pity) + botão único `_ViewEnfrentarProva`;
clicar "Enfrentar Prova" EDITA uma ÚLTIMA vez (`edit_original_response`)
com o resultado - vitória ou fracasso, nunca uma mensagem nova. Só a 1ª
etapa (clicar o botão do Perfil) precisa ser uma mensagem nova (é uma
interação diferente, de outro componente).

**`/colecao_admin definir_afinidade`** (2026-08-29, achado ao testar ao
vivo: "n existe ninguem com afinidade 10" - nenhuma personagem tinha
chegado nem perto de Afinidade 10 em produção ainda) - define a Afinidade
de alguém com uma personagem direto (`db.definir_afinidade_admin`,
UPSERT, 0-10), sem esperar 9 reencontros de verdade. Não mexe em
`is_soulmate`/tentativas, só a Afinidade.

**Fora desta leva (documentado, não implementado)**: sistema de "Nível de
Personagem"/Power do mesmo documento (só teria consumidor real quando a
Torre existir); decisões de Classe-vs-Categoria-de-combate na fórmula de
Power da Torre (FECHADAS nesta revisão - Categoria, não Classe, vira
restrição/composição de andar, nunca multiplicador individual); geração de
andares da Torre via IA (proposta avaliada e aprovada em princípio, mesmo
padrão "IA decide o aberto, código valida o fechado" já usado aqui);
mecânica de Cidade do LegendsAwaken (pesquisada - recursos/edifícios/
trabalhadores via atributos que personagens do ERIS ainda não têm, precisa
de decisão própria de economia antes de portar). Nome já reservado caso o
Colecionador/Torre/Cidade sejam extraídos pra um projeto próprio no futuro:
**Project PANDORA** (decisão de nomenclatura, separação em si ainda não
decidida).

## Bug real: mesma lógica duplicada em 2 lugares, corrigida só numa (2026-08-29)

Achado do usuário depois de eu ter corrigido "Puxada N/M" (ver "Colecionador
de Personagens" acima) só no roll de JOGADOR: "e os rolls dos bots ainda
estao com Puxada X/10. Vc ta ignorando alguns principios e regras de
programação. É a msm coisa, n deveria ter de corrigir em locais
diferentes". Causa raiz: `enviar_resultados` (`gacha.py`, roll de jogador)
e `_rodar_tiros_guild` (`auto_colecionador.py`, roll do bot) tinham cada
uma sua PRÓPRIA cópia do loop "dividir em lotes de até `LIMITE_TECNICO_
EMBEDS_POR_MENSAGEM` (10) pro Discord, mandar cards + botões" - a mesma
ideia escrita 2 vezes, então o fix de numeração global feito numa cópia
nunca alcançou a outra.

**Correção estrutural, não só o número**: extraído `gacha.
enviar_resultados_em_lotes(canal, guild_id, resultados, total_ciclo,
enviar_primeira_mensagem=None)` - agora a ÚNICA implementação desse loop;
`enviar_resultados` virou um wrapper fino (só resolve `total_ciclo` e como
mandar o 1º lote - `interaction.followup.send`) e `_rodar_tiros_guild`
passou a rolar os 50 de uma vez só (`rolar_sem_cooldown(..., 50, ...)`, uma
chamada em vez de 5×10) e delegar a divisão em mensagens pra mesma função
compartilhada. `TAMANHO_LOTE`/`NUMERO_LOTES` (constantes só usadas nesse
loop manual) removidas de `auto_colecionador.py` - ficaram sem uso depois
da extração, nenhuma razão pra manter código morto por precaução.

**Lição registrada pra não repetir**: quando 2 lugares fazem "a mesma
coisa" (mesmo padrão, mesma regra de negócio), a correção certa é extrair
uma função compartilhada ANTES de corrigir o bug - corrigir só onde o
bug foi reportado e deixar a 2ª cópia divergente é dívida técnica visível
na hora, não só teórica.

## Bandeja do sistema + inicialização escondida (2026-08-30)

Pedido do usuário: "n quero terminais abertos p cd bot online, oculta isso.
Cria um icone na bandeja qq coisa." - até aqui, as 2 instâncias (completo/
música) só existiam via `python -m eris.main`/`eris.main musica` digitado
direto num terminal (ver README.md, "Uso standalone"), então cada uma vivia
presa a uma janela de console aberta o tempo todo - fechar a janela por
engano derrubava o bot, e não tinha jeito de fechar/reiniciar sem matar o
processo via Gerenciador de Tarefas.

Resolvido com 2 peças, mesmo padrão já usado pela GAIA:

1. **`iniciar_eris.bat`/`iniciar_eris_oculto.vbs`** - o `.bat` sobe as 2
   instâncias via `.venv\Scripts\pythonw.exe -m eris.main`/`... musica`
   (`pythonw.exe`, não `python.exe` - sem console). O `.vbs` existe só pra
   esconder o console do PRÓPRIO `.bat` (que aparece na hora de abrir, antes
   de terminar de subir os 2 processos) - resolve o próprio caminho em tempo
   de execução (`Scripting.FileSystemObject`), igual ao
   `iniciar_galateia_oculto.vbs` da GAIA. `encerrar_eris.ps1` mata as 2
   instâncias por `CommandLine` (filtra por `Project-ERIS`/`eris\.main`,
   nunca por nome de processo sozinho - `python.exe`/`pythonw.exe` são nomes
   genéricos demais pra confiar sem isso).
2. **`eris/tray.py`** - ícone de bandeja PRÓPRIO por instância (`pystray` +
   `Pillow`, gerado em código - um círculo dourado pro papel "completo"
   (referência à Maçã Dourada da Discórdia do README) e roxo pro "música",
   só pra diferenciar de relance), com menu "Ver logs" (abre o
   `logs/AAAA-MM-DD.log` de hoje), "Reiniciar" e "Fechar". Roda numa THREAD
   daemon separada do loop asyncio do bot (`pystray` no Windows só precisa
   da própria mensagem de loop, não do event loop) - iniciado em
   `eris/main.py::main()` logo antes do `asyncio.run(bot.iniciar_bot(...))`.

**Fechar/Reiniciar precisam encerrar o bot de verdade, não só a janela do
ícone**: como o tray roda numa thread separada, `eris/tray.py` reaproveita o
MESMO padrão já usado por `eris/api_bridge.py` pra falar com o loop do bot
de fora dele - `bot.loop_atual()`/`bot.cliente_conectado()` +
`asyncio.run_coroutine_threadsafe(client.close(), loop)` - fechar o client
faz `asyncio.run(bot.iniciar_bot(...))` retornar sozinho e o processo
terminar normal. Uma rede de segurança (`threading.Timer` de 5s ->
`os._exit(0)`) força a saída mesmo assim se o bot ainda não tiver conectado
(loop inexistente) ou o `close()` travar - o usuário clicou "Fechar", o
processo tem que morrer de um jeito ou de outro. "Reiniciar" sobe um novo
processo ANTES de fechar o atual (`subprocess.Popen([sys.executable, "-m",
"eris.main", ...])` - `sys.executable` já é o `pythonw.exe` correto quando
lançado escondido, então o reinício preserva o modo sem console sozinho),
com o mesmo argumento de papel (`"musica"` ou nenhum).

Dependência opcional em espírito, mas instalada por padrão
(`pyproject.toml`) - se `pystray`/`Pillow` faltarem por algum motivo (venv
quebrada, por exemplo), `iniciar_tray` só imprime um aviso no log e o bot
segue rodando normal sem ícone, nunca derruba o processo por causa disso.

## Pendências

- **Slash commands de ação via webhook** (`/abrir`, `/jornalista`, etc.) -
  desenho fechado, implementação fora do escopo (ponto 3 acima).
- Nenhuma validação contra um servidor/bot Discord real ainda foi feita pro
  resto do ERIS (moderação/exportação/texto) - ver README.md, "Estado da
  extração". Voz por call (Conversa/Intérprete/Tutora) JÁ foi validada com
  sucesso em 2026-08-25 (ver TODO.md, bloqueio DAVE resolvido) - Modo
  Música ainda não (playback numa call real, ver TODO.md).
- **Colecionador de Personagens** - EXTRAÍDO pro [Project PANDORA](../Project-PANDORA)
  (2026-08-29, ver seção acima) - pendências de validação do cutover em si
  (testar cada fluxo ao vivo depois da mudança de repositório) ficam
  registradas no `TODO.md` do PANDORA, não mais aqui.
