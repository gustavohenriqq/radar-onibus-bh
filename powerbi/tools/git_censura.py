"""Filtro git que mantém o endereço do Neon fora do repositório.

clean  (ao gravar no repositório): troca cada valor real pelo marcador.
smudge (ao baixar para a pasta):   troca o marcador de volta pelo valor real.

Os pares ficam em .git/censura.txt (nunca versionado), um por linha: valor_real<TAB>marcador.
Sem esse arquivo, o filtro não altera nada; quem clonar o repositório vê só os marcadores e
precisa trocar o marcador do servidor pelo endpoint do próprio Neon (parâmetro ServidorPostgres).

Configuração (uma vez por clone):
    git config filter.censura.clean  "python -I powerbi/tools/git_censura.py clean"
    git config filter.censura.smudge "python -I powerbi/tools/git_censura.py smudge"
"""
import subprocess
import sys
from pathlib import Path


def pares():
    git_dir = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True).stdout.strip()
    arq = Path(git_dir or ".git") / "censura.txt"
    if not arq.exists():
        return []
    linhas = arq.read_text(encoding="utf-8").splitlines()
    return [tuple(l.split("\t", 1)) for l in linhas if "\t" in l and not l.startswith("#")]


def main(modo):
    dados = sys.stdin.buffer.read()
    try:
        texto = dados.decode("utf-8")
    except UnicodeDecodeError:  # binário: passa direto
        sys.stdout.buffer.write(dados)
        return
    for real, marcador in pares():
        texto = texto.replace(real, marcador) if modo == "clean" else texto.replace(marcador, real)
    sys.stdout.buffer.write(texto.encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv[1])
