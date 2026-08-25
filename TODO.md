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
ambiente onde foram escritos não tem acesso a isso). Antes de confiar no
dia a dia: conectar com um token real, uma conversa por DM de ponta a
ponta (passando pelo webhook reverso até a GAIA), um comando de moderação
de cada grupo (`/moderacao`, `/mensagem`, `/canal`, `/cargo`), e uma
exportação de canal (`/exportar`).

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

### Intérprete/Tutora por voz em call do Discord

**Prioridade:** Média | **Complexidade:** Alta

Desenho fechado (ver ARQUITETURA.md, ponto 4): ERIS entra/sai da call,
captura o áudio do falante até a pausa (`discord-ext-voice-recv` - não
instalado ainda, ver `pyproject.toml`), manda o áudio pra GAIA via webhook
reverso (`/eris/voz_turno`, ainda não existe), a GAIA transcreve (Whisper)/
decide (LLM)/sintetiza (TTS) e devolve os bytes de áudio, o ERIS toca na
call. Continua sendo persona quem decide o conteúdo (Whisper/LLM/TTS ficam
no core da GAIA, decisão de arquitetura já fechada antes da extração) - o
ERIS só transporta.

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
