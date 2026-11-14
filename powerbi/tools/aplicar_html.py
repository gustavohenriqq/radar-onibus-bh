"""Recria a tabela _Medidas no modelo aberto no Desktop, sem reabrir (TMSL createOrReplace via tmsl.ps1).

O TMSL nao troca medida avulsa: a tabela inteira vem do gerador (todas as medidas), depois um refresh
"calculate" refaz a particao calculada.

Serve para iterar o desenho: o arquivo TMDL continua vindo do gerar_pbip.py. Os visuais mostram a medida
nova depois de "Atualizar visuais" (ou trocar de pagina). Nao salve o Desktop depois: ele regravaria o PBIP.

Uso: python -I powerbi/tools/aplicar_html.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PASTA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA))

from modelo import medidas, tag  # noqa: E402


def main() -> None:
    ms = []
    for nome, dax, fmt, pasta, doc, op in medidas():
        m = {"name": nome, "expression": dax, "displayFolder": pasta, "description": doc,
             "lineageTag": tag("medida", nome)}
        if fmt:
            m["formatString"] = fmt
        if op.get("oculta"):
            m["isHidden"] = True
        if op.get("imagem"):
            m["dataCategory"] = "ImageUrl"
        ms.append(m)
    tabela = {"name": "_Medidas", "lineageTag": tag("tabela", "_Medidas"), "measures": ms,
              "columns": [{"name": "x", "dataType": "int64", "isHidden": True, "sourceColumn": "[x]",
                           "type": "calculatedTableColumn", "isDataTypeInferred": True,
                           "lineageTag": tag("coluna", "_Medidas", "x")}],
              "partitions": [{"name": "_Medidas", "mode": "import",
                              "source": {"type": "calculated", "expression": 'ROW ( "x", 0 )'}}]}
    cmd = {"sequence": {"operations": [
        {"createOrReplace": {"object": {"database": "DB", "table": "_Medidas"}, "table": tabela}},
        {"refresh": {"type": "calculate", "objects": [{"database": "DB"}]}}]}}
    arq = Path(tempfile.gettempdir()) / "radar_medidas_tmsl.json"
    arq.write_text(json.dumps(cmd, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-File", str(PASTA / "tools" / "tmsl.ps1"), "-Arquivo", str(arq)],
                       capture_output=True, text=True)
    saida = (r.stdout + r.stderr).strip()
    if r.returncode or "Exce" in saida or "error" in saida.lower():
        sys.exit(saida[-800:])
    print(f"{saida} · {len(ms)} medidas")


if __name__ == "__main__":
    main()
