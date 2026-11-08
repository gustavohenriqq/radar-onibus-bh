"""Fase 5: treino e avaliacao do modelo de bunching.

Roda no conteiner radar-ml:dev, depois de ml.montar:

    docker run --rm -v /home/ubuntu/radar:/app radar-ml:dev python -m ml.treinar [--teste]

Sem --teste, tudo acontece em treino e validacao: escolha da configuracao,
backtest, limiar por custo, prova de vazamento. Com --teste, avalia uma vez no
teste os modelos e o limiar ja escolhidos (o arquivo escolha.json da rodada
anterior) e grava as previsoes.

Modelos, do mais simples ao mais flexivel:
  persistencia  quanto menor o intervalo agora (h_rel), maior o risco
  taxa_hist     taxa do alvo no treino por faixa de h_rel x faixa horaria
  logistica     regressao logistica nas features permitidas
  gbm           HistGradientBoosting nas features permitidas
"""
import ctypes
import gc
import json
import os
import sys
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml import custo, divisao
from ml.features import ALVO, PERMITIDAS, PROIBIDAS

DADOS = os.environ.get("ML_DADOS", "/app/dados/ml")
SAIDA = f"{DADOS}/saida"
SEMENTE = 20261107
MAX_TREINO = 3_000_000
COLADO = 0.25
VERSAO = "v1"
FEATURES = list(PERMITIDAS)
CONFIGS = [
    {"learning_rate": 0.1, "max_leaf_nodes": 31, "min_samples_leaf": 200},
    {"learning_rate": 0.1, "max_leaf_nodes": 63, "min_samples_leaf": 500},
    {"learning_rate": 0.05, "max_leaf_nodes": 127, "min_samples_leaf": 1000},
]

assert not set(FEATURES) & set(PROIBIDAS), "feature proibida na lista de permitidas"


def _compactar(lote):
    """Tipos pequenos lote a lote: ler tudo em float64 e texto Python estoura 4 GB."""
    colunas = {}
    for nome, col in zip(lote.schema.names, lote.columns):
        if nome in FEATURES or nome in ("alvo_disfarcado", "minutos_ate_alvo"):
            col = pc.cast(col, pa.float32())
        elif nome == ALVO:
            col = pc.cast(col, pa.int8())
        elif nome in ("direction_id", "stop_sequence"):
            col = pc.cast(col, pa.int16())
        elif nome in ("route_id", "stop_id", "viagem_id", "faixa_horaria", "conjunto", "data_bh"):
            col = pc.dictionary_encode(pc.cast(col, pa.string()))
        colunas[nome] = col
    return pa.RecordBatch.from_pydict(colunas)


def carregar():
    colunas = FEATURES + [ALVO, "alvo_disfarcado", "conjunto", "data_bh", "faixa_horaria",
                          "route_id", "direction_id", "stop_id", "viagem_id", "stop_sequence",
                          "decisao_unix", "minutos_ate_alvo"]
    # O alocador padrao do pyarrow guarda a memoria do pico de leitura ate o fim
    # do processo; o do sistema devolve.
    pa.set_memory_pool(pa.system_memory_pool())
    dados = ds.dataset(f"{DADOS}/exemplos", format="parquet", partitioning="hive")
    tabela = pa.Table.from_batches([_compactar(b) for b in dados.to_batches(columns=colunas)])
    df = tabela.unify_dictionaries().to_pandas(self_destruct=True)
    del tabela
    # Datas como objetos date compartilhados: um por dia, nao um por linha.
    codigos, dias = pd.factorize(df["data_bh"].astype(str))
    df["data_bh"] = np.array([date.fromisoformat(d) for d in dias], dtype=object)[codigos]
    print(f"exemplos: {len(df):,}, memoria {df.memory_usage(deep=True).sum() / 2**30:.2f} GB", flush=True)
    devolver_memoria()
    rss("depois da carga")
    return df


def amostra(df, n=MAX_TREINO):
    return df.sample(n, random_state=SEMENTE) if len(df) > n else df


