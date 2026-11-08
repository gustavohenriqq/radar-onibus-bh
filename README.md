# Ônibus de BH em tempo real

**O dado deste projeto não existe até ser coletado.** Não há CSV para baixar:
cada linha vem do feed GTFS-Realtime da Prefeitura de Belo Horizonte, lido a
cada 30 segundos por um coletor que precisa ficar no ar. Posição de ônibus que
não foi gravada não volta.

A pergunta que o projeto vai responder:

> Quanto tempo o passageiro perde por irregularidade do serviço, onde isso se
> concentra, e dá para prever o atraso do próximo ônibus?

## Status

| Fase | Entrega | Situação |
|---|---|---|
| **0. Coletor** | Coletor 24/7, bronze particionado, alerta | **no ar desde 14/09/2026, 23:52 UTC**, com alerta externo |
| **1. Bronze e compactação** | Job horário, consolidação do bruto e backup fora da VM | **no ar desde 16/09/2026**; backup desde 23/10/2026 |
| **2. Silver em Delta** | PySpark, deduplicação com MERGE | **pronta em 05/11/2026**: 52 dias e 87,6 milhões de posições; desde 06/11/2026 roda a cada hora pelo Airflow |
| **3. Gold e dbt** | Headway, irregularidade e espera por linha e faixa horária | **pronta em 05/11/2026**: 311 linhas, 49,4 milhões de headways, conferida por uma segunda conta; corredor ficou de fora |
| **4. Análise** | Conclusão com recomendação numérica | **pronta em 06/11/2026**: em dia útil a irregularidade soma 2,9 min à espera (+50%), 20 linhas somam 55% disso; [docs/analise.md](docs/analise.md) |
| **5. ML** | Prever ônibus colados dez paradas antes | **pronta em 08/11/2026**: no teste, PR-AUC 0,511 contra 0,392 da persistência; com a hipótese de custo, alertar poupa só 0,8%; [docs/ml.md](docs/ml.md) |
| **6. Orquestração** | Airflow com backfill por janela de data | **no ar desde 06/11/2026**: Silver e Gold a cada hora fechada, reprocessamento idempotente por janela |

## O feed, medido

