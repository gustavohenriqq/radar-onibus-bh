# Gold: métricas de serviço em dbt

Transforma posições da Silver em headway, irregularidade e espera estimada, por
linha, sentido, dia e faixa horária. Roda com dbt-spark no contêiner da VM de
processamento.

## Como uma posição vira espera

```
stg_posicoes              posições dentro da região de BH, de 15/09 em diante
  |-> int_feed_parado     períodos em que a frota inteira parou de publicar
  |-> int_mapa_parada     parada mais vista por linha, sentido, letreiro e sequência
  |-> int_passagens       uma linha por parada que uma viagem deixou para trás
        |-> int_headways  intervalo entre passagens na mesma linha, sentido e parada
              |-> fct_headway_parada_faixa   métricas por parada, dia e faixa
                    |-> fct_servico_linha_faixa  média entre paradas: o mart de leitura
              |-> fct_qualidade_diaria       o que entrou e o que ficou de fora
```

## A regra de cálculo

**Viagem.** A combinação `(vehicle_id, trip_id, start_date, start_time)`.

**Passagem.** O `current_status` do feed é sempre `IN_TRANSIT_TO`, então `stop_id`
é a próxima parada, nunca a atual. Quando a sequência sobe de `s` para `t` entre
duas posições, as paradas `s` até `t-1` ficaram para trás nesse intervalo.

- O instante é estimado dividindo o intervalo em partes iguais, uma por parada.
  Com uma parada só, é o ponto médio. O erro típico é de cerca de 20 s, metade do
  intervalo mediano entre posições (45 s).
- A primeira parada do salto vem do próprio ônibus. As intermediárias vêm do mapa
  aprendido (`int_mapa_parada`), porque o feed não as informa.
- A sequência é comparada com o máximo já visto na viagem: um recuo do GPS não
  repete passagem.

**Headway.** Intervalo entre passagens consecutivas de qualquer ônibus da mesma
linha, no mesmo sentido, na mesma parada. Variantes de letreiro contam juntas: para
quem está no ponto, é o mesmo ônibus. O headway pertence à passagem que o encerra,
e dela vêm a data e a faixa. Headway acima de 180 min ou que atravessa uma queda do
feed fica marcado como inválido e sai da conta (ver "Quando o feed cai").

**Métricas por parada.** Com `H` o headway:

| Métrica | Fórmula | Leitura |
|---|---|---|
| Headway médio | `E[H]` | de quanto em quanto tempo passa um ônibus |
| Coeficiente de variação | `desvio(H) / E[H]`, desvio populacional | 0 é perfeitamente regular |
| Espera estimada | `E[H²] / (2 E[H])` = `(E[H]/2)(1 + CV²)` | espera média de quem chega ao acaso |
| Espera regular | `E[H] / 2` | a mesma frota, igualmente espaçada |
| Espera em excesso | estimada menos regular | o tempo que a irregularidade custa |

Uma parada pode ter média zero: dois ônibus registrados no mesmo segundo, e nenhum
outro no grupo. A linha fica no mart de parada, com CV e esperas nulos, porque a
divisão não tem valor.

**Métricas por linha.** Média simples entre as paradas com pelo menos 3 headways no
grupo e média acima de zero. Somar os headways de todas as paradas antes misturaria ramais de frequências
diferentes, e essa diferença apareceria como irregularidade. O peso é igual porque
não existe dado de embarque por parada: o número descreve o passageiro que chega a
uma parada qualquer da linha.

**Faixas horárias.** Vêm de `seeds/faixa_horaria.csv`, definidas pelo tamanho da
frota em circulação por hora num dia útil.

| Faixa | Horas em BH | Ônibus em 20/10/2026 |
|---|---|---|
| `madrugada` | 00 a 04 | 74 a 708 |
| `inicio_manha` | 05 | 1.862, ainda subindo |
| `pico_manha` | 06 a 08 | 2.413 a 2.514 |
| `entre_picos` | 09 a 15 | 1.851 a 2.186 |
| `pico_tarde` | 16 a 19 | 2.351 a 2.460 |
| `noite` | 20 a 23 | 898 a 1.903 |

