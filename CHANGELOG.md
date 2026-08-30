# Changelog

Histórico de alto nível do que muda no ERIS, por versão. Ver
`ARQUITETURA.md` pro detalhe técnico completo.

## [Unreleased]

### Removido
- **Colecionador de Personagens EXTRAÍDO pro [Project PANDORA](../Project-PANDORA) (2026-08-29)** - `eris/colecao/*` (~2.780 linhas: `gacha.py`/`paineis.py`/`consulta.py`/`economia.py`/`auto_colecionador.py`/`sincronizador.py`/`importar_get_waifu.py`) e as 14 tabelas `colecao_*` de `eris/db.py` (de 1.773 pra 219 linhas) foram removidos - o Colecionador já era a MAIORIA do peso do ERIS, e o usuário perguntou se valia separar num projeto próprio. Diferente do padrão de satélite HTTP (MOIRAI/ECHO) - REJEITADO de propósito, já que todo clique de roll/claim/troca cai no orçamento de 3s do Discord (2 bugs reais de timeout corrigidos nesta mesma sessão) - o PANDORA é uma BIBLIOTECA Python local (dependência de path via `uv`, `[tool.uv.sources]`), importada direto pelo `eris/bot.py`, zero round-trip de rede. Banco de dado migrado (`data/eris.db` -> `Project-PANDORA/data/pandora.db`, script `migrar_de_eris.py`, 30.965 personagens + todo o resto sem perda). Comandos/painéis (`/waifu`, `/colecao_admin`, etc.) continuam funcionando EXATAMENTE igual do ponto de vista de quem usa o Discord - só o código por trás mudou de repositório. Ver "Extraído pro Project PANDORA" em `ARQUITETURA.md`.

### Corrigido
- **Claim por emoji fazia AMBAS as instâncias (completo + música) responderem (2026-08-30, achado do usuário: "Qnd coleto algum personagem pelo emoji, ambas os bots respondem, tinha q ser so 1")** - `on_raw_reaction_add` era registrado SEM condição de papel, com um comentário que assumia (errado) que "cada processo só recebe evento das próprias mensagens" - o Discord na verdade entrega esse evento pra QUALQUER bot conectado ao canal, reagindo em QUALQUER mensagem dele. Como as 2 instâncias ficam no MESMO servidor/banco, as duas processavam o MESMO claim - `db.reivindicar` atômico garantia só uma vencer a corrida, mas a instância "música" (que nem deveria participar de Colecionador) ainda respondia com erro/duplicado mesmo perdendo. Corrigido registrando o handler só dentro do `if completo:`, mesmo padrão de `on_guild_join`/`on_guild_remove`.
- **Respostas de música sempre no canal configurado, nunca no de onde o comando foi digitado (2026-08-30, pedido do usuário: "quero q tudo relacionado a musica so seja respondido no canal de musica definido, independente se mandar o comando em outro canal")** - a restrição antiga (`_no_canal_certo_de_musica`) só BLOQUEAVA comandos fora de 1 canal configurável; removida e substituída por `_canal_anuncio_musica`/`_responder_no_canal_de_musica` - agora `/musica <ação>`/`/caos` funcionam de QUALQUER canal, mas a resposta pública (Tocando/pular/pausar/continuar/parar/dj_automatico/fila) sempre sai no canal configurado via `/musica canal` - a interação em si vira um ack ephemeral silencioso quando precisa redirecionar (não dá pra fazer uma resposta de interação aparecer num canal diferente de onde ela nasceu). `_obter_ou_criar_sessao` também passou a atualizar `sessao.text_channel` toda vez que um comando roda numa sessão já ativa (antes só gravava na criação, então uma sessão antiga continuava anunciando pro canal de quando começou). Mesmo fix aplicado ao Colecionador (Project-PANDORA, ver `ARQUITETURA.md` de lá).
- **`/colecao_admin dar_personagem` não classificava a personagem (2026-08-29, achado do usuário: "qnd vc da personagem p alguem, n faz os esquemas de por classe... Tem de seguir o msm fluxo de coletar")** - a versão original vivia em `db.py` e só fazia claim+WiShards+Afinidade, sem chamar `revelar_classe` (pede a classe/categoria de combate pra GAIA). Movida pra `gacha.atribuir_personagem_admin` (async, mesmo módulo de `_processar_claim`) - agora reaproveita o MESMO fluxo do claim normal (economia + revelação de classe + embed de confirmação), com uma única diferença de propósito: NÃO desconta o claim de quem recebe (usuário: "soq sem descontar claim" - é presente do admin, não devia gastar a cota normal de ninguém). Comando ganhou `defer()` antes de chamar (mesmo cuidado do bug de timeout - `revelar_classe` pede a GAIA por HTTP, ~1-2s).
- **`/colecao_disponiveis` não batia com o pedido original (2026-08-29, usuário: "esse comando é p listar apenas os personagens n coletados e rolados na ultima hora, e trazer ordenado por popularidade... e eu pedi p retornar apenas os 10 melhores")** - a versão anterior ordenava por RARIDADE e listava TODOS os pendentes (até ~150 com 3 pessoas rolando 50/hora cada), com botão só nos 10 primeiros - descasado do pedido e é a mesma causa do estouro de 2000 caracteres corrigido antes. `gacha.personagens_pendentes` ganhou `limite` (opcional) e passou a ordenar por POPULARIDADE DESC; `/colecao_disponiveis` chama com `limite=10` - agora corta na FONTE, nunca lista mais que 10. O painel `/waifu` -> Coleção -> Disponíveis continua sem `limite` (pode paginar por cima de tudo).
- **Mensagem de botões do roll repetia os cards já mostrados individualmente (2026-08-29, usuário: "ta repetindo os cards de todos os personagens, sendo q eles ja foram enviados 1 por msg antes")** - `gacha.enviar_resultados` (usado por `/wa`/`/ha`/`/ma`) e `auto_colecionador.py` mandavam os MESMOS embeds de novo na mensagem de botões, além dos cards individuais com reação que já tinham acabado de sair. Removidos os embeds dessa mensagem - só sobra o texto "👇 Ou reivindique por aqui:" + os botões (o rótulo de cada botão já mostra o nome).
- **Causa raiz real do "sumiço" de rolls: timeout de 3s do Discord CONSUMIA o ciclo sem mostrar nada (2026-08-29, achado em produção pela 2ª vez)** - usuário relatou "aplicativo não respondeu" na 1ª tentativa de `/wa`, "já usei os 50" na 2ª. `_rolar_e_responder` (`eris/bot.py`) e `ViewHubWaifu._rolar` (`eris/colecao/paineis.py`) chamavam `gacha.rolar_varios` (síncrono) ANTES de `interaction.response.defer()` - o comentário antigo dizia que o defer protegia "puxadas grandes", mas ele vinha DEPOIS da chamada lenta, então não protegia nada. Medido: 50 chamadas de `db.candidatos_por_raridade` sozinhas já levam **4.8s** - bem acima dos 3s que o Discord dá pra um ACK. Como `db.consumir_rolls` acontece bem no INÍCIO de `rolar_varios`, o timeout matava a interação DEPOIS do ciclo já ter sido gasto, sem nenhum resultado visível - exatamente o padrão relatado (1ª tentativa "não respondeu", 2ª já "sem rolls"). Corrigido: `defer()` movido pra ANTES da chamada, `rolar_varios` agora roda em `asyncio.to_thread` (evita travar o loop assíncrono inteiro durante uma puxada de 50), e o caminho "sem rolls" passou a usar `followup.send` (já que a resposta inicial virou sempre um defer). Rolls do usuário resetados manualmente de novo depois do fix.
- **"🔄 Trocar" pedia IDs digitados - virou dropdown só com personagens possuídas (2026-08-29, pedido do usuário)** - "prefiro q seja um dropdown q permita escrever nome para pesquisar doq passar id, n decoro ids" + "coloca apenas personagens possuidos no dropdwon". O Modal original (`_ModalPropostaTroca`) pedia IDs separados por vírgula pra oferecer/pedir - substituído por 2 selects em sequência (`_ViewEscolherPersonagensTroca`, reaproveitada pras 2 etapas): "oferece" populado com a coleção de quem propõe, "pede" populado com a coleção do ALVO - Discord já deixa digitar pra filtrar dentro do próprio select nativo, sem precisar de busca customizada. Só os 2 valores em WiShards continuam sendo texto (`_ModalWishardsTroca`, número é rápido de digitar, personagem não).
- **Upgrade de rolls não dizia o que fazia, só o preço (2026-08-29, pedido do usuário: "n deixa claro oq faz, so o custo")** - mensagem de confirmação do botão "⬆️ Upgrade" no painel agora inclui o efeito (+5 rolls/ciclo PRA SEMPRE, acumulado) antes do preço.
- **"🎲 Rolar" do painel `/waifu` gastava o ciclo INTEIRO num clique só (2026-08-29, achado em produção)** - usuário reportou "meus rolls deveriam ter resetado, mas n consigo rolar" - a causa era o próprio botão: ele chamava `gacha.rolar_varios(..., "ma", 0)`, o MESMO "máximo disponível" que `/ma` sem parâmetro usa de propósito, mas num botão rotulado só "Rolar" isso rola os 50 do ciclo inteiro num único clique, sem aviso nenhum. Corrigido pra `quantidade=1` - `/wa`/`/ha`/`/ma` continuam sendo o caminho pra rolar tudo de propósito. Rolls do usuário resetados manualmente no banco pra compensar o ciclo perdido; personagem #117 (Kirisaki Chitoge) atribuída manualmente à conta da GAIA - ela tinha rolado mas perdeu a corrida de claim (5min) por causa do restart do processo no meio da janela.
- **Painel de Party tinha botão por slot numerado, sem nenhuma utilidade real (2026-08-29)** - usuário perguntou "ter q selecionar 1 por vez em cada slot tem alguma utilidade?" - conferindo o `GruposPanel.cs` do LegendsAwaken de verdade, a resposta era não: o LA não tem conceito de slot NENHUM, só adiciona/remove de um conjunto de até 5; nada no ERIS hoje lê a posição da Party pra decidir algo (sem Torre/formação ainda). Trocado os 5 botões de slot por 2 (➕ Adicionar/➖ Remover, cada um com select multi-escolha até o número de vagas livres) - a coluna `posicao` do banco continua existindo, só parou de aparecer na UI (a próxima posição livre é escolhida sozinha).
- **Wishlist agora marca com "✨" quem já tem dono (2026-08-29, pedido do usuário)** - `db.wishlist_disponiveis_no_guild` já excluía esses itens da chance de aparecer num wish-roll, mas nada avisava por quê o item continuava na lista sem nunca mais sortear.
- **Reset fixo não corrigia sozinho um `*_resetam_em` salvo de ANTES do
  fix (2026-08-29, achado em produção)** - usuário reiniciou o ecossistema
  esperando poder jogar num horário redondo e continuou vendo "tenta de
  novo em ~7 min", porque o valor salvo antes da correção (calculado como
  "última ação + janela") não tinha por que coincidir com a grade fixa
  nova, e reset preguiçoso só recarrega quando o valor salvo JÁ expirou.
  `db._restantes_validos` agora também trata como expirado um reset salvo
  que simplesmente não bate com o horário fixo atual - `claims_
  disponiveis`/`tempo_restante` ganharam esse mesmo tratamento (antes só
  `_consumir_recurso` tinha sido corrigido, o que mascarava o self-heal
  com uma mensagem de espera errada). Sem migração de dado, tudo
  recalculado na leitura. Ver "Reconciliação de reset antigo/desalinhado"
  em `ARQUITETURA.md`.

