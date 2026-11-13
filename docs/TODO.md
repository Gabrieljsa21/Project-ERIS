# TODO - Project ERIS

Mesma regra da GAIA (`Project G.A.I.A/assistant/docs/TODO.md`): item
concluído sai daqui e vira `CHANGELOG.md`/`ARQUITETURA.md`, nunca fica
marcado como ✅ neste arquivo.

## Pendências conhecidas (da extração de 2026-08-24)

### Validar contra um servidor/bot Discord real

**Prioridade:** Alta | **Complexidade:** Baixa

Nenhum dos módulos foi testado com um token/servidor de verdade ainda (o
ambiente onde foram escritos não tem acesso a isso), EXCETO a voz por call
(`/conversar entrar`), validada de ponta a ponta com sucesso em
2026-08-25 depois de uma sessão real de debugging (3 causas raiz
distintas, ver "Voz na call: bloqueio DAVE e fork do voice_recv" no ARQUITETURA.md).
Ainda faltam: conectar com um token real focado em texto, uma
conversa por DM de ponta a ponta, um comando de moderação de cada grupo
(`/moderacao`, `/mensagem`, `/canal`, `/cargo`), uma exportação de canal
(`/exportar`), e o mesmo teste de voz pro Intérprete/Tutora especificamente
(só o Modo Conversa foi validado até agora).

### Validar ao vivo as mudanças da 0.3.0

**Prioridade:** Alta | **Complexidade:** Baixa

Testado só com a suíte local (`python -m pytest`, 31 testes) e com o registro
dos comandos sem conectar ao Discord. Falta conferir numa call e num servidor
de verdade: (1) clicar 👍/▶️/📋 num "Tocando agora" depois de reiniciar o papel
"musica" (botões persistentes); (2) `/pandora`, `/wa` e `/pandora_admin` depois
da separação para `eris/comandos_pandora.py`; (3) um `/jornalista` demorado
(timeout de 90 s); (4) o papel "musica" subindo com o PANDORA indisponível.

### Validar ao vivo os botões do THOTH (0.5.0)

**Prioridade:** Alta | **Complexidade:** Baixa

Testado só com mocks. Falta, com a GAIA já chamando `/notificar_donos_com_botoes`:
(1) receber a DM e clicar Enviar, Editar e Descartar; (2) clicar depois de
reiniciar o papel "principal" (botões persistentes e "Editar" preenchido);
(3) um envio pelo WhatsApp perto dos 60 s (timeout de 120 s do lado do ERIS);
(4) a linha de status e os botões desabilitados numa DM longa, dividida em
duas mensagens.

### Mover `eris/comandos_pandora.py` para o PANDORA

**Prioridade:** Média | **Complexidade:** Média

O ERIS ainda registra os comandos do Colecionador (agora num módulo
próprio, fora do `bot.py`). O dono natural é o PANDORA: ele expor
`registrar(tree)` e o ERIS só chamar. Envolve os dois repositórios ao mesmo
tempo, por isso ficou de fora da 0.3.0.

### Retirar o fork `discord-ext-voice-recv-dave`

**Prioridade:** Baixa | **Complexidade:** Baixa

Quando o upstream (`imayhaveborkedit/discord-ext-voice-recv`) mesclar a PR #54
(ou equivalente) e lançar versão, ou o `py-cord` ganhar recepção com DAVE,
voltar para o pacote oficial. Histórico completo do bloqueio e do fork em
`ARQUITETURA.md`, "Voz na call: bloqueio DAVE e fork do voice_recv".

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

Nenhum dos outros itens abaixo tem escopo definido ainda - só registrado pra
não perder a ideia, mesmo espírito de "Atlas"/"ECHO" no `TODO.md` da GAIA.
Quando qualquer um for implementado, ganha tabela própria no `eris.db`
(nunca uma tabela genérica "kv" pra tudo, ver `eris/db.py`).
