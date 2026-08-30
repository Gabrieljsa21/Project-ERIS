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

**Em produção (2026-08-30), sem terminal aberto**: rode
`iniciar_eris_oculto.vbs` (ou aponte um atalho da área de trabalho pra ele) -
sobe as 2 instâncias (completo + música) escondidas via `pythonw.exe`, cada
uma supervisionada por `eris/watchdog.py` (reinicia sozinho com backoff se
cair sem avisar). Controle por **1 ícone só**, na instância "completo"
(Ver logs/Reiniciar/Fechar + Reiniciar música/Fechar música à distância) -
ver `eris/tray.py`. `encerrar_eris.ps1` encerra as 2 de emergência, se a
bandeja não estiver acessível. Ver "Bandeja do sistema + inicialização
escondida + watchdog" em `ARQUITETURA.md`.

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
Chamado de novo com o ERIS já na call (mesmo pausado), só avisa que já tá
lá em vez de enfileirar mais uma sugestão (2026-08-28).

**Restrito a 1 canal por servidor, se configurado (2026-08-29)** -
`/musica_admin canal <#canal>` (admin do servidor) limita `/musica
tocar/pular/pausar/continuar/fila/parar/dj_automatico` e `/caos` a um único
canal de texto (`/musica_admin ver` mostra a config atual; `/musica_admin
canal` sem informar nenhum canal remove a restrição). `/musica
aprovadas`/`desaprovadas` continuam funcionando de qualquer canal - são
consulta pessoal, não geram barulho.

Toda mensagem de "🎵 Tocando agora" vem com botões **⏯️ pausar/retomar** /
**⏭️ pular** / **👍 like** / **👎 dislike** / **▶️ tocar de novo** /
**📋 fila** (nessa ordem). ⏯️/⏭️ são restritos a quem iniciou a sessão
(controle de reprodução); like/dislike/▶️/📋 são abertos a qualquer membro
(like/dislike ajustam o perfil musical de QUEM CLICOU no ECHO - peso de
gênero, incremental, cada pessoa tem o próprio). ▶️ reenfileira a MESMA
faixa dessa mensagem - útil pra voltar numa música de antes na sessão,
basta rolar até a mensagem dela no canal. A linha do anúncio mostra
"(👍)"/"(👎)" quando a faixa já foi avaliada antes por quem iniciou a
sessão. 👎 já pula pra próxima faixa junto (2026-08-29) quando a faixa
desaprovada é a que está tocando naquele momento - numa mensagem antiga
(rolando o histórico), continua só registrando o voto. O VOTO continua
aberto a qualquer membro, mas o skip só dispara se quem clicou foi quem
iniciou a sessão (mesma régua de ⏭️).

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

## Colecionador de Personagens (2026-08-29 - inspirado na Mudae)

🔥 **Código EXTRAÍDO pro [Project PANDORA](../Project-PANDORA) (2026-08-29,
mesmo dia)** - biblioteca Python local (não satélite HTTP, ver
`ARQUITETURA.md` do PANDORA pro porquê), importada direto pelo `eris/bot.py`.
Os comandos/painéis abaixo continuam funcionando EXATAMENTE igual do ponto
de vista de quem usa o Discord - só o código por trás mudou de repositório.

🔥 **`/waifu` (2026-08-29)** - painel-raiz com botões, pensado pra reduzir a
poluição de comando (chegou a 25 raiz no seletor `/`), inspirado no
LegendsAwaken (bot próprio do usuário, C#/Discord.Net - 1 comando por
sistema, navegação por botão em vez de subcomando). Cobre **🎲 Rolar, 📚
Coleção** (select Minha coleção/🔥 Populares/🎯 Disponíveis pra pegar), **👤
Perfil** (carteira+ranking+favoritas, com Favoritar/Divorciar/Merge), **⭐
Wishlist** (paginada, Modal de adicionar), **👥 Party** (só por botão, sem
comando `/party`), **🛒 Loja**, **🔄 Trocar** (UserSelect + Modal) e **🏆
Ranking**. Os comandos abaixo (`/colecao`, `/carteira`, `/ranking`,
`/favoritar`, `/divorciar`, `/merge`, `/wishlist`, `/party`, `/loja`,
`/trocar`, `/populares`, `/colecao_disponiveis`) continuam existindo até
cada botão equivalente ser validado clicando de verdade no Discord. Ver
"Painel `/waifu`" em `ARQUITETURA.md` pro detalhe completo.

