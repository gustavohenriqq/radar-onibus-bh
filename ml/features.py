"""O que o modelo pode e o que nao pode ver.

Momento da decisao: o onibus B acabou de passar pela parada s. A passagem e
interpolada entre duas posicoes, entao so fica conhecida quando chega a posicao
seguinte: o instante da decisao e passagem_unix + intervalo_s (a conta exata
seria unix_anterior + intervalo_s, que e no maximo esse valor, porque a
passagem fica dentro do intervalo). Toda feature usa so passagens conhecidas
ate esse instante, e todo historico vem de dias anteriores ao dia do exemplo.

O treino aceita so as colunas de PERMITIDAS. PROIBIDAS lista o que existe na
tabela de exemplos (ou foi tentador usar) e por que fica fora; um teste impede
que uma coluna esteja nas duas listas.
"""

PERMITIDAS = {
    # O intervalo atual e o que ja aconteceu com ele nesta viagem.
    "h_s": "intervalo ate o onibus da frente na parada s (s)",
    "h_rel": "h_s dividido pelo intervalo medio historico da parada na faixa",
    "dh_1": "h_s menos o intervalo na parada s-1 (s)",
    "dh_3": "h_s menos o intervalo na parada s-3 (s)",
    "dh_5": "h_s menos o intervalo na parada s-5 (s)",
    # Os vizinhos: o lider do onibus da frente e quem vem atras.
    "lider_rel": "intervalo do onibus da frente para o lider dele na parada s, sobre a media historica",
    "atras_rel": "intervalo do onibus de tras para B na parada s-5, sobre a media historica",
    "atras_censurado": "1 se a passagem do onibus de tras em s-5 ainda nao era conhecida na decisao; entao atras_rel e o tempo decorrido desde B em s-5",
    # O ritmo da propria viagem contra o historico do trecho.
    "trecho_razao": "tempo de B de s-5 ate s dividido pela media historica do trecho na faixa",
    # Contexto conhecido antes do dia.
    "m_hist_min": "intervalo medio historico da parada na faixa (min), 14 dias antes",
    "taxa_colado_hist": "parcela de colados da linha e sentido na faixa, 14 dias antes",
    "hora": "hora de BH com fracao",
    "dia_semana": "1 = segunda ... 5 = sexta",
    "posicao": "posicao da parada na viagem (stop_sequence)",
    "frac_percurso": "posicao sobre a ultima posicao do mapa da linha (estrutura da linha, nao desfecho; o mapa usa o historico inteiro, ver docs/ml.md ressalva 9)",
    # Qualidade da estimativa da passagem atual.
    "paradas_no_intervalo": "paradas divididas no mesmo intervalo entre posicoes",
    "intervalo_s": "segundos entre as duas posicoes que geraram a passagem",
}

PROIBIDAS = {
    "alvo": "o proprio desfecho",
    "h_alvo": "intervalo na parada s+10: e o desfecho antes do limiar",
    "alvo_disfarcado": "h_alvo sobre a media historica: o desfecho com outro nome, usado so na prova de vazamento",
    "m_dia": "media do grupo no dia: usa os intervalos que ainda vao acontecer",
    "minutos_ate_alvo": "acontece depois da decisao",
    "alta_frequencia_dia": "flag do mart calculada com o dia inteiro",
    "viagem_id": "identificador: o modelo decoraria viagens",
    "vehicle_id": "identificador: o modelo decoraria onibus",
    "route_id": "identificador: o historico da linha ja entra por m_hist_min e taxa_colado_hist",
    "stop_id": "identificador: o historico da parada ja entra por m_hist_min",
    "data_bh": "calendario de um ano so: decoraria os dias do treino",
    "decisao_unix": "instante absoluto: o mesmo problema da data",
    "conjunto": "rotulo da divisao, nao do onibus",
}

ALVO = "alvo"
