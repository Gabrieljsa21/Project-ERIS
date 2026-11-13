import asyncio
import io
import json

from eris import api_bridge
from eris.core import mensagens, thoth
from eris.integrations import gaia_webhook

_DIA = 24 * 3600


def testar_custom_id_bate_com_o_template_e_cabe_no_limite():
    padrao = thoth.BotaoThoth.__discord_ui_compiled_template__
    for acao in thoth._BOTOES_THOTH:
        custom_id = f"thoth:{acao}:{'a' * 32}"
        match = padrao.fullmatch(custom_id)
        assert match and match["acao"] == acao and len(custom_id) <= 100


def testar_custom_id_recusa_acao_ou_id_invalidos():
    padrao = thoth.BotaoThoth.__discord_ui_compiled_template__
    for custom_id in ("thoth:apagar:abc123", "thoth:enviar:abc", "thoth:enviar:ABC123", "thoth:enviar:" + "a" * 33):
        assert not padrao.fullmatch(custom_id), custom_id


def testar_view_tem_os_tres_botoes_na_ordem_e_desabilita():
    view = thoth.ViewThoth("abc123", desabilitada=True)
    assert [item.item.custom_id for item in view.children] == [
        "thoth:enviar:abc123", "thoth:editar:abc123", "thoth:descartar:abc123",
    ]
    assert [item.item.label for item in view.children] == ["Enviar", "Editar", "Descartar"]
    assert all(item.item.disabled for item in view.children)


def testar_rascunho_guarda_texto_e_poda_mais_de_7_dias(tmp_path, monkeypatch):
    monkeypatch.setattr(thoth, "_ARQUIVO_RASCUNHOS", str(tmp_path / "thoth_rascunhos.json"))
    agora = 1_000_000_000
    thoth.registrar_rascunho("aaaaaa", "velho", agora=agora - 8 * _DIA)
    thoth.registrar_rascunho("bbbbbb", "recente", agora=agora - 6 * _DIA)
    thoth.registrar_rascunho("cccccc", "novo", agora=agora)
    assert thoth.texto_do_rascunho("aaaaaa") == ""
    assert thoth.texto_do_rascunho("bbbbbb") == "recente"
    thoth.esquecer_rascunho("bbbbbb")
    assert thoth.texto_do_rascunho("bbbbbb") == ""


def testar_status_cabe_no_limite_do_discord():
    assert thoth.conteudo_com_status("oi", "✅ Enviado") == "oi\n\n✅ Enviado"
    longo = thoth.conteudo_com_status("x" * 2000, "🗑️ Descartado")
    assert len(longo) <= 2000 and longo.endswith("🗑️ Descartado")


def testar_pedir_acao_thoth_com_gaia_fora(monkeypatch):
    monkeypatch.setattr(gaia_webhook, "_post", lambda caminho, corpo, timeout=None: None)
    assert gaia_webhook.pedir_acao_thoth(1, "abc123", "enviar") == {"ok": False, "mensagem": "GAIA fora do ar"}


def testar_pedir_acao_thoth_manda_o_corpo_do_contrato(monkeypatch):
    chamadas = []

    def falso_post(caminho, corpo, timeout=None):
        chamadas.append((caminho, corpo))
        return {"ok": True, "mensagem": "Enviado no WhatsApp."}

    monkeypatch.setattr(gaia_webhook, "_post", falso_post)
    resultado = gaia_webhook.pedir_acao_thoth(42, "abc123", "enviar", texto="editado")
    assert resultado == {"ok": True, "mensagem": "Enviado no WhatsApp."}
    assert chamadas == [("/eris/thoth_acao", {
        "discord_user_id": "42", "rascunho_id": "abc123", "acao": "enviar", "texto": "editado",
    })]
    assert gaia_webhook.timeout_da_rota("/eris/thoth_acao") >= 90


class _UsuarioFalso:
    def __init__(self):
        self.enviadas = []

    async def send(self, texto, view=None):
        self.enviadas.append((texto, view))


class _ClientFalso:
    def __init__(self):
        self.usuarios = {}

    async def fetch_user(self, id_):
        if id_ == 999:
            raise RuntimeError("bloqueou o bot")
        return self.usuarios.setdefault(id_, _UsuarioFalso())


def testar_dm_longa_poe_os_botoes_so_na_ultima_mensagem(monkeypatch):
    client = _ClientFalso()
    monkeypatch.setattr(mensagens, "_client_atual", client)
    texto = "a" * 1500 + "\n" + "b" * 1500
    entregues = asyncio.run(mensagens.notificar_donos_com_view(["1", "999"], texto, lambda: "view"))
    assert entregues == 1
    enviadas = client.usuarios[1].enviadas
    assert [view for _, view in enviadas] == [None, "view"]
    assert all(len(bloco) <= 2000 for bloco, _ in enviadas)


