"""Conexões com o banco: o Neon derruba conexão ociosa, então os dois pools (SQLAlchemy e asyncpg) a renovam antes."""

def test_engine_do_banco_testa_a_conexao_antes_de_usar_e_recicla_as_antigas():
    """Neon derruba conexão ociosa: sem pre_ping e recycle curto, o login dava 500 na primeira consulta depois de parado."""
    import database
    assert database.ENGINE_KWARGS == {"pool_pre_ping": True, "pool_recycle": 280}
    assert database.engine.pool._pre_ping is True
    assert database.engine.pool._recycle == 280


def test_pool_asyncpg_fecha_conexao_ociosa_antes_do_neon_derrubar(monkeypatch):
    """O pool de get_pool() mantém min/max e fecha conexões ociosas por 240 s (o padrão do asyncpg é 300 s)."""
    import asyncio
    import database

    capturado = {}

    async def criar_pool_falso(**kwargs):
        capturado.update(kwargs)
        return object()

    class AsyncpgFalso:
        create_pool = staticmethod(criar_pool_falso)

    monkeypatch.setattr(database, "asyncpg", AsyncpgFalso)
    monkeypatch.setattr(database, "URL_NORMALIZADA", "postgresql://u:p@h/db")
    monkeypatch.setattr(database, "_pool", None)
    asyncio.run(database.get_pool())
    assert capturado["max_inactive_connection_lifetime"] == 240
    assert (capturado["min_size"], capturado["max_size"], capturado["command_timeout"]) == (1, 5, 10)
    assert capturado["dsn"] == "postgresql://u:p@h/db"
