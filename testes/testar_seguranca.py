import pytest

from eris.config import RATE_LIMIT_JANELA_SEGUNDOS, RATE_LIMIT_MAX_MENSAGENS
from eris.core import seguranca

CONFIG_PADRAO = {
    "discord_active": True, "server_active": False, "mentions": True,
    "target_user_active": False, "target_user_name": "", "disabled_guilds": [],
}


@pytest.fixture
def config(monkeypatch):
    cfg = dict(CONFIG_PADRAO)
    monkeypatch.setattr(seguranca.db, "obter_config_roteamento", lambda: cfg)
    return cfg


def _processa(**kw):
    base = dict(eh_bot_ou_webhook=False, em_dm=False, guild_id=1, mencionada=False, nome_exibicao="Fulano", nome_usuario="fulano")
    base.update(kw)
    return seguranca.deve_processar_mensagem(**base)


def testar_bot_nunca_passa(config):
    assert not _processa(eh_bot_ou_webhook=True, em_dm=True)


def testar_master_switch_desligado_bloqueia_ate_dm(config):
    config["discord_active"] = False
    assert not _processa(em_dm=True)


def testar_dm_sempre_passa(config):
    assert _processa(em_dm=True, guild_id=None)


def testar_servidor_so_com_mencao(config):
    assert not _processa()
    assert _processa(mencionada=True)


def testar_servidor_desativado_ignora_mencao(config):
    config["disabled_guilds"] = ["1"]
    assert not _processa(mencionada=True)


def testar_usuario_em_foco(config):
    config.update(target_user_active=True, target_user_name="@Fula")
    assert _processa()


def testar_limite_excedido_e_poda(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(seguranca.time, "monotonic", lambda: agora[0])
    monkeypatch.setattr(seguranca, "_mensagens_por_remetente", {})
    monkeypatch.setattr(seguranca, "_ultimo_aviso_limite", {})
    monkeypatch.setattr(seguranca, "_proxima_poda", 0.0)
    resultados = [seguranca.limite_excedido("a") for _ in range(RATE_LIMIT_MAX_MENSAGENS + 1)]
    assert resultados[-1] and not any(resultados[:-1])
    assert seguranca.deveria_avisar_limite("a") and not seguranca.deveria_avisar_limite("a")

    agora[0] += RATE_LIMIT_JANELA_SEGUNDOS * 3
    assert not seguranca.limite_excedido("b")
    assert "a" not in seguranca._mensagens_por_remetente
    assert "a" not in seguranca._ultimo_aviso_limite
