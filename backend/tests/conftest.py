import sys
from pathlib import Path

# O app roda com backend/ na raiz do path (`import database`, `import cobertura`): os testes de API fazem o mesmo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
