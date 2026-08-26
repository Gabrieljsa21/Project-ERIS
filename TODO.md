# TODO - Project ERIS

Mesma regra da GAIA (`Project G.A.I.A/assistant/docs/TODO.md`): item
concluído sai daqui e vira `CHANGELOG.md`/`ARQUITETURA.md`, nunca fica
marcado como ✅ neste arquivo.

## Pendências conhecidas (da extração de 2026-08-24)

### Mascarar segredos no log (`scrubber_segredos.py` da GAIA nunca foi portado)

**Prioridade:** Baixa | **Complexidade:** Baixa

A GAIA mascara qualquer valor de segredo configurado (token/chave) antes de
imprimir no log/Discord (`scripts/scrubber_segredos.py`, movido pra
`assistant/scripts/` em 2026-08-24). O ERIS não tem equivalente - os
`print()` de erro (`eris/bot.py`, `eris/api_bridge.py`) poderiam, em teoria,
vazar `DISCORD_BOT_TOKEN` se ele aparecer dentro de uma mensagem de erro da
própria API do Discord. Risco baixo (não observado ainda), mas o padrão já
existe pronto pra copiar do lado da GAIA.

### Validar contra um servidor/bot Discord real

**Prioridade:** Alta | **Complexidade:** Baixa

Nenhum dos módulos foi testado com um token/servidor de verdade ainda (o
ambiente onde foram escritos não tem acesso a isso), EXCETO a voz por call
(`/conversar entrar`), validada de ponta a ponta com sucesso em
2026-08-25 depois de uma sessão real de debugging (3 causas raiz
distintas, ver "Voz na call - histórico do bloqueio DAVE e correção"
abaixo). Ainda faltam: conectar com um token real focado em texto, uma
conversa por DM de ponta a ponta, um comando de moderação de cada grupo
(`/moderacao`, `/mensagem`, `/canal`, `/cargo`), uma exportação de canal
(`/exportar`), e o mesmo teste de voz pro Intérprete/Tutora especificamente
(só o Modo Conversa foi validado até agora).

### Voz na call - histórico do bloqueio DAVE e correção (RESOLVIDO em 2026-08-25)

**Status: CONFIRMADO funcionando numa call real (2026-08-25) - "agora eu a
escutei".** Fica registrado abaixo o histórico completo do diagnóstico
(3 causas raiz distintas, cada uma mascarando a próxima) - útil se algo
similar quebrar de novo. A dependência do fork ainda precisa ser commitada
(ver final desta seção).