### Corrigido
- **Prova de Soulmate REDESENHADA depois de testar ao vivo (2026-08-29, feedback do usuário sobre a Hyuga Hinata, revisando uma sugestão do GPT)** - a versão original só tinha um texto narrativo ("intro") seguido direto do botão "Enfrentar Prova": prometia "escolha a resposta que melhor demonstra compaixão", mas não existia escolha nenhuma, só a % decidindo tudo - "a Prova promete uma interação e depois parece resolver tudo só pela chance de 3%... isso faz o texto parecer cenográfico, não uma prova de verdade". Agora a GAIA gera uma SITUAÇÃO + exatamente 3 OPÇÕES de resposta (uma marcada como a que combina com a personalidade da personagem); escolher a certa dá um bônus FIXO de chance (+10pp, `gacha._BONUS_ESCOLHA_CORRETA_PROVA_SOULMATE`) só NESSA tentativa - nunca garante sucesso sozinho, o RNG/pity continuam decidindo. `prova_soulmate_intro` (coluna) removida (`DROP COLUMN`, SQLite 3.35+); novas: `prova_soulmate_situacao`/`prova_soulmate_opcoes` (JSON)/`prova_soulmate_reacao_acerto`/`prova_soulmate_reacao_erro`. Também encurtado o texto de derrota (mostrado toda tentativa perdida - antes soava "resposta de assistente genérico" de tanto se repetir, agora é 1 frase só, sem dar conselho). UI consolidada numa ÚNICA mensagem editada (`edit_original_response`/`edit_message` em cada etapa, nunca um followup novo) - antes cada etapa criava uma mensagem "Só você pode ver" separada. `db.definir_textos_prova_soulmate` trocou o guard de `WHERE prova_soulmate_nome IS NULL` pra `WHERE prova_soulmate_opcoes IS NULL` - Hyuga Hinata (testada ANTES do redesenho) se auto-cura sozinha na próxima vez que a Prova dela for aberta, sem UPDATE manual. Ver "Prova de Soulmate" em `ARQUITETURA.md`.
- **"Puxada X/10" voltou a reiniciar a cada lote nos rolls do AUTO-COLECIONADOR (2026-08-29, achado do usuário: "e os rolls dos bots ainda estao com Puxada X/10... é a msm coisa, n deveria ter de corrigir em locais diferentes")** - o fix de numeração global já feito pro roll de JOGADOR (`enviar_resultados`) nunca chegou no auto-colecionador (`auto_colecionador.py::_rodar_tiros_guild`), porque este tinha sua PRÓPRIA cópia manual do mesmo loop "dividir em lotes de 10 pro Discord" (5 chamadas de `rolar_sem_cooldown(..., 10, ...)` em sequência, cada uma reiniciando a numeração). Extraído `gacha.enviar_resultados_em_lotes` - ÚNICA implementação desse loop agora, reaproveitada tanto por `enviar_resultados` quanto pelo auto-colecionador (que passou a rolar os 50 de uma vez só e deixar a divisão em mensagens de 10 pra função compartilhada). Constantes `TAMANHO_LOTE`/`NUMERO_LOTES` removidas de `auto_colecionador.py` (ficaram sem uso depois da extração). Ver "Bug real: mesma lógica duplicada em 2 lugares" em `ARQUITETURA.md`.

