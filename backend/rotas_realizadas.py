"""
Rotas realizadas (Etapa 5b): registro das rotas confirmadas pelo operador, uma linha por rota/viagem.

A tabela é criada SÓ pelo Alembic (migrations/versions/0006_rotas_realizadas.py). As funções recebem uma conexão
asyncpg (`conn`), como frota.py e item_pesos.py. Só o status 'confirmada' conta; desfazer marca 'cancelada' (não
apaga). O dia é sempre o dia em America/Sao_Paulo (23h30 de Brasília ainda é o mesmo dia, mesmo já sendo o dia
seguinte em UTC). Confirmar o mesmo resultado duas vezes não duplica (chave única execucao_id + numero_rota).

Não calcula pagamento: a diária e as rotas por diária entram na Etapa 6 (lojas).
"""
import re
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
        for rota in rotas:  # cada rota pode trazer `pedidos` (ordem, pedido_id, endereco, cidade, uf, volume) para o histórico e a duplicidade
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
            await _gravar_pedidos_da_rota(conn, execucao_id, int(rota["numero_rota"]), rota.get("pedidos") or [])
    return {"execucao_id": execucao_id, "confirmada": True, "novas": novas, "ja_confirmada": novas == 0, "motoristas": await resumo_da_execucao(conn, execucao_id, dia)}


async def _gravar_pedidos_da_rota(conn, execucao_id: str, numero_rota: int, pedidos: list) -> None:
    """
    Pedidos da rota (só o mínimo: id, endereço, cidade, UF e volume; nunca cliente, telefone nem CEP). Chave única (rota, ordem): confirmar de novo não duplica,
    re-confirmar uma rota desfeita reaproveita os pedidos que ficaram ligados a ela, e uma rota confirmada antes desta etapa ganha o detalhe.
    """
    if not pedidos:
        return
    id_rota = await conn.fetchval("SELECT id FROM rotas_realizadas WHERE execucao_id = $1 AND numero_rota = $2", execucao_id, numero_rota)
    if id_rota is None:
        return
    linhas = []
    for p in pedidos:
        pedido_id = str(p.get("pedido_id") or "").strip()[:60]
        if not pedido_id:
            continue
        endereco = " ".join(str(p.get("endereco") or "").split()) or None
        cidade = " ".join(str(p.get("cidade") or "").split())[:120] or None
        uf = (str(p.get("uf") or "").strip().upper()[:2]) or None
        try:
            volume = max(0, int(p.get("volume") or 1))
        except (TypeError, ValueError):
            volume = 1
        linhas.append((int(id_rota), int(p.get("ordem") or len(linhas) + 1), pedido_id, endereco, cidade, uf, volume))
    if linhas:
        await conn.executemany(
            "INSERT INTO rotas_pedidos (rota_id, ordem, pedido_id, endereco, cidade, uf, volume) VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "ON CONFLICT (rota_id, ordem) DO NOTHING",
            linhas,
        )


# ----------------------------------------------------------------------------------------------------------
# Retenção do endereço (Etapa 12): só o endereço some depois do prazo; id, cidade, volume e os dados da rota ficam
# ----------------------------------------------------------------------------------------------------------
_ULTIMA_LIMPEZA: Optional[date] = None  # dia da última limpeza neste processo (o UPDATE é idempotente, então reiniciar só repete uma consulta barata)


async def limpar_enderecos_antigos(conn, hoje: date, dias: int) -> int:
    """
    Apaga o endereço (e só ele) dos pedidos de rotas confirmadas há MAIS de `dias` dias (`data < hoje - dias`, qualquer status da rota) e grava `endereco_apagado_em`.
    Devolve quantos endereços foram apagados. Idempotente.
    """
    corte = hoje - timedelta(days=int(dias))
    linhas = await conn.fetch(
        "UPDATE rotas_pedidos SET endereco = NULL, endereco_apagado_em = $1 "
        "WHERE endereco IS NOT NULL AND rota_id IN (SELECT id FROM rotas_realizadas WHERE data < $2) RETURNING id",
        hoje, corte,
    )
    return len(linhas)


async def limpeza_preguicosa(conn, hoje: date, dias: int) -> int:
    """
    Roda a limpeza no máximo uma vez por dia (sem agendador: o servidor gratuito dorme), ao confirmar rotas ou ao abrir o histórico. Falha nunca derruba
    quem chamou: só registra a classe do erro e tenta de novo na próxima vez.
    """
    global _ULTIMA_LIMPEZA
    if _ULTIMA_LIMPEZA == hoje:
        return 0
    try:
        apagados = await limpar_enderecos_antigos(conn, hoje, dias)
    except Exception as erro:
        print(f"[historico] Falha na limpeza dos endereços antigos: {type(erro).__name__}")
        return 0
    _ULTIMA_LIMPEZA = hoje
    return apagados


# ----------------------------------------------------------------------------------------------------------
# Textos e horas
# ----------------------------------------------------------------------------------------------------------
_RE_OPERADOR = re.compile(r"^(.*?)\s*\([^()]*@[^()]*\)\s*$")


