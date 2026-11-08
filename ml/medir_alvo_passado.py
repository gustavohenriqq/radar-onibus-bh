"""Ressalva 10 de docs/ml.md: o onibus B ja tinha passado por s+10 na decisao?

    docker run --rm --memory 4g -v /home/ubuntu/radar:/app -w /app radar-ml:dev \
        python -m ml.medir_alvo_passado

A decisao acontece quando chega a posicao de GPS que fecha a passagem de B em s
(decisao_unix). Se um unico intervalo de GPS cobre s e s+10, a passagem em s+10
ja aconteceu nesse instante: minutos_ate_alvo <= 0. As features nao veem o alvo,
mas o exemplo deixa de ser previsao. Aqui se conta quantos sao e se refaz a
PR-AUC de validacao e teste sem eles, com as previsoes ja gravadas por
ml.treinar --teste (nada e treinado nem escolhido de novo).

Grava saida/alvo_passado.csv.
"""
import os

import pandas as pd
import pyarrow.dataset as ds
from sklearn.metrics import average_precision_score

DADOS = os.environ.get("ML_DADOS", "/app/dados/ml")
CHAVE = ["viagem_id", "stop_sequence", "decisao_unix", "conjunto"]


def resumo(conjunto, recorte, s):
    y = s["alvo"].astype(int)
    alerta = s["alerta"]
    return {
        "conjunto": conjunto, "recorte": recorte, "exemplos": len(s),
        "taxa_base": round(float(y.mean()), 4),
        "pr_auc_gbm": round(average_precision_score(y, s["prob"]), 4),
        "pr_auc_persistencia": round(average_precision_score(y, -s["h_rel"]), 4),
        "alertas": int(alerta.sum()),
        "precisao": round(float(y[alerta].mean()), 4) if alerta.any() else None,
        "cobertura": round(float(y[alerta].sum() / y.sum()), 4),
    }


def medir(pv, ex):
    x = pv.merge(ex, on=CHAVE, how="left", validate="one_to_one")
    if x["minutos_ate_alvo"].isna().any():
        raise ValueError("previsao sem exemplo correspondente")
    linhas = []
    for conjunto, g in x.groupby("conjunto", sort=False):
        ja = g["minutos_ate_alvo"] <= 0
        linhas += [resumo(conjunto, "todos", g),
                   resumo(conjunto, "sem_alvo_passado", g[~ja]),
                   resumo(conjunto, "so_alvo_passado", g[ja])]
    return pd.DataFrame(linhas)


def contar_todos(ex_todos):
    """Fracao com minutos_ate_alvo <= 0 em cada conjunto, treino incluido."""
    g = ex_todos.assign(ja=ex_todos["minutos_ate_alvo"] <= 0).groupby("conjunto", sort=False)
    return g.agg(exemplos=("ja", "size"), alvo_passado=("ja", "sum")).reset_index()


def principal():
    pv = pd.read_parquet(f"{DADOS}/previsoes.parquet", columns=CHAVE + ["alvo", "prob", "alerta"])
    dados = ds.dataset(f"{DADOS}/exemplos", format="parquet", partitioning="hive")
    ex = dados.to_table(columns=CHAVE + ["minutos_ate_alvo", "h_rel"]).to_pandas()
    contagem = contar_todos(ex)
    r = medir(pv, ex[ex["conjunto"].isin(["validacao", "teste"])])
    r = r.merge(contagem.rename(columns={"exemplos": "exemplos_conjunto"}), on="conjunto", how="left")
    extra = contagem[~contagem["conjunto"].isin(r["conjunto"])].rename(columns={"exemplos": "exemplos_conjunto"})
    r = pd.concat([extra.assign(recorte="contagem"), r], ignore_index=True)
    r.to_csv(f"{DADOS}/saida/alvo_passado.csv", index=False)
    print(r.to_string(index=False), flush=True)


if __name__ == "__main__":
    principal()
