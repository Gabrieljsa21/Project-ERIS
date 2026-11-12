import pytest

from eris import db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "CAMINHO_BANCO", str(tmp_path / "eris.db"))
    monkeypatch.setattr(db, "PASTA_DADOS", str(tmp_path))
    db._invalidar_cache()
    db.inicializar()
    yield
    db._invalidar_cache()


def testar_cache_de_donos_invalida_ao_salvar(banco):
    assert db.ids_donos_ativos() == frozenset()
    db.salvar_donos([{"id": "1", "nome": "A", "ativo": True}, {"id": "2", "nome": "B", "ativo": False}])
    assert db.ids_donos_ativos() == {"1"}


def testar_cache_de_roteamento_invalida_ao_salvar(banco):
    assert db.obter_config_roteamento()["discord_active"] is False
    db.salvar_config_roteamento("discord_active", True)
    db.definir_guild_desativado(99, True)
    cfg = db.obter_config_roteamento()
    assert cfg["discord_active"] is True and cfg["disabled_guilds"] == ["99"]


def testar_copia_devolvida_nao_altera_o_cache(banco):
    db.obter_config_roteamento()["disabled_guilds"].append("x")
    assert db.obter_config_roteamento()["disabled_guilds"] == []


def testar_bootstrap_so_quando_vazio(banco):
    db.importar_donos_bootstrap(["10"])
    db.importar_donos_bootstrap(["20"])
    assert db.ids_donos_ativos() == {"10"}
