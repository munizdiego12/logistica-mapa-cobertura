"""
Frota (Etapa 5): tipos de veículo (valor base por rota e peso de referência opcional) e cadastro de motoristas.

As tabelas são criadas SÓ pelo Alembic (migrations/versions/0004_tipos_veiculo_motoristas.py). As funções de banco
recebem uma conexão asyncpg (`conn`), como item_pesos.py. Motorista nunca é apagado: é desativado (ativo = false).

O peso de referência NÃO é limite: é só um guia para o motor de roteirização. Nada aqui bloqueia nem avisa por peso.
Mensagens de erro são em linguagem do operador (viram o `detail` das respostas 422).
"""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

CUSTO_MAXIMO_ROTA = Decimal("100000")
PESO_REFERENCIA_MAXIMO_KG = Decimal("100000")
TAMANHO_MAXIMO_NOME = 120

MSG_NOME_VAZIO = "Informe o nome do motorista."
MSG_NOME_GRANDE = f"O nome do motorista pode ter até {TAMANHO_MAXIMO_NOME} letras."
MSG_TIPO_INEXISTENTE = "Escolha um tipo de veículo da lista."
TAMANHO_MAXIMO_CODIGO = 40
MSG_CODIGO_VAZIO = "Informe o código do motorista, por exemplo MOT-0001."
MSG_CODIGO_GRANDE = f"O código do motorista pode ter até {TAMANHO_MAXIMO_CODIGO} caracteres."
MSG_CODIGO_REPETIDO = "Já existe um motorista com esse código. Escolha outro código."
MSG_CODIGO_NAO_PODE_FICAR_VAZIO = "Este motorista já tem código, e o código não pode ser apagado. Troque por outro código se precisar."
MSG_TELEFONE_INVALIDO = "O telefone não parece válido. Use o DDD e o número, por exemplo (11) 98765-4321."
MSG_TELEFONE_SEM_DDD = "O telefone precisa ter o DDD, por exemplo (11) 98765-4321."
MSG_LOJA_INEXISTENTE = "Uma das lojas escolhidas não está mais cadastrada. Atualize a lista e escolha de novo."
MSG_LOJAS_FORMATO = "A lista de lojas do motorista não está num formato válido. Atualize a tela e escolha de novo."
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


