from eris.config import ANEXOS_MAX_BYTES_POR_MENSAGEM, ANEXOS_MAX_POR_MENSAGEM
from eris.core.mensagens import fatiar_mensagem, lotes_arquivos, nome_canal_valido


def testar_fatiar_curto_nao_corta():
    assert fatiar_mensagem("oi") == ["oi"]


def testar_fatiar_prefere_quebra_de_linha():
    texto = "a" * 15 + "\n" + "b" * 15
    assert fatiar_mensagem(texto, limite=20) == ["a" * 15, "b" * 15]


def testar_fatiar_sem_quebra_corta_no_limite():
    blocos = fatiar_mensagem("x" * 45, limite=20)
    assert [len(b) for b in blocos] == [20, 20, 5]


def testar_lotes_respeitam_quantidade():
    arquivos = [(f"{i}.txt", b"a") for i in range(ANEXOS_MAX_POR_MENSAGEM + 2)]
    lotes = lotes_arquivos(arquivos)
    assert [len(lote) for lote in lotes] == [ANEXOS_MAX_POR_MENSAGEM, 2]


def testar_lotes_respeitam_bytes_e_anexo_grande_vai_sozinho():
    grande = ("grande.bin", b"x" * (ANEXOS_MAX_BYTES_POR_MENSAGEM + 1))
    lotes = lotes_arquivos([("a.txt", b"a"), grande, ("b.txt", b"b")])
    assert [[nome for nome, _ in lote] for lote in lotes] == [["a.txt"], ["grande.bin"], ["b.txt"]]


def testar_nome_canal_valido():
    assert nome_canal_valido("  Notícias / Jogos!! ") == "notícias-jogos"
    assert nome_canal_valido("???") == "geral"
