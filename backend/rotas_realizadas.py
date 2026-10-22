"""
Rotas realizadas (Etapa 5b): registro das rotas confirmadas pelo operador, uma linha por rota/viagem.

A tabela é criada SÓ pelo Alembic (migrations/versions/0006_rotas_realizadas.py). As funções recebem uma conexão
asyncpg (`conn`), como frota.py e item_pesos.py. Só o status 'confirmada' conta; desfazer marca 'cancelada' (não
apaga). O dia é sempre o dia em America/Sao_Paulo (23h30 de Brasília ainda é o mesmo dia, mesmo já sendo o dia
seguinte em UTC). Confirmar o mesmo resultado duas vezes não duplica (chave única execucao_id + numero_rota).

Não calcula pagamento: a diária e as rotas por diária entram na Etapa 6 (lojas).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem banco de fusos no sistema (ex.: Windows sem o pacote tzdata): o Brasil não tem horário de verão desde 2019
    FUSO_BRASILIA = timezone(timedelta(hours=-3))

CONFIRMADA = "confirmada"
CANCELADA = "cancelada"

MSG_SEM_ROTAS = "Não há rotas para confirmar. Gere as rotas primeiro."
MSG_NAO_CONFIRMADA = "Estas rotas ainda não foram confirmadas, então não há o que desfazer."


def hoje_em_brasilia(agora: Optional[datetime] = None) -> date:
    """Dia de hoje no horário de Brasília. `agora` (com fuso) existe para os testes; sem ele usa o relógio."""
    instante = agora if agora is not None else datetime.now(timezone.utc)
    if instante.tzinfo is None:  # sem fuso: trata como UTC
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(FUSO_BRASILIA).date()


async def contagem_do_dia(conn, dia: date) -> dict:
    """{motorista_id: rotas confirmadas no dia}. Rotas canceladas não entram."""
    linhas = await conn.fetch(
        "SELECT motorista_id, count(*) AS rotas FROM rotas_realizadas "
        "WHERE data = $1 AND status = 'confirmada' GROUP BY motorista_id",
        dia,
    )
    return {int(l["motorista_id"]): int(l["rotas"]) for l in linhas}


async def totais_do_dia(conn, dia: date) -> dict:
    """{motorista_id: {"rotas": n, "pedidos": p}} das rotas CONFIRMADAS no dia (pedidos somados de `qtd_pedidos`). Rotas canceladas não entram."""
    linhas = await conn.fetch(
        "SELECT motorista_id, count(*) AS rotas, COALESCE(SUM(qtd_pedidos), 0) AS pedidos FROM rotas_realizadas "
        "WHERE data = $1 AND status = 'confirmada' GROUP BY motorista_id",
        dia,
    )
    return {int(l["motorista_id"]): {"rotas": int(l["rotas"]), "pedidos": int(l["pedidos"])} for l in linhas}


async def setores_do_dia(conn, dia: date, turno: str) -> dict:
    """
    Regra de rotação (Etapa 8): {motorista_id: {setor: [turnos]}} com os setores que cada motorista já fez no dia em OUTROS turnos
    (rotas confirmadas, com turno e setores gravados; rotas antigas sem setores não entram). O turno igual ao pedido não conta.
    """
    linhas = await conn.fetch(
        "SELECT motorista_id, turno, setores FROM rotas_realizadas "
        "WHERE data = $1 AND status = 'confirmada' AND turno IS NOT NULL AND turno <> $2 AND setores IS NOT NULL",
        dia, turno,
    )
    por_motorista = {}
    for l in linhas:
        for setor in str(l["setores"]).replace(" ", "").split(","):
            if setor:
                turnos = por_motorista.setdefault(int(l["motorista_id"]), {}).setdefault(setor, [])
                if l["turno"] not in turnos:
                    turnos.append(l["turno"])
    return por_motorista


async def resumo_da_execucao(conn, execucao_id: str, dia: date) -> list:
    """Para cada motorista da execução: rotas confirmadas nela agora e total confirmado no dia (todas as execuções)."""
    linhas = await conn.fetch(
        "SELECT m.id AS motorista_id, m.nome AS nome, "
        "  (SELECT count(*) FROM rotas_realizadas x WHERE x.execucao_id = $1 AND x.motorista_id = m.id AND x.status = 'confirmada') AS nesta_execucao, "
        "  (SELECT count(*) FROM rotas_realizadas y WHERE y.motorista_id = m.id AND y.data = $2 AND y.status = 'confirmada') AS total_hoje, "
        "  (SELECT COALESCE(SUM(x2.qtd_pedidos), 0) FROM rotas_realizadas x2 WHERE x2.execucao_id = $1 AND x2.motorista_id = m.id AND x2.status = 'confirmada') AS pedidos_nesta_execucao, "
        "  (SELECT COALESCE(SUM(y2.qtd_pedidos), 0) FROM rotas_realizadas y2 WHERE y2.motorista_id = m.id AND y2.data = $2 AND y2.status = 'confirmada') AS pedidos_hoje "
        "FROM motoristas m "
        "WHERE m.id IN (SELECT motorista_id FROM rotas_realizadas WHERE execucao_id = $1) "
        "ORDER BY lower(m.nome), m.id",
        execucao_id, dia,
    )
    return [
        {"motorista_id": int(l["motorista_id"]), "nome": l["nome"], "nesta_execucao": int(l["nesta_execucao"]), "total_hoje": int(l["total_hoje"]),
         "pedidos_nesta_execucao": int(l["pedidos_nesta_execucao"]), "pedidos_hoje": int(l["pedidos_hoje"])}
        for l in linhas
    ]


async def confirmar(conn, execucao_id: str, rotas: list, dia: date, loja_hub: Optional[str], turno: Optional[str], rotulo_operador: str) -> dict:
    """
    Grava uma linha por rota (com o motorista de cada rota). Rota já confirmada não é gravada de novo; rota cancelada
    antes volta a valer. Devolve quantas rotas entraram agora e o resumo por motorista.
    """
    if not rotas:
        raise ValueError(MSG_SEM_ROTAS)
    novas = 0
    async with conn.transaction():
        for rota in rotas:
            linha = await conn.fetchrow(
                "INSERT INTO rotas_realizadas (execucao_id, numero_rota, motorista_id, data, loja_hub, turno, qtd_pedidos, distancia_km, status, criado_por, setores) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'confirmada', $9, $10) "
                "ON CONFLICT (execucao_id, numero_rota) DO UPDATE SET status = 'confirmada', criado_em = CURRENT_TIMESTAMP, criado_por = EXCLUDED.criado_por, "
                "turno = EXCLUDED.turno, setores = EXCLUDED.setores "
                "WHERE rotas_realizadas.status = 'cancelada' "
                "RETURNING id",
                execucao_id, int(rota["numero_rota"]), int(rota["motorista_id"]), dia, loja_hub, turno,
                int(rota.get("qtd_pedidos") or 0), round(float(rota.get("distancia_km") or 0), 2), rotulo_operador,
                (rota.get("setores") or None),
            )
            if linha is not None:
                novas += 1
    return {"execucao_id": execucao_id, "confirmada": True, "novas": novas, "ja_confirmada": novas == 0, "motoristas": await resumo_da_execucao(conn, execucao_id, dia)}


async def desfazer(conn, execucao_id: str, dia: date) -> dict:
    """Marca as rotas confirmadas da execução como canceladas (não apaga). Erro se não havia nada confirmado."""
    linhas = await conn.fetch(
        "UPDATE rotas_realizadas SET status = 'cancelada' WHERE execucao_id = $1 AND status = 'confirmada' RETURNING id",
        execucao_id,
    )
    if not linhas:
        raise ValueError(MSG_NAO_CONFIRMADA)
    return {"execucao_id": execucao_id, "confirmada": False, "canceladas": len(linhas), "motoristas": await resumo_da_execucao(conn, execucao_id, dia)}
