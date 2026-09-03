# -*- coding: utf-8 -*-
"""Entry point standalone do ERIS (`python -m eris.main`) - extraído da GAIA
em 2026-08-24 (ver `Project G.A.I.A/assistant/docs/ECOSSISTEMA_PROJETOS.md`
-> "Project ERIS"). Diferente do HESTIA (sem loop próprio) e igual ao
MOIRAI: o ERIS tem um loop de vida própria de verdade (a conexão com o
Discord), continua rodando/respondendo moderação e exportação mesmo se a
GAIA estiver fechada - só a conversa/comandos que dependem de conteúdo
ficam indisponíveis nesse caso (ver `eris/bot.py`)."""
import asyncio
import datetime
import faulthandler
import logging
import os
import socket
import subprocess
import sys
import threading
import traceback

from dotenv import load_dotenv

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 🔥 Papel desta instância - "completo" (padrão, bot único de sempre) ou
# "musica" (2ª instância, bot Discord PRÓPRIO dedicado só ao Modo Música -
# 2026-08-26, pedido do usuário: "esse novo bot devo fazer p ERIS? O primeiro
# é da GAIA" -> sim, 2ª instância do MESMO projeto ERIS, token diferente).
# Detectado por argv (`python -m eris.main musica`) em vez de variável de
# ambiente - evita colidir com o `override=True` do load_dotenv abaixo (ver
# `.env.musica.example`).
PAPEL = "musica" if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "musica" else "completo"
_ARQUIVO_ENV = ".env.musica" if PAPEL == "musica" else ".env"

# 🔥 override=True (mesmo motivo já documentado no HESTIA/MOIRAI e corrigido
# na GAIA no mesmo dia, 2026-08-24) - sem isso, uma variável de ambiente
# herdada do processo que lançou o ERIS venceria o `.env`/`.env.musica` local
# em silêncio.
load_dotenv(os.path.join(PASTA_PROJETO, _ARQUIVO_ENV), override=True)

from eris import bot, db, tray  # noqa: E402
from eris.api_bridge import iniciar_servidor_api  # noqa: E402
from pandora import db as colecao_db  # noqa: E402 - mesmo alias de `eris/bot.py`
from eris.config import PORTA_INSTANCIA_UNICA, PORTA_INSTANCIA_UNICA_MUSICA  # noqa: E402
from eris.watchdog import EXIT_CODE_FECHAR  # noqa: E402

_socket_instancia_unica = None
# 🔥 Referência global (2026-09-02) - `faulthandler.enable()` guarda o
# DESCRITOR de arquivo internamente (nível de C), mas o objeto Python
# precisa continuar vivo (senão o GC fecha o arquivo e o descritor vira
# inválido) - nunca reatribuído, só existe pra não deixar isso cair fora
# de escopo.
_arquivo_faulthandler = None


class _RedirecionadorLog:
    """Espelha stdout/stderr pra `logs/AAAA-MM-DD.log` (reabre sozinho se o
    processo atravessar a meia-noite) - achado real 2026-08-25, depurando por
    que o Modo Conversa não respondia numa call: `pythonw.exe` (sem console,
    como o ERIS sempre roda em produção) descarta todo `print()` no vazio, e
    não sobra NENHUM registro pra diagnosticar o que deu errado aqui (do lado
    da GAIA só se vê o efeito - "não chegou pedido nenhum" - nunca a causa).
    Mesmo espírito do `LogRedirector` da GAIA (`ui/qt_painel.py`), bem mais
    simples - sem widget de Painel pra espelhar (o ERIS não tem GUI)."""

    def __init__(self, stream_original):
        self._stream_original = stream_original
        self._arquivo = None
        self._data_arquivo = None
        # 🔥 Horário por linha (2026-09-02, pedido do usuário depois de tentar
        # investigar uma queda do papel "completo" sem conseguir correlacionar
        # nada no log com o horário real - "coloca horario tbm no log") - só
        # no INÍCIO de cada linha nova, nunca no meio de um `print()` picado em
        # várias chamadas de `write()` (`sep`/`end` do print sempre viram
        # `write()`s separados).
        self._inicio_de_linha = True

    def _garantir_arquivo(self):
        hoje = datetime.date.today().isoformat()
        if self._arquivo is not None and self._data_arquivo == hoje:
            return
        if self._arquivo is not None:
            try:
                self._arquivo.close()
            except Exception:
                pass
        try:
            pasta_logs = os.path.join(PASTA_PROJETO, "logs")
            os.makedirs(pasta_logs, exist_ok=True)
            self._arquivo = open(os.path.join(pasta_logs, f"{hoje}.log"), "a", encoding="utf-8")
            self._data_arquivo = hoje
        except Exception:
            self._arquivo = None

    def _com_horario(self, texto):
        if not texto:
            return texto
        partes = []
        for linha in texto.splitlines(keepends=True):
            if self._inicio_de_linha:
                partes.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]")
            partes.append(linha)
            self._inicio_de_linha = linha.endswith("\n")
        return "".join(partes)

    def write(self, texto):
        if self._stream_original:
            try:
                self._stream_original.write(texto)
            except Exception:
                pass
        self._garantir_arquivo()
        if self._arquivo:
            try:
                self._arquivo.write(self._com_horario(texto))
                self._arquivo.flush()
            except Exception:
                pass

    def flush(self):
        for destino in (self._stream_original, self._arquivo):
            if destino:
                try:
                    destino.flush()
                except Exception:
                    pass


