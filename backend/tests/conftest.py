import os
import sys
from pathlib import Path

# O app roda com backend/ na raiz do path (`import database`, `import cobertura`): os testes de API fazem o mesmo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Os testes nunca falam com o banco de verdade: se a sessão tiver a string do Neon, troca por SQLite local antes de
# importar o app (assim o SQLAlchemy nem tenta carregar o psycopg2, que pode estar bloqueado no Windows).
os.environ["DATABASE_URL"] = "sqlite:///./sql_app.db"