Validado em 2026-08-25 com uma call real: `/conversar entrar` conecta,
ativa a escuta (`VoiceRecvClient.listen`), e pacotes RTP CHEGAM de
verdade (confirmado com `discord.ext.voice_recv` em DEBUG) - mas o Opus
decoder falhava com `discord.opus.OpusError: corrupted stream` em todo
pacote. Causa raiz: desde março de 2026, o Discord tornou obrigatória a
criptografia ponta a ponta (protocolo **DAVE**) pra TODA call de voz/vídeo
fora de Stage Channel, sem opção de desligar (nem por conta, nem por
servidor - [confirmado oficialmente](https://support.discord.com/hc/en-us/articles/38749827197591-A-V-E2EE-Enforcement-for-Non-Stage-Voice-Calls)).
O `discord.py` 2.7 já suporta DAVE no cliente de voz PRINCIPAL via o
pacote `davey` (já vem instalado como dependência - envio de áudio pela
call funciona normal), mas o `discord-ext-voice-recv` original (biblioteca
de terceiro pra RECEBER áudio, ver `eris/core/voz_call.py`) tem seu
PRÓPRIO decodificador de pacote separado que nunca foi atualizado pra
entender DAVE - só desencripta a camada RTP
(`aead_xchacha20_poly1305_rtpsize`, que funciona), mas o áudio Opus por
dentro continua criptografado pela camada DAVE (MLS), então virava lixo
pro decoder.

🔥 **Atualização 2026-08-25 (mesmo dia)**: o usuário achou uma PR real da
comunidade que resolve exatamente isso -
[`imayhaveborkedit/discord-ext-voice-recv#54`](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54)
("Added support for DAVE decryption in opus.py"), aberta desde 07/03/2026,
ainda não mesclada upstream (repo original sem commit desde 18/06/2025,
efetivamente sem manutenção desde a imposição do DAVE). Múltiplos usuários
confirmaram nos comentários que resolve o `OpusError: corrupted stream`,
inclusive alguém especificamente no discord.py 2.7.1 (nossa versão exata).
Adotado inicialmente via o fork de terceiro `jstewart0788/discord-ext-voice-recv-dave`
(MIT), que carrega a PR #54 + 1 commit de hardening próprio (except mais
estrito, logs separados de "SSRC sem membro" vs "falha de decrypt DAVE") -
auditado linha por linha antes de instalar (diff pequeno, +26/-4 nos
arquivos originais). Delega a decriptação de verdade pro `davey` oficial
do Discord (nunca reimplementa criptografia própria) - a API do `davey`
0.1.6 já instalado bate exatamente com o que o patch espera
(`MediaType.audio`/`.video`, `DaveSession`).

🔥 **Fork movido pra conta própria (mesmo dia)** - pedido do usuário:
"e ele pode deixar privado ou algo assim e parar de funcionar p nos?".
Depender do fork de uma conta de terceiro é risco de cadeia de
suprimentos de verdade (repo pode sumir/virar privado, `uv sync` do zero
simplesmente falha) - resolvido com um fork DESSE fork pra dentro da
própria conta
([`Gabrieljsa21/discord-ext-voice-recv-dave`](https://github.com/Gabrieljsa21/discord-ext-voice-recv-dave),
via `gh repo fork`, preservando histórico/atribuição). Instalado em
`pyproject.toml`, fixado por commit SHA
(`78fcb434a3484f2abf54cf89e80e86b651e5c28d`, não branch - branch pode
sofrer force-push, SHA é imutável). Caminho de import não mudou
(`discord.ext.voice_recv`) - nenhum código nosso precisou mudar, só a
dependência.

**Ressalvas conhecidas** (ver comentários da PR #54, lidos na íntegra
antes de adotar): um bug de câmera ligada foi corrigido numa revisão
posterior (payload não-áudio causava `member is None`); um usuário relatou
`OpusError: corrupted stream` residual numa revisão intermediária, mas
confirmou que a decriptação em si funcionava; existe um erro ocasional
`DecryptionFailed(UnencryptedWhenPassthroughDisabled)` tratável por
re-escutar; e um bug NÃO resolvido de quem entra pelo Discord Web no
Safari/iPhone não ser ouvido corretamente (edge case raro, sem
reprodução/fix ainda).

🔥 **Validado numa call real (2026-08-25) - 2 causas raiz ADICIONAIS
encontradas depois do fix acima**, cada uma mascarando a seguinte (áudio
chegava e era processado certo em cada etapa, só a etapa seguinte falhava
em silêncio):
1. **Reprodução "concluída sem erro" mas inaudível** - não era DAVE no
   envio (`can_encrypt=True`/`dave_session.ready=True` confirmados em todo
   teste, log de diagnóstico dedicado). Causa raiz de verdade:
   `sintetizar_frase` (`Project G.A.I.A/assistant/core/voice/tts.py`)
   sempre devolveu caminho RELATIVO do áudio - resolvia contra o cwd do
   ERIS, não da GAIA, desde a extração pra processos separados. FFmpeg
   falhava em achar o arquivo EM SILÊNCIO (discord.py não propaga isso
   como exceção). Corrigido do lado da GAIA com `os.path.abspath()` (mesmo
   bug também achado e corrigido na tag `<PRINT>`).
2. **Sob carga pesada (Groq esgotando várias contas em sequência), o turno
   às vezes não gerava resposta nenhuma** - `TIMEOUT_TURNO_VOZ_SEGUNDOS`
   aqui (60s) era menor que o timeout do lado da GAIA pro mesmo turno
   (90s, `integrations/iris_bridge.py`) - o ERIS desistia e fechava a
   conexão ANTES da GAIA terminar de responder, e a resposta certa (já
   gerada) se perdia num `ConnectionAbortedError` ao tentar escrever no
   socket já fechado. Corrigido subindo pra 120s
   (`eris/integrations/gaia_webhook.py`).

**Existe uma 2ª PR concorrente**, [#56](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/56),
mais abrangente (trata vídeo/screenshare/SSRC desconhecido) mas o próprio
autor admite "não é uma implementação completa da máquina de estados
DAVE/MLS ainda" - não adotada por ora, PR #54 é mais enxuta e testada por
mais gente na nossa versão exata do discord.py. Reavaliar se a #54 não se
provar estável.

**Quando retirar este fork** (mesmo critério do `FORK_RATIONALE.md` dele):
upstream mesclar a PR #54 (ou equivalente) e lançar uma release, OU o
`py-cord` ganhar suporte de recepção DAVE no core (acompanhado, mas não
adotado - o suporte a DAVE dele hoje também é só pro lado de envio,
confirmado direto no changelog e no código-fonte).

**Se a correção acima não se provar estável na prática, caminhos
alternativos:**
1. Tentar a PR #56 (mais abrangente, menos madura).
2. Implementar a decriptação DAVE por conta própria, hookando o pacote
   `davey` direto no pipeline de recepção - trabalho real de integração
   de criptografia, não trivial (mas o patch da PR #54 já mostra que o
   caminho funciona).
3. Aceitar a limitação por enquanto - Intérprete/Tutora/Modo Conversa por
   voz numa call ficam bloqueados (a Gala pode ENTRAR e FALAR na call
   normalmente, só não consegue OUVIR ninguém).

### Modo Música - validar numa call real

**Prioridade:** Alta | **Complexidade:** Baixa

Implementado em 2026-08-25 (substitui o Jockie Music - pedido do usuário:
"quero q alguem seja meu dj exclusivo... qnd eu pedir uma musica, ele
continue tocando outras em sequencia na mesma vibe"): busca/streaming via
YouTube (`yt-dlp`, client "android" pra evitar bloqueio de bot sem cookie),
fila com `/musica tocar/pular/pausar/continuar/fila/parar`, continuação
automática via Project ECHO quando a fila esvazia (`eris/core/musica.py`).
Sintaxe/import verificados, busca no YouTube testada isoladamente (extração
real de URL de stream, sem depender de nenhum cookie) e a continuação testada
contra o ECHO real (`POST /radar/proxima`) - **mas o playback de verdade
numa call (FFmpegPCMAudio streamando a URL, o callback `after` avançando a
fila sozinho) nunca foi testado contra um servidor Discord real** (mesma
limitação do resto do ERIS, ver seção acima).

Achado relacionado (mesmo dia): `eris/core/voz_captura.py::SinkVoz` não
filtrava áudio de outros BOTS - se algum dia rodar 2 instâncias do ERIS no
mesmo canal (ver "Múltiplas instâncias" no Roadmap futuro abaixo), a
instância ouvindo pegaria a música da instância tocando como se fosse fala
humana. Corrigido (ignora qualquer áudio de `user.bot == True`).

### Slash commands de ação que dependem da GAIA

**Prioridade:** Média | **Complexidade:** Média

`/abrir`, `/jornalista` e o resto de `core/agent/comandos.py` (GAIA) não
foram migrados - desenho já fechado (ver `ARQUITETURA.md`): o ERIS registra
o slash command (usando metadados que a GAIA expõe - nome/descrição/
argumento) e encaminha `(comando, argumento, eh_dono, remetente_id)` pro
webhook reverso; a GAIA roda o handler de sempre e devolve o texto. Falta
implementar o lado da GAIA que expõe essa lista + o endpoint novo no
webhook reverso (`/eris/comando`, simétrico ao `/eris/mensagem` já
existente).

## Próximo passo confirmado: múltiplas instâncias do ERIS

**Prioridade:** Alta | **Complexidade:** Média | **Status:** próximo a implementar (pedido do usuário 2026-08-25, depois de fechar o Modo Música)

Pergunta real do usuário: dá pra ter um ERIS tocando música e outro
conversando/traduzindo AO MESMO TEMPO no MESMO canal (mesmo espírito do
Jockie, que usa 4 bots separados - Jockie Music/Music 1/2/3)? **Sim,
tecnicamente** - o limite real do Discord é 1 conexão de voz por CONTA de
bot por servidor, não por canal; duas contas de bot diferentes podem estar
no mesmo canal ao mesmo tempo.

Precisa de:
1. Uma 2ª aplicação de bot no Discord Developer Portal (token separado,
   convite separado pro servidor) - só o usuário pode criar isso.
2. Rodar um 2º processo do ERIS com esse token (ex.: `DISCORD_BOT_TOKEN`
   diferente por instância via `.env` separado ou variável de ambiente na
   hora de subir) - o código já é modular o bastante (Música e voz já são
   mutuamente exclusivos DENTRO de uma instância, ver `eris/core/musica.py`/
   `voz_call.py`) pra isso não exigir reescrever nada, é mais trabalho de
   infraestrutura/deploy (2 tokens, 2 processos, talvez 2 portas de API/
   instância única) do que de código novo.
3. Decidir se as 2 instâncias compartilham o mesmo `data/eris.db`
   (donos/config de roteamento) ou têm cada uma o seu - preservar histórico/
   moderação de uma instância "principal" enquanto a "de música" fica mais
   leve provavelmente faz mais sentido.

Achado relacionado já corrigido: `SinkVoz` agora ignora áudio de outros bots
(ver seção "Modo Música" acima) - sem isso, a instância ouvindo pegaria a
música da instância tocando como se fosse um humano falando.

## Roadmap futuro (registrado, sem decisão de design específica ainda)

Levantado pelo usuário ao planejar o ERIS (2026-08-24), citando AmariBot
(amaribot.com/commands), Loritta (loritta.website/br/commands), TempVoice
(tempvoice.xyz) e Mudae (patreon.com/mudae) como referência - domínios de
"bot de comunidade" com uma característica em comum importante: zero
decisão de IA no caminho crítico, então cabem inteiramente no ERIS sem
depender da GAIA pra nada.

- **Economia/moeda própria** (inspirado em AmariBot/Loritta) - moeda
  virtual, recompensa por atividade, ranking. Já pensado na escolha de
  SQLite desde o início (ver ARQUITETURA.md) - esse domínio é exatamente o
  tipo de dado de alta cardinalidade que motivou a decisão.
- **Sistema de XP/nível** (AmariBot/Loritta) - progressão por atividade de
  texto/voz, leaderboard por servidor.
- **Canais de voz temporários** (TempVoice) - usuário cria um canal sob
  demanda, controla (renomear/limitar/expulsar) o próprio canal, deletado
  quando esvazia.
- **Colecionável/gacha** (Mudae) - sortear item/personagem, coleção,
  troca, cooldown.

Nenhum desses tem escopo definido ainda - só registrado pra não perder a
ideia, mesmo espírito de "Atlas"/"ECHO" no `TODO.md` da GAIA. Quando
qualquer um for implementado, ganha tabela própria no `eris.db` (nunca uma
tabela genérica "kv" pra tudo, ver `eris/db.py`).