Medições de 14/09/2026, 22h30 a 22h45 UTC, contra o endpoint
`vehicle-positions` ([dados.pbh.gov.br/dataset/gtfs-rt](https://dados.pbh.gov.br/dataset/gtfs-rt)):

| Medida | Valor |
|---|---|
| Resposta | HTTP 200, `application/x-google-protobuf`, GTFS-RT 1.0 |
| Tamanho por chamada | 199 a 210 KB às 19h30 de BH; ~119 KB às 20h50 |
| Tamanho gravado (gzip) | ~61 KB às 19h30; ~37 KB às 20h50 |
| Latência | 0,47 a 0,77 s |
| Veículos por snapshot | 1.491 a 1.566 |
| Geração de snapshot novo | a cada ~20 s (pelo `header.timestamp`) |

Duas coisas que só apareceram medindo:

- **Coletas repetidas.** Duas chamadas com 15 s de intervalo devolveram a
  resposta idêntica byte a byte. Como o snapshot muda a cada ~20 s e a coleta é
  a cada 30 s, parte das coletas repete a anterior. O coletor marca isso no log
  pelo SHA-256, e a deduplicação por `(vehicle_id, timestamp)` fica na camada
  silver.
- **A API falha, e com frequência mensurável.** Em 18 dias houve 5 episódios,
  todos de `ReadTimeout`, mais um `HTTP 502`. Duram de 45 s a 4 min e se
  resolvem sozinhos. O backoff cobre todos.
- **O volume depende do horário.** O arquivo encolhe cerca de 40% entre o fim
  da tarde e a noite, porque há menos ônibus rodando. Por isso a estimativa de
  disco só será publicada com um dia inteiro coletado, não extrapolada de uma
  medida de pico.

## Auditoria de 18 dias em produção (02/10/2026)

Números medidos na VM, não estimados. Período de 14/09 23h a 02/10 23h UTC:

| Medida | Valor |
|---|---|
| Horas com dado | **433 de 433**, nenhuma hora vazia |
| Coletas gravadas | **51.772** |
| **Cobertura** | **99,934%** das 51.720 coletas esperadas nas 431 horas inteiras |
| Coletas perdidas | 34, concentradas em 5 episódios |
| Reinícios do serviço por falha | **0** |
| Falhas de compactação | **0** em 432 horas consolidadas |
| Falhas de limpeza | **0** |
| Arquivos corrompidos | 0 (`gzip -t` em todos os 3.033 da primeira auditoria; depois, conferência por SHA-256 de cada coleta antes de apagar) |
| Alertas falsos | 0 |

### Os 5 episódios de falha, todos da API

| Quando (UTC) | Duração | Coletas perdidas | Causa |
|---|---|---|---|
| 18/09 09:06 | ~2 min | 8 | `ReadTimeout` |
| 23/09 03:41 | ~2 min | 8 | `ReadTimeout`, depois um `HTTP 502` |
| 27/09 00:40 | 45 s | 1 | `ConnectionError` |
| 28/09 07:08 | ~4 min | 9 | `ReadTimeout` |
| 02/10 03:40 | ~2 min | 8 | `ReadTimeout` |

Nenhuma falha foi do coletor: em todos os casos a API parou de responder e
voltou sozinha. **Parte da perda é do próprio backoff**, que é a decisão certa
mas tem custo visível: o log registra 14 tentativas que falharam, e as outras
20 coletas se perderam enquanto o backoff esperava 60 s, 120 s e 240 s antes de
tentar de novo. É o preço de não martelar uma API pública que já está com
problema.

O reinício do dia 01/10 às 06:05 UTC não foi falha: o `unattended-upgrades` do
Ubuntu reexecutou o systemd, o coletor parou de forma limpa pelo `SIGTERM` e
voltou 4 segundos depois, **sem perder nenhuma coleta**.

### Volume real, por dia da semana

| Dia | Tamanho consolidado |
|---|---|
| Terça a sexta | 30,1 a 32,3 MB |
| Sábado | 18,3 a 19,3 MB |
| **Domingo** | **11,4 a 11,6 MB** |

Domingo tem cerca de **36% do volume de um dia útil**, o que é a frota reduzida
aparecendo no tamanho do arquivo. A média dos 17 dias completos é de **27,5 MB
por dia**, ou **0,82 GB por mês**, bem abaixo dos 2,2 GB/mês estimados no
projeto antes de existir medição. No volume de 100 GB, isso dá mais de **9 anos**
de histórico.

### Deduplicação, medida

A posição de cada veículo chega com idade mediana de 45 s e p90 de 82 s, mais
lenta que a coleta de 30 s. Contando chaves `(vehicle_id, timestamp)`
distintas, **40,1% dos registros no pico da manhã são repetição de coletas
anteriores** (base: total de registros lidos numa janela de 30 min), e 17,5% na
madrugada. A projeção inicial do projeto era de 131 milhões de linhas por mês;
o número real, após deduplicação, fica em torno de **58,7 milhões**.

## Arquitetura da fase 0

```
feed GTFS-RT (a cada 30 s)
        |
   coletor Python (systemd, Restart=always)
        |  resposta crua, gzip, escrita atômica
        v
   /dados/bronze/vehicle_positions/dt=AAAA-MM-DD/hh=HH/AAAAMMDDTHHMMSSZ.pb.gz
        |
   vigia (systemd timer, 5 min) -> check coletor-eventos: sem arquivo, 401/403,
                                   falha de disco e feed parado com status 200
   ping externo (healthchecks)  -> e-mail, Telegram e SMS se parar de gravar,
                                   inclusive com a VM inteira fora do ar
```

## Decisões e o porquê

**Coletor fora do Airflow.** É o único processo cuja falha perde dado para
sempre. Fica o mais simples possível: sem scheduler, banco ou fila. O Airflow
vai orquestrar o que vem depois, que é reprocessável.

**Grava cru, sem decodificar.** Se o parsing tiver bug, o bruto permite
reprocessar. A camada bronze é imutável: o coletor nunca sobrescreve arquivo.

**Particionado por `dt` e `hh` em UTC desde o primeiro arquivo.**
Reparticionar milhões de arquivos depois é caro. UTC porque horário local tem
ambiguidade; a conversão para o horário de BH é da camada silver.

**Um arquivo por coleta, de propósito.** São 2.880 arquivos por dia, o clássico
problema de *small files* para o Spark. Gravar pequeno é seguro (uma coleta
ruim afeta só o próprio arquivo); ler pequeno é lento. A compactação horária da
fase 1 resolve a leitura. Cada responsabilidade num processo.

**Escrita atômica.** Grava num temporário oculto, faz `fsync` e renomeia. Quem
lê a partição nunca vê arquivo pela metade, mesmo com queda de energia.

**Agenda alinhada ao relógio** (:00 e :30), não "dormir 30 s". A latência não
se acumula e lacunas ficam fáceis de achar pelo nome do arquivo.

**Backoff exponencial de 30 s a 5 min.** Nunca retenta mais rápido que a
cadência normal, para não martelar uma API pública justamente quando ela está
com problema.

**401 e 403 viram alerta, não erro comum.** Significam que a chave da URL foi
rotacionada. Sem alerta, o serviço seguiria "rodando" sem gravar nada.

**200 que não é protobuf não vira bronze.** Uma página HTML de manutenção com
status 200 não é dado e não pode fingir ser feed.

**Vigia em processo separado.** Checagem dentro do coletor morre junto com ele.
O vigia mede o resultado que importa: arquivo novo no disco, e posição de ônibus
nova dentro dele.

**Um só processo fala com o check de eventos.** O coletor só registra o status de
cada coleta no log; quem lê esse log e alerta é o vigia. Com os dois pingando o
mesmo check, o "ok" do vigia apagaria o "401" que o coletor acabou de mandar. De
quebra, mudar o alerta não pede reiniciar o coletor.

**Falha de ping nunca derruba a coleta.** Em 18 dias, 23 pings ao serviço de
monitoramento falharam por timeout, contra 14 coletas que falharam. Como o ping
só é tentado depois do arquivo já estar gravado, e a exceção é capturada, essas
falhas não custaram nenhum dado nem geraram alerta falso.

**Ping externo, além do vigia.** O vigia roda na mesma VM; se a VM cair, ele cai
junto. Um serviço externo que alerta quando os pings param cobre esse caso. O
mesmo serviço entrega os alertas do vigia (check `coletor-eventos`), o que
dispensou um bot de Telegram próprio: nenhum token de bot na VM.

## Compactação horária (fase 1)

2.880 arquivos por dia são cerca de 87,7 mil por mês. Esse é o problema
clássico de *small files*, que trava leitura em Spark. O job consolida cada
hora fechada num único contêiner:

```
/dados/bronze/vehicle_positions/dt=2026-09-15/hh=10/*.pb.gz   120 arquivos
        |  compactacao.compactar (timer horário, minuto 20)
        v
/dados/bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.pb.zst
/dados/bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.pb.json
        |  compactacao.limpar (diário, quarentena de 48 h)
        v
originais apagados, só depois de conferidos hash a hash
```

**Resultado medido em 432 horas consolidadas, sem nenhuma falha:** um dia útil
sai de 121,6 MB em 2.880 arquivos para **cerca de 31 MB em 24 arquivos**, uma
redução de **74%**. Na média dos 17 dias completos, incluindo fins de semana,
são **27,5 MB por dia**, ou **0,82 GB por mês**. O lake inteiro de 18 dias ocupa
**504 MB em 432 contêineres**, contra os 87,7 mil arquivos por mês que o layout
original geraria.

### O formato do contêiner

Fluxo zstd contendo o cabecalho `VPBH1` e, para cada coleta, 16 bytes com o
nome (`20260915T100000Z`), 4 bytes big-endian com o tamanho e o protobuf cru.
O formato completo esta documentado em [compactacao/formato.py](compactacao/formato.py).

**Por que não Parquet decodificado.** Medido numa hora de pico: Parquet com as
17 colunas do feed ocupa 2,89 MB e responde uma contagem por `route_id` em
0,25 s, contra 2,16 MB e 1,34 s deste contêiner. O Parquet é mais rápido de
consultar, mas decodificar aqui significaria escolher hoje quais campos
importam e descartar em silêncio qualquer campo novo que a operadora passe a
enviar. O Bronze guarda o que a fonte devolveu; quem decodifica é a Silver.

**Por que é seguro apagar os originais.** O coletor comprime com gzip nível 6 e
`mtime=0`, que é determinístico, então o `.pb.gz` original é reconstruído byte
a byte a partir do contêiner. Verificado em 60 arquivos espalhados por um dia
(60 de 60 com SHA-256 idêntico) e, na primeira execução real, em 4.574 coletas.
O byte de sistema operacional do cabeçalho gzip é fixado em Unix (`03`): a zlib
do Windows grava `0a`, e sem essa fixação a reconstrução só batia dentro da VM.
Isso apareceu no primeiro teste de restauração feito fora dela.

### Idempotência e backfill

- Rodar duas vezes sobre a mesma hora **não duplica nem perde**: a hora já
  compactada é pulada, e o zstd é determinístico, então o contêiner reescrito
  sairia idêntico. Verificado em produção: a segunda execução não tocou em
  nenhum dos 39 arquivos.
- Pular sem conferir seria pior que reprocessar, então a hora só é considerada
  pronta se o contêiner existir, bater em tamanho e em SHA-256 com o manifesto,
  e tiver pelo menos tantas coletas quanto a partição de origem. Contêiner
  truncado ou coleta atrasada que apareceu depois voltam para a fila.
- O job processa **todas** as horas fechadas sem contêiner válido, não apenas a
  anterior. Se a VM ficar horas fora do ar, a execução seguinte recupera tudo
  sozinha.
- A hora H só é elegível 20 minutos depois de H+1, porque o nome do arquivo é o
  horário real da coleta e o backoff do coletor tem teto de 5 minutos.

### Apagar original é um job separado

Com duas travas: quarentena de 48 h e conferência no momento de apagar, não
antes. A conferência é feita para a hora inteira **antes** de apagar qualquer
arquivo, porque apagar durante a verificação deixaria meia hora apagada quando
o arquivo divergente aparece no meio da lista. Modo `--seco` mostra o que seria
apagado sem apagar.

## Backup fora da VM

Os originais são apagados 48 h depois de compactados, então os contêineres são
a única cópia do histórico. Desde 23/10/2026 um job de hora em hora copia cada
contêiner e seu manifesto para um bucket de Object Storage do mesmo provedor:

```
/dados/bronze_horario/.../vp_20260915T10.pb.zst  (+ .pb.json)
        |  backup.enviar (timer horário, minuto 45; hora fechada há 2 h)
        v
bucket radar-onibus-backup, mesmo caminho como nome do objeto
        |  backup.restaurar --dia AAAA-MM-DD (de qualquer máquina)
        v
contêineres conferidos e, com --originais, os .pb.gz por coleta
```

**O que só conta como feito.** O job lê cada objeto de volta do bucket e
compara o SHA-256 com o do manifesto. Status 200 no envio não prova o que ficou
gravado. O estado local guarda o que já foi conferido, então rodar de novo não
reenvia nada; se o estado se perder, o job tenta de novo, o bucket recusa e ele
confere o que já está lá.

**Quem toma a VM não destrói o backup.** O acesso é por URL pré-autenticada,
sem SDK nem chave de API na VM. Ela lê e grava, mas a documentação do provedor
diz que esse tipo de URL não apaga objetos, e o bucket tem uma regra de
retenção indefinida que impede sobrescrever. Testado em 23/10/2026:

| Tentativa pela URL da VM | Resposta |
|---|---|
| Sobrescrever um objeto existente | `403 RetentionRuleViolation` |
| Apagar um objeto | recusado |

A regra de retenção não foi travada de propósito: travar é irreversível, nem o
dono da conta consegue remover depois. Sem trava, ela só sai pelo console.

**Medido na primeira execução:**

| Medida | Valor |
|---|---|
| Horas enviadas e conferidas | 927, de 14/09 a 23/10/2026, 0 falhas |
| Tempo | 4 min 23 s, com 21 s de CPU e prioridade baixa de CPU e disco |
| Efeito no coletor | nenhum aviso no log e o mesmo processo antes e depois |

**Restauração testada.** O dia 15/09/2026, cujos originais já tinham sido
apagados da VM, foi restaurado do bucket num PC Windows: 24 horas e **2.880 de
2.880 coletas** reconstruídas byte a byte, conferidas contra o SHA-256 que o
manifesto guardou antes de o original ser apagado.

**Cota gratuita.** Em conta paga, o provedor dá 10 GB grátis por tier (Standard,
Infrequent Access e Archive) e 50 mil requisições por mês. O job gasta 4
requisições por hora (2 envios e 2 leituras de conferência), cerca de 2.900 por
mês. A 0,82 GB por mês, o Standard enche por volta de setembro de 2027; antes
disso, uma regra de ciclo de vida move o antigo para Archive, que é grátis até
mais 10 GB e serve para restauração de desastre, mesmo levando horas.

**Regra de ciclo de vida.** Em [`backup/ciclo_de_vida.json`](backup/ciclo_de_vida.json):
contêiner (`.pb.zst`) com mais de 180 dias vai para Archive. O manifesto fica
no Standard, porque é 1% do volume (15 MB em 1.287 horas) e é o que a
conferência e a restauração leem primeiro. Aplicada no console em 07/11/2026,
junto da policy `Allow service objectstorage-sa-saopaulo-1 to manage
object-family in tenancy` no compartimento raiz. No console, o tipo do filtro
precisa ser "Include by pattern": com "Include by prefix" o `*` vale como
caractere literal e a regra não pega nada. Por que 180 dias:

| Corte | Primeiro Archive | Standard estável | Grátis até |
|---|---|---|---|
| 90 dias | 13/12/2026 | ~2,6 GB | ~dez/2027 |
| **180 dias** | **13/03/2027** | **~5,2 GB** | **~mar/2028** |
| 300 dias | 11/07/2027 | ~8,5 GB | ~jul/2028 |

Com 180 dias o teste de restauração cabe antes de julho de 2027 e a cota dura
três meses a mais que com 90. Pela documentação do provedor, a retenção
`nao-apagar` deixa o ciclo de vida mudar o tier, mas não apagar; Archive não
cobra para restaurar, guarda no mínimo 90 dias e leva até cerca de 1 h para
liberar o objeto, que fica baixável de 1 a 240 h (padrão 24 h).

**Restaurar dia em Archive.** A URL pré-autenticada não pede reidratação: o
dono marca os contêineres do dia no console (bucket, Objects, Restore) e, com
o estado Restored, roda `backup.restaurar` como sempre. Esse caminho só será
testado em março de 2027, com o primeiro dia arquivado. As três cópias de
hoje (VM do coletor, VM de processamento e bucket) fazem disso só um caso de
desastre. Se o estado do `backup.enviar` se perder, ele tenta conferir de novo
as horas antigas e as que estiverem em Archive aparecem como falha até serem
restauradas.

## Silver em Delta (fase 2)

O Bronze guarda cada coleta como veio. A Silver guarda cada posição uma vez:

```
bucket radar-onibus-backup
        |  silver.sincronizar --de --ate (só o que falta, conferindo o SHA-256)
        v
bronze_horario/ na VM de processamento
        |  silver.processar --de --ate (dia de BH: 24 horas, das 03h às 02h UTC)
        v
tabela Delta silver/posicoes, particionada por data_bh
```

**Onde roda.** A VM do coletor tem 1 GB de RAM e não comporta Spark. O job roda
em Docker numa segunda VM do mesmo provedor (ARM, 2 OCPU, 12 GB), e a entrada é
o bucket de backup. Nada disso toca a VM do coletor.

**As decisões:**

- **Chave do próprio feed.** A deduplicação é por `(vehicle_id, vehicle_ts)`,
  não pelo horário da coleta: o mesmo ônibus parado no feed aparece igual em
  várias coletas.
- **Fica a primeira coleta.** A mesma posição pode cair em dois dias de
  processamento, como nas coletas de 02:59:30 e 03:00:00 UTC. O `MERGE` só
  atualiza quando a cópia nova foi vista antes da gravada, então o resultado
  não depende da ordem.
- **Partição pelo evento.** `data_bh` vem de `vehicle_ts`, convertido para BH.
  Uma posição das 23:59:50 coletada às 00:00:30 pertence ao dia anterior.
- **`OPTIMIZE` depois do `MERGE`.** Cada partição termina com um arquivo,
  ordenado por `route_id`, e o `VACUUM` remove o que ficou sem uso há mais de
  7 dias.

**Medido em 05/11/2026:**

| Medida | Valor |
|---|---|
| Janela | 14/09 a 04/11/2026: 52 dias, com 14/09 parcial (4 horas, início da coleta) |
| Registros lidos | 128.973.953 |
| Linhas na tabela | 87.584.194, igual ao número de chaves distintas |
| Duplicação | 32,1% no total; de 20,6% a 38,8% por dia cheio |
| Horas ausentes | nenhuma nos 51 dias cheios |
| Linhas por dia cheio | de 690.251 a 2.239.563, cerca de 51,4 milhões por mês |
| Tempo | mediana de 164 s por dia nos 38 primeiros; 2,15 h na janela inteira |
| Tamanho | 1,41 GiB em 52 arquivos, contra 1,4 GiB do Bronze comprimido |
| Primeiro `VACUUM` | 115 arquivos e 3,38 GB removidos; pasta de 5,7 para 2,7 GB |

A pasta segue maior que a tabela porque ainda guarda as versões dos últimos 7
dias, que o `VACUUM` só remove quando vencerem.

**Como foi conferido:**

- **Inserções contra a tabela.** A soma das inserções nos 54 `MERGE`s do
  histórico do Delta é 87.584.194, igual à contagem da tabela.
- **Spark contra Python.** No pico de 15/09, o Spark chega à mesma contagem de
  registros e de únicos que uma deduplicação em Python puro, e as 60 primeiras
  coletas reproduzem a auditoria de 16/09 (40,1% de duplicação às 07h em BH,
  17,5% às 02h). Os testes ficam em `tests/test_silver.py`.
- **Reprocessar não muda nada.** O dia 04/11 rodou de novo com 3.101.008
  registros: 0 linhas inseridas e 0 atualizadas. O `MERGE` ainda reescreve os
  arquivos que tocou, com o mesmo conteúdo, então reprocessar ocupa disco até o
  próximo `VACUUM`.
- **Ordem invertida.** As únicas 31 atualizações do histórico vieram de 14/09,
  processado depois de 15/09: a posição gravada ficou com a coleta mais antiga,
  como previsto.

**O que o dado mostrou:**

| Achado | Medida | Consequência |
|---|---|---|
| `speed` nunca vem no feed | 100% nulo | velocidade, se precisar, é calculada pela posição |
| `current_status` só tem um valor | 100% `IN_TRANSIT_TO` | `stop_id` é a próxima parada, nunca a parada atual |
| GPS fora da região de BH | 3 linhas em 25/10, uma em latitude 31,4 | a Silver mantém, a Gold filtra |
| Posição à frente da coleta | 1 linha, 4 s | relógio do veículo adiantado; a Silver mantém |
| Atraso entre evento e primeira coleta | p50 de 41 s, p99 de 79 s, máximo de 600 s | referência para a latência da fase 5 |

Para rodar (os testes de Spark só rodam no contêiner e são pulados fora dele):

```bash
docker build -f Dockerfile.spark -t radar-spark:dev .
docker run --rm --env-file .env -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m silver.sincronizar --de 2026-09-15 --ate 2026-09-21
docker run --rm -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m silver.processar --de 2026-09-15 --ate 2026-09-21 --vacuum
docker run --rm -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m silver.processar --hora 2026-11-04T15 --sem-optimize
docker run --rm -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m silver.manutencao optimize --de 2026-11-04 --ate 2026-11-04
docker run --rm -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m silver.manutencao vacuum
docker run --rm -e RADAR_DADOS_REAIS=/app/dados -v "$PWD:/app" -v "$HOME/ivy:/root/.ivy2.5.2" -w /app radar-spark:dev   python -m pytest -q
```

## Gold em dbt (fase 3)

A Gold transforma posições em espera. Para cada linha, sentido, dia e faixa
horária, mede de quanto em quanto tempo passa um ônibus, quão irregular é esse
intervalo e quanto essa irregularidade custa a quem está no ponto. A regra
completa, com o porquê de cada limite, está em [gold/README.md](gold/README.md).

**Como funciona.** O feed só informa a próxima parada. Quando ela muda, o ônibus
passou pela anterior, e o instante é estimado dentro do intervalo entre as duas
posições. O headway é o tempo entre passagens de ônibus da mesma linha na mesma
parada. Com ele vêm o coeficiente de variação e a espera estimada de quem chega ao
acaso, `E[H²] / (2 E[H])`. A espera em excesso é a diferença para a mesma frota
igualmente espaçada.

**Onde roda.** dbt-spark no mesmo contêiner da Silver, na VM de processamento. As
tabelas ficam em Delta no disco dessa VM, como a Silver. O build completo levou
19 min.

**Medido em 05/11/2026, de 15/09 a 04/11:**

| Medida | Valor |
|---|---|
| Mart de leitura | 90.325 linhas, 311 linhas de ônibus |
| Headways | 49.440.404, 97,4% válidos |
| Espera em excesso média | 3,07 min por espera, com CV de 0,416 |
| Pior e melhor faixa | madrugada 4,39 min, início da manhã 1,75 min |
| Pico da tarde contra pico da manhã | 3,82 contra 2,18 min |

**Como foi conferido.**

- **Segunda conta.** `gold/conferencia.py` refaz o cálculo em Python puro a partir
  da Silver. Em 3 linhas e 12 dias, 307 linhas do mart e 235.790 headways, deu 0
  divergências.
- **Testes.** 68 testes de dados (unicidade, nulos, faixa plausível e conciliação
  entre camadas), 10 testes unitários dos modelos, 13 testes Python da conferência
  e 5 da impressão digital (`tests/test_digitais.py`).
- **Dado sujo conhecido vira aviso.** Os 3 GPS fora da região e a posição à frente
  da coleta têm testes que avisam se aparecer um caso novo.

**O que o dado mostrou.**

- **O feed cai e o status continua 200.** Foram 16 quedas, de até 82 min, em que a
  frota inteira parou de publicar. O headway que atravessa uma queda mede o feed,
  não o serviço: tirá-los baixou a espera em excesso de 26/10 em 19%. Desde a
  issue #4 o vigia percebe a queda na hora: alerta quando a posição mais nova do
  feed passa de 10 min.
- **25 a 28/10 têm de 2,5 a 3 vezes mais buraco de GPS**, em 85% dos veículos e
  em todas as horas, sem causa conhecida. Os números desses dias ficam, com o aviso.

**Corredor ficou de fora.** Agrupar linhas por corredor pede a geometria das vias,
que o feed em tempo real não traz.

```bash
docker build -f Dockerfile.gold -t radar-gold:dev .
sh gold/rodar.sh seed
sh gold/rodar.sh build
```

## Orquestração com Airflow (fase 6)

O Airflow roda na VM de processamento e encadeia, a cada hora fechada, Silver e
Gold. O coletor, a compactação e o backup continuam no systemd da VM do coletor:
são o que não pode parar, e não dependem do Airflow para nada.

```
coletor (VM 1) -> compactação -> backup no bucket, minuto 45
                                     |
radar_horario (VM 2, uma execução por hora UTC)
  aguardar_backup  sensor: o manifesto da hora chegou ao bucket?
  sincronizar      traz o contêiner da hora e confere o SHA-256
  silver           MERGE só daquela hora
  gold             dbt build com a janela de ontem e hoje (dias de BH)
  avisar_ok        ping no healthchecks
  na última hora do dia de BH: OPTIMIZE da Silver daquele dia
  na última hora do domingo:   VACUUM da Silver e da Gold, 7 dias de retenção

radar_reprocessar (manual): de, até e camadas -> Silver e Gold da janela

radar_limpeza (diária, 06:30 UTC, pool spark)
  limpar_banco     airflow db clean do que tem mais de 30 dias, sem arquivar
  limpar_logs      apaga log de tarefa com mais de 30 dias e as pastas vazias
```

**Decisão: Airflow dentro da VM de processamento.** A VM tem 2 OCPU e 12 GB. O
Airflow parado ocupa cerca de 1,0 GB (scheduler 370 MB, processador de DAGs
321 MB, API 283 MB, Postgres 44 MB). O Spark sobe só durante a tarefa, num
contêiner irmão, com 4 GB de driver na Silver e 8 GB na Gold, e o pool `spark`
deixa um por vez. Pico medido em 06/11/2026: 7.306 MB usados de 11.925 no
reprocessamento de 7 dias e 6.838 MB nas 33 horas da DAG horária. Fora da VM
custaria uma máquina a mais para
ganhar nada: o Airflow só dispara contêineres.

**Como ficou enxuto.** LocalExecutor, sem Redis nem worker; sem triggerer; a
interface só escuta em `127.0.0.1` e é acessada por túnel SSH. As tarefas são
`DockerOperator` com as mesmas imagens `radar-spark` e `radar-gold` da linha de
comando: o que roda no Airflow é o mesmo comando que roda à mão.

**Idempotência.** Rodar a mesma hora de novo não muda nada: a Silver deduplica
por `(vehicle_id, vehicle_ts)` com MERGE, e a Gold regrava só as partições da
janela. Provado com a impressão digital de cada tabela por dia
(`gold/digitais.py`):

| Teste | Resultado |
|---|---|
| Silver de uma hora já processada (04/11, 15h UTC) | 154.091 registros lidos, 0 inseridos, 0 atualizados, em 112 s |
| Build completo contra reprocessamento de 19 a 25/10 | 0 dias diferentes nas 8 tabelas; a janela de 7 dias levou 10 min |
| A mesma janela rodada duas vezes | 0 dias diferentes; 10 min de novo |
| DAG horária de 05/11, 03h UTC, a 06/11, 11h UTC (33 horas) | 33 sucessos, 7 a 8 min por hora: Silver cerca de 1 min 30 s, Gold cerca de 6 min 40 s (janela de ontem e hoje) |
| OPTIMIZE da Silver no fim do dia de BH (05/11) | 1 min 13 s |
| VACUUM da Gold, 10 tabelas | 11 min; nada removido, porque toda a Gold tinha menos de 7 dias |

Em regime, cada hora termina cerca de 2 h 50 depois de fechar: o sensor espera a
compactação e o backup da VM do coletor.

**Alerta.** A DAG pinga o check `processamento-horario` no fim de cada hora e
manda `/fail` quando uma tarefa falha. A URL fica no `.env`.

**Limpeza do próprio Airflow.** Cada execução deixa log por tarefa e linhas no
Postgres; sem limpeza, crescem sem fim (medido em 07/11/2026: 33 MB de log e
13 MB de banco depois de 47 execuções, cerca de 0,6 MB de log por hora). A DAG
`radar_limpeza` apaga o que tem mais de 30 dias, todo dia às 06:30 UTC. As duas
tarefas usam o pool `spark`, então esperam o Spark da hora acabar. Os logs do
`radar_reprocessar` ficam para sempre: ele roda à mão, poucas vezes, e o log é a
prova do que foi refeito e quando. No banco ele vence como o resto, por dois
limites do Airflow 3.3.2, achados no teste em modo seco:

- `--exclude-dag-ids` quebra o comando: a configuração do `db clean` diz que
  `deadline`, `asset_event` e `task_reschedule` têm `dag_id`, mas as tabelas não
  têm, e limpar `dag_run` puxa `deadline` junto.
- O processo da tarefa não enxerga o banco de metadados (o Airflow 3 troca a URL
  por uma inválida). A tarefa remonta a URL só para o subprocesso do `db clean`,
  com a senha do `orquestracao/.env` que o compose já usa.

O `db clean` mantém a última execução agendada de cada DAG, então o agendamento
não recua. Regras e testes em `orquestracao/dags/radar_limpeza_regras.py` e
`tests/test_limpeza_airflow.py`.

**Hora que nunca chega.** Se o coletor ficar parado uma hora inteira, o manifesto
dela nunca existe. O sensor espera 6 h, falha e avisa. Como a DAG roda uma hora
por vez (`max_active_runs=1`), as horas seguintes ficam na fila durante essa
espera e andam em sequência depois da falha, porque cada hora é independente na
Silver. Se a hora chegar ao bucket depois das 6 h, basta limpar a tarefa
`aguardar_backup` daquela execução na interface para ela rodar de novo.

Para subir, na VM de processamento:

```bash
cp orquestracao/.env.example orquestracao/.env   # preencher; nunca vai para o Git
cd orquestracao && docker compose up -d
ssh -L 8080:localhost:8080 ubuntu@<ip-da-vm>        # e abrir http://localhost:8080
docker compose exec airflow-scheduler airflow dags trigger radar_reprocessar   -c '{"de": "2026-10-19", "ate": "2026-10-25", "camadas": "so_gold"}'
```

## O que foi descartado, com a evidência

Cada alternativa abaixo foi medida no dado real antes de ser descartada.

### Coletar com intervalo maior que 30 s

A auditoria mostrou 40,1% de registros repetidos no pico, o que sugeria coletar
com menos frequência. Simulado nas horas já compactadas de 15/09/2026, pegando
uma coleta a cada duas (60 s) e a cada três (90 s):

| Hora (BH) | Intervalo | Posições únicas | Perdidas | Disco compactado | Intervalo mediano entre posições do mesmo ônibus |
|---|---|---|---|---|---|
| 07h, pico | **30 s** | **141.758** | 0 | 2,16 MB | **45 s** |
| 07h, pico | 60 s | 111.892 | 21,1% | 1,79 MB | 60 s |
| 07h, pico | 90 s | 76.050 | 46,4% | 1,30 MB | 91 s |
| 11h | **30 s** | **95.843** | 0 | 1,50 MB | **45 s** |
| 11h | 60 s | 70.261 | 26,7% | 1,16 MB | 61 s |
| 11h | 90 s | 47.967 | 50,0% | 0,85 MB | 91 s |
| 02h | **30 s** | **4.547** | 0 | 0,08 MB | **31 s** |
| 02h | 60 s | 2.626 | 42,2% | 0,05 MB | 61 s |

Base dos percentuais: posições únicas `(vehicle_id, timestamp)` capturadas a
30 s na mesma hora. 45 s não foi simulado porque não cai no grid de coleta.

**Por que ficou em 30 s:**

- A troca é ruim: coletar a 60 s perde de 21% a 27% das posições únicas nas
  horas de operação para economizar de 17% a 23% de disco já compactado.
- Repetição não é desperdício puro. Parte das coletas "repetidas" traz posição
  nova de outros veículos, e o zstd elimina quase todo o custo das que de fato
  se repetem.
- A pergunta do projeto é sobre intervalo entre ônibus. A resolução de 45 s por
  veículo pioraria para 60 s justamente na métrica que a análise quer medir.
- A decisão é assimétrica: dado coletado pode ser descartado na Silver; dado
  não coletado não volta.

### Parquet decodificado no Bronze

Medido numa hora de pico (120 coletas, 233.306 registros):

| Formato | Tamanho | Contagem por `route_id` | Preserva o byte cru |
|---|---|---|---|
| 120 arquivos `.pb.gz` (antes) | 8,94 MB | 1,77 s | sim |
| **Contêiner zstd (escolhido)** | **2,16 MB** | 1,34 s | **sim** |
| Parquet decodificado, 17 colunas, zstd | 2,89 MB | 0,25 s | não |
| Parquet com o protobuf em coluna binária | 4,84 MB | 1,20 s | sim |
| `tar` dos arquivos `.pb.gz` | 9,15 MB | não medido | sim |

O Parquet decodificado responde consulta cinco vezes mais rápido, mas obriga a
escolher hoje quais campos do feed importam, e campo novo que a operadora passe
a enviar seria descartado sem aviso. Consulta rápida é papel da Silver em Delta.
O Parquet com coluna binária preserva o bruto e é lido nativamente pelo Spark,
mas ocupa 2,2 vezes o contêiner sem ganho de leitura, porque o protobuf ainda
precisa ser decodificado. O `tar` não compacta nada: os arquivos já estão em
gzip, e o gzip por arquivo não enxerga a redundância entre coletas vizinhas.

### Destino do backup

Limites conferidos nas páginas oficiais em 23/10/2026:

| Destino | Grátis | Conta nova | Fora do provedor da VM |
|---|---|---|---|
| **Object Storage do mesmo provedor (escolhido)** | 10 GB por tier, 50 mil requisições/mês | não | não |
| Cloudflare R2 | 10 GB-mês | sim | sim |
| Backblaze B2 | primeiros 10 GB | sim | sim |
| Azure for Students | crédito anual, renovável enquanto estudante | sim | sim |
| Backup do block volume | 5 backups | não | não |

O escolhido resolve o risco que motivou o backup, que é o volume falhar, sem
conta nova, sem SDK na VM de 1 GB e com proteção contra sobrescrita. O que ele
não cobre é a perda da conta inteira, porque primário e cópia ficam no mesmo
provedor. Esse risco fica registrado abaixo, em aberto. A ideia inicial era
gravar a Silver no Azure e ganhar a cópia fora do provedor com isso; a Silver
acabou em disco local, então essa cópia não veio com a fase 2.

### Deduplicar na coleta ou na compactação

Descartado por princípio, não por custo: o Bronze guarda o que a API devolveu,
inclusive a repetição, que é informação sobre a fonte (é dela que saiu a
medida de idade das posições). A deduplicação por `(vehicle_id, timestamp)`
fica na Silver, com `MERGE`, onde é versionada e testável.

## Rodando localmente

Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env        # COLETOR_URL; URLs de ping são opcionais
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m coletor          # Ctrl+C para parar
.\.venv\Scripts\python.exe -m coletor.vigia    # checagem avulsa
```

Os arquivos vão para `./dados` e o log de cada coleta para
`./logs/coletas.jsonl`, uma linha JSON com horário, status, bytes, latência,
hash e se repetiu a coleta anterior.

## Produção

Uma VM Always Free (1 GB de RAM, Ubuntu 24.04) com um block volume de 100 GB
separado do disco de boot, montado em `/dados`.

| Peça | Configuração | Por quê |
|---|---|---|
| Volume de dados | separado do boot, montado por UUID, `noatime`, `nofail` | O dado sobrevive se a VM for recriada; se o volume falhar no boot, a VM ainda sobe e aceita SSH |
| Coletor | `Restart=always`, `StartLimitIntervalSec=0`, `RequiresMountsFor=/dados` | Nunca desiste de reiniciar e nunca grava no disco de boot por engano |
| Usuário `coletor` | conta de sistema sem login; código pertence ao root | O processo não consegue alterar o próprio código |
| `.env` | `root:coletor`, modo 640 | Segredos legíveis só pelo serviço |
| Swap | 1 GB, `swappiness=10` | Com 1 GB de RAM, sem swap o kernel mata processo quando a memória acaba |

Testado em 14/09/2026, antes de acumular dado, e confirmado em produção depois:

| Teste | Resultado |
|---|---|
| 36 testes, no Windows e na VM (Python 3.12.3) | todos passando |
| `kill -9` no coletor | reiniciado em ~10 s, nenhuma coleta perdida |
| Reboot da VM | volume montou, coletor e vigia voltaram; 2 coletas perdidas durante o boot |
| Queda simulada do ping (16/09) | alerta `DOWN` em 11 min no Telegram e no e-mail, sem perder coleta |
| `unattended-upgrades` reiniciando o serviço (01/10, não planejado) | parada limpa pelo `SIGTERM` e volta em 4 s, **sem perder coleta** |
| Vigia contra o check `coletor-eventos` (06/11), na VM, com dados e log temporários | os 4 casos detectados: sem arquivo, 401, falha de disco e feed parado (arquivo real de 30 min antes: posição 31 min velha); os 4 alertas e os 4 avisos de volta chegaram no e-mail e no Telegram, com o motivo; sem tocar no coletor |

Instalação das units:

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coletor-onibus.service coletor-onibus-vigia.timer
sudo systemctl enable --now coletor-onibus-compactacao.timer coletor-onibus-limpeza.timer coletor-onibus-backup.timer
journalctl -u coletor-onibus -f          # acompanhar as coletas
systemctl list-timers coletor-onibus-vigia.timer
```

### Alertas

Duas camadas, porque cada uma cobre o que a outra não vê:

| Camada | Onde roda | Dispara quando | Cobre VM fora do ar? |
|---|---|---|---|
| Ping externo (healthchecks.io) | fora da VM | nenhum arquivo gravado em 1 min + 10 min de tolerância | sim |
| Vigia local (systemd timer, 5 min), check `coletor-eventos` | na VM | última coleta com 401/403 ou falha de disco (lidos do log de coletas); mais de 10 min sem arquivo novo; feed parado: arquivo chega com status 200, mas a posição de ônibus mais nova passa de 10 min | não |

O vigia pinga sucesso a cada rodada boa. Com problema, manda `/fail` com o motivo
no corpo, uma vez por motivo, e o aviso de volta quando normaliza. O healthchecks
só notifica mudança de estado, então, se o motivo muda com o check já fora, o
vigia manda um ok antes do `/fail` novo: são dois avisos, mas a causa nova chega.
Se o próprio vigia parar, o check vence em 1 h + 1 h e avisa.

Canais por check, cada um testado com notificação real:

| Check | Período e tolerância | E-mail | Telegram | SMS |
|---|---|---|---|---|
| `coletor-onibus-bh` | 1 min + 10 min | sim | sim | **sim** |
| `compactacao-horaria` | 1 h + 30 min | sim | sim | não |
| `backup-horario` | 1 h + 2 h | sim | sim | não |
| `coletor-eventos` | 1 h + 1 h | sim | sim | não |

SMS só no coletor porque os créditos são limitados e a queda do coletor é a
única falha que perde dado para sempre. A compactação e o backup são
reprocessáveis: se pararem, o backfill recupera tudo quando voltarem, e o dado
continua na VM enquanto isso.

O coletor só pinga **depois de gravar um arquivo**, não a cada tentativa. Assim
o ping mede o resultado que importa: um coletor vivo que recebe 401 e não grava
nada também para de pingar e dispara o alerta.

### Riscos conhecidos

- **Recuperação de VM ociosa.** A documentação do provedor diz que instâncias
  Always Free com CPU p95 e rede abaixo de 20% por 7 dias podem ser
  recuperadas. O coletor usa muito menos que isso. A migração da conta para
  cobrança por uso foi solicitada em 14/09/2026 (sem custo enquanto só usa
  recursos Always Free, com alerta de orçamento); relatos no fórum do provedor
  dizem que contas pagas ficam fora dessa regra, mas a documentação oficial não
  confirma. A migração foi concluída sem cobrança. Até 02/10/2026 a VM atravessou duas janelas de 7 dias sem ser
  tocada, o que é evidência a favor, não garantia. O ping externo continua
  sendo a defesa real.
- **Dependência de uma API de terceiro.** Os 5 episódios de falha em 18 dias
  foram todos do lado do fornecedor. Nenhum passou de 4 minutos, mas uma queda
  longa custaria dado que não volta. É o que torna a segunda fonte (SPTrans) um
  plano de contingência, e não enfeite.
- **Backup no mesmo provedor.** O backup cobre falha do volume e da VM, mas não
  a perda da conta inteira. A segunda cópia, fora do provedor, segue sem data.
- **Silver sem cópia.** A tabela fica só no disco da VM de processamento. Se a
  VM se perder, ela é refeita do backup: o histórico atual levou 2,15 h de
  processamento, sem contar o download.
- **Cota gratuita do backup.** O tier Standard enche por volta de setembro de
  2027. Antes disso é preciso criar a regra de ciclo de vida para o Archive,
  senão o excedente passa a ser cobrado.
- **Validade do link do bucket.** O envio usa um pre-authenticated request,
  que tem data de vencimento. O primeiro venceu em 30/10/2026 e o backup parou
  por 6 horas, até o check `backup-horario` avisar e o link ser trocado. Nada
  se perdeu: os contêineres ficam na VM e o envio retoma de onde parou. O link
  atual vence em 31/12/2030.

## Estrutura

```
coletor/
  config.py          configuração por variável de ambiente
  armazenamento.py   layout particionado e escrita atômica
  coletor.py         loop, backoff, tratamento de status
  alerta.py          ping ok e /fail no check coletor-eventos
  vigia.py           sem arquivo, 401/403, disco e feed parado, num só check
  registro.py        log JSON Lines com rotação
compactacao/
  formato.py         contêiner horário: escrita, leitura e reconstrução do bruto
  horas.py           quais horas fecharam e quais faltam compactar
  compactar.py       job horário, idempotente e com backfill
  limpar.py          apaga originais já compactados, com quarentena
backup/
  remoto.py          leitura e escrita no bucket por URL pré-autenticada
  enviar.py          job horário: envia, lê de volta e confere o SHA-256
  restaurar.py       restaura e confere um dia inteiro, de qualquer máquina
silver/
  sincronizar.py     traz do bucket os contêineres de uma janela de datas
  janela.py          dia de BH em horas UTC
  decodificar.py     protobuf para linhas, sem confundir ausente com zero
  processar.py       job Spark: deduplicação e MERGE, por janela de dias ou por hora
  manutencao.py      OPTIMIZE e VACUUM, separados do job horário
deploy/              units do systemd (coletor, vigia, compactação, limpeza e backup)
gold/                dbt: modelos, testes, seeds, a segunda conta (conferencia.py)
                     e a impressão digital por dia (digitais.py)
orquestracao/
  docker-compose.yml Airflow da VM de processamento: Postgres, scheduler, API
  dags/              DAG horária, DAG de reprocessamento, DAG de limpeza e as regras
                     de calendário e de limpeza
analise/
  calcular.py        Fase 4: espera extra e bunching a partir da Gold (roda na VM)
  graficos.py        PNGs de docs/img a partir dos CSVs
  saida/             CSVs da última rodada, com as conferências
docs/analise.md      conclusão da Fase 4, com gráficos e onde conferir cada número
ml/
  montar.py          Fase 5: exemplos a partir da Gold, um dia por vez (Spark, na VM)
  features.py        colunas permitidas e o motivo de cada proibida
  divisao.py         treino, validação e teste por semanas, e os blocos do backtest
  treinar.py         baselines, HistGBM, backtest, limiar pelo custo e o teste único
  custo.py           hipótese de custo e ponto de equilíbrio
  publicar.py        previsões de validação e teste para gold/ml/previsao_bunching
  graficos.py        PNGs de docs/img a partir dos CSVs
  medir_frente.py    ressalva 7: passagem do ônibus da frente conhecida na decisão?
  saida/             CSVs da rodada de 08/11
docs/ml.md           conclusão da Fase 5, com gráficos e ressalvas
Dockerfile.spark     imagem do Spark com Delta
Dockerfile.gold      imagem do dbt-spark, sobre a do Spark
Dockerfile.ml        imagem da Fase 5: a do Spark mais pandas e scikit-learn
tests/               119 testes: coletor, vigia, formato, idempotência, limpeza, backup, Silver,
                     Gold, limpeza do Airflow e o que o modelo da Fase 5 pode ver
```

## Agradecimento

O monitoramento externo usa o [healthchecks.io](https://healthchecks.io), que
concedeu gratuitamente os limites do plano Business para este projeto
open-source.

## Licença

Código sob licença [MIT](LICENSE). O dado coletado não fica neste repositório:
ele vem do portal de dados abertos da Prefeitura de Belo Horizonte e segue as
condições de uso publicadas lá.