def _ativar_log_em_disco():
    sys.stdout = _RedirecionadorLog(sys.stdout)
    sys.stderr = _RedirecionadorLog(sys.stderr)


def _ativar_diagnostico_de_saida():
    """2026-09-02, pedido do usuário depois de investigar uma queda do
    papel "completo" (código 15) sem achar NENHUM rastro - nem traceback
    no log, nem crash reportado no Event Viewer do Windows. Isso descarta
    uma exceção Python normal (teria log) e um crash nativo relatado pelo
    próprio Windows (teria evento) - sobra "algo terminou o processo sem
    Python conseguir reagir" (crash nativo silencioso numa lib com
    extensão C - `discord.opus`/PyNaCl/`pystray`- ou término externo).
    3 camadas, cada uma cobrindo um tipo de silêncio diferente:

    1. `sys.excepthook` - exceção não tratada na THREAD PRINCIPAL. Python
       já imprime isso sozinho, mas fica bem mais fácil de achar no log
       gigante com um marcador ÓBVIO ("EXCEÇÃO NÃO TRATADA").
    2. `threading.excepthook` - mesma coisa, mas pras threads de fundo
       (ícone da bandeja `pystray`, ponte HTTP `api_bridge`) - por padrão
       o Python só manda isso pro handler de log de última instância, fácil
       de se perder no meio do resto.
    3. `faulthandler` - a camada que interessa de verdade pro caso do
       código 15: registra um handler de baixo nível pra sinais FATAIS
       (access violation/segfault, inclusive de dentro de extensões C como
       `discord.opus`/PyNaCl) e despeja a pilha de TODAS as threads num
       arquivo antes do processo morrer - o único jeito de capturar algo
       que nem chega a passar pelo `sys.excepthook` normal do Python.
       🔥 PRECISA de um arquivo de verdade (`fileno()` de baixo nível - é
       um handler de SINAL, não roda em contexto Python normal) - o
       `_RedirecionadorLog`/`sys.stderr` NÃO serve (achado ao vivo:
       `AttributeError: '_RedirecionadorLog' object has no attribute
       'fileno'`, travava o boot inteiro num loop de crash) - abre um
       arquivo PRÓPRIO (`logs/crash_<papel>.log`), fora do redirecionador."""
    def _excecao_nao_tratada(tipo, valor, tb):
        print(" [SISTEMA] !!! EXCEÇÃO NÃO TRATADA (thread principal) !!!")
        traceback.print_exception(tipo, valor, tb)

    def _excecao_thread(args):
        print(f" [SISTEMA] !!! EXCEÇÃO NÃO TRATADA (thread \"{args.thread.name}\") !!!")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _excecao_nao_tratada
    threading.excepthook = _excecao_thread

    global _arquivo_faulthandler
    try:
        pasta_logs = os.path.join(PASTA_PROJETO, "logs")
        os.makedirs(pasta_logs, exist_ok=True)
        _arquivo_faulthandler = open(os.path.join(pasta_logs, f"crash_{PAPEL}.log"), "a", encoding="utf-8")
        faulthandler.enable(file=_arquivo_faulthandler, all_threads=True)
    except Exception:
        print(" [SISTEMA] faulthandler não pôde ser ativado (não é crítico, resto do diagnóstico continua valendo).")


