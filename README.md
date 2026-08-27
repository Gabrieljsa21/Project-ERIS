# Project ERIS

Bot de Discord da GAIA - conexão, segurança, mensagens, moderação,
exportação e voz (como transporte). Processo próprio, **sem interface
gráfica** - só uma ponte HTTP; quem decide O QUE a persona responde é
sempre a [GAIA](../Project%20G.A.I.A) (assistente pessoal do mesmo autor),
consultada por um webhook reverso. O ERIS nunca gera conteúdo - só executa
a operação dentro do Discord.

Extraído da GAIA em 2026-08-24 (`features/discord_presence/discord_bot.py`,
`integrations/discord/discord_exportador.py`,
`integrations/discord/discord_voz_nativa.py` - ver histórico completo em
`Project G.A.I.A/assistant/docs/FUNCIONALIDADES.md`/`CHANGELOG.md`).
Arquitetura completa e decisões de design em [`ARQUITETURA.md`](ARQUITETURA.md).

## A origem do nome

Éris, deusa grega da discórdia (Maçã Dourada, Julgamento de Páris) - além da
mitologia, o trocadilho literal Eris → discórdia → Discord. Símbolo: a Maçã
Dourada da Discórdia.

## O contrato: funciona sozinho, ganha mais com a GAIA

Igual ao [Project ARGUS](../Project-ARGUS) no espírito (mesmo que o
mecanismo de integração seja diferente - ver ARQUITETURA.md), o ERIS
standalone já é um bot funcional de verdade: conecta, modera (kick/ban/
timeout/canal/cargo), exporta canal pra JSON, bloqueia bot/webhook, aplica
rate limit - tudo isso sem depender da GAIA. Quando a GAIA está de pé, ele
ganha o que só ela pode dar: resposta de conversa (DM, menção, canal de
servidor). Se a GAIA estiver fora do ar, quem mandar mensagem recebe um
aviso claro em vez de silêncio.

## Uso standalone

```bash
uv venv
uv pip install -e .
python -m eris.main
```

Precisa de `DISCORD_BOT_TOKEN` no `.env` (ver `.env.example`) - sem ele, o
processo encerra na hora com uma mensagem clara. `DISCORD_OWNER_IDS` é só
bootstrap da 1ª execução (a lista real, com nome + toggle por conta, é
editada depois no Painel da GAIA ou nas rotas HTTP - persiste em
`data/eris.db`, SQLite).

Diferente do HESTIA (sem loop próprio): o ERIS tem vida própria de verdade -
a conexão com o Discord fica de pé mesmo com a GAIA fechada, respondendo
moderação/exportação. Só a conversa (que depende de conteúdo) fica
indisponível nesse caso.

## Integração com a GAIA

`integrations/eris_client.py` (repo da GAIA) fala com a ponte HTTP daqui -
usado pelo Agendador Diário/monitoramentos (entrega de mensagem proativa) e
pelo Painel (CRUD de donos/config de roteamento, lista de servidores,
exportação). Na direção contrária, o ERIS pede conteúdo pra GAIA via
`eris/integrations/gaia_webhook.py` (`POST /eris/mensagem` no bridge da
GAIA, porta 8766) toda vez que uma mensagem passa pelo filtro local de
roteamento - ver `eris/core/seguranca.py` pro contrato completo e
`eris/api_bridge.py` pro HTTP completo.

## Modo Conversa, Modo Intérprete e Modo Tutora por voz (migrados em 2026-08-25)

`/conversar entrar`/`sair`, `/interprete entrar`/`sair` e `/tutora
entrar`/`sair` (também por menção - "@Gala entra"/"conversa" pro Modo
Conversa, "@Gala traduz" pro Intérprete, "@Gala sai" pra qualquer um dos
três) - o ERIS entra na call, captura o áudio de cada participante até a
pausa (`eris/core/voz_captura.py`, RMS) e manda pra GAIA em turnos
(`eris/core/voz_call.py` + `eris/integrations/gaia_webhook.py`); a GAIA
continua dona de STT/LLM/TTS (transcrição, tradução ou resposta, síntese) e
devolve o caminho local do áudio pra tocar na call. Modo Conversa é
bate-papo comum, sem exigir nada antes; Tutora por voz exige uma sessão de
texto já iniciada (`/iniciar_tutora <idioma>`, por DM/menção) - o comando de
voz só entra na call, não inicia a sessão.

## Modo Música (2026-08-25 - substitui o Jockie Music)