### Adicionado
- **`/colecao_admin definir_afinidade` (2026-08-29, pedido do usuário: "n existe ninguem com afinidade 10, de comando de admin p editar")** - define a Afinidade de alguém com uma personagem direto (0-10, `db.definir_afinidade_admin`), sem passar pelos reencontros de verdade - pensado pra testar a Prova de Soulmate (que só habilita em Afinidade 10) sem esperar 9 rolls sortudos. Exige que o alvo já seja dono da personagem nesse servidor (mesma checagem de `_definir_slot_equipe`); não mexe em `is_soulmate`/tentativas, só na Afinidade em si.
- **Prova de Soulmate (2026-08-29, `ERIS_power_afinidade_soulmate_niveis.md`)** - substitui o auto-flag antigo "Afinidade 10 == Soulmate" (só cosmético `💍`) por uma tentativa de verdade que o jogador precisa vencer, 1x/hora por personagem, com chance/pity POR RARIDADE (de ~35% inicial +15pp/falha, pity na 5ª tentativa pra 1⭐, até 3% inicial +4pp/falha, pity na 20ª pra 5⭐ - números validados numa revisão sobre uma proposta do GPT). Botão "💞 Prova de Soulmate" no painel `/waifu` -> Perfil (`ViewPerfilAcoes`) abre um select das personagens elegíveis (`db.personagens_prontas_para_prova`, Afinidade 10 e ainda não Soulmate) e depois a tela da Prova, com flavor text (nome/descrição/intro/derrota/vitória) gerado 1x pela GAIA via LLM (`POST /eris/colecao_prova_soulmate`, espelha `/eris/colecao_classificar`) e cacheado pra sempre (`colecao_personagens.prova_soulmate_*`) - se a GAIA estiver fora do ar, cai pra um texto genérico baseado no nome, a mecânica em si nunca depende da LLM responder. O pity é um branch EXPLÍCITO (`tentativa >= pity: sucesso forçado`), não emerge sozinho da matemática. `is_soulmate`/`soulmate_tentativas`/`soulmate_ultima_tentativa_em` (novo em `colecao_afinidade`) trocam o `afinidade >= 10` antigo em `montar_embed`/`consulta.linha_personagem`/`db.obter_equipe` - emoji trocado de `💍` pra `💞`, com cor de embed exclusiva (`gacha._COR_SOULMATE`) fazendo as vezes de "moldura" (ERIS usa embed puro, sem asset de imagem renderizada). Nenhum Soulmate real existia em produção ainda, então não teve migração de dado - só o comportamento mudou. Sistema de "Nível de Personagem"/Power (mesmo documento) e Torre/Cidade (mecânica do LegendsAwaken) ficam de fora desta leva - ver `ARQUITETURA.md`.
- **Cards de reação pendentes PERSISTIDOS - sobrevivem a restart (2026-08-29, pedido do usuário: "cria uma tabela com a msm logica dos colecoes disponiveis, ela registra a hora q foi feito o roll, checa o tempo de duração configurado no server p ficar disponiveil, todas q expiraram pode remover")** - achado real: um restart do processo (bem comum durante esta sessão de fixes) no meio da janela de 1h fazia perder acesso a uma personagem já rolada - o card continuava visível no canal, mas a reação virava um no-op silencioso, já que `gacha._CARDS_REACAO_PENDENTES` vivia só em memória. Tabela nova `colecao_cards_pendentes` (`message_id`, `guild_id`, `personagem_id`, `emoji`, `expira_em`) + `db.registrar_card_pendente`/`card_pendente_por_mensagem`/`remover_card_pendente`/`cards_pendentes` - reset PREGUIÇOSO (remove expirados na leitura, sem job/cron à parte) e filtra quem JÁ tem dono (reivindicado pelo OUTRO caminho - botão da mensagem combinada - conta de verdade em vez de confiar em toda ação de claim lembrar de limpar a linha). Pedido junto: "se possivel, isso ser feito sem causar delay enquanto ta rodando comando" - `/colecao_disponiveis` agora deferre ANTES de consultar (`asyncio.to_thread`), mesmo cuidado do bug de timeout corrigido mais cedo hoje; a query em si é pequena/indexada por guild, bem mais leve que o `rolar_varios` que causou aquele bug.
- **"Puxada N/M" agora mostra a posição real dentro do limite do ciclo, não do lote de 10 (2026-08-29, pedido do usuário: "é p ser o numero q aquele roll representa dentre o limite atual do usuario ex 13/50")** - antes reiniciava em 1 a cada lote de 10 embeds (limite técnico de botões, não de dificuldade), então uma puxada de 50 mostrava "1/10, 2/10... 1/10" de novo. `gacha._limite_rolls_atual` (extraída de `rolar_varios`, evita duplicar a conta) calcula o limite de rolls da pessoa nesse ciclo (config do servidor + upgrade permanente); `enviar_cards_individuais` ganhou `indice_inicial`/`total_ciclo` pra numerar GLOBALMENTE dentro do roll inteiro.
- **Upgrade permanente de claims, espelhando o de rolls (2026-08-29, pedido do usuário: "claim tem q ter upgrade permanente tbm")** - `/loja upgrade_claims` (e o botão "🔺 Upgrade de claims" no painel `/waifu` -> Loja) compra até 5 níveis, +1 claim/ciclo PERMANENTE por nível (`db.comprar_upgrade_claims`/`nivel_upgrade_claims`, coluna nova `nivel_upgrade_claims`, migração aditiva). Preços mais altos que o upgrade de rolls (2000/5000/10000/20000/40000 WiShards - `PRECOS_UPGRADE_CLAIMS`) de propósito - claim é o recurso que decide quem fica com a personagem, bem mais valioso que um roll extra. `_processar_claim` (núcleo do claim, botão E reação) passou a somar esse bônus ao `claims_por_ciclo` do servidor, mesmo padrão que rolls já tinham.
- **`/colecao_admin resetar_rolls`/`resetar_claims`/`dar_personagem` (2026-08-29, pedido do usuário: "cria um comando q me permite resetar rolls de alguem ou dar uma personagem p alguem qnd sou admin", seguido de "comando p resetar claim tbm")** - formaliza correções manuais que eu vinha fazendo direto no banco durante esta sessão (reset de ciclo travado, atribuição de personagem perdida por restart no meio da janela do auto-colecionador). `db.resetar_rolls_admin`/`resetar_claims_admin(guild_id, user_id)` forçam o ciclo a recarregar AGORA (mesmo cálculo do reset preguiçoso, só que sem esperar o horário fixo passar - ambos já incluem o upgrade permanente de quem chamar); `db.atribuir_personagem_admin(guild_id, personagem_id, user_id)` dá uma personagem LIVRE direto pra alguém, com a MESMA recompensa econômica de um claim normal (WiShards + Afinidade inicial) - recusa se a personagem já tiver dono, nunca rouba de ninguém.
- **`/waifu` - painel-raiz do Colecionador, inspirado no LegendsAwaken (2026-08-29, Fase 1 COMPLETA - passos 1 a 5)** - usuário reportou "os bots estão ficando muito poluídos" (25 comandos raiz no seletor `/`, boa parte do Colecionador) e apontou o próprio bot LegendsAwaken (`C:\Workspace\LegendsAwaken`, C#/Discord.Net) como referência: 1 comando por sistema, navegação depois via embed+botões editados/reenviados, não subcomando. `/waifu` (novo, sem argumento) abre um hub com 8 botões, todos reaproveitando as MESMAS funções de `db`/`gacha`/`consulta`/`economia` que os comandos antigos já chamavam (sem duplicar regra nenhuma):
  - **🎲 Rolar** (mesmo `gacha.rolar_varios(..., "ma", 0)` de `/ma` sem parâmetro) e **📚 Coleção** (`paineis.ViewColecaoHub`, estende `consulta.ViewColecao` com select de modo - Minha coleção/🔥 Populares/🎯 Disponíveis pra pegar).
  - **👤 Perfil** (painel NOVO - junta `/carteira`+`/ranking`+contagem de favoritas nova, `db.contar_favoritas`) com botões Favoritar/Divorciar/Merge abrindo um select de até 25 personagens da própria coleção; **⭐ Wishlist** paginada com botão "+ Adicionar" (`discord.ui.Modal`, único desta leva) e select de remoção.
  - **👥 Party** - SEM comando `/party` nem `/waifu party`, só alcançável pelo botão (mesmo modelo do `Grupos` do LA, zero pegada no seletor `/`) - 5 botões de slot, cada um abrindo um select de personagem + opção de esvaziar.
  - **🛒 Loja** (comprar/garantir raridade/upgrade de rolls, cada um com seu próprio fluxo de select+confirmação) e **🔄 Trocar** (peça mais arriscada - "propor" virou `discord.ui.UserSelect` + `discord.ui.Modal` em vez de parâmetros de texto; `economia.criar_e_avaliar_troca` extraído do comando antigo, compartilhado pelos dois caminhos) e **🏆 Ranking** (top 25, sem paginação de verdade ainda - formato incompatível com `ViewColecao`).
  - `economia.executar_merge` também extraído do `/merge` antigo, mesmo motivo (compartilhar regra com o botão Merge do Perfil).
  Módulo novo `eris/colecao/paineis.py` (~450 linhas). **Passo 6 (remover os comandos antigos) ainda NÃO feito de propósito** - só depois de validar cada botão ao vivo no servidor real, nunca antes (mesmo cuidado de sempre nesse projeto). ERIS reiniciado (papéis "completo" e "musica") pra sincronizar - `/waifu` e `/musica_admin` já aparecem no Discord. Ver "Painel `/waifu`" em `ARQUITETURA.md`.
- **Rolar o máximo disponível num clique + `/colecao_disponiveis`
  (2026-08-29)** - pedido do usuário: "quero a opção de com 1 unico
  clique, rodar os maximo de rolls disponiveis, q no caso é 50. N apenas
  os 10". `quantidade:0` em `/wa`/`/ha`/`/ma` rola tudo que sobrar no
  ciclo (ignora `max_rolls_por_comando` de propósito - esse teto é por
  comando, pedir o máximo é explícito) - e é o DEFAULT do parâmetro
  (complemento no mesmo dia: "esse quantidade tem q ser opcional, se n
  colocar, manda tudo"), `/wa` sem nada já rola o máximo. Resultados em
  qualquer quantidade agora saem em lotes de 10 (cards individuais +
  mensagem combinada por lote), não mais limitados a um único lote de 10.
  Seguido de: "um comando q filtre todos os personagens q ainda da p
  coletar...
  por raridade, ou ordenado por raridade, com o botao de coletar dos 10
  principais" - `/colecao_disponiveis [raridade]` lista os cards com
  reação ainda pendentes (não expirados, sem dono), ordenados por
  raridade, com botão de claim pros 10 primeiros. Ver "Rolar o máximo
  disponível"/"`/colecao_disponiveis`" em `ARQUITETURA.md`.
- **Cards individuais com reação pra reivindicar, estilo Mudae + confirmação
  de claim consolidada (2026-08-29)** - pedido do usuário: "quero que cada
  personagem seja enviada em uma mensagem separada, e nela venha a opcao
  de reagir p pegar, igual no mudae, a mensagem com os 10 botoes pode
  ficar numa mensagem separada no final normalmente". Cada personagem
  rolada agora também vira uma mensagem própria com reação de claim
  (`gacha.enviar_cards_individuais`) - a mensagem combinada de sempre (N
  embeds + botões) continua igual, mandada por último. Seguido de: "é bom
  deixar claro que pegou, e a raridade da personagem... unificar tudo
  relevante p ela em 1 unica mensagem" - as 2 mensagens de confirmação
  (WiShards + classe) viraram 1 embed só, mencionando quem reivindicou.
  Vale tanto pra `/wa`/`/ha`/`/ma` quanto pro auto-colecionador. Ver
  "Cards individuais com reação"/"Confirmação de claim CONSOLIDADA" em
  `ARQUITETURA.md`.
- **`/musica_admin canal` - restringe o Modo Música a um canal de texto (2026-08-29)** - pedido do usuário: "assim como a coleção de waifu roda em 1 canal, quero q parte de musica tbm fique so em 1 canal configuravel". `/musica tocar/pular/pausar/continuar/fila/parar/dj_automatico` e `/caos` passam a checar `musica.obter_canal_restrito` antes de agir (`/musica aprovadas`/`desaprovadas` ficam de fora - são consulta pessoal ephemeral, sem barulho no canal). Guardado em `data/musica_canal_restrito.json` (não em `eris.db` - o papel "musica", que é quem registra esses comandos, nunca chama `db.inicializar()`). `/musica_admin ver` mostra a config atual; sem canal informado em `/musica_admin canal`, remove a restrição. Configurado no servidor real (canal `1388915991223730377`).
- **Classe canônica x classe de exibição (2026-08-29)** - usuário reportou
  classes erradas (profissão/personalidade em vez de arquétipo de RPG,
  ex.: "Maid", "Comediante") e uma tensão entre a regra "sempre masculino"
  e cards femininos artificiais ("Ai Hayasaka [Ladino]"). Corrigido:
  prompt da GAIA ganhou instrução explícita contra classes-profissão + uma
  coluna nova (`classe_exibicao`) que concorda em gênero com a personagem
  pra EXIBIÇÃO, enquanto `classe` continua canônica/masculina pras
  estatísticas - "Ladino"/"Ladina" nunca viram duas classes. 5 personagens
  corrigidas manualmente no banco. Ver "Classe deve ser arquétipo de
  RPG"/"Classe CANÔNICA x classe de EXIBIÇÃO" em `ARQUITETURA.md`.
- **Sincronização contínua do catálogo (2026-08-29)** - a importação do
  get_waifu deixa de ser carga única. Módulo novo `eris/colecao/
  sincronizador.py` reimporta o catálogo sozinho, 1x por semana (pedido do
  usuário), baixando a versão mais recente e fazendo upsert (nunca
  duplica). Não dispara de novo só por causa de um restart do processo -
  só quando o prazo semanal realmente vence. Ver "Sincronização contínua
  do catálogo" em `ARQUITETURA.md`.
- **`/populares` (2026-08-29)** - pedido do usuário: "tem comando para
  listar personagens por popularidade?". Lista o top N (padrão 50, até
  200) do CATÁLOGO INTEIRO por popularidade, com paginação e respeitando
  o filtro de NSFW do servidor. Ver "/populares - ranking de popularidade
  do catálogo" em `ARQUITETURA.md`.
- **Auto-colecionador (GAIA/ERIS jogam também) + trocas automáticas com
  conta de bot (2026-08-29)** - pedido do usuário: "coloca para a gaia e a
  eris tbm coletarem personagens, cada uma roda seus 50 tiros, a gaia vai
  rodar sempre aos XX:05, e apos 5min, vai escolher o de maior raridade, a
  eris fara o mesmo, mas rodará aos XX:30 e escolhe aos XX:35". Módulo novo
  `eris/colecao/auto_colecionador.py` - cada conta de bot rola 50
  personagens FIXOS (sem cooldown, sem passar por `max_puxada`), em 5
  lotes de 10 postados como mensagens DE VERDADE no canal configurável
  (`/colecao_admin canal`, novo) - **corrigido no mesmo dia** (pedido do
  usuário: "os rolls q os bots fazem tem q mostrar as opcoes, igual os
  meus. é literalmente rodar /wa 10 5x"): os cards são iguais a um `/wa 10`
  normal, com botão de Reivindicar de verdade que qualquer humano pode
  clicar. 5 minutos depois, cada conta reconsulta quem ainda está sem dono
  e fica com a mais POPULAR entre as que sobraram ("ai da 5min p alguem
  tentar pegar algum, ele tira da lista das escolhas os q ja foram pegos,
  e pega o mais popular" - critério é popularidade, não raridade).
  Seguido de: "elas aceitam trocar se o valor oferecido for 10x oq
  pagaram... contanto q a soma seja superior ou igual a 10x" -
  `/trocar propor` com uma conta de bot como alvo agora é decidido na hora
  (`economia.avaliar_proposta_npc`), sem esperar clique. Ver
  "Auto-colecionador" em `ARQUITETURA.md`.
- **Reset de rolls/claims em cronograma FIXO + cor do botão de claim por
  raridade (2026-08-29)** - correção pedida pelo usuário: "os resets tem
  de ser a cada hora, 1h, 2h, 3h... não 1h após interação do usuário, vai
  ser fixo pra geral". O reset deixa de ser calculado a partir da última
  ação de CADA jogador e passa a ser um horário FIXO compartilhado por
  todo mundo (ex.: janela de 1h reseta às XX:00 pra todo mundo,
  simultaneamente), ancorado matematicamente na Época Unix. Botão de
  Reivindicar também ganhou cor/emoji por raridade (⚪🟢🔵🟣🟡, mesma
  paleta do embed) - pedido junto: "coloca a cor dos botoes com nome dos
  personagens condizerem com a raridade". Ver "Ciclo FIXO ancorado na
  Época Unix" em `ARQUITETURA.md`.
- **Categoria de combate, Party, Vitrine, Favoritas e Upgrade de Rolls
  (2026-08-29)** - 3ª fatia de `ERIS_sistema_colecao_wishards.md`.
  Categoria de combate (DPS/Tank/Support) decidida pela GAIA junto com a
  classe, mesma chamada de LLM. `/favoritar` protege contra divórcio
  acidental (exige confirmação, não bloqueia). `/party ver`/`definir`/
  `remover`/`limpar` (até 5 slots, bloqueia DURO o Merge de quem estiver
  lá dentro) e `/vitrine` (mesma mecânica, só mostruário público). `/loja
  upgrade` compra rolls máximos permanentes (+5/nível, até 5 níveis).
  `/colecao_admin bloquear_serie`/`desbloquear_serie`. Soulmate (Afinidade
  10) ganha marcador cosmético 💍. Torre/Steal/conquistas/eventos ficaram
  de fora - ver TODO.md pro motivo de cada um.
- **Loja, Guaranteed Roll, Merge e Trocas (2026-08-29)** - 2ª fatia de
  `ERIS_sistema_colecao_wishards.md`. `/loja ver`/`comprar` (só personagens
  livres, preços fixos por raridade, reembolsa se perder a corrida);
  `/loja garantir` (garante raridade mínima no PRÓXIMO roll, consumo
  único); `/merge <5 ids> [confirmar]` (5 da mesma raridade → 1 aleatória
  da seguinte, exige `confirmar:true` se alguma tiver Afinidade > 1);
  `/trocar propor` (troca bilateral personagem/personagem/WiShards em
  qualquer combinação, botões Aceitar/Recusar - revalida tudo de novo no
  aceite, sem reservar nada durante a proposta, simplificação deliberada
  pra escala pessoal). Módulo novo `eris/colecao/economia.py`. Ver "Loja,
  Guaranteed Roll, Merge e Trocas" em `ARQUITETURA.md`.
- **WiShards, Afinidade e Reencontro (2026-08-29)** - 1ª fatia de
  `ERIS_sistema_colecao_wishards.md` (economia). Personagem já reivindicada
  volta a poder aparecer no roll - rolar a própria personagem é um
  "reencontro" (Afinidade +1 até 10, paga `valor_base × afinidade` na hora,
  sem clique); rolar a de outra pessoa paga METADE desse valor pro dono de
  verdade, sem mudar Afinidade nem dar nada a quem rolou. Afinidade nasce
  em 1 no claim e SOBREVIVE ao divórcio (resgate futuro mantém o vínculo).
  Divórcio agora paga `valor_base × afinidade` (antes não pagava nada).
  Comando novo `/carteira`. `/colecao` mostra Afinidade (`❤️N`). Decisão de
  classes revisada: taxonomia aberta (GAIA) continua como estava; uma
  "categoria de combate" fixa (DPS/Tank/Support) pra regras da Torre é
  atributo SEPARADO, ainda não implementado. Ver "WiShards, Afinidade e
  Reencontro" em `ARQUITETURA.md`.
- **Colecionador de Personagens - MVP inspirado na Mudae (2026-08-29)** -
  `/wa`/`/ha`/`/ma` (roll + card com botão de Reivindicar), `/colecao`,
  `/personagem`, `/divorciar`, `/ranking`, `/wishlist`, `/colecao_admin
  nsfw`. Catálogo de 30.965 personagens importado do
  [get_waifu](https://github.com/JiachenRen/get_waifu) (`eris/colecao/
  importar_get_waifu.py`); raridade fixa por percentil de popularidade
  (50/30/15/4/1%); dono único por (servidor, personagem), claim atômico
  (`ON CONFLICT DO NOTHING`); cooldown de roll/claim com reset preguiçoso,
  sem job; NSFW ligado por padrão, desligável a qualquer momento por
  servidor. Divisão de módulos (`eris/colecao/gacha.py`/`consulta.py`)
  inspirada no [Fable](https://github.com/ker0olos/fable) (MIT), sem
  copiar a stack dele (TypeScript+MongoDB). Ver "Colecionador de
  Personagens" em `ARQUITETURA.md` pro detalhe completo das decisões, e
  TODO.md pro que ficou de fora do MVP (economia real, trocas, `/wg`/`/hg`/
  `/mg`) - ainda não validado contra um servidor Discord real.
- **Perfil "VIP fácil" + "puxada" de várias personagens (2026-08-29)** -
  pedido do usuário logo depois do MVP acima: "quero q seja tipo um vip do
  mudae, ser mais fácil". Card de Reivindicar passou de 30s pra 1h; roll
  de 10/hora pra 50/hora; claim de 1 a cada 3h pra 1 a cada 1h. `/wa`/
  `/ha`/`/ma` ganharam o parâmetro `quantidade` (1-10, "permitir dar 10
  pulls de 1x") - uma mensagem só com até 10 embeds e um botão de
  Reivindicar por personagem (`ViewClaimMultiplo`, substitui a `ViewClaim`
  de botão único).
- **Toda a dificuldade virou configurável por servidor (2026-08-29)** -
  pedido do usuário: "o certo seria tudo q definimos ali ser configurável".
  Rolls/ciclo, claims/ciclo, duração do card, tamanho máximo da puxada e
  chance de wish-roll saíram de constantes fixas em `gacha.py` pra colunas
  em `colecao_configuracao_guild` (migração aditiva, preserva servidores já
  configurados). `/colecao_admin` ganhou `rolls`, `claims`, `duracao_card`,
  `max_puxada`, `wishlist_chance` e `ver` (mostra a config atual) -
  restritos a administrador do servidor, igual `/colecao_admin nsfw` já
  era.
- **Tela visual no Painel da GAIA pra configurar o Colecionador (2026-08-29)**
  - pedido do usuário: "n tem uma tela ou algo visual p configurar?". 2
  rotas HTTP novas (`GET /colecao_config/<guild_id>`, `POST /colecao_
  config`) pra config por servidor (diferente de `/config_roteamento`, que
  é global do bot) - `/colecao_admin` no Discord continua existindo, agora
  é só mais um jeito de editar o mesmo dado.
- **Classe da personagem, decidida pela GAIA na hora da reivindicação
  (2026-08-29)** - pedido do usuário: "consegue pegar 5 personagens e
  definir fácil classe e raridade delas?" seguido de "o ideal não é você
  fazer isso, é a gaia... essa info vai ser meio que secreta". `classe` fica
  NULL até o 1º claim de cada personagem em qualquer servidor - nunca
  aparece no card do roll, só em `/colecao`/`/personagem`/`/wishlist` depois
  de revelada. Webhook reverso novo (`POST /eris/colecao_classificar`) pede
  pra GAIA (LLM) decidir, com taxonomia ABERTA que cresce sozinha
  (reaproveita classe existente quando encaixa, inventa uma nova só quando
  necessário - "tipo pirata"). Nunca atrasa o claim (mensagem separada,
  chega ~1-2s depois). Achado testando: `MODELO_JUIZ` (Groq) está
  descomissionado (404) - também quebra o juiz do Modo em Grupo, bug
  pré-existente não corrigido aqui (fora do escopo), registrado em TODO.md.
- **`/musica fila`/📋 agora mostram "(👍)"/"(👎)" igual o anúncio de "tocando agora" (2026-08-28)** - pedido do usuário: "no listar tem q por o voto se tiver, igual tem os (👍) no final de qnd toca". `obter_fila` virou async pra buscar o voto de cada faixa antes de montar a resposta.
- **`/musica aprovadas`/`desaprovadas` ganharam páginas e permitem trocar o voto (2026-08-28)** - pedido do usuário: "a lista de musicas com like e dislike supera muito 25, tem q criar paginas e permitir alterar". Antes cortava silenciosamente em `faixas[:25]`; agora `musica.ViewListaVotos` pagina de verdade (◀️/▶️, até 25 por página) e um select deixa escolher uma faixa da página pra abrir `_ViewTrocarVoto` (botões Aprovar/Desaprovar, o que já reflete o voto atual vem desabilitado) - reaproveita o mesmo `gaia_webhook.pedir_feedback_musica` dos botões 👍/👎 de "tocando agora", sem precisar esperar a faixa tocar de novo.

### Alterado
- **👎 na mensagem de "tocando agora" já pula a faixa junto (2026-08-29)** - pedido do usuário: "qnd clico no dislike, pode ja pular a musica junto tbm". Só pula quando a faixa desaprovada é a que está tocando NAQUELE momento (`sessao.tocando_agora`) - clicar 👎 numa mensagem antiga (rolando o histórico do canal) continua só registrando o voto, sem mexer na música atual. Skip restrito a quem iniciou a sessão (pedido em seguida: "pode restirngir o skip do dislike a quem iniciou") - o voto em si continua aberto a qualquer membro, só o efeito colateral de pular fica com a mesma régua de `/musica pular`/⏭️.
- **Um 👎 numa faixa não afeta mais o resto do mesmo artista (2026-08-27)** - implementado E revertido no mesmo dia: primeiro adicionei `SessaoMusica.remover_artista_da_fila_logica` pra limpar candidatos do mesmo artista da fila lógica local num 👎 (espelhando `pool.invalidar_relacionados` do ECHO), depois o usuário apontou que a premissa em si estava errada - "um 👎 em 1 musica n pode condenar todas desse artista. Assim como o like n aprova todas tbm, algumas eu gosto e outras nao". Revertido - voto agora fica estritamente na faixa exata, nunca no artista inteiro (ver changelog do [Project ECHO](../../Project-ECHO)).
- **`/caos` não sugere mais nada se já tem sessão ativa no servidor (2026-08-28)** - antes reaproveitava a sessão existente e enfileirava mais uma sugestão do ECHO por baixo dos panos, mesmo com música pausada (o usuário esqueceu que já tava tocando/pausada e usou `/caos` de novo achando que ela ainda ia entrar na call). Agora avisa "Já tô na call tocando música nesse servidor." e, se pausada, complementa pedindo `/musica continuar` - não mexe mais na sessão nesse caso.

## [0.1.0] - 2026-08-24 a 2026-08-27: Extração completa - moderação, voz e Modo Música com buffer em 3 camadas (PRs #1 a #27)

### Novidades
- **Repositório criado (extração parcial, 2026-08-24)** - conexão,
  segurança (donos, rate limit, filtro de roteamento), mensagens (DM/canal/
  categoria/anexos/mensagem de voz nativa) e exportação de canal movidos de
  `Project G.A.I.A/assistant/features/discord_presence/discord_bot.py` +
  `integrations/discord/{discord_exportador,discord_voz_nativa}.py`. Rodando
  como processo próprio, ponte HTTP (porta 8772) pro Project G.A.I.A
  (`integrations/eris_client.py`), webhook reverso pra pedir conteúdo à
  persona (`eris/integrations/gaia_webhook.py`, mesmo padrão já usado por
  MOIRAI/HESTIA). Persistência em SQLite desde o início (`eris.db`), não
  JSON solto - decisão pensada pro roadmap futuro (ver TODO.md).
- **Moderação/administração do servidor (feature nova, nunca existiu na
  GAIA)** - slash commands `/moderacao` (kick/ban/desbanir/timeout/
  remover_timeout/advertir), `/mensagem` (fixar/desfixar/deletar/modolento/
  limpar), `/canal` (bloquear/desbloquear/criar/renomear/arquivar) e
  `/cargo` (atribuir/remover). Restrito a donos da Galateia, independente
  de cargo de administrador no servidor. `/mensagem limpar` exige
  `confirmar:true` explícito (irreversível, respeita o limite de 14 dias do
  bulk delete da API do Discord).
- **Slash command `/exportar`** - mesma função do antigo botão "📤 EXPORTAR
  CANAL (JSON)" do Painel da GAIA, agora também acionável direto no
  Discord ou via HTTP (`POST /exportar`).
- **Modo Intérprete e Modo Tutora por voz migrados (2026-08-25)** -
  `/interprete entrar/sair` (também por menção, "traduz"/"tradução"/
  "intérprete" pra entrar, "sai" pra sair) e `/tutora entrar/sair`. O ERIS
  entra na call, captura o áudio por participante até a pausa e toca o
  áudio de resposta (`eris/core/voz_call.py`, `voz_captura.py`, `vad.py`); a
  GAIA continua dona de STT/LLM/TTS via webhook reverso por turno (`POST
  /eris/interprete/{iniciar,encerrar,turno}`, `GET /eris/tutora/status`,
  `POST /eris/tutora/turno`).
- **Modo Conversa por voz (2026-08-25)** - terceiro modo de voz na call,
  bate-papo comum com a Galateia sem tradução (Intérprete) nem prática de
  idioma (Tutora), sem exigir nenhuma sessão prévia. `/conversar entrar/
  sair`, também por menção ("entra"/"entrar"/"conversa"/"conversar" - o
  gatilho genérico "entra" que antes sempre acionava o Intérprete agora cai
  aqui). Qualquer participante da call pode falar, não só o dono. Endpoint
  novo `POST /eris/conversa/turno`.
- **Modo Música (2026-08-25) - substitui o Jockie Music** - pedido do
  usuário: "quero q alguem seja meu dj exclusivo... qnd eu pedir uma musica,
  ele continue tocando outras em sequencia na mesma vibe". `/musica tocar/
  pular/pausar/continuar/fila/parar/dj_automatico`, aberto a qualquer membro
  do servidor. Busca/streaming via YouTube (`yt-dlp`, client "android" -
  evita bloqueio de bot sem precisar de cookie/login). Quando a fila
  esvazia com DJ automático ligado (padrão), pede pro Project ECHO (via
  webhook reverso pra GAIA) uma sugestão "na mesma vibe" da faixa que
  acabou de tocar, excluindo tudo já tocado NESTA sessão - resolve a queixa
  real do usuário sobre o Jockie repetir depois de um tempo. Mutuamente
  exclusivo com Conversa/Intérprete/Tutora (Discord só permite 1 conexão de
  voz por conta de bot por servidor) - `eris/core/musica.py`.
- **Múltiplas instâncias (2026-08-26) - Música e voz simultâneas no mesmo
  canal** - resolve o mutuamente exclusivo acima: `python -m eris.main
  musica` sobe uma 2ª instância dedicada (bot Discord PRÓPRIO, token em
  `.env.musica`, ver `.env.musica.example`), registrando só `/musica` (sem
  moderação, texto livre, `on_message`/webhook de conversa, `eris.db`).
  Papel escolhido por argv, porta de instância única separada
  (`PORTA_INSTANCIA_UNICA_MUSICA = 8779`). **Validado numa call real** com
  as 2 instâncias JUNTAS no mesmo canal - `ERIS#0983` tocando música
  enquanto a instância "completo" respondia por voz ao mesmo tempo. A GAIA
  sobe as duas sozinha no boot (`garantir_eris_musica_rodando`). Ver
  "Múltiplas instâncias" em `ARQUITETURA.md`.
- **`/caos` - sessão musical sem pedir referência nenhuma** (2026-08-26,
  pedido do usuário: "ERIS entra no canal de voz do usuário e inicia uma
  sessão musical contínua... sem exigir artista, gênero, música ou
  qualquer outra referência inicial") - entra na call e já começa a tocar
  sozinha, escolhendo a partir do perfil/histórico musical (via nova rota
  do [Project ECHO](../../Project-ECHO), `POST /radar/semente`), depois
  continua na mesma vibe automaticamente (mesmo motor do DJ automático de
  sempre). Funciona mesmo com perfil vazio (cai pro que está em alta).
  Validado ao vivo: comando sincronizado, rota testada contra o Last.fm
  real com o perfil do usuário.
- **Botões 👍/👎/⏭️ em toda mensagem de "tocando agora"** (2026-08-26,
  pedido do usuário: "quando ela toca uma musica, podia aparecer botoes
  de like, dislike e next") - cobre tanto o play manual quanto a
  continuação automática (mesma origem, `_tocar()` virou o único lugar
  que anuncia). Like/dislike ajustam o perfil musical no
  [Project ECHO](../../Project-ECHO) (nova rota `POST /radar/
  feedback_ao_vivo`, cria a entrada no histórico na hora se a faixa nunca
  passou pelo Radar); pular reusa `musica.pular()` de sempre. Validado ao
  vivo: rota do ECHO testada com dados reais, bot reconectado sem erro
  com o código novo.
- **Buffer em 3 camadas + dono da sessão + feedback passivo (2026-08-26)** -
  redesenho completo do Modo Música pra eliminar espera perceptível entre
  músicas, junto com a reescrita por pessoa do lado do
  [Project ECHO](../../Project-ECHO). `SessaoMusica` ganhou `fila_logica`
  (20-50, identidade sem stream, puxada do pool do ECHO em background) e
  mantém `fila` (5-10, streams JÁ resolvidos) sempre cheia - `_avancar()`
  só consome o topo pronto, nenhuma rede no meio. Fila lógica persistida
  (`data/fila_sessao_<guild_id>.json`) sobrevive a um restart do ERIS.
  `SessaoMusica.iniciado_por` restringe pular/pausar/continuar/parar/
  dj_automatico a quem começou a sessão (adicionar à fila e like/dislike
  continuam livres). `/musica tocar` sem parâmetro toca a lista de
  aprovadas de quem chamou até esgotar (`tocar_aprovadas`, pedido do
  usuário); `/musica aprovadas`/`/musica desaprovadas` (novos) listam o
  que cada pessoa já avaliou. Tempo de escuta (fração tocada, se foi
  pulada) medido e mandado pro ECHO como sinal fraco/acumulativo. Ver
  "Buffer em 3 camadas" em `ARQUITETURA.md`.
- **Botão ▶️ pra voltar numa música que já tocou (2026-08-26, pedido do
  usuário: "Adicionar botão de play, para caso queira voltar em alguma
  musica que tocou")** - toda mensagem antiga de "tocando agora" continua
  no canal com seus próprios botões válidos (`timeout=None`) - basta rolar
  até ela e clicar em ▶️ pra reenfileirar a MESMA faixa, sem precisar
  digitar o nome de novo. Aberto a qualquer membro, mesmo espírito de
  adicionar à fila.
- **Redesenho dos controles da mensagem de "tocando agora" (2026-08-27)** -
  botão ⏯️ novo (pausar/retomar num só clique, restrito a quem iniciou a
  sessão) e botão 📋 novo (mostra a fila, mesmo texto de `/musica fila`).
  Ordem final: ⏯️/⏭️/👍/👎/▶️/📋 (pedido do usuário). A confirmação privada
  "🎵 Tocando." foi removida quando toca IMEDIATAMENTE - o card público já
  confirma sozinho; "Adicionado à fila" continua respondendo (só ela tem
  informação nova, a posição). A linha do anúncio agora também mostra
  "(👍)"/"(👎)" quando a faixa já foi avaliada antes por quem iniciou a
  sessão - avaliamos trocar 👍/👎 por reações nativas do Discord, mas a
  API não permite marcar uma reação como "já votada" numa mensagem NOVA
  (reação é sempre por mensagem), então ficou como botão + texto em vez
  de simular visualmente algo que o Discord não suporta.
- **Título linkado no anúncio (2026-08-27, pedido do usuário)** - "Tocando
  agora" agora aponta pro vídeo do YouTube tocado (título vira link
  markdown).
- **Mensagens do bot viram Embed com borda colorida (2026-08-27, pedido do
  usuário)** - "pra ficar facil diferenciar" das mensagens normais do
  canal. Aplicado no anúncio de "tocando agora" e no aviso de aprovadas
  esgotadas.

### Correções
- **`/caos` depois de `/musica tocar` (aprovadas) ficava preso no modo
  errado (2026-08-27)** - reportado pelo usuário: "assim q eu uso o /caos,
  ele tem de ignorar tudo p tras e seguir a logica do /caos... O caos so
  ta tocando 1 musica". `iniciar_caos` reaproveitava a sessão ativa sem
  resetar `_modo_aprovadas`, então continuava tratando `/caos` como se
  ainda fosse a lista fechada de aprovadas (parava e repetia o aviso de
  esgotado, nunca reabastecia a fila lógica). Corrigido resetando a flag
  no início de `iniciar_caos`.
- **Intérprete/Tutora entravam na call mas não ouviam nem falavam nada** - achado pelo usuário na prática ("Quando eu peço ela p entrar na call, ela entra mas n conversa comigo"). Causa raiz: discord.py embute o DLL do libopus no pacote, mas NÃO carrega ele automaticamente no import (só versões bem antigas da lib faziam isso) - sem `discord.opus.load_opus`/`_load_default()`, a conexão de voz em si funciona (não depende de opus), mas a decodificação do áudio recebido (`discord-ext-voice-recv`) e o encode do áudio de resposta falham em silêncio, sem nenhum erro visível no Discord. Corrigido chamando `discord.opus._load_default()` no início de `iniciar_bot` (`eris/bot.py`), com aviso no log se falhar.
- **ERIS não tinha NENHUM log em disco** - achado depurando o bug acima (e de novo depurando por que o Modo Conversa não respondia): rodando via `pythonw.exe` (sem console, como sempre roda em produção), todo `print()` era descartado no vazio - não sobrava nenhum registro do lado do ERIS pra saber SE a call recebeu áudio, SE o webhook pra GAIA foi chamado, ou onde exatamente algo falhou. `eris/main.py::_RedirecionadorLog` (mesmo espírito do `LogRedirector` da GAIA, `ui/qt_painel.py`) agora espelha stdout/stderr pra `logs/AAAA-MM-DD.log`, ativado logo no início de `main()`.
- **Logs de diagnóstico da captura de voz (2026-08-25)** - mesmo com o log em disco e o libopus carregados, uma tentativa real numa call não gerou NENHUMA linha nova - nem confirmação de recebimento de áudio, nem erro. `eris/core/voz_captura.py`/`voz_call.py` ganharam logs pontuais (throttle de 2s, não por pacote): confirmação de SSRC resolvido pra um usuário, RMS de verdade a cada checagem (`VoiceFilterRMS.calcular_rms`, novo método - antes só devolvia bool), fala fechada (dispatch pra GAIA) ou descartada por curta demais, e aviso 1x se o SSRC nunca resolver pra ninguém. Sem isso, não dava pra saber em qual das 3 camadas (recepção de pacote/resolução de usuário/limiar de volume) o silêncio estava acontecendo.
- **DEBUG do `discord.ext.voice_recv` ligado (2026-08-25)** - nem os logs pontuais acima dispararam numa tentativa real (nenhum aviso de SSRC não resolvido, nenhum RMS, nada) - a própria extensão de voz (biblioteca de terceiro, `discord-ext-voice-recv`, ainda "experimental" segundo o próprio pacote) loga em DEBUG quando um pacote chega e é IGNORADO antes mesmo do nosso Sink (`PacketRouter.feed_rtp`). `eris/main.py::_ativar_log_debug_voice_recv` liga DEBUG só desse logger (não o `discord.py` inteiro, que já loga heartbeat de texto a cada ~40s) - próximo teste real deve mostrar se o pacote nunca chega no soquete (rede/firewall) ou chega e é descartado por dentro da lib.
- **`SinkVoz` não filtrava áudio de outros bots (2026-08-25)** - achado discutindo se dava pra rodar 2 instâncias do ERIS na mesma call (uma tocando música, outra ouvindo) - sem o filtro, o áudio que QUALQUER bot manda pro canal (incluindo música tocada por outra instância do ERIS, ou o próprio Jockie) seria capturado e mandado pro Whisper/GAIA como se fosse fala humana. `eris/core/voz_captura.py::SinkVoz.write` agora ignora qualquer pacote de um usuário com `user.bot == True`.
- **Modo Música/`/caos` repetia a mesma música sem parar** (2026-08-26, achado pelo usuário: "esta repetindo sempre a msm musica, quando pulo para a proxima pelo botão tbm") - o dedup de sessão comparava o título CRU do YouTube (cheio de "(Official Video)"/"ft. Fulano") contra o "artista::título" LIMPO que o ECHO usa nos próprios candidatos - a exclusão nunca batia (log confirmou a mesma faixa tocando 3x seguidas). `_buscar_sugestao_no_youtube` (`eris/core/musica.py`) agora sobrescreve artista/título pro valor limpo do ECHO antes de tocar/registrar - ver ARQUITETURA.md.
- **`/musica`/`/caos` apareciam também no bot principal (GAIA#9308)** (2026-08-26, achado pelo usuário: "pq a gaia e a eris tem /caos? N deveria ser apenas da eris?") - registro não checava papel nenhum; um clique acidental na instância "completo" ocupava o único slot de voz dela com música, derrubando Conversa/Intérprete/Tutora até parar a música de propósito. Agora exclusivo do papel "musica" (`eris/bot.py`) - confirmado ao vivo: GAIA#9308 caiu de 10 pra 8 slash commands sincronizados, ERIS#0983 continua com os 2.
- **`/musica tocar`/`/caos` mandavam 2 mensagens** (2026-08-26, achado pelo usuário: "mandou 2 mensagens... a primeira desnecessaria") - a confirmação da interação ("🎵 Tocando.") era pública, duplicando o anúncio de verdade ("🎵 Tocando agora: ..." + botões) que já sai à parte. Confirmação agora sempre ephemeral (`eris/bot.py`) - só o anúncio com botões fica visível pra todo mundo.
- **`/caos` parava depois de 1 música quando o artista-semente estava bloqueado por feedback negativo** (2026-08-26, mesmo relato "tocou apenas 1 musica, n mandou mais") - causa raiz do lado do [Project ECHO](../../Project-ECHO): `obter_faixas_por_tag` (fallback por gênero) sempre devolvia lista vazia por um bug de chave na resposta da API - sem candidato nenhum sobrando quando o artista principal é excluído, a sessão simplesmente parava. Corrigido no ECHO (ver changelog de lá).

### Causa raiz encontrada (2026-08-25) - voz na call não escuta nada, bloqueado por DAVE (E2EE) do Discord

Com o DEBUG acima, uma call real mostrou: pacotes RTP CHEGAM de verdade
("Received packet for unknown ssrc"), mas o Opus decoder sempre falha com
`discord.opus.OpusError: corrupted stream`. Causa raiz **não é bug
nosso**: desde março de 2026 o Discord tornou obrigatória a criptografia
ponta a ponta (protocolo **DAVE**) pra TODA call de voz/vídeo fora de
Stage Channel, sem opção de desligar. `discord.py` 2.7 já suporta DAVE no
cliente PRINCIPAL (via o pacote `davey`, já instalado - a Gala consegue
ENTRAR e FALAR na call normal), mas o `discord-ext-voice-recv` (lib de
terceiro que usamos pra RECEBER áudio) ainda decripta só a camada RTP,
não a camada DAVE por dentro - vira lixo pro Opus decoder. Confirmado como
limitação conhecida e aberta da própria lib ([issue #64](https://github.com/imayhaveborkedit/discord-ext-voice-recv/issues/64),
sem resolução ainda).

### Correção instalada e VALIDADA (2026-08-25, mesmo dia)

O usuário achou uma PR real da comunidade
([`discord-ext-voice-recv#54`](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54))
que adiciona decriptação DAVE em `opus.py`, delegando pro `davey` oficial
do Discord - múltiplos usuários confirmaram nos comentários que resolve o
`corrupted stream`, inclusive no discord.py 2.7.1 (nossa versão). Adotado
via o fork de terceiro `jstewart0788/discord-ext-voice-recv-dave` (carrega
a PR #54 + hardening próprio), auditado linha por linha antes de instalar
- trocado em `pyproject.toml` (fixado por commit SHA), caminho de import
inalterado, nenhum código nosso precisou mudar. **Validado numa call real
- "agora eu a escutei"** (Modo Conversa funcionando de ponta a ponta).
Depois movido pra um fork PRÓPRIO (`Gabrieljsa21/discord-ext-voice-recv-dave`,
pedido do usuário: risco de o repositório de terceiro sumir/virar privado)
- mesmo commit SHA, mesmo comportamento, agora numa conta controlada.
Detalhe completo (ressalvas conhecidas, PR concorrente #56, quando
retirar o fork) em `TODO.md`.

### Diagnóstico de reprodução na call (2026-08-25)

Testando a correção candidata acima numa call real: o áudio já chegava e
era mandado pra GAIA processar, mas a resposta não era ouvida na call.
`_tocar` (`eris/core/voz_call.py`) não logava NADA sobre a reprodução -
nem sucesso nem erro do `.play()`/callback `after` - então não dava pra
saber se a reprodução falhava em silêncio ou se o problema era outro
(era outro: conteúdo errado do lado da GAIA, ver
`Project G.A.I.A/assistant/docs/CORRECOES.md`). Adicionado log de início/
fim/erro da reprodução.

### Diagnóstico de criptografia DAVE no ENVIO (2026-08-25, 2ª rodada)

Com o conteúdo corrigido do lado da GAIA e a captura funcionando de
verdade, a reprodução continuava "concluída sem erro" mas inaudível pro
usuário. Achado real no código do `discord.py`
(`VoiceClient._get_voice_packet`): o pacote de ENVIO só é criptografado
com DAVE (`dave_session.encrypt_opus`) se `_connection.can_encrypt` for
`True` (== sessão DAVE "ready") - senão vai sem a camada DAVE, e um
cliente humano com DAVE ativo (obrigatório desde março/2026) provavelmente
descarta isso em silêncio, sem gerar erro nenhum do nosso lado (`.play()`
sempre reporta sucesso, mesmo mandando pacote sem DAVE). Log direto do
estado real da sessão (`dave_session`/`can_encrypt`/`ready`) adicionado em
`_tocar` ANTES de tocar, pra confirmar/descartar essa hipótese na próxima
call real.

### Voz na call CONFIRMADA funcionando (2026-08-25) - Modo Conversa validado numa call real de ponta a ponta

A causa raiz real da reprodução inaudível não era DAVE (que já estava
`can_encrypt=True`/`ready=True` em todo teste) - era o caminho de arquivo
RELATIVO devolvido por `sintetizar_frase` (corrigido do lado da GAIA, ver
`Project G.A.I.A/assistant/CHANGELOG.md`). Com essa correção, o usuário
confirmou: "agora eu a escutei" - Modo Conversa por voz numa call do
Discord funcionando de ponta a ponta pela primeira vez.

### Correção: timeout do turno de voz menor do que o da GAIA (2026-08-25)

Sob carga pesada (várias contas do Groq esgotadas em sequência, caindo pro
fallback NVIDIA), um turno de voz às vezes não gerava resposta nenhuma -
achado real: `TIMEOUT_TURNO_VOZ_SEGUNDOS` aqui era 60s, mas o lado da GAIA
(`integrations/iris_bridge.py`) espera até 90s pelo próprio turno
(`future.result(timeout=90)`) - o ERIS desistia (fechando a conexão) ANTES
da GAIA terminar de responder. A GAIA gerava a resposta certinho, mas
`ConnectionAbortedError` ao tentar escrever no socket já fechado jogava
tudo fora, silenciosamente. Corrigido subindo pra 120s (folga real sobre
os 90s do outro lado).

### Pendências conhecidas (ver ARQUITETURA.md e TODO.md)
- Slash commands de ação que dependem da GAIA (`/abrir`, `/jornalista`
  etc.) não foram migrados - desenho fechado, implementação para depois.
- Nenhuma validação contra um servidor/bot Discord real ainda foi feita
  (conexão/mensagem/moderação/exportação) - a voz por call FOI validada,
  achou o bloqueio de DAVE acima, e agora tem uma correção candidata
  aguardando validação com uma call real.