def nome_do_operador(rotulo) -> Optional[str]:
    """'Maria Souza (maria@zubale.com)' -> 'Maria Souza' (nunca o e-mail)."""
    texto = " ".join(str(rotulo or "").split())
    achou = _RE_OPERADOR.match(texto)
    return (achou.group(1).strip() if achou else texto) or None


def hora_em_brasilia(instante) -> Optional[str]:
    """'HH:MM' no horário de Brasília a partir do `criado_em` (datetime com fuso, ou texto ISO; sem fuso vale UTC)."""
    if instante is None:
        return None
    if isinstance(instante, str):
        try:
            instante = datetime.fromisoformat(instante.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(FUSO_BRASILIA).strftime("%H:%M")


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _em_blocos(itens: list, tamanho: int):
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


# ----------------------------------------------------------------------------------------------------------
# Duplicidade (Etapa 9)
# ----------------------------------------------------------------------------------------------------------
MAX_IDS_DUPLICIDADE = 20000
TAMANHO_DO_BLOCO = 500


async def ja_roteirizados(conn, ids: list, dia: date) -> dict:
    """
    Dos ids de pedido recebidos, só os que estão em rotas CONFIRMADAS do `dia`: {id: {rota, motorista, turno, loja, operador (só o nome), hora}}.
    Rota cancelada, outro dia e id desconhecido não aparecem. Se o mesmo pedido estiver em mais de uma rota confirmada, vale a mais recente.
    """
    unicos = []
    vistos = set()
    for bruto in ids or []:
        texto = str(bruto).strip()
        if texto and texto not in vistos:
            vistos.add(texto)
            unicos.append(texto)
    escolhidos = {}
    for bloco in _em_blocos(unicos, TAMANHO_DO_BLOCO):
        marcadores = ", ".join(f"${i + 2}" for i in range(len(bloco)))
        linhas = await conn.fetch(
            "SELECT rp.pedido_id AS pedido_id, rr.id AS rota_id, rr.numero_rota AS numero_rota, rr.turno AS turno, rr.loja_hub AS loja, "
            "       rr.criado_por AS criado_por, rr.criado_em AS criado_em, m.nome AS motorista "
            "FROM rotas_pedidos rp JOIN rotas_realizadas rr ON rr.id = rp.rota_id JOIN motoristas m ON m.id = rr.motorista_id "
            f"WHERE rr.status = 'confirmada' AND rr.data = $1 AND rp.pedido_id IN ({marcadores})",
            dia, *bloco,
        )
        for l in linhas:
            chave = (str(l["criado_em"]), int(l["rota_id"]))
            atual = escolhidos.get(l["pedido_id"])
            if atual is None or chave > atual[0]:
                escolhidos[l["pedido_id"]] = (chave, l)
    return {
        pedido_id: {
            "rota": int(l["numero_rota"]), "motorista": l["motorista"], "turno": l["turno"], "loja": l["loja"],
            "operador": nome_do_operador(l["criado_por"]), "hora": hora_em_brasilia(l["criado_em"]),
        }
        for pedido_id, (_, l) in escolhidos.items()
    }


# ----------------------------------------------------------------------------------------------------------
# Histórico (Etapa 12)
# ----------------------------------------------------------------------------------------------------------
LIMITE_PADRAO_DO_HISTORICO = 50
LIMITE_MAXIMO_DO_HISTORICO = 200
DIAS_DO_PERIODO_PADRAO = 7


def periodo_padrao(hoje: date) -> tuple:
    """Últimos 7 dias, hoje incluído."""
    return hoje - timedelta(days=DIAS_DO_PERIODO_PADRAO - 1), hoje


async def historico(
    conn, de: date, ate: date, loja: Optional[str] = None, motorista_id: Optional[int] = None, operador: Optional[str] = None,
    q: Optional[str] = None, desfeitas: bool = False, limite: int = LIMITE_PADRAO_DO_HISTORICO, deslocamento: int = 0,
) -> dict:
    """
    Rotas do período, mais recentes primeiro (dia, loja, hora, número), com os pedidos de cada uma. Só as confirmadas, a menos que `desfeitas`.
    `q`: id do pedido (exato, sem diferença de maiúsculas) ou trecho do endereço. O operador sai só pelo nome. Paginado: `tem_mais` diz se há outra página.
    """
    limite = max(1, min(int(limite), LIMITE_MAXIMO_DO_HISTORICO))
    deslocamento = max(0, int(deslocamento))
    condicoes, parametros = ["rr.data >= $1", "rr.data <= $2"], [de, ate]

    def novo(valor) -> str:
        parametros.append(valor)
        return f"${len(parametros)}"

    if not desfeitas:
        condicoes.append("rr.status = 'confirmada'")
    if loja:
        condicoes.append(f"rr.loja_hub = {novo(loja)}")
    if motorista_id is not None:
        condicoes.append(f"rr.motorista_id = {novo(int(motorista_id))}")
    if operador:
        nome = " ".join(str(operador).split())
        condicoes.append(f"(lower(rr.criado_por) = lower({novo(nome)}) OR lower(rr.criado_por) LIKE lower({novo(_escapar_like(nome) + ' (%')}) ESCAPE '\\')")
    if q and q.strip():
        termo = q.strip()
        exato, trecho = novo(termo), novo(_escapar_like(termo))
        condicoes.append(
            "EXISTS (SELECT 1 FROM rotas_pedidos rp WHERE rp.rota_id = rr.id AND "
            f"(lower(rp.pedido_id) = lower({exato}) OR lower(COALESCE(rp.endereco, '')) LIKE '%' || lower({trecho}) || '%' ESCAPE '\\'))"
        )
    linhas = await conn.fetch(
        "SELECT rr.id AS id, rr.data AS data, rr.loja_hub AS loja, rr.motorista_id AS motorista_id, m.nome AS motorista, rr.numero_rota AS numero_rota, "
        "       rr.turno AS turno, rr.criado_em AS criado_em, rr.qtd_pedidos AS qtd_pedidos, rr.distancia_km AS distancia_km, rr.status AS status, "
        "       rr.criado_por AS criado_por "
        "FROM rotas_realizadas rr JOIN motoristas m ON m.id = rr.motorista_id "
        f"WHERE {' AND '.join(condicoes)} "
        "ORDER BY rr.data DESC, lower(COALESCE(rr.loja_hub, '')), rr.criado_em, rr.numero_rota, rr.id "
        f"LIMIT {limite + 1} OFFSET {deslocamento}",
        *parametros,
    )
    tem_mais = len(linhas) > limite
    linhas = linhas[:limite]
    pedidos_por_rota = {}
    if linhas:
        marcadores = ", ".join(f"${i + 1}" for i in range(len(linhas)))
        for p in await conn.fetch(
            "SELECT rota_id, ordem, pedido_id, endereco, cidade, uf, volume, endereco_apagado_em FROM rotas_pedidos "
            f"WHERE rota_id IN ({marcadores}) ORDER BY rota_id, ordem",
            *[int(l["id"]) for l in linhas],
        ):
            pedidos_por_rota.setdefault(int(p["rota_id"]), []).append({
                "ordem": int(p["ordem"]), "id": p["pedido_id"], "endereco": p["endereco"],
                "endereco_apagado": p["endereco"] is None and p["endereco_apagado_em"] is not None,
                "cidade": p["cidade"], "uf": p["uf"], "volume": int(p["volume"] or 0),
            })
    rotas = []
    for l in linhas:
        pedidos = pedidos_por_rota.get(int(l["id"]), [])
        rotas.append({
            "id": int(l["id"]), "dia": str(l["data"])[:10], "loja": l["loja"], "motorista": {"id": int(l["motorista_id"]), "nome": l["motorista"]},
            "numero": int(l["numero_rota"]), "turno": l["turno"], "hora": hora_em_brasilia(l["criado_em"]), "qtd_pedidos": int(l["qtd_pedidos"] or 0),
            "km": float(l["distancia_km"] or 0), "status": l["status"], "operador": nome_do_operador(l["criado_por"]),
            "sem_detalhe": not pedidos and int(l["qtd_pedidos"] or 0) > 0, "pedidos": pedidos,
        })
    return {"rotas": rotas, "tem_mais": tem_mais, "limite": limite, "deslocamento": deslocamento}


async def filtros_do_historico(conn, de: date, ate: date) -> dict:
    """Lojas, motoristas e operadores (só os nomes) que aparecem nas rotas do período, para os seletores de filtro."""
    base = "FROM rotas_realizadas rr JOIN motoristas m ON m.id = rr.motorista_id WHERE rr.data >= $1 AND rr.data <= $2"
    lojas = sorted({l["loja"] for l in await conn.fetch(f"SELECT DISTINCT rr.loja_hub AS loja {base}", de, ate) if l["loja"]}, key=str.lower)
    motoristas = [
        {"id": int(l["id"]), "nome": l["nome"]}
        for l in await conn.fetch(f"SELECT DISTINCT m.id AS id, m.nome AS nome {base} ORDER BY lower(m.nome), m.id", de, ate)
    ]
    operadores = sorted({nome_do_operador(l["criado_por"]) for l in await conn.fetch(f"SELECT DISTINCT rr.criado_por AS criado_por {base}", de, ate)} - {None}, key=str.lower)
    return {"lojas": lojas, "motoristas": motoristas, "operadores": operadores}


async def desfazer(conn, execucao_id: str, dia: date) -> dict:
    """Marca as rotas confirmadas da execução como canceladas (não apaga). Erro se não havia nada confirmado."""
    linhas = await conn.fetch(
        "UPDATE rotas_realizadas SET status = 'cancelada' WHERE execucao_id = $1 AND status = 'confirmada' RETURNING id",
        execucao_id,
    )
    if not linhas:
        raise ValueError(MSG_NAO_CONFIRMADA)
    return {"execucao_id": execucao_id, "confirmada": False, "canceladas": len(linhas), "motoristas": await resumo_da_execucao(conn, execucao_id, dia)}