def _chamar_rota(monkeypatch, corpo):
    respostas = []
    handler = api_bridge._API.__new__(api_bridge._API)
    bruto = json.dumps(corpo).encode("utf-8")
    handler.path = "/notificar_donos_com_botoes"
    handler.command = "POST"
    handler.headers = {"Content-Length": str(len(bruto))}
    handler.rfile = io.BytesIO(bruto)
    monkeypatch.setattr(handler, "_responder_json", lambda dados, status=200: respostas.append((status, dados)), raising=False)
    handler.do_POST()
    return respostas


def testar_rota_guarda_rascunho_e_manda_dm(tmp_path, monkeypatch):
    monkeypatch.setattr(thoth, "_ARQUIVO_RASCUNHOS", str(tmp_path / "thoth_rascunhos.json"))
    despachadas = []

    def falso_rodar(coro):
        despachadas.append(coro.cr_frame.f_locals)
        coro.close()
        return 1

    monkeypatch.setattr(api_bridge, "_rodar_no_loop_do_bot", falso_rodar)
    respostas = _chamar_rota(monkeypatch, {
        "donos_ids": ["123"], "texto": "Fulano mandou oi.", "rascunho": {"id": "abc123def456", "texto": "Oi, tudo bem?"},
    })
    assert respostas == [(200, {"ok": True})]
    assert despachadas[0]["donos_ids"] == ["123"] and despachadas[0]["texto"] == "Fulano mandou oi."
    assert thoth.texto_do_rascunho("abc123def456") == "Oi, tudo bem?"


def testar_rota_recusa_corpo_invalido_e_bot_desconectado(tmp_path, monkeypatch):
    monkeypatch.setattr(thoth, "_ARQUIVO_RASCUNHOS", str(tmp_path / "thoth_rascunhos.json"))

    def falso_rodar(coro):
        coro.close()
        return None

    monkeypatch.setattr(api_bridge, "_rodar_no_loop_do_bot", falso_rodar)
    invalido = _chamar_rota(monkeypatch, {"donos_ids": ["123"], "texto": "oi", "rascunho": {"id": "XYZ"}})
    assert invalido[0][0] == 400 and invalido[0][1]["ok"] is False
    desconectado = _chamar_rota(monkeypatch, {"donos_ids": ["123"], "texto": "oi", "rascunho": {"id": "abc123"}})
    assert desconectado[0][0] == 503 and desconectado[0][1]["ok"] is False


class _InteracaoFalsa:
    def __init__(self):
        self.user = type("U", (), {"id": 42})()
        self.followups = []
        resposta = type("R", (), {})()

        async def defer(ephemeral=False):
            pass

        resposta.defer = defer
        self.response = resposta
        seguimento = type("F", (), {})()

        async def send(texto, ephemeral=False):
            self.followups.append(texto)

        seguimento.send = send
        self.followup = seguimento


class _MensagemFalsa:
    content = "Fulano mandou oi."

    def __init__(self):
        self.edicoes = []

    async def edit(self, content=None, view=None):
        self.edicoes.append((content, view))


def _executar(monkeypatch, tmp_path, resultado_gaia, acao):
    monkeypatch.setattr(thoth, "_ARQUIVO_RASCUNHOS", str(tmp_path / "thoth_rascunhos.json"))
    monkeypatch.setattr(gaia_webhook, "pedir_acao_thoth", lambda *args: resultado_gaia)
    thoth.registrar_rascunho("abc123", "Oi")
    interacao, mensagem = _InteracaoFalsa(), _MensagemFalsa()

    async def rodar():
        await thoth.executar_acao(interacao, "abc123", acao, None, mensagem)

    asyncio.run(rodar())
    return interacao, mensagem


def testar_acao_ok_desabilita_botoes_e_poe_status(tmp_path, monkeypatch):
    interacao, mensagem = _executar(monkeypatch, tmp_path, {"ok": True, "mensagem": "Descartado."}, "descartar")
    conteudo, view = mensagem.edicoes[0]
    assert conteudo == "Fulano mandou oi.\n\n🗑️ Descartado"
    assert all(item.item.disabled for item in view.children)
    assert interacao.followups == ["Descartado."]
    assert thoth.texto_do_rascunho("abc123") == ""


def testar_acao_com_falha_so_avisa_e_mantem_botoes(tmp_path, monkeypatch):
    interacao, mensagem = _executar(monkeypatch, tmp_path, {"ok": False, "mensagem": "GAIA fora do ar"}, "enviar")
    assert mensagem.edicoes == []
    assert interacao.followups == ["Falhou: GAIA fora do ar"]
    assert thoth.texto_do_rascunho("abc123") == "Oi"
