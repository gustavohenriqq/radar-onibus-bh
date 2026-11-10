"""Segunda conta do painel: o banco de servico bate com os CSVs da analise?

Na janela da analise (15/09 a 05/11), as metricas calculadas em SQL sobre
radar.linha_dia_faixa e radar.hist_dia tem de dar os numeros de
analise/saida/*.csv, com tolerancia de meia casa decimal (o CSV vem
arredondado). Roda onde ha NEON_URL, no conteiner radar-spark:dev:

    docker run --rm -v /home/ubuntu/radar:/app radar-spark:dev python -m painel.conciliar

Sai com codigo 1 se algum numero nao bater ou se o banco vier vazio.
"""
import csv
import sys
from datetime import date
from pathlib import Path

from painel.consultas import ESQUEMA, METRICAS, filtro, sql_metricas

INI, FIM = date(2026, 9, 15), date(2026, 11, 5)
SAIDA = Path(__file__).resolve().parent.parent / "analise" / "saida"

# CSV da analise: (chaves, filtro extra). A faixa entra pela ordem e pelo nome.
RECORTES = {
    "rede": (["tipo_dia", "alta_frequencia"], {}),
    "rede_faixa": (["tipo_dia", "alta_frequencia", "ordem_faixa", "faixa_horaria"], {}),
    "linhas": (["tipo_dia", "alta_frequencia", "route_id"], {}),
    "linhas_faixa_dia_util": (["route_id", "ordem_faixa", "faixa_horaria"],
                              {"tipo_dia": "dia_util", "alta_frequencia": True}),
}


def ler_csv(nome: str) -> list[dict]:
    with open(SAIDA / f"{nome}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def comparar(nome: str, esperado: list[dict], obtido: list[dict], chaves: list[str], metricas) -> list[str]:
    """Lista de divergencias (vazia = bateu). Confere tambem que nada sobra ou falta."""
    erros = []
    if not esperado:
        return [f"{nome}: CSV vazio"]
    exp = {tuple(r[c] for c in chaves): r for r in esperado}
    # str() do Postgres e do Spark coincidem: True/False, inteiros sem .0.
    obt = {tuple(str(r[c]) for c in chaves): r for r in obtido}
    for k in sorted(set(exp) ^ set(obt)):
        erros.append(f"{nome} {k}: so {'no CSV' if k in exp else 'no banco'}")
    for k in sorted(set(exp) & set(obt)):
        for m, casas in metricas:
            e, o = exp[k][m], obt[k][m]
            if e == "" or o is None:
                if not (e == "" and o is None):
                    erros.append(f"{nome} {k} {m}: CSV {e!r}, banco {o!r}")
                continue
            tol = 0.5 * 10 ** -casas + 1e-9
            if abs(float(e) - float(o)) > tol:
                erros.append(f"{nome} {k} {m}: CSV {e}, banco {o}")
    return erros


def conciliar(con) -> tuple[int, list[str]]:
    """(numeros conferidos, divergencias)."""
    metricas = [(m, casas) for m, (_, casas) in METRICAS.items()]
    conferidos, erros = 0, []
    with con.cursor() as cur:
        for nome, (chaves, extra) in RECORTES.items():
            onde, params = filtro(INI, FIM, **extra)
            cur.execute(sql_metricas(chaves, onde), params)
            cols = [d.name for d in cur.description]
            obtido = [dict(zip(cols, r)) for r in cur.fetchall()]
            esperado = ler_csv(nome)
            erros += comparar(nome, esperado, obtido, chaves, metricas)
            conferidos += len(esperado) * len(metricas)

        cur.execute(f"""select tipo_dia, alta_frequencia, classe, sum(headways) as headways
                        from {ESQUEMA}.hist_dia where data_bh between %s and %s
                        group by 1, 2, 3""", (INI, FIM))
        cols = [d.name for d in cur.description]
        obtido = [dict(zip(cols, r)) for r in cur.fetchall()]
        esperado = ler_csv("hist_h_sobre_media")
        erros += comparar("hist", esperado, obtido, ["tipo_dia", "alta_frequencia", "classe"], [("headways", 0)])
        conferidos += len(esperado)
    return conferidos, erros


def main():
    import psycopg

    from servico.exportar import url_do_banco
    url = url_do_banco()
    if not url:
        sys.exit("NEON_URL nao definida")
    with psycopg.connect(url, connect_timeout=60) as con:
        conferidos, erros = conciliar(con)
    for e in erros[:30]:
        print(e)
    print(f"{conferidos} numeros conferidos, {len(erros)} divergencias")
    sys.exit(1 if erros or conferidos == 0 else 0)


if __name__ == "__main__":
    main()
