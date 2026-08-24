# Rafael Costa Plugins

Marketplace Codex/ChatGPT com o plugin **Project Continuity**.

Project Continuity transfere estado verificado de projeto entre ChatGPT e Codex. O que viaja é um checkpoint PCP/1, não o transcript da conversa.

| | |
|---|---|
| Marketplace | `rafaelscosta-plugins` |
| Plugin | `project-continuity` v1.0.0 |
| Superfícies | ChatGPT Desktop e Codex CLI |
| Tipo | Skills only — sem MCP |

## Instalação

Precisa do [Codex CLI](https://github.com/openai/codex) no `PATH`.

### Do GitHub (recomendado)

```bash
codex plugin marketplace add rafaelscosta/plugins
codex plugin add project-continuity --marketplace rafaelscosta-plugins
```

### Clone local

```bash
git clone https://github.com/rafaelscosta/plugins.git
cd plugins
./install.sh          # macOS / Linux
# .\install.ps1       # Windows PowerShell
```

O script valida o pacote, registra esta pasta como marketplace e instala o plugin. Não mova a pasta depois — o Codex guarda esse caminho.

### ChatGPT Desktop

1. Instale pelo Codex CLI (passos acima).
2. Reinicie o ChatGPT Desktop.
3. Abra **Plugins** e escolha **Rafael Costa Plugins**.
4. Instale **Project Continuity** se ainda não estiver instalado.
5. Abra uma **conversa nova**. A skill antiga pode ficar em memória na sessão atual.

O ChatGPT **web** não vê marketplace local/GitHub. Use Desktop ou Codex CLI.

## Uso

Um arquivo de interchange: `~/Downloads/pcp-handoff.json`.

### ChatGPT → Codex

No ChatGPT, com o plugin ativo:

```text
Handoff to Codex
```

A skill deve responder **só** com um JSON PCP/1 válido (template portable). Salve esse JSON em `~/Downloads/pcp-handoff.json`.

No repositório, no Codex:

```bash
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

Ou diga **Handoff in**. O consume vira um draft de reconciliação. Claims de “done” entram como `reported` até você provar de novo no repo. Não promova o HEAD sem evidência local.

### Codex → ChatGPT

No repositório:

```bash
python3 <skill-root>/scripts/continuity.py handoff-out --root .
```

Ou diga **Handoff out**. Isso copia o HEAD sealed para `~/Downloads/pcp-handoff.json`. Anexe esse arquivo no ChatGPT e peça para consumir como checkpoint sealed FULL — sem reescrever como prosa portable.

`<skill-root>` no clone é:

```text
plugins/project-continuity/skills/project-continuity
```

Depois de instalar pelo marketplace, o Codex resolve o path da skill sozinho.

### Trabalho só no Codex (mesmo repo)

Não precisa do JSON. Peça inspect/doctor/checkpoint no projeto. O estado canônico fica em `.continuity/`.

## CLI

```bash
python3 plugins/project-continuity/skills/project-continuity/scripts/continuity.py \
  init --root . --project-name "Meu projeto"

python3 plugins/project-continuity/skills/project-continuity/scripts/continuity.py \
  handoff-out --root .

python3 plugins/project-continuity/skills/project-continuity/scripts/continuity.py \
  handoff-in --root .

python3 plugins/project-continuity/skills/project-continuity/scripts/continuity.py \
  verify --root . --json

python3 plugins/project-continuity/skills/project-continuity/scripts/continuity.py \
  doctor --root . --json
```

`--out` e `--checkpoint` só se o arquivo não estiver em `~/Downloads/pcp-handoff.json`.

`handoff-in` não promove o HEAD. `consume` continua disponível para um path arbitrário.

## Validar o pacote

```bash
python3 plugins/project-continuity/scripts/validate_plugin.py plugins/project-continuity
python3 -m unittest discover -s plugins/project-continuity/skills/project-continuity/tests -v
```

## Estrutura

```text
.agents/plugins/marketplace.json
plugins/project-continuity/
```

Este repositório é o catálogo. Cada pasta em `plugins/` é um plugin. Project Continuity é o primeiro.

## Remover

```bash
codex plugin marketplace remove rafaelscosta-plugins
```
