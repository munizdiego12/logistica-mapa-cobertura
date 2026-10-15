"""
Frota (Etapa 5): tipos de veículo (valor base por rota e peso de referência opcional) e cadastro de motoristas.

As tabelas são criadas SÓ pelo Alembic (migrations/versions/0004_tipos_veiculo_motoristas.py). As funções de banco
recebem uma conexão asyncpg (`conn`), como item_pesos.py. Motorista nunca é apagado: é desativado (ativo = false).

O peso de referência NÃO é limite: é só um guia para o motor de roteirização. Nada aqui bloqueia nem avisa por peso.
Mensagens de erro são em linguagem do operador (viram o `detail` das respostas 422).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

CUSTO_MAXIMO_ROTA = Decimal("100000")
PESO_REFERENCIA_MAXIMO_KG = Decimal("100000")
TAMANHO_MAXIMO_NOME = 120

MSG_NOME_VAZIO = "Informe o nome do motorista."
MSG_NOME_GRANDE = f"O nome do motorista pode ter até {TAMANHO_MAXIMO_NOME} letras."
MSG_TIPO_INEXISTENTE = "Escolha um tipo de veículo da lista."
MSG_ESCOLHA_UM_MOTORISTA = "Marque pelo menos um motorista para gerar as rotas."
MSG_MOTORISTA_INEXISTENTE = "Um dos motoristas escolhidos não está mais cadastrado. Atualize a lista e escolha de novo."
MSG_SEM_MOTORISTAS = (
    "Não há motoristas cadastrados. Cadastre pelo menos um motorista na tela \"Motoristas e veículos\" "
    "antes de gerar as rotas."
)


def _numero(valor) -> Decimal:
    """Número a partir de número ou texto em português ("1,5", "1.5", "1.234,56", "R$ 130", "300 kg")."""
    if isinstance(valor, bool):
        raise ValueError("não é número")
    if isinstance(valor, (int, float, Decimal)):
        numero = Decimal(str(valor))
    else:
        texto = str(valor).replace("\xa0", " ").strip().lower()
        texto = texto.removeprefix("r$").replace(" ", "").removesuffix("kg")
        if not texto or not all(c in "0123456789.,-" for c in texto):
            raise ValueError("não é número")
        if "," in texto and "." in texto:
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            texto = texto.replace(".", "")
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            raise ValueError("não é número") from None
    if not numero.is_finite():
        raise ValueError("não é número")
    return numero


def interpretar_custo_rota(valor) -> Decimal:
    """Valor base por rota do tipo de veículo, em reais (zero é permitido; negativo, vazio ou texto, não)."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise ValueError("Informe o valor base da rota, por exemplo 130 ou 130,50.")
    try:
        numero = _numero(valor)
    except ValueError:
        raise ValueError("O valor base da rota precisa ser um valor em reais, por exemplo 130 ou 130,50.") from None
    if numero < 0:
        raise ValueError("O valor base da rota não pode ser negativo.")
    if numero > CUSTO_MAXIMO_ROTA:
        raise ValueError("O valor base da rota está alto demais. Confira o valor digitado.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interpretar_valor_informado(valor, nome_tipo: str = "") -> Optional[Decimal]:
    """
    Valor por rota digitado pelo operador na roteirização. Vazio/None = não informou (devolve None: vale o valor
    base). Zero é aceito (foi digitado de propósito). Negativo ou texto: erro com mensagem em linguagem do operador.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    onde = f" de {nome_tipo}" if nome_tipo else ""
    try:
        numero = _numero(valor)
    except ValueError:
        raise ValueError(
            f"O valor por rota{onde} precisa ser um valor em reais, por exemplo 130 ou 130,50 "
            "(ou deixe em branco para usar o valor base)."
        ) from None
    if numero < 0:
        raise ValueError(f"O valor por rota{onde} não pode ser negativo (ou deixe em branco para usar o valor base).")
    if numero > CUSTO_MAXIMO_ROTA:
        raise ValueError(f"O valor por rota{onde} está alto demais. Confira o valor digitado.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interpretar_valor_proprio(valor) -> Optional[Decimal]:
    """
    Valor próprio por rota de um motorista (cadastro). Vazio/None = sem valor próprio (usa o valor base do tipo).
    Zero é aceito (de propósito); negativo ou texto: erro com mensagem em linguagem do operador.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        numero = _numero(valor)
    except ValueError:
        raise ValueError(
            "O valor próprio por rota precisa ser um valor em reais, por exemplo 130 ou 130,50 "
            "(ou deixe em branco para usar o valor base)."
        ) from None
    if numero < 0:
        raise ValueError("O valor próprio por rota não pode ser negativo (ou deixe em branco para usar o valor base).")
    if numero > CUSTO_MAXIMO_ROTA:
        raise ValueError("O valor próprio por rota está alto demais. Confira o valor digitado.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interpretar_valores_informados(valores) -> dict:
    """
    {"Carro de passeio": "130,50", "Fiorino/Utilitário": ""} -> {"carro de passeio": Decimal("130.50")}.
    Tipos com o campo ausente ou vazio ficam de fora (usam o valor base). A chave sai em minúsculas.
    """
    resultado = {}
    for nome, valor in (valores or {}).items():
        numero = interpretar_valor_informado(valor, str(nome).strip())
        if numero is not None:
            resultado[str(nome).strip().lower()] = numero
    return resultado


def interpretar_peso_referencia(valor) -> Optional[Decimal]:
    """Peso de referência em kg. Vazio/None = "sem referência" (devolve None). Negativo, zero ou texto: erro."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        numero = _numero(valor)
    except ValueError:
        raise ValueError("O peso de referência precisa ser um número em kg, por exemplo 300 (ou deixe em branco).") from None
    if numero <= 0:
        raise ValueError("O peso de referência precisa ser maior que zero (ou deixe em branco para \"sem referência\").")
    if numero > PESO_REFERENCIA_MAXIMO_KG:
        raise ValueError("O peso de referência está alto demais. Confira o valor digitado.")
    return numero.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def normalizar_nome_motorista(valor) -> str:
    nome = " ".join(str(valor or "").split())
    if not nome:
        raise ValueError(MSG_NOME_VAZIO)
    if len(nome) > TAMANHO_MAXIMO_NOME:
        raise ValueError(MSG_NOME_GRANDE)
    return nome


# ----------------------------------------------------------------------------------------------------------
# Banco (conexão asyncpg)
# ----------------------------------------------------------------------------------------------------------
_COLUNAS_TIPO = "id, nome, custo_rota, peso_referencia_kg, ativo, atualizado_em, atualizado_por"
_COLUNAS_MOTORISTA = "id, nome, tipo_veiculo, valor_rota, ativo, atualizado_em, atualizado_por"

# "Não mexer no valor próprio": usado quando o pedido de edição não traz o campo valor_rota.
MANTER = object()


def _motorista_para_dict(linha) -> dict:
    d = dict(linha)
    d["valor_rota"] = None if d.get("valor_rota") is None else float(d["valor_rota"])
    return d


def _tipo_para_dict(linha) -> dict:
    d = dict(linha)
    d["custo_rota"] = float(d["custo_rota"])
    d["peso_referencia_kg"] = None if d["peso_referencia_kg"] is None else float(d["peso_referencia_kg"])
    return d


async def listar_tipos_veiculo(conn) -> list:
    linhas = await conn.fetch(f"SELECT {_COLUNAS_TIPO} FROM tipos_veiculo ORDER BY id")
    return [_tipo_para_dict(l) for l in linhas]


async def atualizar_tipo_veiculo(conn, id_tipo: int, custo_rota, peso_referencia_kg, rotulo_operador: str) -> Optional[dict]:
    """Edita o valor base por rota e o peso de referência (vazio = sem referência). None se o tipo não existe."""
    custo = interpretar_custo_rota(custo_rota)
    peso = interpretar_peso_referencia(peso_referencia_kg)
    linha = await conn.fetchrow(
        f"UPDATE tipos_veiculo SET custo_rota = $2, peso_referencia_kg = $3, atualizado_em = NOW(), atualizado_por = $4 "
        f"WHERE id = $1 RETURNING {_COLUNAS_TIPO}",
        id_tipo, custo, peso, rotulo_operador,
    )
    return None if linha is None else _tipo_para_dict(linha)


async def _nome_do_tipo(conn, nome_tipo) -> Optional[str]:
    """Nome exato do tipo cadastrado (aceita diferença de maiúsculas) ou None."""
    return await conn.fetchval("SELECT nome FROM tipos_veiculo WHERE lower(nome) = lower($1)", str(nome_tipo or "").strip())


async def listar_motoristas(conn, incluir_inativos: bool = True) -> list:
    onde = "" if incluir_inativos else "WHERE ativo"
    linhas = await conn.fetch(f"SELECT {_COLUNAS_MOTORISTA} FROM motoristas {onde} ORDER BY ativo DESC, lower(nome), id")
    return [_motorista_para_dict(l) for l in linhas]


async def criar_motorista(conn, nome, tipo_veiculo, rotulo_operador: str, valor_rota=None) -> dict:
    nome = normalizar_nome_motorista(nome)
    valor = interpretar_valor_proprio(valor_rota)
    tipo = await _nome_do_tipo(conn, tipo_veiculo)
    if tipo is None:
        raise ValueError(MSG_TIPO_INEXISTENTE)
    linha = await conn.fetchrow(
        f"INSERT INTO motoristas (nome, tipo_veiculo, valor_rota, ativo, atualizado_por) VALUES ($1, $2, $3, TRUE, $4) RETURNING {_COLUNAS_MOTORISTA}",
        nome, tipo, valor, rotulo_operador,
    )
    return _motorista_para_dict(linha)


async def atualizar_motorista(conn, id_motorista: int, nome, tipo_veiculo, ativo: bool, rotulo_operador: str, valor_rota=MANTER) -> Optional[dict]:
    """
    Edita nome, tipo, situação (ativar/desativar) e valor próprio por rota. None se o motorista não existe. Nunca apaga.
    valor_rota: vazio/None apaga o valor próprio (volta a valer o valor base); ausente (MANTER) não mexe nele.
    """
    nome = normalizar_nome_motorista(nome)
    valor = None if valor_rota is MANTER else interpretar_valor_proprio(valor_rota)
    tipo = await _nome_do_tipo(conn, tipo_veiculo)
    if tipo is None:
        raise ValueError(MSG_TIPO_INEXISTENTE)
    if valor_rota is MANTER:
        linha = await conn.fetchrow(
            f"UPDATE motoristas SET nome = $2, tipo_veiculo = $3, ativo = $4, atualizado_em = NOW(), atualizado_por = $5 "
            f"WHERE id = $1 RETURNING {_COLUNAS_MOTORISTA}",
            id_motorista, nome, tipo, bool(ativo), rotulo_operador,
        )
    else:
        linha = await conn.fetchrow(
            f"UPDATE motoristas SET nome = $2, tipo_veiculo = $3, ativo = $4, valor_rota = $6, atualizado_em = NOW(), atualizado_por = $5 "
            f"WHERE id = $1 RETURNING {_COLUNAS_MOTORISTA}",
            id_motorista, nome, tipo, bool(ativo), rotulo_operador, valor,
        )
    return None if linha is None else _motorista_para_dict(linha)


async def frota_ativa(conn) -> list:
    """Motoristas ativos com o valor próprio (se houver), o valor base e o peso de referência do tipo de veículo."""
    linhas = await conn.fetch(
        "SELECT m.id, m.nome, m.tipo_veiculo, m.valor_rota, t.custo_rota, t.peso_referencia_kg "
        "FROM motoristas m JOIN tipos_veiculo t ON t.nome = m.tipo_veiculo "
        "WHERE m.ativo ORDER BY m.id"
    )
    return [
        {"id": l["id"], "nome": l["nome"], "tipo_veiculo": l["tipo_veiculo"], "custo_rota": float(l["custo_rota"]),
         "valor_rota": None if l.get("valor_rota") is None else float(l["valor_rota"]),
         "peso_referencia_kg": None if l["peso_referencia_kg"] is None else float(l["peso_referencia_kg"])}
        for l in linhas
    ]


async def selecionar_motoristas(conn, ids) -> list:
    """
    Motoristas escolhidos para a roteirização (na ordem escolhida, sem repetir), com o tipo de veículo e o valor base.
    ValueError em linguagem do operador se não escolheu nenhum, se algum não existe ou se algum está desativado.
    """
    pedidos = []
    for bruto in ids or []:
        try:
            if isinstance(bruto, bool) or (isinstance(bruto, float) and not bruto.is_integer()):
                raise ValueError
            numero = int(bruto)
        except (TypeError, ValueError):
            raise ValueError(MSG_MOTORISTA_INEXISTENTE) from None
        if numero not in pedidos:
            pedidos.append(numero)
    if not pedidos:
        raise ValueError(MSG_ESCOLHA_UM_MOTORISTA)
    linhas = await conn.fetch(
        "SELECT m.id, m.nome, m.ativo, m.tipo_veiculo, m.valor_rota, t.custo_rota, t.peso_referencia_kg "
        "FROM motoristas m JOIN tipos_veiculo t ON t.nome = m.tipo_veiculo"
    )
    por_id = {int(l["id"]): l for l in linhas}
    escolhidos = []
    for numero in pedidos:
        linha = por_id.get(numero)
        if linha is None:
            raise ValueError(MSG_MOTORISTA_INEXISTENTE)
        if not linha["ativo"]:
            raise ValueError(f'{linha["nome"]} está desativado. Ative-o na tela "Motoristas" ou tire-o da escolha.')
        escolhidos.append({
            "id": int(linha["id"]), "nome": linha["nome"], "tipo_veiculo": linha["tipo_veiculo"], "custo_rota": float(linha["custo_rota"]),
            "valor_rota": None if linha["valor_rota"] is None else float(linha["valor_rota"]),
            "peso_referencia_kg": None if linha["peso_referencia_kg"] is None else float(linha["peso_referencia_kg"]),
        })
    return escolhidos