def _ativar_log_debug_voice_recv():
    """DEBUG só do `discord.ext.voice_recv` (não do discord.py inteiro - o
    gateway de texto sozinho já loga heartbeat a cada ~40s, ruído demais pra
    esse fim) - achado real 2026-08-25: os logs pontuais de `voz_captura.py`
    (RMS/fala fechada) confirmaram que a call conecta e ativa a escuta sem
    erro nenhum, mas NENHUM pacote chega no nosso Sink - nem o aviso de "SSRC
    não resolvido" dispara. A própria lib loga em DEBUG se um pacote chegou e
    foi IGNORADO (`PacketRouter.feed_rtp`: "Ignoring packet from dropped ssrc
    %s") - sem ligar isso, não dá pra distinguir "pacote nunca chegou no
    soquete" (rede/firewall) de "chegou mas foi descartado antes do Sink"
    (bug na própria lib/versão). Chamado SÓ depois de _ativar_log_em_disco -
    precisa que sys.stdout já seja o _RedirecionadorLog, pra este handler
    escrever no mesmo lugar."""
    logger = logging.getLogger("discord.ext.voice_recv")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [voice_recv debug] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)


def _garantir_instancia_unica():
    global _socket_instancia_unica
    porta = PORTA_INSTANCIA_UNICA_MUSICA if PAPEL == "musica" else PORTA_INSTANCIA_UNICA
    _socket_instancia_unica = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _socket_instancia_unica.bind(("127.0.0.1", porta))
    except OSError:
        print(
            f" [SISTEMA] Já existe uma instância do ERIS (papel \"{PAPEL}\") rodando "
            f"(porta {porta} ocupada) - encerrando esta pra não conectar o mesmo token duas vezes."
        )
        # 🔥 EXIT_CODE_FECHAR (não 1) - sob eris/watchdog.py (2026-08-30), um
        # código de saída genérico faria o watchdog achar que foi um crash e
        # tentar de novo pra sempre (com backoff), perdendo a corrida contra
        # a instância real de novo a cada vez. Isso NÃO foi uma falha
        # transitória - watchdog não deve reinicar.
        sys.exit(EXIT_CODE_FECHAR)


def _verificar_migracao_completa():
    """🔥 CAUSA RAIZ ACHADA (2026-09-02) - `colecao_series_favoritas_bonus`
    e depois a coluna `cooldown_batalha_ativo` não existiam em produção
    mesmo com `_SCHEMA` do PANDORA já atualizado. Rastreei por 2 achados ao
    vivo achando que era caching de bytecode/venv/race condition - a causa
    real é muito mais simples: **`colecao_db.inicializar()` (a migração de
    verdade do Colecionador, `pandora.db`) NUNCA foi chamada em lugar
    nenhum do boot do ERIS**. `main()` só chamava `db.inicializar()` (o
    `db` IMPORTADO NO TOPO DESTE ARQUIVO É `eris.db`, o núcleo pequeno do
    PRÓPRIO ERIS - donos/roteamento/auditoria - não tem nenhuma relação com
    o Colecionador) - nome igual, banco/schema completamente diferentes. O
    schema do Colecionador só existia porque o script de migração
    ONE-SHOT da extração (2026-08-29, `migrar_de_eris.py`) rodou
    `pandora.db.inicializar()` UMA VEZ; nenhuma mudança de schema feita
    DEPOIS disso (World Boss/Séries Favoritas/cooldown de Batalha, todas
    de hoje) nunca foi aplicada automaticamente - só quando eu rodava a
    migração manualmente pra investigar. Corrigido: `main()` agora chama
    `colecao_db.inicializar()` (import novo, mesmo alias de `eris/bot.py`)
    de verdade. Esta função continua existindo como VERIFICAÇÃO/rede de
    segurança (não confiar cegamente que "rodou sem erro" = "aplicou")."""
    def _faltando():
        faltando = []
        with colecao_db.conexao() as conn:
            colunas_config = {r["name"] for r in conn.execute("PRAGMA table_info(colecao_configuracao_guild)")}
            for coluna in colecao_db._NOVAS_COLUNAS_CONFIG_COLECAO:
                if coluna not in colunas_config:
                    faltando.append(f"coluna colecao_configuracao_guild.{coluna}")
            tabelas = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for tabela in ("colecao_series_favoritas", "colecao_series_favoritas_bonus"):
                if tabela not in tabelas:
                    faltando.append(f"tabela {tabela}")
        return faltando

    try:
        faltando = _faltando()
        if faltando:
            print(f" [SISTEMA] !!! MIGRAÇÃO DO COLECIONADOR INCOMPLETA - faltando: {', '.join(faltando)} - tentando rodar colecao_db.inicializar() de novo...")
            colecao_db.inicializar()
            faltando = _faltando()
        if faltando:
            print(f" [SISTEMA] !!! MIGRAÇÃO DO COLECIONADOR AINDA INCOMPLETA depois de 2 tentativas - faltando: {', '.join(faltando)} - precisa de investigação manual.")
        else:
            print(" [SISTEMA] Migração do Colecionador (pandora.db) verificada - nada faltando.")
    except Exception:
        print(" [SISTEMA] Não consegui verificar a migração (não é crítico, mas fica sem essa checagem dessa vez).")
        traceback.print_exc()


