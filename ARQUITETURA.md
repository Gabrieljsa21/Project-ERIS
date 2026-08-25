# Arquitetura do Project-ERIS

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
| Voz (Intérprete/Tutora) | ✅ conexão/captura/playback (`eris.core.voz_call`) | ✅ transcrição/tradução/resposta/síntese via webhook |
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

## Sem conflito com o Project ECHO

Ao planejar o roadmap futuro, foi levantada a dúvida se o Modo DJ (Project
ECHO, ainda como ideia registrada) teria alguma sobreposição com a conexão
de voz do ERIS. Confirmado que não: o ECHO não toca canal de voz do Discord
nenhuma vez na especificação (`Project ECHO.md`) - a reprodução de música
acontece via provedor de streaming (Spotify/YouTube Music), nunca numa call
que o bot entra. Se o Radar Musical for entregue por Discord um dia, é só
mais uma entrega de notificação de texto, sem peça nova pro ERIS.

## Pendências

- **Slash commands de ação via webhook** (`/abrir`, `/jornalista`, etc.) -
  desenho fechado, implementação fora do escopo (ponto 3 acima).
- Nenhuma validação contra um servidor/bot Discord real ainda foi feita -
  ver README.md, "Estado da extração" (agora vale também pro Intérprete/
  Tutora por voz: sintaxe/imports verificados, mas nenhuma call de voz de
  verdade foi testada).
