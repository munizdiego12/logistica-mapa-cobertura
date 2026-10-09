"""Conexão e pool asyncpg simulados, para testar o código que fala com o banco sem um Postgres de verdade."""


class FakeConn:
    """Devolve as `respostas` na ordem (uma por fetch/fetchrow/fetchval) e registra tudo em `chamadas` e `eventos`."""

    def __init__(self, respostas=None, eventos=None, erro_no_fetch=None):
        self.respostas = list(respostas or [])
        self.chamadas = []
        self.eventos = eventos if eventos is not None else []
        self.erro_no_fetch = erro_no_fetch

    def _proxima(self):
        return self.respostas.pop(0) if self.respostas else None

    async def fetch(self, sql, *args):
        self.eventos.append("fetch")
        self.chamadas.append(("fetch", sql, args))
        if self.erro_no_fetch:
            raise self.erro_no_fetch
        return self._proxima() or []

    async def fetchrow(self, sql, *args):
        self.eventos.append("fetchrow")
        self.chamadas.append(("fetchrow", sql, args))
        return self._proxima()

    async def executemany(self, sql, linhas):
        self.eventos.append("executemany")
        self.chamadas.append(("executemany", sql, list(linhas)))

    async def close(self):
        self.eventos.append("fechar")

    def transaction(self):
        conn = self

        class _Transacao:
            async def __aenter__(self):
                conn.eventos.append("begin")
                conn.chamadas.append(("begin", None, None))

            async def __aexit__(self, *erro):
                nome = "commit" if erro[0] is None else "rollback"
                conn.eventos.append(nome)
                conn.chamadas.append((nome, None, None))

        return _Transacao()


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Contexto:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *erro):
                return False

        return _Contexto()
