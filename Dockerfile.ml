# Imagem da fase 5: a do Spark (montagem dos exemplos) mais pandas e
# scikit-learn (treino). Separada para nao pesar a imagem que o Airflow usa.
FROM radar-spark:dev
COPY requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt
