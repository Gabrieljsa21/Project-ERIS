<p align="center">
  <img src="assets/icone_eris.png" alt="Project ERIS" width="180">
</p>

# Project ERIS

Bot de Discord que cuida da conexão, segurança, moderação, mensagens, exportação de canais e voz.

## Recursos principais

- comandos de moderação e controle de cargos e canais;
- mensagens diretas, menções e respostas em canais permitidos;
- exportação de canais para JSON;
- modos de conversa por voz;
- reprodução musical em uma instância separada;
- ícone na bandeja e reinício automático após falhas.

## Origem do nome

ERIS vem de Éris (Ἔρις), deusa grega da discórdia, da rivalidade e da contenda. O próprio nome grego está ligado a disputa e conflito. A ligação com o Discord é direta: **Éris → discórdia → Discord**.

No mito, Éris usa a Maçã Dourada para provocar a disputa que leva ao Julgamento de Páris. Por isso, a maçã dourada virou o símbolo do projeto.

### Identidade visual

A logo mostra uma maçã dourada fragmentada, com um núcleo escuro atravessado por energia azul. A maçã remete à Maçã da Discórdia, enquanto os fragmentos sugerem instabilidade e efeitos que se espalham.

A energia azul leva o símbolo mitológico para a paleta tecnológica do ecossistema. A composição reúne **maçã → fragmentação → discórdia → Discord**.

## Requisitos

- Python 3.11 ou mais recente;
- bot criado no Discord;
- token do bot no arquivo `.env`.

## Instalação e uso

```powershell
uv venv
uv pip install -e .
Copy-Item .env.example .env
python -m eris.main
```

Preencha `DISCORD_BOT_TOKEN` no `.env`. `DISCORD_OWNER_IDS` define os donos na primeira execução. Depois disso, a lista fica salva em `data/eris.db`.

Em uso diário, `iniciar_eris_oculto.vbs` abre as instâncias principal e de música sem terminais visíveis. O ícone da bandeja permite ver logs, reiniciar e encerrar as duas instâncias. Use `encerrar_eris.ps1` somente quando o ícone não responder.

## Integrações com outros projetos

- **GAIA:** cria o conteúdo das conversas, interpreta voz e envia mensagens programadas. Se estiver desligada, os recursos locais do bot continuam ativos.
- **ECHO:** escolhe músicas com base no gosto de cada pessoa e evita repetições durante a sessão.
- **PANDORA:** acrescenta o colecionador de personagens, incluindo rolls, claims, afinidade, loja, party, batalhas e eventos.

## Documentação

- [Arquitetura](docs/ARQUITETURA.md)
- [Pendências](docs/TODO.md)
- [Histórico de versões](CHANGELOG.md)
- [Padrão de documentação](docs/PADRAO_DOCUMENTACAO.md)

## Situação atual

O bot principal e o bot de música rodam em processos separados. Moderação, mensagens, exportação, voz e a ponte local estão em uso.
