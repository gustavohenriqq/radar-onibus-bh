"""Acesso ao bucket de backup por URL pre-autenticada (PAR) do Object Storage.

Por que PAR e nao SDK com chave de API:

- Nada pesado na VM de 1 GB. O SDK oficial puxa dezenas de dependencias; aqui
  basta o `requests`, que o coletor ja usa.
- Permissao minima. A PAR do bucket permite ler e gravar objetos, mas nao
  apagar (a doc do provedor: "Pre-authenticated requests can't be used to
  delete buckets or objects"). Somada a regra de retencao do bucket, que impede
  sobrescrever, quem tomar a VM nao consegue destruir o backup.

A URL tem o formato
    https://objectstorage.<regiao>.oraclecloud.com/p/<token>/n/<namespace>/b/<bucket>/o/
e o nome do objeto vai no fim.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

import requests

BLOCO = 1024 * 1024


class ErroRemoto(RuntimeError):
    pass


class NaoEncontrado(ErroRemoto):
    pass


class Remoto:
    def __init__(self, url_par: str, sessao: requests.Session | None = None, timeout_s: float = 120):
        if not url_par.endswith("/o/"):
            raise ValueError("BACKUP_PAR_URL deve ser a URL da PAR do bucket, terminando em /o/")
        self.base = url_par
        self.sessao = sessao or requests.Session()
        self.timeout_s = timeout_s

    def _url(self, nome: str) -> str:
        # "/" fica literal: o Object Storage trata o nome inteiro como chave, e
        # a barra so organiza a listagem no console.
        return self.base + quote(nome, safe="/")

    def enviar(self, nome: str, caminho: Path) -> int:
        """PUT em streaming: o arquivo nao e carregado inteiro na memoria.
        Devolve o status HTTP; quem chama decide o que fazer com recusa."""
        with open(caminho, "rb") as f:
            r = self.sessao.put(self._url(nome), data=f, timeout=self.timeout_s,
                                headers={"Content-Type": "application/octet-stream"})
        return r.status_code

    def sha256(self, nome: str) -> str:
        """Le o objeto de volta e calcula o SHA-256, em blocos."""
        h = hashlib.sha256()
        for bloco in self._ler(nome):
            h.update(bloco)
        return h.hexdigest()

    def baixar(self, nome: str, destino: Path) -> None:
        """Baixa para um temporario e renomeia, como toda escrita do projeto."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(f".{destino.name}.tmp")
        with open(temporario, "wb") as f:
            for bloco in self._ler(nome):
                f.write(bloco)
        temporario.replace(destino)

    def _ler(self, nome: str):
        r = self.sessao.get(self._url(nome), stream=True, timeout=self.timeout_s)
        if r.status_code == 404:
            r.close()
            raise NaoEncontrado(nome)
        if r.status_code != 200:
            r.close()
            raise ErroRemoto(f"GET {nome}: http {r.status_code}")
        with r:
            yield from r.iter_content(BLOCO)
