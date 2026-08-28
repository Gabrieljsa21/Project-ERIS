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
desaprovadas` (novos) listam (até 25) o que cada pessoa já avaliou.

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

## Bug real: `/caos` depois de `/musica tocar` (aprovadas) ficava preso no modo errado (2026-08-27)

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

## Pendências

- **Slash commands de ação via webhook** (`/abrir`, `/jornalista`, etc.) -
  desenho fechado, implementação fora do escopo (ponto 3 acima).
- Nenhuma validação contra um servidor/bot Discord real ainda foi feita pro
  resto do ERIS (moderação/exportação/texto) - ver README.md, "Estado da
  extração". Voz por call (Conversa/Intérprete/Tutora) JÁ foi validada com
  sucesso em 2026-08-25 (ver TODO.md, bloqueio DAVE resolvido) - Modo
  Música ainda não (playback numa call real, ver TODO.md).
