"""
Conversão da DATABASE_URL (formato do Render/Neon) para o que o asyncpg e o SQLAlchemy assíncrono aceitam.

Por que existe: o psycopg2 pode estar bloqueado no Windows (política de Controle de Aplicativo), então o
Alembic e os scripts de carga rodam com asyncpg. O asyncpg não entende `sslmode` na URL do SQLAlchemy e rejeita
`channel_binding` (que o Neon coloca na string): aqui eles viram `ssl=True` ou são removidos.

Módulo sem dependências do projeto (só biblioteca padrão): é usado pelo env.py do Alembic, por scripts/ e pelos testes.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_MODOS_SSL = {"require", "verify-ca", "verify-full"}
_PARAMETROS_REMOVIDOS = {"sslmode", "channel_binding"}


def normalizar_url(url: str) -> str:
    """O Render entrega 'postgres://...'; o resto do mundo espera 'postgresql://...'."""
    url = (url or "").strip()
    if not url:
        raise ValueError("DATABASE_URL vazia")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if not url.startswith("postgresql"):
        raise ValueError("DATABASE_URL deve começar com postgresql:// ou postgres://")
    return url


def _sem_parametros(url: str, remover: set) -> tuple:
    partes = urlsplit(url)
    consulta = parse_qsl(partes.query, keep_blank_values=True)
    modo = next((v for k, v in consulta if k == "sslmode"), None)
    restante = [(k, v) for k, v in consulta if k not in remover]
    return urlunsplit((partes.scheme, partes.netloc, partes.path, urlencode(restante), partes.fragment)), modo


def dsn_asyncpg(url: str) -> str:
    """DSN para asyncpg.connect(): mantém sslmode (o asyncpg entende) e tira channel_binding (ele rejeitaria)."""
    limpa, _ = _sem_parametros(normalizar_url(url), {"channel_binding"})
    return limpa


def url_sqlalchemy_asyncpg(url: str) -> tuple:
    """(url 'postgresql+asyncpg://...' sem sslmode/channel_binding, connect_args); sslmode=require vira ssl=True."""
    limpa, modo = _sem_parametros(normalizar_url(url), _PARAMETROS_REMOVIDOS)
    partes = urlsplit(limpa)
    esquema = "postgresql+asyncpg"
    url_final = urlunsplit((esquema, partes.netloc, partes.path, partes.query, partes.fragment))
    return url_final, ({"ssl": True} if modo in _MODOS_SSL else {})


def mascarar_senha(url: str) -> str:
    """Para mensagens de erro: troca a senha por ***."""
    try:
        partes = urlsplit(url)
        if partes.password:
            netloc = partes.netloc.replace(":" + partes.password + "@", ":***@")
            return urlunsplit((partes.scheme, netloc, partes.path, partes.query, partes.fragment))
    except ValueError:
        pass
    return url
