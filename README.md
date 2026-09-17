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
| **1. Bronze e compactação** | Job horário, consolidação do bruto | **no ar desde 16/09/2026** |
| 2. Silver em Delta | PySpark, deduplicação com MERGE, headway | aguarda 4 semanas de dado |
| 3. Gold e dbt | Métricas por linha, corredor e faixa horária | |
| 4. Análise | Conclusão com recomendação numérica | |
| 5. ML | Previsão de chegada e detecção de *bus bunching* | |
| 6. Orquestração | Airflow com backfill por janela de data | |

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
- **A API falha.** Nos primeiros dois minutos de coleta houve um
  `ConnectionError`. O backoff esperou 30 s e a coleta seguinte voltou normal.
- **O volume depende do horário.** O arquivo encolhe cerca de 40% entre o fim
  da tarde e a noite, porque há menos ônibus rodando. Por isso a estimativa de
  disco só será publicada com um dia inteiro coletado, não extrapolada de uma
  medida de pico.

## Auditoria de 25 horas de coleta (16/09/2026)

Números medidos na VM, não estimados:

| Medida | Valor |
|---|---|
| Cobertura da linha do tempo | **99,93%** (3.032 arquivos em 25,27 h) |
| Dia 15/09 completo | **2.880 de 2.880 coletas, 100%** |
| Lacunas | 1, de 90 s, causada por um reboot de teste |
| Arquivos corrompidos (`gzip -t` em todos) | 0 |
| Falhas de coleta no log | 0 em 3.032 |
| Latência da API | mediana 466 ms, p90 584 ms, p99 698 ms |
| Amostra decodificada (288 arquivos) | 288 válidos, 0 registros sem `route_id` ou posição |
| Veículos por coleta | média diária 1.081, mínimo 32 (02h), máximo 2.057 (07h) |
| Volume bruto | 121,6 MB/dia, 3,61 GB/mês |

**Deduplicação, medida:** a posição de cada veículo chega com idade mediana de
45 s e p90 de 82 s, mais lenta que a coleta de 30 s. Contando chaves
`(vehicle_id, timestamp)` distintas, **40,1% dos registros no pico da manhã
são repetição de coletas anteriores** (base: total de registros lidos numa
janela de 30 min), e 17,5% na madrugada. A projeção inicial do projeto era de
131 milhões de linhas por mês; o número real, após deduplicação, fica em torno
de **58,7 milhões**.

## Arquitetura da fase 0

```
feed GTFS-RT (a cada 30 s)
        |
   coletor Python (systemd, Restart=always)
        |  resposta crua, gzip, escrita atômica
        v
   /dados/bronze/vehicle_positions/dt=AAAA-MM-DD/hh=HH/AAAAMMDDTHHMMSSZ.pb.gz
        |
   vigia (systemd timer, 5 min) -> alerta local se 10 min sem arquivo novo
   ping externo (healthchecks)  -> e-mail e Telegram se parar de gravar,
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
O vigia mede o resultado que importa: arquivo novo no disco.

**Ping externo, além do vigia.** O vigia roda na mesma VM; se a VM cair, ele cai
junto. Um serviço externo que alerta quando os pings param cobre esse caso, e
foi o que tornou opcional o bot de Telegram próprio: o serviço externo já
entrega no Telegram, sem token na VM.

## Compactação horária (fase 1)

2.880 arquivos por dia são cerca de 87,7 mil por mês. Esse é o problema
clássico de *small files*, que trava leitura em Spark. O job consolida cada
hora fechada num único contêiner:

```
/dados/bronze/vehicle_positions/dt=2026-09-15/hh=10/*.pb.gz   120 arquivos
        |  compactacao.compactar (timer horário, minuto 20)
        v
/dados/bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.pb.zst
/dados/bronze_horario/vehicle_positions/dt=2026-09-15/vp_20260915T10.json
        |  compactacao.limpar (diário, quarentena de 48 h)
        v
originais apagados, só depois de conferidos hash a hash
```

**Resultado medido em 39 horas reais:** de 121,6 MB para **32 MB por dia**, uma
redução de **74%**, e o dia inteiro passa de 2.880 arquivos para 24. Projetado
para o mês: **0,95 GB** em vez de 3,61 GB, o que estende a autonomia do disco
de 27 meses para mais de 8 anos.

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
Copy-Item .env.example .env        # preencher o Telegram, se quiser alerta
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

Testado em 14/09/2026, antes de acumular dado:

| Teste | Resultado |
|---|---|
| 18 testes na VM (Python 3.12.3) | todos passando |
| `kill -9` no coletor | reiniciado em ~10 s, nenhuma coleta perdida |
| Reboot da VM | volume montou, coletor e vigia voltaram; 2 coletas perdidas durante o boot |

Instalação das units:

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coletor-onibus.service coletor-onibus-vigia.timer
journalctl -u coletor-onibus -f          # acompanhar as coletas
systemctl list-timers coletor-onibus-vigia.timer
```

### Alertas

Duas camadas, porque cada uma cobre o que a outra não vê:

| Camada | Onde roda | Dispara quando | Cobre VM fora do ar? |
|---|---|---|---|
| Ping externo (healthchecks.io) | fora da VM | nenhum arquivo gravado em 1 min + 10 min de tolerância | sim |
| Vigia local (systemd timer, 5 min) | na VM | mais de 10 min sem arquivo novo; também 401/403 e falha de disco pelo coletor. Hoje só registra no log: o envio ao Telegram exige `TELEGRAM_BOT_TOKEN`, não configurado | não |

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
  confirma. O ping externo é a garantia real.
- **Sem backup do volume.** As políticas prontas de backup acumulam mais que os
  5 backups gratuitos. A proteção planejada é copiar o Parquet compactado da
  fase 1 para fora da VM.

## Estrutura

```
coletor/
  config.py          configuração por variável de ambiente
  armazenamento.py   layout particionado e escrita atômica
  coletor.py         loop, backoff, tratamento de status
  alerta.py          Telegram, com limite de repetição
  vigia.py           alerta de 10 min sem arquivo novo
  registro.py        log JSON Lines com rotação
compactacao/
  formato.py         contêiner horário: escrita, leitura e reconstrução do bruto
  horas.py           quais horas fecharam e quais faltam compactar
  compactar.py       job horário, idempotente e com backfill
  limpar.py          apaga originais já compactados, com quarentena
deploy/              units do systemd (coletor, vigia, compactação e limpeza)
tests/               36 testes: coletor, vigia, formato, idempotência e limpeza
```

## Agradecimento

O monitoramento externo usa o [healthchecks.io](https://healthchecks.io), que
concedeu gratuitamente os limites do plano Business para este projeto
open-source.

## Licença

Código sob licença [MIT](LICENSE). O dado coletado não fica neste repositório:
ele vem do portal de dados abertos da Prefeitura de Belo Horizonte e segue as
condições de uso publicadas lá.