`/wa` (feminino anime/mangá), `/ha` (masculino), `/ma` (qualquer gênero) -
rola personagem(ns) do catálogo (30.965 personagens importados do
[get_waifu](https://github.com/JiachenRen/get_waifu), sincronizado
sozinho 1x por semana). Cada personagem sai numa mensagem PRÓPRIA
(estilo Mudae), com uma REAÇÃO pra reivindicar (emoji colorido por
raridade - ⚪ comum a 🟡 lendária); depois de todas, uma última mensagem
combinada (mesmos cards + botão de Reivindicar por personagem, ativo por
1h) dá uma 2ª forma de pegar a mesma personagem - o que resolver primeiro
(reação ou clique) ganha a corrida. Aceitam `quantidade` pra "puxar"
várias de uma vez, em lotes de 10 (cards individuais + mensagem combinada
por lote) - `quantidade:0` (ou sem informar nada - é o DEFAULT) puxa TUDO
que sobrar no ciclo atual de uma vez (pedido do usuário: "com 1 unico
clique, rodar os maximo de rolls disponiveis... esse quantidade tem q ser
opcional, se n colocar, manda tudo"). `/colecao_disponiveis [raridade]`
lista os cards ainda
disponíveis pra reivindicar (não expirados), ordenados por raridade, com
botão de claim pros 10 primeiros. `/colecao [membro]` mostra a coleção
(paginada) de você ou de outra pessoa nesse servidor; `/personagem
<nome>` busca no catálogo; `/populares [quantidade]` lista o top do
catálogo INTEIRO por popularidade (paginado); `/divorciar <#id>` libera
uma personagem;
`/ranking` mostra quem tem mais personagens no servidor; `/wishlist
adicionar/remover/listar`
aumenta moderadamente a chance de uma personagem específica aparecer
(nunca garante). Dono único por personagem em cada servidor, mas ela
CONTINUA aparecendo no roll depois de reivindicada - rolar a sua própria é
um "reencontro" (Afinidade sobe, paga WiShards na hora); rolar a de outra
pessoa paga metade desse valor pro dono de verdade.

**WiShards** é a moeda do Colecionador - `/carteira [membro]` mostra o
saldo. Fontes hoje: claim inicial, reencontro (rolar sua própria
personagem, quanto maior a Afinidade mais paga) e divórcio (`valor_base ×
afinidade`). **Afinidade** (0-10, `❤️N` em `/colecao`) nasce em 1 no claim,
sobe reencontrando, e sobrevive a um divórcio - resgatar a mesma personagem
depois mantém o vínculo.

Gastos: `/loja ver <raridade>`/`comprar <#id>` (só personagens livres,
preço fixo por raridade); `/loja garantir <raridade>` garante que seu
PRÓXIMO roll saia com pelo menos essa raridade; `/loja upgrade` compra
rolls máximos permanentes (+5 por nível, até 5 níveis). `/merge <5 #ids>`
sacrifica 5 personagens da mesma raridade por 1 aleatória da raridade
seguinte (precisa de `confirmar:true` se alguma tiver Afinidade > 1, e
nunca deixa sacrificar quem está na sua Party). `/trocar propor <membro>
[personagens/WiShards dos dois lados]` propõe uma troca bilateral - a
outra pessoa aceita ou recusa com um botão (exceto se `<membro>` for uma
conta de BOT - GAIA/ERIS decidem na hora, ver "Auto-colecionador" abaixo).

Cada personagem também tem uma **classe** (Guerreiro, Mago, etc.) e uma
**categoria de combate** (DPS/Tank/Support) - ambas "secretas" até ser
reivindicada pela 1ª vez em qualquer servidor, decididas juntas pela GAIA
(LLM); a classe usa uma taxonomia que cresce sozinha (reaproveita uma já
usada quando encaixa, inventa uma nova quando não), a categoria é sempre
uma das 3. Aparece como mensagem separada logo depois do claim, e a partir
daí em `/colecao`/`/personagem`/`/wishlist listar`.

`/favoritar <#id>` protege uma personagem contra divórcio acidental (exige
confirmação, nunca bloqueia de vez). `/party ver`/`definir`/`remover`/
`limpar` monta uma equipe de até 5 (ainda sem combate pra usar, mas já
protegida contra Merge - nunca é possível sacrificar quem está lá).
`/vitrine` é a mesma mecânica, só como mostruário público. Afinidade 10
NÃO vira Soulmate sozinha mais (2026-08-29) - habilita o botão "💞 Prova de
Soulmate" no painel `/waifu` -> Perfil, uma tentativa (1x/hora por
personagem) com chance por raridade que cresce a cada falha até garantir;
só depois de VENCER a personagem ganha o marcador 💞 de verdade.

Toda a dificuldade é configurável por servidor via `/colecao_admin`
(precisa ser administrador do servidor) - `nsfw <true/false>` (vem ligado
por padrão), `rolls <quantidade> <minutos>`, `claims <quantidade>
<minutos>`, `duracao_card <segundos>`, `max_puxada <quantidade>`,
`wishlist_chance <porcentagem>`, `canal <#canal>` (onde o auto-colecionador
anuncia, ver abaixo) e `ver` (mostra a config atual). Padrão "VIP fácil"
pra servidor que nunca configurou nada: 50 rolls/hora, 1 claim/hora, card
ativo por 1h, até 10 personagens por puxada, 20% de chance de wish-roll. O
reset de rolls/claims acontece num horário FIXO compartilhado por todo
mundo (ex.: janela de 1h reseta às XX:00 pra todo mundo ao mesmo tempo),
não mais "1h depois que cada um rolou por último". Arquitetura completa
(raridade por percentil, claim atômico, cooldown sem job, schema da
config) em `ARQUITETURA.md`.

**Auto-colecionador**: GAIA e ERIS também jogam, cada uma com seu próprio
horário FIXO - GAIA (papel "completo") rola 50 personagens às XX:05 (5
lotes de 10, postados como cards DE VERDADE - iguais a um `/wa 10`,
mensagem individual + reação por personagem, mais a mensagem combinada com
botão de Reivindicar) e às XX:10 fica com
a mais POPULAR entre as que sobraram sem dono; ERIS (papel "musica") faz o
mesmo às XX:30/XX:35. Não usa cooldown nem conta com `max_puxada` (número
sempre fixo em 50). Rola no canal configurado em `/colecao_admin canal`
(ou no canal padrão do servidor, se nenhum foi definido). Personagens de
uma conta de bot também entram no jogo normal -
podem ser roladas por humanos ("de terceiro"), reivindicadas de volta se
divorciarem, e trocadas: `/trocar propor` com uma conta de bot como alvo é
decidido na hora (nunca fica pendente) - ela topa se o valor total
oferecido (WiShards + personagens) for pelo menos 10x o valor do que está
sendo pedido dela.

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