`/musica tocar`, `/musica pular`, `/musica pausar`, `/musica continuar`,
`/musica fila`, `/musica aprovadas`, `/musica desaprovadas`, `/musica parar`,
`/musica dj_automatico` - toca áudio de verdade numa call de voz (busca no
YouTube via `yt-dlp`, mesma técnica usada por praticamente todo bot de
música de Discord - zona cinzenta de ToS conhecida). `/musica tocar <busca>`
e like/dislike continuam abertos a qualquer membro do servidor (feature
social); pular/pausar/continuar/parar/dj_automatico ficam restritos a quem
INICIOU a sessão (2026-08-26, resolvendo a fronteira entre "social" e
"precisa de um dono"). `/musica tocar` SEM busca toca a lista de aprovadas
de quem chamou até esgotar. Quando a fila esvazia com "DJ automático"
ligado (padrão), o ERIS pede pro [Project ECHO](../../Project-ECHO) (via
webhook reverso pra GAIA) uma sugestão de próxima música "na mesma vibe" da
que acabou de tocar - nunca repete o que já tocou NESTA sessão, nem o que
já foi apresentado ALGUMA vez pra essa pessoa (pool do ECHO).

🔥 **Buffer em 3 camadas (2026-08-26)** - mantém sempre 20-50 identidades já
reservadas do pool do ECHO e 5-10 streams JÁ resolvidos no YouTube,
reabastecidos em background - a troca de música não espera rede nenhuma no
caminho normal. Ver "Buffer em 3 camadas" em `ARQUITETURA.md`.

**`/caos` (2026-08-26)** - mesma call, sem pedir NADA antes: entra sozinha
e já toca algo baseado só no seu perfil/histórico musical (pede pro ECHO
uma sugestão de partida sem faixa/artista/gênero de semente), depois
continua na mesma vibe automaticamente igual o DJ automático de sempre.
Funciona mesmo com perfil totalmente vazio (cai pro que está em alta).

Toda mensagem de "🎵 Tocando agora" vem com botões **⏯️ pausar/retomar** /
**⏭️ pular** / **👍 like** / **👎 dislike** / **▶️ tocar de novo** /
**📋 fila** (nessa ordem). ⏯️/⏭️ são restritos a quem iniciou a sessão
(controle de reprodução); like/dislike/▶️/📋 são abertos a qualquer membro
(like/dislike ajustam o perfil musical de QUEM CLICOU no ECHO - peso de
gênero, incremental, cada pessoa tem o próprio). ▶️ reenfileira a MESMA
faixa dessa mensagem - útil pra voltar numa música de antes na sessão,
basta rolar até a mensagem dela no canal. A linha do anúncio mostra
"(👍)"/"(👎)" quando a faixa já foi avaliada antes por quem iniciou a
sessão.

Mutuamente exclusivo com Conversa/Intérprete/Tutora DENTRO de uma mesma
instância (Discord só permite 1 conexão de voz por conta de bot por
servidor - ver `eris/core/musica.py`). Pra tocar música e conversar/traduzir
ao mesmo tempo no MESMO canal, suba uma 2ª instância dedicada:

```bash
python -m eris.main musica
```

Precisa de `DISCORD_BOT_TOKEN` (bot Discord PRÓPRIO, aplicação separada) em
`.env.musica` (ver `.env.musica.example`) - sem o argumento `musica`, sobe
o papel "completo" de sempre, lendo `.env`. A instância "musica" só
registra `/musica`/`/caos` (sem moderação/texto livre/`eris.db`) - ver
"Múltiplas instâncias" em `ARQUITETURA.md`.

## Estado da extração (2026-08-24/25)

Conexão, segurança (donos, rate limit, filtro de roteamento), mensagens
(DM/canal/categoria/anexos/mensagem de voz nativa), exportação, moderação
(membro/mensagem/canal/cargo, tudo novo, nunca existiu na GAIA) completos
e com sintaxe/import verificados. **Ainda não validado contra um servidor
Discord real** - antes de confiar no dia a dia, testar: conectar com um
token real, uma conversa por DM de ponta a ponta, um comando de
moderação, uma exportação de canal.

**Voz na call (Conversa/Intérprete/Tutora) validada em 2026-08-25 e
BLOQUEADA** - a Gala entra na call e fala normalmente, mas não escuta
nada: o Discord tornou obrigatória a criptografia ponta a ponta (DAVE) pra
toda call de voz desde março de 2026, e a lib que usamos pra RECEBER
áudio (`discord-ext-voice-recv`) ainda não sabe decodificar isso (issue
aberta no repo dela, sem previsão). Não é bug nosso - ver TODO.md pro
detalhe completo com fontes.
