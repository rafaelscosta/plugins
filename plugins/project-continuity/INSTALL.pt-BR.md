# Instalação e teste local

## Caminho recomendado

Use o pacote separado:

```text
project-continuity-local-marketplace-v1.0.0.zip
```

Descompacte-o em uma pasta permanente. O marketplace registra o caminho dessa pasta.

### macOS ou Linux

```bash
cd project-continuity-local-marketplace
./install.sh
```

### Windows PowerShell

```powershell
Set-Location project-continuity-local-marketplace
.\install.ps1
```

Depois:

1. reinicie o ChatGPT Desktop;
2. abra **Plugins** e selecione **Rafael Local Plugins**;
3. instale **Project Continuity**;
4. abra uma nova conversa;
5. no Codex CLI, use `/plugins`, instale o plugin e abra uma nova sessão.

## Teste inicial no ChatGPT

```text
Use Project Continuity to create a PCP/1 portable checkpoint for this conversation. Separate reported claims from verified evidence and do not claim repository access.
```

## Teste inicial no Codex

```text
Use Project Continuity to inspect this repository, initialize PCP/1 if needed, run the continuity doctor, and report the verified baseline without changing application code.
```

## Publicação

O ZIP principal é um pacote **Skills only** preparado para o portal de submissão. A publicação pública ainda depende da identidade verificada do desenvolvedor, da permissão Apps Management: Write, dos testes do portal e da aprovação da OpenAI.