# --- modelos ----------------------------------------------------------------

class Persistencia:
    nome = "persistencia"

    def fit(self, df):
        return self

    def prever(self, df):
        # Ordenacao, nao probabilidade: menor h_rel, maior risco.
        return -df["h_rel"].to_numpy()


class TaxaHistorica:
    nome = "taxa_hist"
    CORTES = [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, np.inf]

    def _classe(self, df):
        return pd.cut(df["h_rel"], self.CORTES, right=False, labels=False).astype("int16")

    def fit(self, df):
        chave = pd.DataFrame({"c": self._classe(df), "f": df["faixa_horaria"], "y": df[ALVO]})
        self.taxa = chave.groupby(["c", "f"])["y"].mean()
        self.geral = df[ALVO].mean()
        return self

    def prever(self, df):
        idx = pd.MultiIndex.from_arrays([self._classe(df), df["faixa_horaria"]])
        return self.taxa.reindex(idx).fillna(self.geral).to_numpy()


class Logistica:
    nome = "logistica"

    def fit(self, df):
        self.m = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                               LogisticRegression(max_iter=500))
        self.m.fit(df[FEATURES], df[ALVO])
        return self

    def prever(self, df):
        return self.m.predict_proba(df[FEATURES])[:, 1]


class Gbm:
    nome = "gbm"

    def __init__(self, config, features=FEATURES):
        self.config, self.features = config, features

    def fit(self, df):
        self.m = HistGradientBoostingClassifier(max_iter=400, early_stopping=True, validation_fraction=0.1,
                                                n_iter_no_change=20, random_state=SEMENTE, **self.config)
        self.m.fit(df[self.features], df[ALVO])
        return self

    def prever(self, df):
        return self.m.predict_proba(df[self.features])[:, 1]


# --- metricas ---------------------------------------------------------------

def metricas(nome, conjunto, recorte, y, p, probabilidade=True):
    return {
        "modelo": nome, "conjunto": conjunto, "recorte": recorte, "exemplos": len(y),
        "taxa_base": round(float(y.mean()), 4),
        "roc_auc": round(roc_auc_score(y, p), 4),
        "pr_auc": round(average_precision_score(y, p), 4),
        "brier": round(brier_score_loss(y, p), 5) if probabilidade else None,
    }


def decis(nome, conjunto, recorte, y, p):
    """Decil 10 = os 10% de maior risco. Taxa real e probabilidade media."""
    d = pd.DataFrame({"y": y, "p": p})
    d["decil"] = pd.qcut(d["p"].rank(method="first"), 10, labels=range(1, 11)).astype(int)
    r = d.groupby("decil").agg(exemplos=("y", "size"), taxa=("y", "mean"), prob_media=("p", "mean")).reset_index()
    r.insert(0, "recorte", recorte)
    r.insert(0, "conjunto", conjunto)
    r.insert(0, "modelo", nome)
    return r


def recortes(df):
    """Todos os exemplos e so os que ainda nao estao colados em s."""
    return {"todos": df, "nao_colado_em_s": df[df["h_rel"] >= COLADO]}


def avaliar(modelos, df, conjunto):
    linhas, tabelas, previsoes = [], [], {}
    for m in modelos:
        p = m.prever(df)
        previsoes[m.nome] = p
        prob = m.nome != "persistencia"
        for recorte, parte in recortes(df).items():
            pp = p[df.index.get_indexer(parte.index)]
            y = parte[ALVO].to_numpy()
            linhas.append(metricas(m.nome, conjunto, recorte, y, pp, prob))
            tabelas.append(decis(m.nome, conjunto, recorte, y, pp))
    return linhas, tabelas, previsoes


