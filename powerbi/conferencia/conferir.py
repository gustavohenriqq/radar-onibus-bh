"""Confere as medidas do Power BI contra o SQL do painel, recorte a recorte.

Segunda conta do relatorio: as 14 metricas de painel/consultas.py (METRICAS)
saem do modelo aberto no Desktop (DAX via ADOMD, dax.ps1) e do banco do
painel (SQL, usuario so leitura do PAINEL_URL), nos recortes de casos.json.
Toda metrica e razao de somas, entao as duas contas devem bater ate o erro
de arredondamento do double (tolerancia relativa de 1e-9).

Uso (Desktop aberto com powerbi/Radar.pbip, dados atualizados):
    .venv\\Scripts\\python.exe -I powerbi/conferencia/conferir.py [--caso nome] [--porta 12345]
Sai com codigo 1 se houver divergencia.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parents[1]
sys.path.insert(0, str(RAIZ))

from painel.consultas import METRICAS, filtro, sql_metricas  # noqa: E402

# Metrica do SQL -> medida do modelo (powerbi/modelo.py, pasta Base)
MEDIDAS = {
    "grupos": "Grupos", "headways": "Intervalos", "horas": "Horas de serviço",
    "regular_min": "Espera regular", "excesso_min": "Espera extra", "volume_min_h": "Volume",
    "colados_pct": "Colados", "abaixo_60s_pct": "Abaixo de 60 s", "reducao_pct": "Corte sem colagem",
    "pares": "Pares colados", "pulo_primeiro": "Colado no início", "pulo_colado": "Colado atrás de colado",
    "vies_min": "Viés de interpolação", "vies_pct": "Viés de interpolação %",
}
# Chave de agrupamento -> coluna da dimensao que filtra fato_linha
COLUNAS = {"route_id": "dim_linha[route_id]", "faixa_horaria": "dim_faixa[faixa_horaria]",
           "tipo_dia": "dim_tipo_dia[tipo_dia]"}
TOLERANCIA = 1e-9


def texto_dax(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def data_dax(d: str) -> str:
    a, m, dd = (int(x) for x in d.split("-"))
    return f"DATE ( {a}, {m}, {dd} )"


def consulta_dax(caso: dict) -> str:
    """SUMMARIZECOLUMNS com os filtros do caso; colunas de saida com o nome das metricas do SQL."""
    partes = [COLUNAS[c] for c in caso.get("agrupar", [])]
    partes.append(f"FILTER ( ALL ( dim_data[data] ), dim_data[data] >= {data_dax(caso['de'])} "
                  f"&& dim_data[data] <= {data_dax(caso['ate'])} )")
    if caso.get("tipo_dia"):
        partes.append(f"TREATAS ( {{ {texto_dax(caso['tipo_dia'])} }}, dim_tipo_dia[tipo_dia] )")
    if caso.get("alta_frequencia") is not None:
        freq = "alta" if caso["alta_frequencia"] else "baixa"
        partes.append(f'TREATAS ( {{ "{freq}" }}, dim_frequencia[frequencia] )')
    if caso.get("linhas"):
        lista = ", ".join(texto_dax(x) for x in caso["linhas"])
        partes.append(f"TREATAS ( {{ {lista} }}, dim_linha[route_id] )")
    medidas = [f'"{m}", [{MEDIDAS[m]}]' for m in METRICAS]
    return "EVALUATE\nSUMMARIZECOLUMNS (\n    " + ",\n    ".join(partes + medidas) + "\n)"


def sql_caso(caso: dict) -> tuple[str, list]:
    onde, params = filtro(date.fromisoformat(caso["de"]), date.fromisoformat(caso["ate"]),
                          caso.get("tipo_dia"), caso.get("alta_frequencia"), caso.get("linhas"))
    return sql_metricas(list(caso.get("agrupar", [])), onde), params


def nome_coluna(c: str) -> str:
    """'dim_linha[route_id]' ou '[grupos]' -> 'route_id' / 'grupos'."""
    return c[c.rfind("[") + 1:-1] if c.endswith("]") else c


def numero(v) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


def comparar(caso: dict, dax: list[dict], sql: list[dict]) -> tuple[int, list[str]]:
    """(numeros conferidos, divergencias). Chave = colunas de agrupamento."""
    chaves = list(caso.get("agrupar", []))
    def indexar(linhas):
        return {tuple(str(l[c]) for c in chaves): l for l in linhas}
    d = indexar([{nome_coluna(k): v for k, v in l.items()} for l in dax])
    s = indexar(sql)
    erros = [f"{caso['nome']}: {k} so no {'DAX' if k in d else 'SQL'}" for k in sorted(set(d) ^ set(s))]
    n = 0
    for k in sorted(set(d) & set(s)):
        for m in METRICAS:
            a, b = numero(d[k].get(m)), numero(s[k][m])
            n += 1
            if a is None and b is None:
                continue
            if a is None or b is None or not math.isclose(a, b, rel_tol=TOLERANCIA, abs_tol=TOLERANCIA):
                erros.append(f"{caso['nome']}: {k} {m} DAX={a} SQL={b}")
    return n, erros


def url_painel() -> str:
    if os.environ.get("PAINEL_URL"):
        return os.environ["PAINEL_URL"]
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.startswith("PAINEL_URL="):
                return linha.split("=", 1)[1].strip().strip("'\"")
    sys.exit("Falta PAINEL_URL (usuario so leitura) no ambiente ou no .env da raiz")


def rodar_dax(consulta: str, porta: int) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        q, saida = Path(tmp) / "q.dax", Path(tmp) / "r.json"
        q.write_text(consulta, encoding="utf-8")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PASTA / "dax.ps1"),
               "-DaxArquivo", str(q), "-Saida", str(saida)] + (["-Porta", str(porta)] if porta else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not saida.exists():
            sys.exit(f"DAX falhou (Desktop aberto com Radar.pbip?):\n{r.stderr or r.stdout}")
        return json.loads(saida.read_text(encoding="utf-8-sig") or "[]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", help="so este caso de casos.json")
    ap.add_argument("--porta", type=int, default=0, help="porta do motor do Desktop (padrao: a mais recente)")
    a = ap.parse_args()
    casos = json.loads((PASTA / "casos.json").read_text(encoding="utf-8"))["casos"]
    if a.caso:
        casos = [c for c in casos if c["nome"] == a.caso] or sys.exit(f"caso {a.caso} nao existe")

    import psycopg
    total, erros = 0, []
    with psycopg.connect(url_painel(), connect_timeout=60, application_name="conferencia-powerbi") as con:
        for caso in casos:
            sql, params = sql_caso(caso)
            cur = con.execute(sql, params)
            cols = [c.name for c in cur.description]
            linhas_sql = [dict(zip(cols, l)) for l in cur.fetchall()]
            linhas_dax = rodar_dax(consulta_dax(caso), a.porta)
            n, e = comparar(caso, linhas_dax, linhas_sql)
            print(f"{caso['nome']:<26} {len(linhas_sql):>4} linhas, {n:>5} numeros, {len(e)} divergencias")
            total += n
            erros += e
    for e in erros[:40]:
        print("  " + e)
    print(f"--- {total} numeros conferidos, {len(erros)} divergencias")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
