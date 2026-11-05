#!/bin/sh
# Roda o dbt no conteiner da Gold, na VM de processamento.
# Uso: sh gold/rodar.sh build --vars '{data_inicio: 2026-10-19, data_fim: 2026-10-25}'
# O Spark 4 guarda os jars em ~/.ivy2.5.2: montar ali evita baixar tudo a cada execucao.
exec docker run --rm \
  -v /home/ubuntu/radar:/app -v /home/ubuntu/ivy:/root/.ivy2.5.2 \
  -w /app/gold radar-gold:dev dbt "$@"
