"""Graficos de docs/analise.md a partir dos CSVs de analise/calcular.py.

    py -3.11 analise/graficos.py <pasta dos CSVs>

Grava PNGs em docs/img/. Recorte de todos: dia util, linhas de alta frequencia
(headway medio de ate 15 min), onde a espera estimada vale.
"""
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ENTRADA = Path(sys.argv[1] if len(sys.argv) > 1 else "analise/saida")
SAIDA = Path("docs/img")
AZUL, LARANJA, CINZA = "#2a78d6", "#eb6834", "#b8b6ae"
TEXTO, TEXTO2, FUNDO = "#0b0b0b", "#52514e", "#fcfcfb"
NOME_FAIXA = {"madrugada": "madrugada", "inicio_manha": "início\nda manhã", "pico_manha": "pico\nda manhã",
              "entre_picos": "entre\npicos", "pico_tarde": "pico\nda tarde", "noite": "noite"}

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


def util_alta(linhas):
    return [r for r in linhas if r["tipo_dia"] == "dia_util" and r["alta_frequencia"] == "True"]


def pt(x, casas=1):
    return f"{x:.{casas}f}".replace(".", ",")


def salvar(fig, nome):
    SAIDA.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA / f"{nome}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("gravado", SAIDA / f"{nome}.png")


def espera_por_faixa():
    rs = sorted(util_alta(ler("rede_faixa")), key=lambda r: int(r["ordem_faixa"]))
    nomes = [NOME_FAIXA.get(r["faixa_horaria"], r["faixa_horaria"]) for r in rs]
    reg = [float(r["regular_min"]) for r in rs]
    exc = [float(r["excesso_min"]) for r in rs]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.bar(nomes, reg, color=AZUL, width=0.6, label="espera com ônibus regulares")
    ax.bar(nomes, exc, bottom=reg, color=LARANJA, width=0.6, label="espera extra pela irregularidade",
           edgecolor=FUNDO, linewidth=2)
    for i, (a, b) in enumerate(zip(reg, exc)):
        ax.text(i, a + b + 0.15, f"+{pt(b)}", ha="center", color=TEXTO, fontsize=10)
    ax.set_ylabel("minutos")
    ax.set_title("Espera média no ponto por faixa horária, dia útil")
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)
    salvar(fig, "espera_por_faixa")


def linhas_top(n=15):
    rs = util_alta(ler("linhas"))
    total = sum(float(r["volume_min_h"]) for r in rs)
    rs = sorted(rs, key=lambda r: -float(r["volume_min_h"]))[:n][::-1]
    rot = [(r["route_short_name"] or r["route_id"]) for r in rs]
    par = [100 * float(r["volume_min_h"]) / total for r in rs]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.barh(rot, par, color=LARANJA, height=0.62)
    for i, (v, r) in enumerate(zip(par, rs)):
        ax.text(v + 0.05, i, f"{pt(v)}%  ({pt(float(r['excesso_min']))} min extra)", va="center",
                color=TEXTO2, fontsize=9)
    ax.set_xlabel("% da espera extra da rede (dia útil, alta frequência)")
    ax.set_title(f"As {n} linhas que mais somam espera extra")
    ax.set_xlim(0, max(par) * 1.6)
    salvar(fig, "linhas_top")


def histograma():
    rs = util_alta(ler("hist_h_sobre_media"))
    x = [int(r["classe"]) * 0.05 for r in rs]
    y = [int(r["headways"]) for r in rs]
    tot = sum(y)
    cor = [LARANJA if v < 0.25 else AZUL for v in x]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x, [100 * v / tot for v in y], width=0.046, align="edge", color=cor)
    ax.axvline(0.25, color=TEXTO2, linewidth=1, linestyle="--")
    ax.axvline(1.0, color=TEXTO2, linewidth=1, linestyle=":")
    topo = max(100 * v / tot for v in y)
    ax.set_ylim(0, topo * 1.45)
    alto_colado = max(100 * v / tot for v, c in zip(y, x) if c < 0.25)
    i_alto = max((v, c) for v, c in zip(y, x) if c < 0.25)[1]
    ax.annotate("colados:\nmenos de 1/4 do\nintervalo médio", xy=(i_alto + 0.023, alto_colado * 1.02),
                xytext=(0.34, topo * 1.4), va="top", color=TEXTO, fontsize=9,
                bbox=dict(boxstyle="square,pad=0.2", fc=FUNDO, ec="none"),
                arrowprops=dict(arrowstyle="-", color=TEXTO2, linewidth=0.8, shrinkA=0, shrinkB=0))
    ax.text(1.04, topo * 1.4, "intervalo médio", va="top", color=TEXTO2, fontsize=9)
    ax.set_xlim(0, 4)
    ax.set_xlabel("intervalo entre ônibus ÷ intervalo médio do ponto naquela faixa")
    ax.set_ylabel("% dos intervalos")
    ax.set_title("Distribuição dos intervalos, dia útil, alta frequência")
    salvar(fig, "intervalos")


def mapa_paradas():
    rs = [r for r in util_alta(ler("paradas")) if r["stop_lat"] and float(r["horas"]) >= 50]
    rs.sort(key=lambda r: float(r["excesso_min"]))
    lon = [float(r["stop_lon"]) for r in rs]
    lat = [float(r["stop_lat"]) for r in rs]
    exc = [min(float(r["excesso_min"]), 6) for r in rs]
    fig, ax = plt.subplots(figsize=(7.5, 8))
    sc = ax.scatter(lon, lat, c=exc, cmap="Oranges", vmin=0, vmax=6, s=9, edgecolors="#d9d7cf", linewidths=0.2)
    cb = fig.colorbar(sc, ax=ax, shrink=0.6)
    cb.set_label("espera extra (min); 6 = 6 ou mais", color=TEXTO2)
    ax.set_aspect(1 / 0.94)  # cos(19,9 graus)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Espera extra por ponto, dia útil, alta frequência")
    salvar(fig, "mapa_paradas")


if __name__ == "__main__":
    espera_por_faixa()
    linhas_top()
    histograma()
    mapa_paradas()
