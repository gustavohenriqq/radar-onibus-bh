"""Divisao temporal e blocos do backtest. Python puro."""
from datetime import date, timedelta

# Os exemplos comecam 14 dias depois do primeiro dia da Gold: o historico das
# features (m_hist, taxa_colado_hist, trecho) olha os 14 dias anteriores.
INICIO = date(2026, 9, 29)
FIM_TREINO = date(2026, 10, 19)
FIM_VALIDACAO = date(2026, 10, 26)
FIM = date(2026, 11, 6)

# Blocos de 7 dias do backtest, todos dentro de treino + validacao: o teste e
# usado uma vez so, fora daqui. Cada bloco treina com tudo antes dele.
BLOCOS_BACKTEST = [
    (date(2026, 10, 6), date(2026, 10, 12)),
    (date(2026, 10, 13), date(2026, 10, 19)),
    (date(2026, 10, 20), date(2026, 10, 26)),
]


def conjunto(dia: date) -> str | None:
    if dia < INICIO or dia > FIM:
        return None
    if dia <= FIM_TREINO:
        return "treino"
    if dia <= FIM_VALIDACAO:
        return "validacao"
    return "teste"


def dias(inicio: date, fim: date):
    d = inicio
    while d <= fim:
        yield d
        d += timedelta(days=1)
