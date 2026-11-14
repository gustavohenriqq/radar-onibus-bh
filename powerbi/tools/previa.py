"""Previa de uma pagina sem abrir o Power BI: arte de fundo + paineis HTML avaliados no motor do Desktop.

Cada medida HTML da pagina e avaliada no modelo aberto (via avaliar_texto.ps1) com o periodo escolhido,
e o resultado e posto sobre fundo_<pagina>.png nas mesmas posicoes do relatorio. O Edge fotografa.
A tabela eventos e definida na propria consulta a partir do gerador, para a previa valer antes de
atualizar o modelo. Visuais nativos (filtros, menu) nao aparecem.

Uso: python -I powerbi/tools/previa.py visao [7|28|tudo]
Saida: powerbi/arte/html/previa_<pagina>_<periodo>.png
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA))

import modelo  # noqa: E402
import paineis  # noqa: E402
from arte import EDGE  # noqa: E402
from relatorio import POR_CHAVE, area_html  # noqa: E402

SAIDA = PASTA / "arte" / "html"
PERIODOS = {"7": "Últimos 7 dias", "28": "Últimos 28 dias", "tudo": "Tudo desde 15/09"}  # apelido sem acento


def consulta(dax: str, periodo: str) -> str:
    eventos = modelo.calc_eventos()
    dax = dax.replace("FILTER ( eventos,", "FILTER ( eventos_p,").replace("eventos[", "eventos_p[")
    return (f"DEFINE\n    TABLE eventos_p = {eventos}\n    MEASURE _Medidas[__T] =\n{dax}\n"
            f'EVALUATE CALCULATETABLE ( ROW ( "v", [__T] ), sel_periodo[periodo] = "{periodo}" )')


def main() -> None:
    chave = sys.argv[1] if len(sys.argv) > 1 else "visao"
    periodo = PERIODOS[sys.argv[2] if len(sys.argv) > 2 else "28"]
    pag = POR_CHAVE[chave]
    SAIDA.mkdir(parents=True, exist_ok=True)
    blocos = []
    for (pg, painel), (nome, fn, _) in paineis.PAINEIS.items():
        if pg != chave:
            continue
        x, y, w, h = area_html(pag.p(painel))
        q = SAIDA / f"q_{painel}.dax"
        v = SAIDA / f"v_{painel}.html"
        q.write_text(consulta(fn(w, h), periodo), encoding="utf-8")
        r = subprocess.run(["powershell", "-NoProfile", "-File", str(PASTA / "tools" / "avaliar_texto.ps1"),
                            "-DaxArquivo", str(q), "-Saida", str(v)], capture_output=True, text=True)
        if r.returncode or r.stderr.strip():
            sys.exit(f"{nome}: {r.stderr.strip()[:800]}")
        blocos.append(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
                      f'{v.read_text(encoding="utf-8")}</div>')
        print(f"{nome}: {v.stat().st_size // 1024} KB")
    fundo = (PASTA / "arte" / f"fundo_{chave}.png").as_uri()
    html = (f'<!doctype html><html><head><meta charset="utf-8"><style>*{{margin:0;padding:0}}'
            f'body{{width:{pag.largura}px;height:{pag.altura}px;position:relative;overflow:hidden;'
            f'background:url("{fundo}") 0 0/100% 100%}}</style></head><body>{"".join(blocos)}</body></html>')
    arq = SAIDA / f"previa_{chave}.html"
    arq.write_text(html, encoding="utf-8")
    png = SAIDA / f"previa_{chave}_{sys.argv[2] if len(sys.argv) > 2 else '28'}.png"
    png.unlink(missing_ok=True)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--user-data-dir={SAIDA / 'perfil_edge'}", "--no-first-run", "--allow-file-access-from-files",
                    f"--window-size={pag.largura},{pag.altura}", "--virtual-time-budget=4000",
                    f"--screenshot={png}", arq.as_uri()], check=True, capture_output=True, timeout=180)
    for _ in range(60):  # o Edge devolve o controle antes de terminar de gravar
        if png.exists() and png.stat().st_size:
            break
        time.sleep(0.5)
    print(png)


if __name__ == "__main__":
    main()
