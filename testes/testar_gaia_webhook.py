from eris.integrations import gaia_webhook


def testar_timeout_sempre_maior_que_a_espera_da_gaia():
    for rota, espera in gaia_webhook._ESPERA_DA_GAIA_POR_ROTA.items():
        assert gaia_webhook.timeout_da_rota(rota) > espera, rota


def testar_comando_nao_e_mais_30s():
    assert gaia_webhook.timeout_da_rota("/eris/comando") >= 90


def testar_rota_sem_entrada_usa_padrao():
    assert gaia_webhook.timeout_da_rota("/eris/musica_voto") == gaia_webhook.TIMEOUT_SEGUNDOS
