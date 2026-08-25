# -*- coding: utf-8 -*-
"""Persistência do ERIS via SQLite (`sqlite3` da stdlib, sem dependência nova) -
escolha deliberada em vez do JSON solto que MOIRAI/HESTIA usam: aqueles têm
dado de baixa cardinalidade (uma lista de animes/jogos rastreados); o ERIS já
nasce pensando em domínios futuros de alta cardinalidade por usuário/servidor
(economia, níveis, canais temporários, colecionáveis - ver TODO.md,
"Roadmap futuro") onde escrita concorrente e consulta tipo "top 10" tornam
JSON solto inadequado desde já. Trocar depois seria retrabalho evitável.

Hoje só guarda o que a v1 usa de verdade: donos, configuração de roteamento
(quem recebe resposta de persona), cache de servidores e auditoria de
moderação - schemas novos (economia etc.) entram como tabelas próprias
quando a feature for implementada, nunca uma tabela genérica "kv" pra tudo."""
import os
import sqlite3
from contextlib import contextmanager

from eris.config import CAMINHO_BANCO, PASTA_DADOS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS donos (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS config_roteamento (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS guilds_desativados (
    guild_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS guilds_cache (
    guild_id TEXT PRIMARY KEY,
    nome TEXT
);

CREATE TABLE IF NOT EXISTS auditoria_moderacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ator_id TEXT NOT NULL,
    acao TEXT NOT NULL,
    alvo TEXT,
    guild_id TEXT,
    detalhe TEXT
);
"""

# 🔥 Valores padrão de config_roteamento (2026-08-24) - mesmo default de sempre
# (`obter_config_servidor_discord`, GAIA, antes da extração): sem servidor
# configurado, só responde em DM; discord_active precisa ser ligado
# explicitamente no Painel (nunca liga sozinho).
_PADROES_CONFIG = {
    "discord_active": "0",
    "server_active": "0",
    "mentions": "1",
    "target_user_active": "0",
    "target_user_name": "",
}


def _garantir_pasta():
    os.makedirs(PASTA_DADOS, exist_ok=True)


@contextmanager
def conexao():
    _garantir_pasta()
    conn = sqlite3.connect(CAMINHO_BANCO)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def inicializar():
    with conexao() as conn:
        conn.executescript(_SCHEMA)
        for chave, valor in _PADROES_CONFIG.items():
            conn.execute(
                "INSERT OR IGNORE INTO config_roteamento (chave, valor) VALUES (?, ?)",
                (chave, valor),
            )


# --------------------------------------------------------------------------
# Donos
# --------------------------------------------------------------------------

def listar_donos():
    with conexao() as conn:
        linhas = conn.execute("SELECT id, nome, ativo FROM donos ORDER BY nome").fetchall()
        return [{"id": r["id"], "nome": r["nome"], "ativo": bool(r["ativo"])} for r in linhas]


def ids_donos_ativos():
    with conexao() as conn:
        linhas = conn.execute("SELECT id FROM donos WHERE ativo = 1").fetchall()
        return {r["id"] for r in linhas}


def salvar_donos(lista):
    """Substitui a lista inteira (mesmo contrato que `salvar_discord_donos`
    tinha na GAIA) - `lista`: [{"id", "nome", "ativo"}, ...]."""
    with conexao() as conn:
        conn.execute("DELETE FROM donos")
        conn.executemany(
            "INSERT INTO donos (id, nome, ativo) VALUES (?, ?, ?)",
            [(str(d["id"]), d["nome"], 1 if d.get("ativo") else 0) for d in lista],
        )


def importar_donos_bootstrap(ids):
    """Só popula se a tabela estiver vazia (primeira execução) - mesma ideia
    da migração automática que existia em `obter_discord_donos` (GAIA):
    importa `DISCORD_OWNER_IDS` do `.env` uma vez, sem sobrescrever o que já
    foi configurado depois pelo Painel."""
    if listar_donos():
        return
    if not ids:
        return
    salvar_donos([{"id": i, "nome": f"Conta {n + 1} (bootstrap do .env)", "ativo": True} for n, i in enumerate(ids)])


# --------------------------------------------------------------------------
# Roteamento (filtro de "vale a pena chamar a persona?")
# --------------------------------------------------------------------------

def obter_config_roteamento():
    with conexao() as conn:
        linhas = conn.execute("SELECT chave, valor FROM config_roteamento").fetchall()
        cfg = {r["chave"]: r["valor"] for r in linhas}
    desativados = listar_guilds_desativados()
    return {
        "discord_active": cfg.get("discord_active", "0") == "1",
        "server_active": cfg.get("server_active", "0") == "1",
        "mentions": cfg.get("mentions", "1") == "1",
        "target_user_active": cfg.get("target_user_active", "0") == "1",
        "target_user_name": cfg.get("target_user_name", ""),
        "disabled_guilds": desativados,
    }


def salvar_config_roteamento(campo, valor):
    """`campo` em {"discord_active", "server_active", "mentions",
    "target_user_active", "target_user_name"} - `disabled_guilds` tem sua
    própria função (ver `definir_guild_desativado`) por ser uma lista, não um
    valor escalar."""
    valor_serializado = "1" if valor is True else "0" if valor is False else str(valor)
    with conexao() as conn:
        conn.execute(
            "INSERT INTO config_roteamento (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (campo, valor_serializado),
        )


def listar_guilds_desativados():
    with conexao() as conn:
        linhas = conn.execute("SELECT guild_id FROM guilds_desativados").fetchall()
        return [r["guild_id"] for r in linhas]


def definir_guild_desativado(guild_id, desativado):
    with conexao() as conn:
        if desativado:
            conn.execute("INSERT OR IGNORE INTO guilds_desativados (guild_id) VALUES (?)", (str(guild_id),))
        else:
            conn.execute("DELETE FROM guilds_desativados WHERE guild_id = ?", (str(guild_id),))


# --------------------------------------------------------------------------
# Cache de servidores (só exibição no Painel da GAIA)
# --------------------------------------------------------------------------

def salvar_guilds_cache(guilds):
    """`guilds`: [{"id", "name"}, ...] - substitui a lista inteira, chamado
    em on_ready/on_guild_join (ver eris/bot.py)."""
    with conexao() as conn:
        conn.execute("DELETE FROM guilds_cache")
        conn.executemany(
            "INSERT INTO guilds_cache (guild_id, nome) VALUES (?, ?)",
            [(str(g["id"]), g["name"]) for g in guilds],
        )


def obter_guilds_cache():
    with conexao() as conn:
        linhas = conn.execute("SELECT guild_id, nome FROM guilds_cache ORDER BY nome").fetchall()
        return [{"id": r["guild_id"], "name": r["nome"]} for r in linhas]


# --------------------------------------------------------------------------
# Auditoria de moderação
# --------------------------------------------------------------------------

def registrar_auditoria(timestamp, ator_id, acao, alvo=None, guild_id=None, detalhe=None):
    with conexao() as conn:
        conn.execute(
            "INSERT INTO auditoria_moderacao (timestamp, ator_id, acao, alvo, guild_id, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, str(ator_id), acao, alvo, str(guild_id) if guild_id else None, detalhe),
        )


def listar_auditoria(limite=50):
    with conexao() as conn:
        linhas = conn.execute(
            "SELECT timestamp, ator_id, acao, alvo, guild_id, detalhe FROM auditoria_moderacao "
            "ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [dict(r) for r in linhas]
