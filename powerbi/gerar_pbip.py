"""Gera o projeto Power BI do radar (PBIP: modelo em TMDL e relatorio em PBIR).

Le a camada de servico no Neon (esquema radar), a mesma do painel web. O
modelo vem de modelo.py, as paginas de relatorio.py e a arte de fundo de
arte.py (rode arte.py antes quando o layout mudar).

O endereco do Neon sai do PAINEL_URL do .env da raiz e entra no parametro
ServidorPostgres. No Git ele vira um marcador: o filtro tools/git_censura.py
troca na hora do commit (git config feita por este script, uma vez por clone).
A senha nunca passa por aqui: o Power BI Desktop pede na primeira atualizacao.

Uso: python -I powerbi/gerar_pbip.py
     Depois, no Desktop: abrir Radar.pbip (ou "Aplicar alteracoes externas").
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
sys.path.insert(0, str(PASTA))

import modelo  # noqa: E402
import relatorio  # noqa: E402

NOME = "Radar"
MODELO = PASTA / f"{NOME}.SemanticModel"
RELATORIO = PASTA / f"{NOME}.Report"
MARCADOR_HOST = "SEU-ENDPOINT.neon.tech"
MARCADOR_BANCO = "neondb"


def endereco() -> tuple[str, str]:
    """(host, banco) do PAINEL_URL no .env; marcadores se nao houver .env."""
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.startswith("PAINEL_URL="):
                u = urlparse(linha.split("=", 1)[1].strip().strip("'\""))
                return u.hostname or MARCADOR_HOST, (u.path or "/").lstrip("/") or MARCADOR_BANCO
    return MARCADOR_HOST, MARCADOR_BANCO


def preparar_censura(host: str) -> None:
    """Par host -> marcador em .git/censura.txt e o filtro no git config deste clone."""
    if host == MARCADOR_HOST:
        return
    git_dir = Path(subprocess.run(["git", "rev-parse", "--git-dir"], cwd=RAIZ, capture_output=True,
                                  text=True).stdout.strip() or ".git")
    if not git_dir.is_absolute():
        git_dir = RAIZ / git_dir
    (git_dir / "censura.txt").write_text(f"{host}\t{MARCADOR_HOST}\n", encoding="utf-8")
    script = "powerbi/tools/git_censura.py"
    for modo in ("clean", "smudge"):
        subprocess.run(["git", "config", f"filter.censura.{modo}", f"python -I {script} {modo}"], cwd=RAIZ, check=True)


def gravar(caminho: Path, conteudo: str | dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(conteudo, dict):
        conteudo = json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n"
    caminho.write_text(conteudo, encoding="utf-8", newline="\n")


def gerar_modelo(host: str, banco: str) -> None:
    shutil.rmtree(MODELO / "definition", ignore_errors=True)
    gravar(MODELO / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    for rel, texto in modelo.arquivos_modelo(host, banco).items():
        gravar(MODELO / "definition" / rel, texto)


def visual_proprio() -> dict:
    """Desempacota o carrossel (recursos/<guid>.pbiviz, gerado em powerbi/carrossel) dentro do relatorio.

    O .pbiviz e um zip com package.json e resources/<guid>.pbiviz.json (JS, CSS e icone juntos).
    O PBIR guarda o mesmo par em CustomVisuals/<guid>/ e lista no report.json como pacote CustomVisual.
    """
    guid = relatorio.CARROSSEL
    pacote = PASTA / "recursos" / f"{guid}.pbiviz"
    if not pacote.exists():
        sys.exit(f"Falta {pacote.name}: rode npx pbiviz package em powerbi/carrossel e copie o dist para recursos/")
    destino = RELATORIO / "CustomVisuals" / guid
    with zipfile.ZipFile(pacote) as z:
        for nome in ("package.json", f"resources/{guid}.pbiviz.json"):
            (destino / nome).parent.mkdir(parents=True, exist_ok=True)
            (destino / nome).write_bytes(z.read(nome))
    # Formato copiado do que o Desktop grava (Salvar como, 14/11): item com o nome do pbiviz.json,
    # caminho relativo a resources/. Com "package.json" ou "resources/..." o Desktop ignora o visual.
    nome = f"{guid}.pbiviz.json"
    return {"name": guid, "type": "CustomVisual", "items": [{"name": nome, "path": nome, "type": "CustomVisualMetadata"}]}


def gerar_relatorio() -> None:
    shutil.rmtree(RELATORIO / "definition", ignore_errors=True)
    shutil.rmtree(RELATORIO / "StaticResources", ignore_errors=True)
    shutil.rmtree(RELATORIO / "CustomVisuals", ignore_errors=True)
    proprio = visual_proprio()
    d = RELATORIO / "definition"
    rr = RELATORIO / "StaticResources" / "RegisteredResources"
    base = RELATORIO / "StaticResources" / "SharedResources" / "BaseThemes"
    base.mkdir(parents=True)
    rr.mkdir(parents=True)
    shutil.copy(PASTA / "recursos" / "Fluent2-CY26SU09.json", base / "Fluent2-CY26SU09.json")
    gravar(rr / "tema-radar.json", relatorio.tema())
    imagens = sorted(p.name for p in (PASTA / "arte").glob("fundo_*.png"))
    faltam = {f"fundo_{p.chave}.png" for p in relatorio.PAGINAS} - set(imagens)
    if faltam:
        sys.exit(f"Falta a arte {sorted(faltam)}: rode python -I powerbi/arte.py")
    for nome in imagens:
        shutil.copy(PASTA / "arte" / nome, rr / nome)

    gravar(RELATORIO / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NOME}.SemanticModel"}}})
    gravar(d / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"})
    versao = {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"}
    L = relatorio.L
    gravar(d / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "Fluent2-CY26SU09", "reportVersionAtImport": versao, "type": "SharedResources"},
            "customTheme": {"name": "tema-radar.json", "reportVersionAtImport": versao, "type": "RegisteredResources"}},
        "publicCustomVisuals": [relatorio.HTML_VISUAL],
        "objects": {"section": [{"properties": {"verticalAlignment": L("'Top'")}}],
                    "outspacePane": [{"properties": {"expanded": L("false")}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "Fluent2-CY26SU09", "path": "BaseThemes/Fluent2-CY26SU09.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "tema-radar.json", "path": "tema-radar.json", "type": "CustomTheme"}]
             + [{"name": n, "path": n, "type": "Image"} for n in imagens]},
            proprio,
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })

    paginas = relatorio.construir()
    for pg in paginas:
        pd = d / "pages" / pg.nome
        gravar(pd / "page.json", pg.json_pagina())
        for v in pg.visuais:
            gravar(pd / "visuals" / v["name"] / "visual.json", v)
    gravar(d / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [pg.nome for pg in paginas], "activePageName": paginas[0].nome})


def main() -> None:
    host, banco = endereco()
    gravar(PASTA / f"{NOME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NOME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    gerar_modelo(host, banco)
    gerar_relatorio()
    preparar_censura(host)
    n_vis = sum(1 for _ in RELATORIO.glob("definition/pages/*/visuals/*/visual.json"))
    print(f"{NOME}.pbip: {len(modelo.medidas())} medidas, {len(relatorio.PAGINAS)} paginas, {n_vis} visuais"
          + ("" if host != MARCADOR_HOST else " (sem .env: servidor com marcador)"))


if __name__ == "__main__":
    main()
