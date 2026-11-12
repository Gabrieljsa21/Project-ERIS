# -*- coding: utf-8 -*-
"""Leitura e gravação de JSON em `data/` sem corromper o arquivo numa queda
(2026-11-12). Grava num `.tmp` ao lado e troca com `os.replace`, que no
Windows e no Linux substitui o destino de uma vez: quem ler depois vê o
arquivo antigo inteiro ou o novo inteiro, nunca a metade. Mesmo padrão do
ECHO (`core/armazenamento.py`) e do SIREN (`playlists.json`)."""
import json
import os


def ler_json(caminho, padrao=None):
    """Devolve o conteúdo, ou `padrao` se o arquivo não existir ou estiver
    ilegível (nunca levanta exceção)."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def salvar_json_atomico(caminho, dados):
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    temporario = f"{caminho}.tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, caminho)
