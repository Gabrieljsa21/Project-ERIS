# -*- coding: utf-8 -*-
"""Watchdog do ERIS - sobe `python -m eris.main [musica]` como subprocesso,
monitora se caiu, e reinicia automaticamente com BACKOFF EXPONENCIAL se a
causa for persistente (mesmo padrão/motivo de `Project G.A.I.A/assistant/
scripts/watchdog.py`, recomendação de HoppouAI/ProjectGabriel-Remastered).

2026-08-30, pedido do usuário: "o bot de musica ficava caindo direto [durante
a extração do Colecionador pro Project PANDORA]. Quero evitar isso tbm" -
antes disso, nada supervisionava nenhum dos 2 papéis do ERIS; um crash saía
sem avisar ninguém e o bot ficava fora do ar até alguém notar e subir de
novo manualmente.

Convenção de código de saída (EXIT_CODE_* abaixo, usados em `eris/tray.py` e
`eris/main.py`) - IDÊNTICA à da GAIA de propósito, pra qualquer um que já
conhece o padrão de lá reconhecer na hora:
- EXIT_CODE_REINICIAR: pedido explícito de reinício (tray local do
  "completo", ou comando remoto "REINICIAR" recebido pelo "musica" via
  `PORTA_CONTROLE_MUSICA`) - reinicia IMEDIATAMENTE (sem esperar backoff,
  que reseta pro valor inicial), já que não foi uma falha.
- EXIT_CODE_FECHAR: usuário pediu pra desligar de vez (tray local ou
  comando remoto "FECHAR") - watchdog não reinicia, encerra também.
- qualquer outro código (crash, exceção não tratada, kill externo): falha
  inesperada - espera (backoff) e reinicia sozinho.

Roda escondido via pythonw.exe (ver `iniciar_eris.bat`) - print() vai pro
log redirecionado pelo próprio `.bat` (`logs\\watchdog_completo.log`/
`logs\\watchdog_musica.log`); a saída do PRÓPRIO ERIS (stdout/stderr do
subprocesso supervisionado) já vai pro `logs/AAAA-MM-DD.log` de dentro dele
mesmo (`eris/main.py::_RedirecionadorLog`), então o Popen aqui não precisa
capturar/redirecionar isso de novo - só descarta (`DEVNULL`)."""
import os
import subprocess
import sys
import time

EXIT_CODE_REINICIAR = 42
EXIT_CODE_FECHAR = 43

BACKOFF_INICIAL_SEGUNDOS = 5
BACKOFF_MAXIMO_SEGUNDOS = 300
BACKOFF_MULTIPLICADOR = 3
# 🔥 Mesmo raciocínio do watchdog da GAIA - se o ERIS ficou de pé por mais
# tempo que isso antes de cair, não foi um crash-loop; reseta o backoff pro
# valor inicial, senão uma falha rara isolada deixaria os restarts futuros
# sempre lentos, mesmo meses depois.
DURACAO_MINIMA_PARA_RESETAR_BACKOFF_SEGUNDOS = 60

PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
PASTA_PROJETO = os.path.dirname(PASTA_PROJETO)


def _papel_do_argv():
    return "musica" if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "musica" else "completo"


def supervisionar(papel, dormir=time.sleep):
    argv = [sys.executable, "-m", "eris.main"]
    if papel == "musica":
        argv.append("musica")

    backoff = BACKOFF_INICIAL_SEGUNDOS
    print(f"[SISTEMA] Watchdog iniciado - supervisionando ERIS (papel \"{papel}\")")

    while True:
        inicio = time.time()
        processo = subprocess.Popen(
            argv, cwd=PASTA_PROJETO,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        codigo = processo.wait()
        duracao = time.time() - inicio
        print(f"[SISTEMA] ERIS (papel \"{papel}\") terminou (código {codigo}) depois de {duracao:.0f}s.")

        if codigo == EXIT_CODE_FECHAR:
            print("[SISTEMA] Fechamento pedido - watchdog encerrando.")
            return

        if duracao >= DURACAO_MINIMA_PARA_RESETAR_BACKOFF_SEGUNDOS:
            backoff = BACKOFF_INICIAL_SEGUNDOS

        if codigo == EXIT_CODE_REINICIAR:
            print("[SISTEMA] Reinício pedido - subindo de novo agora (sem esperar backoff).")
            continue

        print(f"[SISTEMA] Saída inesperada - reiniciando em {backoff}s (backoff exponencial)...")
        dormir(backoff)
        backoff = min(backoff * BACKOFF_MULTIPLICADOR, BACKOFF_MAXIMO_SEGUNDOS)


if __name__ == "__main__":
    supervisionar(_papel_do_argv())
