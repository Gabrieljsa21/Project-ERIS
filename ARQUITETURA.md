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
  (cache de guilds, usa `db`) só existem no papel "completo". `/musica` e
  `on_voice_state_update` (sair sozinho de call vazia) valem pros dois -
  este último já era agnóstico de papel, checa `voz_call.canal_ativo` OU
  `musica.canal_ativo`.
- **Testado com o token real do usuário (2026-08-26)**: `python -m
  eris.main musica` conecta como `ERIS#0983`, sincroniza só 1 grupo de
  slash command (`/musica`), sem tocar no `eris.db` nem abrir a porta
  8772 - validado lendo `logs/2026-08-26.log` (processo derrubado logo
  depois, teste isolado, sem entrar numa call de verdade ainda).
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