def _mostrar_versao_boot():
    """Mesmo raciocínio do `run.py` da GAIA (2026-08-25) - Python nunca
    recarrega código sozinho, então um ERIS de pé pode estar rodando uma
    versão bem mais antiga do que o código no disco agora, sem nenhum
    aviso visual óbvio. Falha em silêncio se `git` não estiver disponível."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PASTA_PROJETO,
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        resumo = subprocess.run(
            ["git", "log", "-1", "--format=%cd %s", "--date=format:%d/%m %H:%M"], cwd=PASTA_PROJETO,
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if commit:
            print(f" [SISTEMA] Código carregado: commit {commit} - {resumo}")
    except Exception:
        pass


def main():
    _ativar_log_em_disco()
    _ativar_diagnostico_de_saida()
    _ativar_log_debug_voice_recv()
    _garantir_instancia_unica()
    _mostrar_versao_boot()

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(f" [SISTEMA] DISCORD_BOT_TOKEN não configurado no {_ARQUIVO_ENV} - o ERIS não tem como conectar. Veja .env.example/.env.musica.example.")
        # 🔥 EXIT_CODE_FECHAR - mesmo motivo do _garantir_instancia_unica
        # acima: token ausente é erro de configuração, não crash transitório;
        # o watchdog não deve ficar tentando de novo pra sempre.
        sys.exit(EXIT_CODE_FECHAR)

    if PAPEL == "completo":
        db.inicializar()
        # 🔥 `colecao_db.inicializar()` (2026-09-02, correção de causa raiz -
        # ver docstring de `_verificar_migracao_completa`) - NUNCA era
        # chamado antes; só o `db.inicializar()` acima (que é `eris.db`, o
        # núcleo pequeno do PRÓPRIO ERIS, sem nenhuma relação com o schema
        # do Colecionador/PANDORA) rodava. Toda mudança de schema do
        # Colecionador feita depois da extração (2026-08-29) nunca tinha
        # sido aplicada automaticamente em produção até agora.
        colecao_db.inicializar()
        _verificar_migracao_completa()
        ids_bootstrap = [i.strip() for i in os.getenv("DISCORD_OWNER_IDS", "").split(",") if i.strip()]
        db.importar_donos_bootstrap(ids_bootstrap)
        threading.Thread(target=iniciar_servidor_api, args=(token,), daemon=True).start()
        print(" [SISTEMA] ERIS pronto - ponte HTTP na porta 8772, conectando ao Discord...")
    else:
        # 🔥 Papel "musica" não precisa de `db` (sem moderação/donos) nem da
        # ponte HTTP (`api_bridge.py`, porta 8772 já em uso pela instância
        # "completo") - a GAIA nunca chama DENTRO dessa instância, só ela
        # chamando a GAIA (`gaia_webhook.pedir_proxima_musica`).
        print(" [SISTEMA] ERIS (papel música) pronto - conectando ao Discord...")

    # 🔥 Ícone de bandeja (2026-08-30) - o ERIS roda em produção via
    # pythonw.exe (sem console, ver iniciar_eris.bat/iniciar_eris_oculto.vbs).
    # Só o papel "completo" mostra ícone de verdade (usuário: "falei q era p
    # criar apenas 1 [icone] contendo as 2") - "musica" só sobe o listener de
    # controle remoto que esse ícone usa pra Reiniciar/Fechar à distância,
    # ver eris/tray.py.
    tray.iniciar(PAPEL)

    asyncio.run(bot.iniciar_bot(token, papel=PAPEL))
    # 🔥 `run()` só retorna depois de `client.close()` (pedido local pelo tray
    # ou remoto via socket) - `tray.codigo_saida()` diz ao watchdog externo
    # (`eris/watchdog.py`) se foi um pedido explícito (reiniciar/fechar) ou
    # uma queda inesperada (0 == nenhum dos dois pediu, trata como crash).
    # 🔥 Log explícito ANTES de sair (2026-09-02) - se o processo morrer por
    # OUTRO caminho que não seja `run()` retornar aqui (crash nativo, término
    # externo), essa linha simplesmente não vai aparecer - o que já é um
    # diagnóstico útil por exclusão (compara com o horário do log de
    # `watchdog_completo.log`/`watchdog_musica.log`).
    codigo = tray.codigo_saida()
    print(f" [SISTEMA] Encerrando de propósito (client.close() retornou) - código de saída {codigo}.")
    sys.exit(codigo)


if __name__ == "__main__":
    main()
