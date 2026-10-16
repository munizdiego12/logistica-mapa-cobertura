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

    async def fetchval(self, sql, *args):
        self.eventos.append("fetchval")
        self.chamadas.append(("fetchval", sql, args))
        return self._proxima()

    async def executemany(self, sql, linhas):
        self.eventos.append("executemany")
        self.chamadas.append(("executemany", sql, list(linhas)))

    async def close(self):
        self.eventos.append("fechar")

    def transaction(self, **opcoes):
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


# ----------------------------------------------------------------------------------------------------------
# Banco SQLite em memória com a interface da conexão asyncpg (fetch/fetchrow/fetchval/transaction) e as tabelas
# das migrations 0004 a 0008. Testa o SQL de verdade (contagens, upsert, status), sem Postgres.
# ----------------------------------------------------------------------------------------------------------
import importlib.util
import re
import sqlite3
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

_VERSOES = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _migracao(arquivo: str):
    spec = importlib.util.spec_from_file_location(f"migracao_{arquivo}", _VERSOES / arquivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class ConexaoSqlite:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)  # o TestClient roda a rota em outra thread
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.create_function("btrim", 1, lambda s: s.strip() if isinstance(s, str) else s, deterministic=True)  # função do Postgres
        self.sqls = []

    @staticmethod
    def _sql(sql):
        return re.sub(r"\$(\d+)(::\w+)?", r"?\1", sql).replace("NOW()", "CURRENT_TIMESTAMP")

    @staticmethod
    def _args(args):
        convertidos = []
        for a in args:
            if isinstance(a, time):
                a = a.isoformat(timespec="minutes")
            elif isinstance(a, (date, datetime)):
                a = a.isoformat()
            elif isinstance(a, Decimal):
                a = float(a)
            convertidos.append(a)
        return convertidos

    def _rodar(self, sql, args):
        self.sqls.append(sql)
        return self.db.execute(self._sql(sql), self._args(args))

    async def fetch(self, sql, *args):
        return [dict(l) for l in self._rodar(sql, args).fetchall()]

    async def fetchrow(self, sql, *args):
        linha = self._rodar(sql, args).fetchone()
        return None if linha is None else dict(linha)

    async def fetchval(self, sql, *args):
        linha = self._rodar(sql, args).fetchone()
        return None if linha is None else linha[0]

    async def execute(self, sql, *args):
        self._rodar(sql, args)

    async def close(self):
        pass

    def transaction(self, **opcoes):
        conn = self

        class _Transacao:
            async def __aenter__(self):
                conn.db.execute("BEGIN")

            async def __aexit__(self, *erro):
                conn.db.execute("COMMIT" if erro[0] is None else "ROLLBACK")

        return _Transacao()

    def inserir_motorista(self, nome, tipo="Carro de passeio", ativo=True):
        cursor = self.db.execute("INSERT INTO motoristas (nome, tipo_veiculo, ativo) VALUES (?, ?, ?)", (nome, tipo, 1 if ativo else 0))
        return cursor.lastrowid


def criar_banco_sqlite():
    """Cria o banco em memória aplicando as migrations 0004 a 0008 (SQL traduzido do Postgres para o SQLite)."""
    conn = ConexaoSqlite()
    for arquivo in ("0004_tipos_veiculo_motoristas.py", "0005_motoristas_valor_rota.py", "0006_rotas_realizadas.py", "0007_lojas.py", "0008_motorista_lojas.py"):
        for comando in _migracao(arquivo).COMANDOS:
            colunas = {l[1] for l in conn.db.execute("PRAGMA table_info(motoristas)")}
            adicionada = re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", comando)
            if adicionada and adicionada.group(1) in colunas:
                continue
            comando = (comando.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("TIMESTAMPTZ", "TIMESTAMP")
                       .replace("NOW()", "CURRENT_TIMESTAMP").replace("length(btrim(nome))", "length(trim(nome))")
                       .replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"))
            conn.db.execute(comando)
    return conn
