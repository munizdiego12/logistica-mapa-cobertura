import os
import sys
from pathlib import Path

# O app roda com backend/ na raiz do path (`import database`, `import cobertura`): os testes de API fazem o mesmo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Os testes nunca falam com o banco de verdade: se a sessão tiver a string do Neon, troca por SQLite local antes de
# importar o app (assim o SQLAlchemy nem tenta carregar o psycopg2, que pode estar bloqueado no Windows).
os.environ["DATABASE_URL"] = "sqlite:///./sql_app.db"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _matriz_sem_rede(monkeypatch):
    """Nenhum teste consulta o OSRM de verdade: a matriz de distâncias vira a de linha reta (os testes de matriz chamam matriz.py direto)."""
    try:
        import main
        import matriz
    except Exception:  # testes que não carregam o app
        return

    async def matriz_falsa(cliente, pontos):
        distancias, duracoes = matriz.matriz_linha_reta(pontos)
        return {"distancias_m": distancias, "duracoes_s": duracoes, "origem": "osrm", "aviso": None}

    monkeypatch.setattr(main, "obter_matriz", matriz_falsa)
