"""Impressao digital da Gold por tabela e por dia, para provar que o backfill e idempotente.

Para cada tabela Delta da Gold e cada data_bh: numero de linhas, soma do hash das
colunas exatas (texto, inteiro, data) e, para cada coluna decimal, duas somas.
As somas nao dependem da ordem das linhas.

Coluna decimal nao entra no hash. O Spark soma em ordem diferente a cada execucao
e a media muda na 15a casa; arredondar antes do hash nao resolve, porque um valor
perto da fronteira (medido: 1 em cerca de 2.000 num dia) cai para um lado ou para
o outro e muda o hash sem que o resultado tenha mudado. Por isso a coluna decimal
vira soma simples e soma ponderada por um peso tirado das colunas exatas (o peso
pega valores trocados de linha), comparadas com tolerancia relativa de 1e-9.

Uso, no conteiner da Gold:
    python -m gold.digitais --saida /app/dados/digitais_completo.json
    python -m gold.digitais --comparar a.json b.json [--de 2026-10-19 --ate 2026-10-25]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

GOLD = Path("/app/dados/gold")
TABELAS = {
    "int": ["int_mapa_contagem", "int_mapa_parada", "int_feed_parado", "int_passagens", "int_headways"],
    "marts": ["fct_headway_parada_faixa", "fct_servico_linha_faixa", "fct_qualidade_diaria"],
}
TOLERANCIA = 1e-9


def digitais(spark, caminho: str, versao: int | None = None) -> dict[str, dict]:
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    leitor = spark.read.format("delta")
    if versao is not None:
        leitor = leitor.option("versionAsOf", versao)
    df = leitor.load(caminho)
    decimais = (T.DoubleType, T.FloatType, T.DecimalType)
    exatas = [F.col(c.name) for c in df.schema.fields if not isinstance(c.dataType, decimais)]
    flutuantes = sorted(c.name for c in df.schema.fields if isinstance(c.dataType, decimais))
    hash_linha = F.xxhash64(*exatas) if exatas else F.lit(0).cast("long")
    peso = (F.pmod(hash_linha, F.lit(997)) + 1).cast("double")
    grupo = F.col("data_bh").cast("string") if "data_bh" in df.columns else F.lit("todos")
    aggs = [F.count("*").alias("n"), F.sum(hash_linha.cast("decimal(38,0)")).cast("string").alias("h")]
    for i, c in enumerate(flutuantes):
        v = F.col(c).cast("double")
        aggs += [F.sum(v).alias(f"s{i}"), F.sum(v * peso).alias(f"w{i}")]
    linhas = df.groupBy(grupo.alias("dia")).agg(*aggs).collect()
    return {
        r.dia: {"n": r.n, "h": r.h, "f": {c: [r[f"s{i}"], r[f"w{i}"]] for i, c in enumerate(flutuantes)}}
        for r in linhas
    }


def gerar(saida: Path) -> None:
    from silver.processar import sessao
    spark = sessao("6g")
    spark.sparkContext.setLogLevel("WARN")
    resultado = {}
    for pasta, nomes in TABELAS.items():
        for nome in nomes:
            caminho = GOLD / pasta / nome
            if (caminho / "_delta_log").exists():
                resultado[nome] = digitais(spark, str(caminho))
    spark.stop()
    saida.write_text(json.dumps(resultado, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({t: sum(v["n"] for v in d.values()) for t, d in resultado.items()}))


def _perto(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=TOLERANCIA, abs_tol=TOLERANCIA)


def igual(a: dict | None, b: dict | None) -> bool:
    """Mesmo dia nas duas fotos: contagem e hash exatos, decimais com tolerancia."""
    if a is None or b is None:
        return a is b
    if a["n"] != b["n"] or a["h"] != b["h"] or set(a["f"]) != set(b["f"]):
        return False
    return all(_perto(x, y) for c in a["f"] for x, y in zip(a["f"][c], b["f"][c]))


def comparar(a: Path, b: Path, de: str | None, ate: str | None) -> int:
    da = json.loads(a.read_text(encoding="utf-8"))
    db = json.loads(b.read_text(encoding="utf-8"))
    diferencas = 0
    for tabela in sorted(set(da) | set(db)):
        ta, tb = da.get(tabela, {}), db.get(tabela, {})
        dias = sorted(set(ta) | set(tb))
        if de or ate:
            dias = [d for d in dias if d == "todos" or ((not de or d >= de) and (not ate or d <= ate))]
        errados = [d for d in dias if not igual(ta.get(d), tb.get(d))]
        diferencas += len(errados)
        print(json.dumps({"tabela": tabela, "dias": len(dias), "diferentes": len(errados),
                          "exemplos": errados[:10], "linhas": sum(ta[d]["n"] for d in dias if d in ta)}))
    print(json.dumps({"dias_diferentes": diferencas}))
    return 1 if diferencas else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Impressao digital da Gold por dia")
    p.add_argument("--saida", type=Path)
    p.add_argument("--comparar", nargs=2, type=Path)
    p.add_argument("--de")
    p.add_argument("--ate")
    args = p.parse_args(argv)
    if args.comparar:
        return comparar(*args.comparar, args.de, args.ate)
    if args.saida:
        gerar(args.saida)
        return 0
    p.error("use --saida ou --comparar")
    return 2


if __name__ == "__main__":
    sys.exit(main())