## Quando o feed cai

O feed às vezes para de publicar para a frota inteira, e o status continua 200. Na
queda de 26/10/2026, às 19:21:42 UTC, as posições congelaram com o relógio do
cabeçalho andando, e depois a lista veio vazia até 19:55. O coletor registrou tudo
como resposta normal, e a Silver guardou o que veio: o problema está na fonte.

Os ônibus seguem rodando nessas horas. Um headway que atravessa a queda mede o feed,
não o serviço, e aparecia como irregularidade.

**A regra.** `int_feed_parado` acha os intervalos de pelo menos 5 min sem nenhuma
posição nova em toda a frota (`feed_parado_s`). Headway que começa antes do fim do
período e termina depois do início dele fica com `atravessa_feed_parado` verdadeiro
e `headway_valido` falso. `fct_qualidade_diaria` conta esses casos em
`headways_feed_parado`, separados de `headways_longos`.

**Medido de 15/09 a 04/11/2026:**

| Medida | Valor |
|---|---|
| Quedas | 16, somando 32.790 s; a maior, de 4.899 s, em 02/10 às 03:38 UTC |
| Repetição | três quedas de cerca de 80 min começando por volta de 03:38 UTC (23/09, 02/10, 07/10) |
| Headways que atravessam | 378.508 de 49.502.070, 0,76% |
| Espera em excesso média | 3,160 para 3,070 min, queda de 2,8% |
| CV médio | 0,421 para 0,416 |
| Dia mais afetado | 26/10, duas quedas: excesso de 4,184 para 3,381 min, queda de 19% |
| Outros | 26/09 de 3,004 para 2,514; 30/10 de 3,530 para 3,046; 01/10 de 4,428 para 3,696 |

O "antes" foi medido fora do dbt, com a mesma conta sem a regra. O "depois" é o mart.

## Por que cada limite

Todos ficam em `vars` no `dbt_project.yml`. A sensibilidade foi medida de 19 a
23/10/2026, com espera em excesso de referência de 2,129 min por parada e hora.

| Limite | Valor | Por quê | Sensibilidade |
|---|---|---|---|
| Feed parado (`feed_parado_s`) | 5 min | com até 2.514 ônibus circulando, a frota inteira não fica 5 min sem publicar | fora das 16 quedas, o maior vazio é de 198 s, e só 7 passam de 2 min |
| Buraco de GPS (`intervalo_max_s`) | 5 min | dividir um intervalo maior em partes iguais é chute | 60 min em vez de 5: excesso 2,140, variação de 0,5% |
| Mesmo ônibus repetido (`repeticao_mesmo_onibus_s`) | 5 min | é o feed reatribuindo a viagem, não duas passagens | remove 0,13% das passagens |
| Headway máximo (`headway_max_min`) | 180 min | acima disso é fim de serviço, não espera | fica registrado em `headways_longos` |
| Amostra mínima (`min_headways_parada`) | 3 | com 1 headway o CV é zero por construção | |
| Alta frequência (`alta_frequencia_min`) | 15 min | ver "O que estes números não dizem" | |

**Viagens curtas ficam.** Viagens com menos de 5 passagens somam 0,5% do total, e
tirá-las muda o CV de 0,601 para 0,600.

**Dois ônibus na mesma viagem programada ficam.** Isso é comum: 29% dos headways
abaixo de 30 s são desse tipo, contra 7% dos acima de 2 min. Foi conferido se era
o mesmo ônibus duplicado. Em 20/10 eram 12.496 pares, com mediana de 1,8 km de
distância e 7 paradas de diferença, e só 19 andaram colados por mais de 20 min. São
ônibus diferentes, que o feed encaixou no mesmo horário. Tratar como erro apagaria
justamente o comboio que a métrica existe para medir. Se ainda assim todos esses
casos abaixo de 2 min fossem artefato, o excesso cairia de 2,129 para 1,982 min, 7%:
esse é o tamanho máximo do erro por essa causa.

## Números conferidos

Build completo em 05/11/2026, de 15/09 a 04/11:

