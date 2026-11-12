from eris.persistencia import ler_json, salvar_json_atomico


def testar_salva_e_le(tmp_path):
    caminho = tmp_path / "sub" / "x.json"
    salvar_json_atomico(str(caminho), {"ação": [1, 2]})
    assert ler_json(str(caminho)) == {"ação": [1, 2]}
    assert not (tmp_path / "sub" / "x.json.tmp").exists()


def testar_arquivo_ausente_ou_corrompido_devolve_padrao(tmp_path):
    assert ler_json(str(tmp_path / "nada.json"), {}) == {}
    corrompido = tmp_path / "ruim.json"
    corrompido.write_text('{"metade": ', encoding="utf-8")
    assert ler_json(str(corrompido), []) == []
