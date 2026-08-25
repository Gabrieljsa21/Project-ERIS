# Changelog

Histórico de alto nível do que muda no ERIS, por versão. Ver
`ARQUITETURA.md` pro detalhe técnico completo.

## [Unreleased]

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

### Correções
- **Intérprete/Tutora entravam na call mas não ouviam nem falavam nada** - achado pelo usuário na prática ("Quando eu peço ela p entrar na call, ela entra mas n conversa comigo"). Causa raiz: discord.py embute o DLL do libopus no pacote, mas NÃO carrega ele automaticamente no import (só versões bem antigas da lib faziam isso) - sem `discord.opus.load_opus`/`_load_default()`, a conexão de voz em si funciona (não depende de opus), mas a decodificação do áudio recebido (`discord-ext-voice-recv`) e o encode do áudio de resposta falham em silêncio, sem nenhum erro visível no Discord. Corrigido chamando `discord.opus._load_default()` no início de `iniciar_bot` (`eris/bot.py`), com aviso no log se falhar.
- **ERIS não tinha NENHUM log em disco** - achado depurando o bug acima (e de novo depurando por que o Modo Conversa não respondia): rodando via `pythonw.exe` (sem console, como sempre roda em produção), todo `print()` era descartado no vazio - não sobrava nenhum registro do lado do ERIS pra saber SE a call recebeu áudio, SE o webhook pra GAIA foi chamado, ou onde exatamente algo falhou. `eris/main.py::_RedirecionadorLog` (mesmo espírito do `LogRedirector` da GAIA, `ui/qt_painel.py`) agora espelha stdout/stderr pra `logs/AAAA-MM-DD.log`, ativado logo no início de `main()`.
- **Logs de diagnóstico da captura de voz (2026-08-25)** - mesmo com o log em disco e o libopus carregados, uma tentativa real numa call não gerou NENHUMA linha nova - nem confirmação de recebimento de áudio, nem erro. `eris/core/voz_captura.py`/`voz_call.py` ganharam logs pontuais (throttle de 2s, não por pacote): confirmação de SSRC resolvido pra um usuário, RMS de verdade a cada checagem (`VoiceFilterRMS.calcular_rms`, novo método - antes só devolvia bool), fala fechada (dispatch pra GAIA) ou descartada por curta demais, e aviso 1x se o SSRC nunca resolver pra ninguém. Sem isso, não dava pra saber em qual das 3 camadas (recepção de pacote/resolução de usuário/limiar de volume) o silêncio estava acontecendo.
- **DEBUG do `discord.ext.voice_recv` ligado (2026-08-25)** - nem os logs pontuais acima dispararam numa tentativa real (nenhum aviso de SSRC não resolvido, nenhum RMS, nada) - a própria extensão de voz (biblioteca de terceiro, `discord-ext-voice-recv`, ainda "experimental" segundo o próprio pacote) loga em DEBUG quando um pacote chega e é IGNORADO antes mesmo do nosso Sink (`PacketRouter.feed_rtp`). `eris/main.py::_ativar_log_debug_voice_recv` liga DEBUG só desse logger (não o `discord.py` inteiro, que já loga heartbeat de texto a cada ~40s) - próximo teste real deve mostrar se o pacote nunca chega no soquete (rede/firewall) ou chega e é descartado por dentro da lib.

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

### Correção candidata instalada (2026-08-25, mesmo dia) - aguardando validação com call real

O usuário achou uma PR real da comunidade
([`discord-ext-voice-recv#54`](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54))
que adiciona decriptação DAVE em `opus.py`, delegando pro `davey` oficial
do Discord - múltiplos usuários confirmaram nos comentários que resolve o
`corrupted stream`, inclusive no discord.py 2.7.1 (nossa versão). Adotado
via o fork `jstewart0788/discord-ext-voice-recv-dave` (carrega a PR #54 +
hardening próprio), auditado linha por linha antes de instalar - trocado
em `pyproject.toml` (fixado por commit SHA), caminho de import inalterado,
nenhum código nosso precisou mudar. Detalhe completo (ressalvas
conhecidas, PR concorrente #56, quando retirar o fork) em `TODO.md`. **A
dependência em si ainda não foi commitada** - pedido do usuário, testar
localmente numa call real primeiro.

### Diagnóstico de reprodução na call (2026-08-25)

Testando a correção candidata acima numa call real: o áudio já chegava e
era mandado pra GAIA processar, mas a resposta não era ouvida na call.
`_tocar` (`eris/core/voz_call.py`) não logava NADA sobre a reprodução -
nem sucesso nem erro do `.play()`/callback `after` - então não dava pra
saber se a reprodução falhava em silêncio ou se o problema era outro
(era outro: conteúdo errado do lado da GAIA, ver
`Project G.A.I.A/assistant/docs/CORRECOES.md`). Adicionado log de início/
fim/erro da reprodução.

### Pendências conhecidas (ver ARQUITETURA.md e TODO.md)
- Slash commands de ação que dependem da GAIA (`/abrir`, `/jornalista`
  etc.) não foram migrados - desenho fechado, implementação para depois.
- Nenhuma validação contra um servidor/bot Discord real ainda foi feita
  (conexão/mensagem/moderação/exportação) - a voz por call FOI validada,
  achou o bloqueio de DAVE acima, e agora tem uma correção candidata
  aguardando validação com uma call real.
