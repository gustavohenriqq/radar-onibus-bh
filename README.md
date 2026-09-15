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
| 1. Bronze e compactação | Job horário, bruto para Parquet | aguarda 1 semana de dado |
| 2. Silver em PySpark | Decodificação, deduplicação, headway | aguarda 4 semanas de dado |
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
| Ping externo (healthchecks.io, plano gratuito) | fora da VM | nenhum arquivo gravado em 1 min + 10 min de tolerância | sim |
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
deploy/              units do systemd (coletor, vigia e timer)
tests/               testes do coletor e do vigia
```

## Licença

Código sob licença [MIT](LICENSE). O dado coletado não fica neste repositório:
ele vem do portal de dados abertos da Prefeitura de Belo Horizonte e segue as
condições de uso publicadas lá.