| Medida | Valor |
|---|---|
| Mart de leitura | 90.325 linhas, 311 linhas de ônibus |
| Headways | 49.502.070; 48.139.727 válidos, 983.835 acima de 180 min, 378.508 em queda do feed |
| Espera em excesso média | 3,07 min, com CV de 0,416 e headway médio de 29,1 min |
| Testes | 67 testes de dados, 9 testes unitários, 13 testes Python da conferência |

**Segunda conta.** `gold/conferencia.py` refaz tudo em Python puro, a partir da
Silver, sem SQL: passagens, repetição, quedas do feed, headways e médias. Para as
linhas 62, 9104 e 4110 de 19 a 30/10, janela que inclui as quedas de 20, 26 e 30/10,
deu 307 linhas iguais às do mart, 235.790 headways e 0 divergências.

**Por faixa horária:**

| Faixa | Linhas no mart | Excesso médio (min) | CV | Headway médio (min) |
|---|---|---|---|---|
| `madrugada` | 5.727 | 4,385 | 0,425 | 40,2 |
| `pico_tarde` | 18.893 | 3,817 | 0,467 | 30,2 |
| `entre_picos` | 18.514 | 3,627 | 0,442 | 31,5 |
| `noite` | 17.880 | 2,998 | 0,373 | 33,6 |
| `pico_manha` | 18.590 | 2,179 | 0,402 | 24,1 |
| `inicio_manha` | 10.721 | 1,754 | 0,374 | 18,2 |

A madrugada tem o maior excesso, mas é onde a fórmula de chegada ao acaso menos
vale (ver abaixo). O pico da tarde custa 1,6 min a mais por espera do que o pico da
manhã. Dia útil fica em 3,203 min, sábado em 2,540 e domingo ou feriado em
2,817.

## O que estes números não dizem

- **A espera estimada supõe chegada ao acaso.** Vale para linha frequente. Acima de
  15 min de headway as pessoas consultam o horário, e a fórmula superestima a espera
  real. A coluna `alta_frequencia` marca a diferença; compare espera absoluta só onde
  ela é verdadeira.
- **Ônibus sem GPS parece ônibus que não passou.** Um veículo que some do feed
  encurta a lista de passagens e alonga o headway. O feed não distingue os dois casos,
  então o excesso tende a ser superestimado.
- **A última parada de cada viagem não gera passagem**, porque o ônibus nunca informa
  uma próxima parada depois dela. A primeira também não: a menor sequência vista no
  feed é 2.
- **O mapa é um só para a janela inteira.** Se um itinerário mudar no meio, a parada
  mais vista ganha para o período todo. O mapa concorda com o próprio feed em 99,83%
  das observações no histórico inteiro.
- **25 a 28/10/2026 têm mais buraco de GPS, sem causa conhecida.** A fração de
  passagens descartadas por intervalo longo foi de 8,4%, 7,6%, 7,2% e 6,9%, contra
  a mediana de 2,78% no período inteiro, e 3,8% em 29/10. Não é efeito de domingo: os
  outros domingos ficam entre 2,2% e 3,5%. Atingiu 2.332 de 2.740 veículos, em todas
  as horas, com a cadência de coleta normal. 25/10 tem a maior espera em excesso do
  histórico (5,08 min), e parte disso pode vir desses buracos. Os números desses dias
  ficam no mart, mas pedem cuidado.
- **Corredor ainda não existe.** A issue cita corredor no título, mas o critério de
  pronto não. Agrupar linhas por corredor pede a geometria das vias, que o feed em
  tempo real não traz.

## Para rodar

```bash
docker build -f Dockerfile.gold -t radar-gold:dev .   # pede radar-spark:dev
sh gold/rodar.sh seed
sh gold/rodar.sh build
sh gold/rodar.sh build --vars '{data_inicio: 2026-10-19, data_fim: 2026-10-25}'
docker run --rm -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-gold:dev \
  python -m gold.conferencia --linhas 62 9104 4110 --de 2026-10-19 --ate 2026-10-30
```

Com `--vars` a tabela inteira é reconstruída só com aquela janela, então serve para
desenvolver, não para atualizar. O backfill por janela é da fase 6.
