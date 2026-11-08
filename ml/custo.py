"""Limiar por custo. Python puro.

HIPOTESE INVENTADA, declarada como tal (nao ha dado de lotacao nem de
operacao): o alerta manda segurar o onibus B na parada s.
  - CUSTO_ALERTA: segurar ~45 s com ~40 pessoas a bordo = 30 passageiro-minutos.
  - CUSTO_COLADO: um colado deixa um buraco atras; com 0,5 passageiro/min por
    parada e um buraco de ~10 min a mais, a espera extra passa de 100
    passageiro-minutos somando as paradas seguintes.
  - EFICACIA: metade dos colados alertados deixa de acontecer.
Com esses numeros alertar compensa quando a precisao passa de
CUSTO_ALERTA / (EFICACIA x CUSTO_COLADO) = 60%.
"""

CUSTO_ALERTA = 30.0
CUSTO_COLADO = 100.0
EFICACIA = 0.5


def equilibrio(custo_alerta=CUSTO_ALERTA, custo_colado=CUSTO_COLADO, eficacia=EFICACIA):
    """Precisao acima da qual cada alerta se paga."""
    return custo_alerta / (eficacia * custo_colado)


def custo(alertas, acertos, positivos,
          custo_alerta=CUSTO_ALERTA, custo_colado=CUSTO_COLADO, eficacia=EFICACIA):
    """Custo total de uma politica: alertas pagos + colados que sobraram."""
    return alertas * custo_alerta + (positivos - eficacia * acertos) * custo_colado


def curva(probs, alvos):
    """(limiar, alertas, acertos) para cada corte possivel, do mais alto ao mais baixo.

    Empates de probabilidade entram juntos: um limiar nao separa exemplos iguais.
    O primeiro ponto e "nunca alertar" (limiar infinito).
    """
    pares = sorted(zip(probs, alvos), key=lambda x: -x[0])
    pontos = [(float("inf"), 0, 0)]
    alertas = acertos = 0
    i = 0
    while i < len(pares):
        p = pares[i][0]
        while i < len(pares) and pares[i][0] == p:
            alertas += 1
            acertos += int(pares[i][1])
            i += 1
        pontos.append((p, alertas, acertos))
    return pontos


def melhor_limiar(probs, alvos, **hipotese):
    """Limiar de menor custo; empate fica com o limiar mais alto (menos alertas)."""
    positivos = sum(int(a) for a in alvos)
    melhor = None
    for limiar, alertas, acertos in curva(probs, alvos):
        c = custo(alertas, acertos, positivos, **hipotese)
        if melhor is None or c < melhor[1]:
            melhor = (limiar, c)
    return melhor[0]


def avaliar(probs, alvos, limiar, **hipotese):
    """Custo do limiar escolhido contra nunca e sempre alertar."""
    positivos = sum(int(a) for a in alvos)
    alertas = sum(1 for p in probs if p >= limiar)
    acertos = sum(int(a) for p, a in zip(probs, alvos) if p >= limiar)
    return {
        "exemplos": len(alvos),
        "positivos": positivos,
        "alertas": alertas,
        "acertos": acertos,
        "precisao": acertos / alertas if alertas else None,
        "cobertura": acertos / positivos if positivos else None,
        "custo_modelo": custo(alertas, acertos, positivos, **hipotese),
        "custo_nunca": custo(0, 0, positivos, **hipotese),
        "custo_sempre": custo(len(alvos), positivos, positivos, **hipotese),
    }
