"""Dias fora do normal no periodo, usados no painel web e no Power BI (powerbi/modelo.py le
este arquivo sem importar o Streamlit)."""

# Eventos conferidos em notícias (fontes em docs/analise.md, seção 9).
EVENTOS = {
    "2026-10-04": "Eleição, 1º turno: ônibus de graça e 4 mil viagens extras",
    "2026-10-05": "Chuva forte de manhã, quase 50 mm",
    "2026-10-13": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-14": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-15": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-16": "Recesso escolar da rede municipal (13 a 16/10)",
    "2026-10-20": "Itinerário novo da linha 5033",
    "2026-10-21": "Ato de campanha no Centro (15h às 17h) e obra muda o trânsito da Cristiano Machado",
    "2026-10-25": "Eleição, 2º turno, com 4 mil viagens extras; temporal à tarde derruba árvores e semáforos",
    "2026-10-26": "Depois do temporal: 45 mil imóveis sem luz de manhã e árvores caídas em vias",
}
# Mesmos ônibus e viagens, mas com horas sem posição: a espera extra das linhas S fica inflada.
FALHA_S = {d: "GPS das suplementares falhou em parte do dia" for d in
           ("2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-29")}
