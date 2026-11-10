"""Numeros no formato brasileiro fixo (1.234,5; 12,3%), sem depender do idioma do servidor."""
import math
from datetime import date


def _vazio(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def br(x, casas: int = 1) -> str:
    if _vazio(x):
        return "sem dado"
    s = f"{float(x):,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, casas: int = 1) -> str:
    return "sem dado" if _vazio(x) else br(100 * float(x), casas) + "%"


def data_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")
