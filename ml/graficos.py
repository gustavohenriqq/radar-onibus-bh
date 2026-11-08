"""Graficos de docs/ml.md a partir dos CSVs de ml.treinar.

    py -3.11 ml/graficos.py <pasta dos CSVs>

Grava PNGs em docs/img/ com o prefixo ml_. Usa o teste quando ele ja rodou e a
validacao enquanto isso, e diz no titulo qual dos dois aparece.
"""
import csv
import sys
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ENTRADA = Path(sys.argv[1] if len(sys.argv) > 1 else "ml/saida")
SAIDA = Path("docs/img")
AZUL, LARANJA, CINZA = "#2a78d6", "#eb6834", "#b8b6ae"
TEXTO, TEXTO2, FUNDO, GRADE = "#0b0b0b", "#52514e", "#fcfcfb", "#e6e5e0"
NOME = {"gbm": "modelo (HistGBM)", "persistencia": "persistência (intervalo de agora)"}
COR = {"gbm": AZUL, "persistencia": LARANJA}
ACENTO = {"teste": "teste", "validacao": "validação"}

plt.rcParams.update({
    "font.size": 11, "axes.edgecolor": CINZA, "axes.labelcolor": TEXTO2,
    "xtick.color": TEXTO2, "ytick.color": TEXTO2, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": FUNDO, "axes.facecolor": FUNDO,
    "savefig.facecolor": FUNDO, "axes.titlecolor": TEXTO, "axes.titlesize": 13,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def ler(nome):
    with open(ENTRADA / f"{nome}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def existe(nome):
    return (ENTRADA / f"{nome}.csv").exists()


def pt(x, casas=1):
    return f"{x:.{casas}f}".replace(".", ",")


def grade(ax, eixo="y"):
    ax.grid(axis=eixo, color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def salvar(fig, nome):
    SAIDA.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA / f"{nome}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("gravado", SAIDA / f"{nome}.png")


def conjunto():
    return "teste" if existe("decis_teste") else "validacao"


def decis():
    c = conjunto()
    rs = [r for r in ler(f"decis_{c}") if r["recorte"] == "todos"]
    base = [float(r["taxa_base"]) for r in ler(f"metricas_{c}")
            if r["modelo"] == "gbm" and r["recorte"] == "todos"][0]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    largura = 0.4
    for k, m in enumerate(("persistencia", "gbm")):
        linhas = sorted((r for r in rs if r["modelo"] == m), key=lambda r: int(r["decil"]))
        x = [int(r["decil"]) + (k - 0.5) * largura for r in linhas]
        y = [100 * float(r["taxa"]) for r in linhas]
        ax.bar(x, y, width=largura, color=COR[m], label=NOME[m])
        ax.text(x[-1], y[-1] + 1, pt(y[-1], 0) + "%", ha="center", color=TEXTO, fontsize=9)
    ax.axhline(100 * base, color=TEXTO2, linewidth=1, linestyle="--")
    ax.text(0.6, 100 * base + 1, f"média: {pt(100 * base)}%", color=TEXTO2, fontsize=10)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("decil de risco previsto (10 = os 10% de maior risco)")
    ax.set_ylabel("% que chegou colado em s+10")
    ax.set_title(f"Quem o modelo aponta chega colado mais vezes ({ACENTO[c]})")
    ax.legend(frameon=False, loc="upper left")
    grade(ax)
    salvar(fig, "ml_decis")


def custo_dias():
    if not existe("custo_teste_dias"):
        print("sem custo_teste_dias.csv: o teste ainda nao rodou")
        return
    rs = ler("custo_teste_dias")
    dias = [r["data_bh"][8:10] + "/" + r["data_bh"][5:7] for r in rs]
    economia = [100 * (1 - float(r["custo_modelo"]) / float(r["custo_nunca"])) for r in rs]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(dias, economia, color=[AZUL if e >= 0 else LARANJA for e in economia], width=0.6)
    folga = 0.02 * max(abs(e) for e in economia)
    for i, e in enumerate(economia):
        ax.text(i, e + (folga if e >= 0 else -folga), pt(e, 2), ha="center",
                va="bottom" if e >= 0 else "top", color=TEXTO, fontsize=10)
    ax.axhline(0, color=CINZA, linewidth=1)
    ax.set_ylim(min(0, min(economia) * 1.15), max(0, max(economia) * 1.15))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: pt(v)))
    ax.set_ylabel("economia sobre nunca alertar (%)")
    ax.set_title("Economia por dia do teste, limiar fixado na validação")
    grade(ax)
    salvar(fig, "ml_custo_dias")


def backtest():
    rs = ler("backtest")
    blocos = sorted({(r["inicio"], r["fim"]) for r in rs})
    nomes = [f"{a[8:10]}/{a[5:7]} a {b[8:10]}/{b[5:7]}" for a, b in blocos]
    fig, ax = plt.subplots(figsize=(8, 4))
    largura = 0.35
    for k, m in enumerate(("persistencia", "gbm")):
        y = [float(next(r["pr_auc"] for r in rs if r["modelo"] == m and (r["inicio"], r["fim"]) == b))
             for b in blocos]
        x = [i + (k - 0.5) * largura for i in range(len(blocos))]
        ax.bar(x, y, width=largura, color=COR[m], label=NOME[m])
        for xi, yi in zip(x, y):
            ax.text(xi, yi + 0.01, pt(yi, 2), ha="center", color=TEXTO, fontsize=10)
    base = [float(next(r["taxa_base"] for r in rs if (r["inicio"], r["fim"]) == b)) for b in blocos]
    ax.plot(range(len(blocos)), base, color=TEXTO2, linestyle="--", marker="o", linewidth=1,
            label="taxa de colados (PR-AUC de quem chuta)")
    ax.set_xticks(range(len(blocos)))
    ax.set_xticklabels(nomes)
    ax.set_ylabel("PR-AUC")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    ax.set_title("Backtest: cada semana prevista só com o que veio antes")
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2)
    grade(ax)
    salvar(fig, "ml_backtest")


def importancia(n=10):
    rs = ler("importancia")[:n][::-1]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    y = [float(r["queda_pr_auc"]) for r in rs]
    ax.barh([r["feature"] for r in rs], y, xerr=[float(r["desvio"]) for r in rs], color=AZUL,
            ecolor=TEXTO2, height=0.6)
    ax.set_xlabel("queda da PR-AUC ao embaralhar a coluna")
    ax.set_title(f"O que o modelo usa: as {n} colunas que mais pesam")
    grade(ax, "x")
    salvar(fig, "ml_importancia")


if __name__ == "__main__":
    decis()
    custo_dias()
    backtest()
    importancia()