def _sem_acento(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")


def normalizar_codigo(valor) -> str:
    """
    Código do motorista como é guardado: sem acentos, sem espaços e em maiúsculas ("mot 0001" -> "MOT0001").
    Vazio devolve "" (quem chama decide se é obrigatório). Erro se passar do tamanho.
    """
    codigo = "".join(_sem_acento(valor).split()).upper()
    if len(codigo) > TAMANHO_MAXIMO_CODIGO:
        raise ValueError(MSG_CODIGO_GRANDE)
    return codigo


def chave_do_codigo(valor) -> str:
    """Chave de comparação do código (a mesma regra do índice único): normalizado e em minúsculas."""
    return normalizar_codigo(valor).lower()


_DDDS_VALIDOS = frozenset(
    "11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 "
    "61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99".split()
)


def normalizar_telefone(valor) -> Optional[str]:
    """
    Telefone do Brasil só com dígitos (10 ou 11, com DDD). Aceita parênteses, traços, pontos, espaços, +55 e 0 antes
    do DDD. Vazio/None = sem telefone (devolve None). Inválido ou sem DDD: ValueError, e a mensagem NUNCA repete o
    número digitado (telefone é dado pessoal e não pode ir parar em log nem em resposta de erro).
    """
    if valor is None or isinstance(valor, bool):
        if valor is None:
            return None
        raise ValueError(MSG_TELEFONE_INVALIDO)
    texto = str(valor).strip()
    if not texto:
        return None
    if re.search(r"[^\d\s()+\-.]", texto):
        raise ValueError(MSG_TELEFONE_INVALIDO)
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    elif len(digitos) in (11, 12) and digitos.startswith("0"):
        digitos = digitos[1:]
    if len(digitos) in (8, 9):
        raise ValueError(MSG_TELEFONE_SEM_DDD)
    if len(digitos) not in (10, 11) or digitos[:2] not in _DDDS_VALIDOS:
        raise ValueError(MSG_TELEFONE_INVALIDO)
    numero = digitos[2:]
    if len(digitos) == 11 and numero[0] != "9":
        raise ValueError(MSG_TELEFONE_INVALIDO)
    if len(digitos) == 10 and numero[0] not in "2345":
        raise ValueError(MSG_TELEFONE_INVALIDO)
    return digitos


def mascarar_telefone(telefone) -> Optional[str]:
    """(11) *****-1234 (11 dígitos) ou (11) ****-1234 (10 dígitos). Sem telefone: None."""
    digitos = re.sub(r"\D", "", str(telefone or ""))
    if len(digitos) not in (10, 11):
        return None
    return f"({digitos[:2]}) {'*' * (len(digitos) - 6)}-{digitos[-4:]}"


def interpretar_lojas(valor) -> list:
    """Lista de ids de loja (sem repetir, na ordem recebida). ValueError se não for uma lista de números inteiros."""
    if valor is None:
        return []
    if not isinstance(valor, (list, tuple, set)):
        raise ValueError(MSG_LOJAS_FORMATO)
    ids = []
    for bruto in valor:
        try:
            if isinstance(bruto, bool) or (isinstance(bruto, float) and not bruto.is_integer()):
                raise ValueError
            numero = int(bruto)
        except (TypeError, ValueError):
            raise ValueError(MSG_LOJAS_FORMATO) from None
        if numero not in ids:
            ids.append(numero)
    return ids


# ----------------------------------------------------------------------------------------------------------
# Banco (conexão asyncpg)
# ----------------------------------------------------------------------------------------------------------
_COLUNAS_TIPO = "id, nome, custo_rota, peso_referencia_kg, ativo, atualizado_em, atualizado_por"
_COLUNAS_MOTORISTA = "id, codigo, nome, tipo_veiculo, valor_rota, telefone, ativo, atualizado_em, atualizado_por"

# "Não mexer no campo": usado quando o pedido de edição não traz o campo (valor_rota, código, telefone, lojas).
MANTER = object()


def _motorista_para_dict(linha, lojas=None, completo: bool = False) -> dict:
    """
    Motorista para a resposta da API. O telefone completo só sai com `completo=True` (tela de edição de um motorista);
    nas listas e nas respostas de gravação vai só o mascarado e `tem_telefone`.
    """
    d = dict(linha)
    telefone = d.pop("telefone", None)
    d["valor_rota"] = None if d.get("valor_rota") is None else float(d["valor_rota"])
    if "ativo" in d:
        d["ativo"] = bool(d["ativo"])
    d.setdefault("codigo", None)
    d["tem_telefone"] = bool(telefone)
    d["telefone_mascarado"] = mascarar_telefone(telefone)
    if completo:
        d["telefone"] = telefone or None
    d["lojas"] = list(lojas or [])
    return d


def _e_violacao_de_unico(erro: Exception) -> bool:
    return type(erro).__name__ in ("UniqueViolationError", "IntegrityError")


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


async def _lojas_dos_motoristas(conn) -> dict:
    """{motorista_id: [{id, nome, ativo}]}, em ordem de nome da loja. Loja desativada continua na lista."""
    linhas = await conn.fetch(
        "SELECT ml.motorista_id, l.id AS loja_id, l.nome, l.ativo FROM motorista_lojas ml "
        "JOIN lojas l ON l.id = ml.loja_id ORDER BY lower(l.nome), l.id"
    )
    por_motorista = {}
    for l in linhas:
        por_motorista.setdefault(int(l["motorista_id"]), []).append(
            {"id": int(l["loja_id"]), "nome": l["nome"], "ativo": bool(l["ativo"])}
        )
    return por_motorista


async def listar_motoristas(conn, incluir_inativos: bool = True) -> list:
    """Todos os motoristas com código e lojas; o telefone vai só mascarado (nunca o número completo)."""
    onde = "" if incluir_inativos else "WHERE ativo"
    linhas = await conn.fetch(f"SELECT {_COLUNAS_MOTORISTA} FROM motoristas {onde} ORDER BY ativo DESC, lower(nome), id")
    lojas = await _lojas_dos_motoristas(conn)
    return [_motorista_para_dict(l, lojas.get(int(l["id"]))) for l in linhas]


async def obter_motorista(conn, id_motorista: int, completo: bool = True) -> Optional[dict]:
    """Um motorista, com o telefone completo (tela de edição). None se não existe."""
    linha = await conn.fetchrow(f"SELECT {_COLUNAS_MOTORISTA} FROM motoristas WHERE id = $1", id_motorista)
    if linha is None:
        return None
    lojas = await _lojas_dos_motoristas(conn)
    return _motorista_para_dict(linha, lojas.get(int(linha["id"])), completo)


_PADRAO_CODIGO_SUGERIDO = re.compile(r"^MOT-?(\d+)$")


async def proximo_codigo(conn) -> str:
    """Próximo código livre no padrão MOT-0001 (maior número já usado + 1)."""
    linhas = await conn.fetch("SELECT codigo FROM motoristas WHERE codigo IS NOT NULL")
    maior = 0
    for l in linhas:
        achou = _PADRAO_CODIGO_SUGERIDO.match(normalizar_codigo(l["codigo"]))
        if achou:
            maior = max(maior, int(achou.group(1)))
    return f"MOT-{maior + 1:04d}"


async def _codigo_em_uso(conn, codigo: str, exceto_id: Optional[int] = None) -> bool:
    achou = await conn.fetchval(
        "SELECT id FROM motoristas WHERE lower(btrim(codigo)) = lower($1) AND id <> $2",
        codigo, -1 if exceto_id is None else exceto_id,
    )
    return achou is not None


async def _conferir_lojas_novas(conn, ids_novos: list) -> None:
    """Vínculo novo só com loja cadastrada e ativa (vínculos antigos de lojas hoje desativadas podem ficar)."""
    if not ids_novos:
        return
    linhas = await conn.fetch("SELECT id, nome, ativo FROM lojas")
    por_id = {int(l["id"]): l for l in linhas}
    for numero in ids_novos:
        loja = por_id.get(numero)
        if loja is None:
            raise ValueError(MSG_LOJA_INEXISTENTE)
        if not loja["ativo"]:
            raise ValueError(f'A loja {loja["nome"]} está desativada. Ative-a na tela "Lojas" ou tire-a da escolha.')


async def criar_motorista(conn, nome, tipo_veiculo, rotulo_operador: str, valor_rota=None, codigo=None, telefone=None, lojas=None) -> dict:
    """Cadastro novo: o código é obrigatório e único; telefone, valor próprio e lojas são opcionais."""
    nome = normalizar_nome_motorista(nome)
    codigo = normalizar_codigo(codigo)
    if not codigo:
        raise ValueError(MSG_CODIGO_VAZIO)
    valor = interpretar_valor_proprio(valor_rota)
    fone = normalizar_telefone(telefone)
    ids_lojas = interpretar_lojas(lojas)
    tipo = await _nome_do_tipo(conn, tipo_veiculo)
    if tipo is None:
        raise ValueError(MSG_TIPO_INEXISTENTE)
    if await _codigo_em_uso(conn, codigo):
        raise ValueError(MSG_CODIGO_REPETIDO)
    await _conferir_lojas_novas(conn, ids_lojas)
    try:
        async with conn.transaction():
            linha = await conn.fetchrow(
                f"INSERT INTO motoristas (codigo, nome, tipo_veiculo, valor_rota, telefone, ativo, atualizado_por) "
                f"VALUES ($1, $2, $3, $4, $5, TRUE, $6) RETURNING {_COLUNAS_MOTORISTA}",
                codigo, nome, tipo, valor, fone, rotulo_operador,
            )
            for id_loja in ids_lojas:
                await conn.execute(
                    "INSERT INTO motorista_lojas (motorista_id, loja_id, atualizado_por) VALUES ($1, $2, $3)",
                    linha["id"], id_loja, rotulo_operador,
                )
    except Exception as erro:
        if _e_violacao_de_unico(erro):
            raise ValueError(MSG_CODIGO_REPETIDO) from None
        raise
    return await obter_motorista(conn, linha["id"], completo=False)


async def atualizar_motorista(conn, id_motorista: int, nome, tipo_veiculo, ativo: bool, rotulo_operador: str,
                              valor_rota=MANTER, codigo=MANTER, telefone=MANTER, lojas=MANTER) -> Optional[dict]:
    """
    Edita nome, tipo, situação (ativar/desativar), código, telefone, valor próprio por rota e lojas. None se o motorista
    não existe. Nunca apaga o motorista. Campo ausente (MANTER) não é mexido; valor_rota e telefone vazios apagam o
    valor; `lojas` presente substitui o conjunto de lojas; o código não pode ser apagado de quem já tem.
    """
    nome = normalizar_nome_motorista(nome)
    valor = None if valor_rota is MANTER else interpretar_valor_proprio(valor_rota)
    fone = None if telefone is MANTER else normalizar_telefone(telefone)
    ids_lojas = None if lojas is MANTER else interpretar_lojas(lojas)
    novo_codigo = None if codigo is MANTER else normalizar_codigo(codigo)
    tipo = await _nome_do_tipo(conn, tipo_veiculo)
    if tipo is None:
        raise ValueError(MSG_TIPO_INEXISTENTE)
    atual = await conn.fetchrow("SELECT id, codigo FROM motoristas WHERE id = $1", id_motorista)
    if atual is None:
        return None
    if codigo is not MANTER:
        if not novo_codigo:
            if atual["codigo"]:
                raise ValueError(MSG_CODIGO_NAO_PODE_FICAR_VAZIO)
            novo_codigo = None
        elif await _codigo_em_uso(conn, novo_codigo, id_motorista):
            raise ValueError(MSG_CODIGO_REPETIDO)
    ja_vinculadas = []
    if ids_lojas is not None:
        existentes = await conn.fetch("SELECT loja_id FROM motorista_lojas WHERE motorista_id = $1", id_motorista)
        ja_vinculadas = [int(l["loja_id"]) for l in existentes]
        await _conferir_lojas_novas(conn, [i for i in ids_lojas if i not in ja_vinculadas])

    campos = ["nome = $2", "tipo_veiculo = $3", "ativo = $4", "atualizado_em = NOW()", "atualizado_por = $5"]
    args = [id_motorista, nome, tipo, bool(ativo), rotulo_operador]
    for coluna, ausente, conteudo in (("valor_rota", valor_rota is MANTER, valor), ("telefone", telefone is MANTER, fone),
                                      ("codigo", codigo is MANTER, novo_codigo)):
        if not ausente:
            args.append(conteudo)
            campos.append(f"{coluna} = ${len(args)}")
    try:
        async with conn.transaction():
            linha = await conn.fetchrow(f"UPDATE motoristas SET {', '.join(campos)} WHERE id = $1 RETURNING id", *args)
            if ids_lojas is not None:
                for id_loja in ja_vinculadas:
                    if id_loja not in ids_lojas:
                        await conn.execute("DELETE FROM motorista_lojas WHERE motorista_id = $1 AND loja_id = $2", id_motorista, id_loja)
                for id_loja in ids_lojas:
                    if id_loja not in ja_vinculadas:
                        await conn.execute(
                            "INSERT INTO motorista_lojas (motorista_id, loja_id, atualizado_por) VALUES ($1, $2, $3)",
                            id_motorista, id_loja, rotulo_operador,
                        )
    except Exception as erro:
        if _e_violacao_de_unico(erro):
            raise ValueError(MSG_CODIGO_REPETIDO) from None
        raise
    if linha is None:
        return None
    return await obter_motorista(conn, id_motorista, completo=False)


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


MSG_MOTORISTA_DA_ROTA = "O motorista escolhido para uma das rotas não está mais ativo ou cadastrado. Atualize a lista e escolha de novo."


async def nomes_dos_motoristas_ativos(conn, ids) -> dict:
    """
    Etapa 10 (troca de motorista na matriz de despacho): {id: nome} dos motoristas pedidos, todos ATIVOS. ValueError em linguagem do operador se algum
    valor não for um número, não existir ou estiver desativado. Não devolve telefone nem código.
    """
    numeros = set()
    for bruto in ids or []:
        if isinstance(bruto, bool) or (isinstance(bruto, float) and not bruto.is_integer()):
            raise ValueError(MSG_MOTORISTA_DA_ROTA)
        try:
            numeros.add(int(bruto))
        except (TypeError, ValueError):
            raise ValueError(MSG_MOTORISTA_DA_ROTA) from None
    if not numeros:
        return {}
    linhas = await conn.fetch("SELECT id, nome, ativo FROM motoristas")
    ativos = {int(l["id"]): l["nome"] for l in linhas if l["ativo"]}
    if any(n not in ativos for n in numeros):
        raise ValueError(MSG_MOTORISTA_DA_ROTA)
    return {n: ativos[n] for n in numeros}


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
