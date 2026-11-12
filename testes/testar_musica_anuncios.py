from eris.core import musica


def testar_anuncio_guarda_faixa_e_limita_tamanho(tmp_path, monkeypatch):
    monkeypatch.setattr(musica, "_ARQUIVO_ANUNCIOS", str(tmp_path / "anuncios.json"))
    monkeypatch.setattr(musica, "_ANUNCIOS_MAX", 3)
    for i in range(5):
        musica.registrar_anuncio(i, f"Artista {i}", f"Faixa {i}")
    assert musica.faixa_do_anuncio(4) == ("Artista 4", "Faixa 4")
    assert musica.faixa_do_anuncio(1) == (None, None)  # o mais antigo saiu


def testar_custom_id_bate_com_o_template_e_cabe_no_limite():
    padrao = musica.BotaoMusica.__discord_ui_compiled_template__
    for acao in musica._BOTOES_MUSICA:
        custom_id = f"eris_musica:{acao}:{2 ** 63}"
        assert padrao.fullmatch(custom_id) and len(custom_id) <= 100
        assert hasattr(musica._ControlesMusica, f"_{acao}")


def testar_view_tem_os_seis_botoes_na_ordem():
    view = musica._ViewControlesMusica(123, "A", "T")
    assert [item.item.custom_id.split(":")[1] for item in view.children] == list(musica._BOTOES_MUSICA)