def psi(treino, outro, features=FEATURES, classes=10):
    """Population Stability Index por feature, classes pelos decis do treino."""
    r = []
    for f in features:
        a, b = treino[f].dropna().to_numpy(), outro[f].dropna().to_numpy()
        cortes = np.unique(np.quantile(a, np.linspace(0, 1, classes + 1)))
        if len(cortes) < 3:
            r.append({"feature": f, "psi": 0.0})
            continue
        cortes[0], cortes[-1] = -np.inf, np.inf
        pa = np.histogram(a, cortes)[0] / len(a)
        pb = np.histogram(b, cortes)[0] / len(b)
        pa, pb = np.clip(pa, 1e-6, None), np.clip(pb, 1e-6, None)
        r.append({"feature": f, "psi": round(float(np.sum((pb - pa) * np.log(pb / pa))), 4)})
    return pd.DataFrame(r)


def devolver_memoria():
    """Devolve ao sistema o que o malloc guardou depois do pico de leitura."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:  # fora do Linux
        pass


def rss(etapa):
    """Memoria em uso do processo, para achar onde o limite do conteiner aperta."""
    with open("/proc/self/status") as f:
        kb = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
    print(f"[memoria] {etapa}: {kb / 2**20:.2f} GB", flush=True)


def gravar(df, nome):
    df.to_csv(f"{SAIDA}/{nome}.csv", index=False)
    print(f"{nome}.csv: {len(df)} linhas", flush=True)
    devolver_memoria()
    rss(nome)


# --- etapas -----------------------------------------------------------------

def desenvolvimento(df):
    treino = df[df["conjunto"] == "treino"].reset_index(drop=True)
    val = df[df["conjunto"] == "validacao"].reset_index(drop=True)
    t = amostra(treino)
    print(f"treino {len(treino):,} (amostra {len(t):,}), validacao {len(val):,}", flush=True)

    # Configuracao do gbm escolhida pela PR-AUC na validacao.
    configs = []
    for i, cfg in enumerate(CONFIGS):
        g = Gbm(cfg).fit(t)
        p = g.prever(val)
        configs.append({"config": i, **cfg, "iteracoes": g.m.n_iter_,
                        "pr_auc_validacao": round(average_precision_score(val[ALVO], p), 4)})
        print(configs[-1], flush=True)
    configs = pd.DataFrame(configs)
    gravar(configs, "configs")
    melhor = int(configs.sort_values("pr_auc_validacao", ascending=False)["config"].iloc[0])

    modelos = [Persistencia().fit(t), TaxaHistorica().fit(t), Logistica().fit(t), Gbm(CONFIGS[melhor]).fit(t)]
    linhas, tabelas, prev = avaliar(modelos, val, "validacao")
    gravar(pd.DataFrame(linhas), "metricas_validacao")
    gravar(pd.concat(tabelas), "decis_validacao")

    # Limiar por custo, escolhido na validacao com o gbm.
    limiar = custo.melhor_limiar(prev["gbm"].tolist(), val[ALVO].tolist())
    r = custo.avaliar(prev["gbm"].tolist(), val[ALVO].tolist(), limiar)
    gravar(pd.DataFrame([{"conjunto": "validacao", "limiar": limiar, "equilibrio": custo.equilibrio(), **r}]),
           "custo_validacao")

    # Prova de vazamento: o alvo disfarcado entre as features. Nao e salvo.
    vaz = Gbm(CONFIGS[0], FEATURES + ["alvo_disfarcado"]).fit(t)
    pv = vaz.prever(val)
    gravar(pd.DataFrame([metricas("gbm_com_alvo_disfarcado", "validacao", "todos", val[ALVO].to_numpy(), pv)]),
           "vazamento")

    # Importancia por permutacao numa amostra da validacao.
    vs = amostra(val, 300_000)
    imp = permutation_importance(modelos[3].m, vs[FEATURES], vs[ALVO], scoring="average_precision",
                                 n_repeats=3, random_state=SEMENTE)
    gravar(pd.DataFrame({"feature": FEATURES, "queda_pr_auc": imp.importances_mean.round(4),
                         "desvio": imp.importances_std.round(4)}).sort_values("queda_pr_auc", ascending=False),
           "importancia")

    # A escolha sai antes do backtest, que e o trecho que mais pede memoria.
    with open(f"{SAIDA}/escolha.json", "w") as f:
        json.dump({"config": melhor, "limiar": limiar, "versao": VERSAO}, f)
    del treino, val, t, modelos, prev, vaz, pv, vs, imp
    devolver_memoria()

    # Backtest: cada bloco de 7 dias treina com tudo antes dele.
    bt = []
    for ini, fim in divisao.BLOCOS_BACKTEST:
        antes = amostra(df[df["data_bh"] < ini])
        bloco = df[(df["data_bh"] >= ini) & (df["data_bh"] <= fim)].reset_index(drop=True)
        g = Gbm(CONFIGS[melhor]).fit(antes)
        y = bloco[ALVO].to_numpy()
        for m, p in (("gbm", g.prever(bloco)), ("persistencia", Persistencia().prever(bloco))):
            bt.append({"inicio": ini, "fim": fim, "treino": len(antes),
                       **metricas(m, "backtest", "todos", y, p, m == "gbm")})
        print(bt[-2], flush=True)
        del antes, bloco, g
        devolver_memoria()
    gravar(pd.DataFrame(bt), "backtest")


def teste(df):
    """Uma vez so: os modelos treinados no treino, o limiar da validacao."""
    with open(f"{SAIDA}/escolha.json") as f:
        escolha = json.load(f)
    if os.path.exists(f"{SAIDA}/metricas_teste.csv"):
        sys.exit("o teste ja foi usado (metricas_teste.csv existe); apague de proposito se for refazer")
    treino = df[df["conjunto"] == "treino"].reset_index(drop=True)
    tst = df[df["conjunto"] == "teste"].reset_index(drop=True)
    val = df[df["conjunto"] == "validacao"].reset_index(drop=True)
    # O df inteiro nao serve mais: solta antes de treinar, que e onde a memoria aperta.
    del df
    devolver_memoria()
    rss("recortes do teste")
    t = amostra(treino)
    modelos = [Persistencia().fit(t), TaxaHistorica().fit(t), Logistica().fit(t),
               Gbm(CONFIGS[escolha["config"]]).fit(t)]
    del t
    devolver_memoria()
    rss("modelos treinados")
    linhas, tabelas, prev = avaliar(modelos, tst, "teste")
    gravar(pd.DataFrame(linhas), "metricas_teste")
    gravar(pd.concat(tabelas), "decis_teste")

    limiar = escolha["limiar"]
    r = custo.avaliar(prev["gbm"].tolist(), tst[ALVO].tolist(), limiar)
    por_dia = []
    for dia, parte in tst.groupby("data_bh"):
        idx = parte.index.to_numpy()
        por_dia.append({"data_bh": dia, **custo.avaliar(prev["gbm"][idx].tolist(), parte[ALVO].tolist(), limiar)})
    gravar(pd.DataFrame([{"conjunto": "teste", "limiar": limiar, "equilibrio": custo.equilibrio(), **r}]),
           "custo_teste")
    gravar(pd.DataFrame(por_dia), "custo_teste_dias")
    gravar(psi(treino, tst), "psi")

    # Previsoes de validacao e teste para a Gold. Treino fica fora: e otimista.
    pv = modelos[3].prever(val)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saida = []
    for parte, p in ((val, pv), (tst, prev["gbm"])):
        s = parte[["route_id", "direction_id", "stop_id", "viagem_id", "stop_sequence", "data_bh",
                   "decisao_unix", "conjunto", ALVO]].copy()
        s["prob"] = p.astype("float32")
        s["alerta"] = s["prob"] >= limiar
        s["limiar"] = limiar
        s["versao_modelo"] = escolha["versao"]
        s["gerado_em"] = agora
        saida.append(s)
    pd.concat(saida).to_parquet(f"{DADOS}/previsoes.parquet", index=False)
    print("previsoes.parquet gravado", flush=True)


if __name__ == "__main__":
    os.makedirs(SAIDA, exist_ok=True)
    # Sem variavel intermediaria: assim a funcao consegue soltar o df quando quiser.
    if "--teste" in sys.argv:
        teste(carregar())
    else:
        desenvolvimento(carregar())
