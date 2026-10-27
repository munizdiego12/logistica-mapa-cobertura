"""
Solver de rotas (Etapa 8 e 8b): divide os pedidos entre os motoristas, divide a carga de cada motorista em viagens, ordena as paradas e
avisa o que não saiu como o ideal. Só trabalha com matrizes e dados simples (sem rede, sem banco), então é testável sozinho. O resultado é uma
SUGESTÃO: o operador ajusta depois e o sistema nunca recusa.

Equilíbrio por MOTORISTA (não por rota). Dois níveis:
  1) CARGA POR MOTORISTA (OR-Tools Routing, um veículo por motorista, sem teto): cada motorista recebe uma cota exata de pedidos (`n // D`; o resto vai,
     um a mais, para quem tem MENOS rotas confirmadas no dia). A cota é a mesma com ou sem número de viagens escolhido e não depende do tipo de veículo.
     Como cada veículo é um motorista, a regra de ROTAÇÃO entra direto (custo de arco maior para os setores que o motorista já fez em outro turno hoje:
     forte, mas finita, nunca bloqueante). Minimiza a distância total.
  2) VIAGENS DE CADA MOTORISTA: automático = `ceil(cota / teto do tipo de veículo)` viagens; personalizado = o número escolhido pelo operador (nunca viagem
     vazia, e o teto do tipo NÃO vale: só avisa quando passa dele). A carga do motorista é dividida em viagens equilibradas (tamanhos que diferem em no máximo 1),
     minimizando a distância e preferindo setores diferentes entre as viagens do mesmo motorista.
Capacidade é sempre em NÚMERO de pedidos; o PESO não entra (é só informativo, nunca restrição nem aviso). Gancho para depois (os pedidos ainda não trazem
SKU): o peso de referência do veículo poderia servir de guia de equilíbrio, NUNCA de restrição. Hoje nada aqui lê peso.
Sem ortools (ou sem solução), uma reserva por varredura angular monta as rotas e o resultado avisa.
"""
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import setores as modulo_setores

LIMITE_MINIMO_S = 2.0
LIMITE_MAXIMO_S = 10.0
FATOR_NIVEL_1_COM_VIAGENS = 0.6  # parte do tempo do solver para a carga por motorista quando alguém precisa de mais de uma viagem
LIMITE_MINIMO_DIVISAO_S = 0.3
PENALIDADE_ROTACAO_MINIMA = 5000  # em metros equivalentes por parada num setor que o motorista já fez em outro turno hoje
PENALIDADE_SETOR_REPETIDO_M = 2000  # por setor em comum entre duas viagens do mesmo motorista
PENALIDADE_SETOR_PROXIMO_M = 100  # por degrau de proximidade entre os setores principais (opostos custam 0)


@dataclass
class MotoristaSolver:
    id: int
    nome: str
    modal: str
    capacidade: int  # teto RECOMENDADO de PEDIDOS por viagem do tipo de veículo
    viagens: Optional[int] = None  # None = automático; número = viagens escolhidas pelo operador (rota personalizada)


@dataclass
class RotaSolver:
    motorista_id: int
    viagem_num: int
    modal: str
    pedidos: list  # índices dos pedidos (0-based, na ordem das paradas)
    distancia_m: int = 0
    duracao_s: int = 0
    setores: dict = field(default_factory=dict)  # setor -> paradas
    violacoes: list = field(default_factory=list)  # setores da rota que o motorista já fez em outro turno hoje
    personalizada: bool = False
    teto_recomendado: int = 0
    viagens_solicitadas: Optional[int] = None


@dataclass
class ResultadoSolver:
    rotas: list
    metodo: str  # "ortools" | "reserva"
    motivo_reserva: Optional[str] = None
    tempo_solver_s: float = 0.0
    limite_s: float = 0.0
    viagens_extras: int = 0
    avisos: list = field(default_factory=list)  # {"tipo", "gravidade", "mensagem"}


def limite_de_tempo(n_pedidos: int) -> float:
    """Tempo máximo do solver: 0,25 s por pedido, entre 2 e 10 segundos."""
    return min(LIMITE_MAXIMO_S, max(LIMITE_MINIMO_S, 0.25 * n_pedidos))


def _aviso(tipo: str, gravidade: str, mensagem: str) -> dict:
    return {"tipo": tipo, "gravidade": gravidade, "mensagem": mensagem}


# ----------------------------------------------------------------------------------------------------------
# Cotas por motorista e número de viagens
# ----------------------------------------------------------------------------------------------------------
def cotas_por_motorista(n_pedidos: int, motoristas: list, rotas_hoje: Optional[dict] = None) -> dict:
    """
    {motorista_id: pedidos} com a divisão exata `n // D`; o resto vai, um a mais, para os motoristas com MENOS rotas confirmadas no dia (empate
    pela ordem da lista). Com menos pedidos que motoristas, só os de menor contagem recebem 1 pedido. Independe do tipo de veículo e do nº de viagens.
    """
    rotas_hoje = rotas_hoje or {}
    ordem = sorted(range(len(motoristas)), key=lambda i: (int(rotas_hoje.get(motoristas[i].id, 0)), i))
    base, resto = divmod(n_pedidos, len(motoristas))
    cotas = {m.id: base for m in motoristas}
    for posicao, i in enumerate(ordem):
        if posicao < resto:
            cotas[motoristas[i].id] += 1
    return cotas


def numero_de_viagens(motorista: MotoristaSolver, cota: int) -> int:
    """Automático: ceil(cota / teto do tipo de veículo) (mínimo 1). Personalizado: o escolhido, nunca mais que a cota (sem viagem vazia)."""
    if cota <= 0:
        return 0
    if motorista.viagens is None:
        return max(1, math.ceil(cota / max(1, motorista.capacidade)))
    return max(1, min(int(motorista.viagens), cota))


def _tamanhos(total: int, viagens: int) -> list:
    base, resto = divmod(total, viagens)
    return [base + (1 if i < resto else 0) for i in range(viagens)]


# ----------------------------------------------------------------------------------------------------------
# Auxiliares geométricos
# ----------------------------------------------------------------------------------------------------------
def _distancia_da_rota(dist: list, paradas: list) -> int:
    if not paradas:
        return 0
    nos = [0] + [p + 1 for p in paradas] + [0]
    return sum(dist[a][b] for a, b in zip(nos, nos[1:]))


def _melhorar_2opt(dist: list, paradas: list) -> list:
    paradas = list(paradas)
    melhorou = True
    while melhorou and len(paradas) > 2:
        melhorou = False
        for i in range(len(paradas) - 1):
            for j in range(i + 1, len(paradas)):
                candidata = paradas[:i] + paradas[i:j + 1][::-1] + paradas[j + 1:]
                if _distancia_da_rota(dist, candidata) < _distancia_da_rota(dist, paradas):
                    paradas, melhorou = candidata, True
    return paradas


def _ordenar_vizinho(dist: list, pedidos: list) -> list:
    """Ordem das paradas por vizinho mais próximo a partir da loja, melhorada por 2-opt."""
    restantes, rota, atual = list(pedidos), [], 0
    while restantes:
        proximo = min(restantes, key=lambda p: dist[atual][p + 1])
        rota.append(proximo)
        restantes.remove(proximo)
        atual = proximo + 1
    return _melhorar_2opt(dist, rota)


def ordenar_uma_rota(dist: list, pedidos: list, limite_s: float = 1.0, usar_ortools: bool = True) -> list:
    """
    Ordem das paradas de UMA viagem (Etapa 10b, mover pedido): vizinho mais próximo + 2-opt e, com ortools, uma busca curta (`limite_s`) que só
    vale se encurtar a rota. Nunca falha: sem ortools ou com erro, fica a ordem do vizinho.
    """
    base = _ordenar_vizinho(dist, pedidos)
    if not usar_ortools or len(base) <= 3:
        return base
    try:
        otimizada = _dividir_ortools(dist, list(base), 1, limite_s, [base])
    except Exception:
        return base
    if otimizada and _distancia_da_rota(dist, otimizada[0]) < _distancia_da_rota(dist, base):
        return otimizada[0]
    return base


def _varredura(azimutes: list, pedidos: list) -> list:
    """Pedidos em ordem angular, começando logo depois do maior vão entre azimutes vizinhos (assim a varredura não corta um grupo no meio)."""
    ordenados = sorted(pedidos, key=lambda p: (azimutes[p], p))
    if len(ordenados) < 2:
        return ordenados
    graus = [azimutes[p] for p in ordenados]
    vaos = [((graus[(i + 1) % len(graus)] - graus[i]) % 360.0, i) for i in range(len(graus))]
    _, fim = max(vaos)
    inicio = (fim + 1) % len(ordenados)
    return ordenados[inicio:] + ordenados[:inicio]


def _fatiar(sequencia: list, tamanhos: list) -> list:
    fatias, posicao = [], 0
    for t in tamanhos:
        fatias.append(sequencia[posicao:posicao + t])
        posicao += t
    return fatias


def _setores_da_rota(setores_dos_pedidos: list, paradas: list) -> dict:
    return dict(Counter(setores_dos_pedidos[p] for p in paradas))


def _custo_rotacao(setores_da_rota: dict, proibidos: Optional[dict]) -> int:
    return sum(paradas for setor, paradas in setores_da_rota.items() if setor in (proibidos or {}))


def _setor_principal(setores_da_rota: dict) -> str:
    return max(setores_da_rota, key=lambda s: (setores_da_rota[s], s))


# ----------------------------------------------------------------------------------------------------------
# Nível 1: carga por motorista
# ----------------------------------------------------------------------------------------------------------
def _resolver_roteamento(roteamento, parametros, rotas_iniciais: Optional[list]):
    """Resolve partindo de rotas iniciais viáveis (cotas exatas são difíceis de achar do zero); sem elas ou se não servirem, resolve do zero."""
    if rotas_iniciais:
        roteamento.CloseModelWithParameters(parametros)
        atribuicao = roteamento.ReadAssignmentFromRoutes(rotas_iniciais, True)
        if atribuicao is not None:
            solucao = roteamento.SolveFromAssignmentWithParameters(atribuicao, parametros)
            if solucao is not None:
                return solucao
    return roteamento.SolveWithParameters(parametros)


def _agrupar_ortools(dist: list, setores_dos_pedidos: list, ativos: list, cotas: dict, proibidos: dict, limite_s: float, inicial: Optional[dict] = None) -> Optional[dict]:
    """{motorista_id: pedidos na ordem das paradas} com a cota exata de cada motorista, ou None se o solver não achou solução."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # importado aqui: o app sobe mesmo sem o ortools

    n = len(setores_dos_pedidos)
    gerente = pywrapcp.RoutingIndexManager(n + 1, len(ativos), 0)
    roteamento = pywrapcp.RoutingModel(gerente)

    def distancia(de, para):
        return dist[gerente.IndexToNode(de)][gerente.IndexToNode(para)]

    indice_distancia = roteamento.RegisterTransitCallback(distancia)
    roteamento.SetArcCostEvaluatorOfAllVehicles(indice_distancia)
    media_ate_a_loja = sum(dist[0][i] for i in range(1, n + 1)) / max(1, n)
    penalidade = max(PENALIDADE_ROTACAO_MINIMA, int(10 * media_ate_a_loja))
    for v, m in enumerate(ativos):  # rotação: setores que este motorista já fez em outro turno hoje custam muito mais (forte, mas não proibido)
        vetados = set((proibidos.get(m.id) or {}).keys())
        if not vetados:
            continue

        def com_rotacao(de, para, vetados=vetados):
            no = gerente.IndexToNode(para)
            extra = penalidade if no != 0 and setores_dos_pedidos[no - 1] in vetados else 0
            return dist[gerente.IndexToNode(de)][no] + extra

        roteamento.SetArcCostEvaluatorOfVehicle(roteamento.RegisterTransitCallback(com_rotacao), v)

    def demanda(de):
        return 0 if gerente.IndexToNode(de) == 0 else 1  # NÚMERO de pedidos; peso nunca entra

    indice_demanda = roteamento.RegisterUnaryTransitCallback(demanda)
    roteamento.AddDimensionWithVehicleCapacity(indice_demanda, 0, [n] * len(ativos), True, "Pedidos")
    contagem = roteamento.GetDimensionOrDie("Pedidos")
    for v, m in enumerate(ativos):  # a carga de cada motorista é exatamente a cota dele
        contagem.CumulVar(roteamento.End(v)).SetRange(cotas[m.id], cotas[m.id])

    parametros = pywrapcp.DefaultRoutingSearchParameters()
    parametros.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parametros.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parametros.time_limit.FromMilliseconds(int(limite_s * 1000))
    solucao = _resolver_roteamento(roteamento, parametros, [[p + 1 for p in inicial[m.id]] for m in ativos] if inicial else None)
    if solucao is None:
        return None
    saida = {}
    for v, m in enumerate(ativos):
        indice, paradas = roteamento.Start(v), []
        while not roteamento.IsEnd(indice):
            no = gerente.IndexToNode(indice)
            if no != 0:
                paradas.append(no - 1)
            indice = solucao.Value(roteamento.NextVar(indice))
        saida[m.id] = paradas
    return saida if sum(len(p) for p in saida.values()) == n else None


def _agrupar_reserva(dist: list, setores_dos_pedidos: list, azimutes: list, ativos: list, cotas: dict, rotas_hoje: dict, proibidos: dict) -> dict:
    """
    Reserva (sem ortools ou sem solução): varredura angular dos pedidos em fatias do tamanho das cotas; cada fatia vai para o motorista de mesma cota
    com menor custo de rotação (e, depois, menos rotas no dia). Nunca deixa pedido de fora.
    """
    sequencia = _varredura(azimutes, list(range(len(setores_dos_pedidos))))
    tamanhos = sorted((cotas[m.id] for m in ativos), reverse=True)
    fatias = _fatiar(sequencia, tamanhos)
    livres = list(ativos)
    saida = {}
    for fatia in fatias:
        setores = _setores_da_rota(setores_dos_pedidos, fatia)
        candidatos = [m for m in livres if cotas[m.id] == len(fatia)]
        escolhido = min(candidatos, key=lambda m: (_custo_rotacao(setores, proibidos.get(m.id)), int(rotas_hoje.get(m.id, 0)), m.id))
        livres.remove(escolhido)
        saida[escolhido.id] = _ordenar_vizinho(dist, fatia)
    return saida


# ----------------------------------------------------------------------------------------------------------
# Nível 2: viagens de cada motorista
# ----------------------------------------------------------------------------------------------------------
def _dividir_ortools(dist: list, pedidos: list, viagens: int, limite_s: float, inicial: Optional[list] = None) -> Optional[list]:
    """Divide os pedidos do motorista em `viagens` viagens equilibradas (tamanhos entre floor e ceil), minimizando a distância."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    nos = [0] + [p + 1 for p in pedidos]
    gerente = pywrapcp.RoutingIndexManager(len(nos), viagens, 0)
    roteamento = pywrapcp.RoutingModel(gerente)
    indice = roteamento.RegisterTransitCallback(lambda de, para: dist[nos[gerente.IndexToNode(de)]][nos[gerente.IndexToNode(para)]])
    roteamento.SetArcCostEvaluatorOfAllVehicles(indice)
    demanda = roteamento.RegisterUnaryTransitCallback(lambda de: 0 if gerente.IndexToNode(de) == 0 else 1)
    teto = math.ceil(len(pedidos) / viagens)
    roteamento.AddDimensionWithVehicleCapacity(demanda, 0, [teto] * viagens, True, "Pedidos")
    contagem = roteamento.GetDimensionOrDie("Pedidos")
    piso = len(pedidos) // viagens
    for v in range(viagens):
        contagem.CumulVar(roteamento.End(v)).SetRange(piso, teto)
    parametros = pywrapcp.DefaultRoutingSearchParameters()
    parametros.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parametros.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parametros.time_limit.FromMilliseconds(int(limite_s * 1000))
    posicao = {p: i + 1 for i, p in enumerate(pedidos)}  # índice do pedido -> nó local
    solucao = _resolver_roteamento(roteamento, parametros, [[posicao[p] for p in v] for v in inicial] if inicial else None)
    if solucao is None:
        return None
    lista = []
    for v in range(viagens):
        i, paradas = roteamento.Start(v), []
        while not roteamento.IsEnd(i):
            no = gerente.IndexToNode(i)
            if no != 0:
                paradas.append(pedidos[no - 1])
            i = solucao.Value(roteamento.NextVar(i))
        lista.append(paradas)
    return lista if sum(len(x) for x in lista) == len(pedidos) and all(lista) else None


def _pontuar_divisao(dist: list, setores_dos_pedidos: list, divisao: list) -> int:
    """Distância total mais a penalidade por setores em comum entre as viagens do mesmo motorista (prefere setores diferentes ou opostos)."""
    total = sum(_distancia_da_rota(dist, v) for v in divisao)
    conjuntos = [_setores_da_rota(setores_dos_pedidos, v) for v in divisao]
    for i in range(len(conjuntos)):
        for j in range(i + 1, len(conjuntos)):
            a, b = conjuntos[i], conjuntos[j]
            total += PENALIDADE_SETOR_REPETIDO_M * len(set(a) & set(b))
            total += PENALIDADE_SETOR_PROXIMO_M * (4 - modulo_setores.distancia_circular(_setor_principal(a), _setor_principal(b)))
    return total


def _dividir_viagens(dist: list, setores_dos_pedidos: list, azimutes: list, ordem: list, viagens: int, limite_s: float, usar_ortools: bool) -> list:
    """`viagens` viagens com os pedidos do motorista (cada uma ordenada). Com 1 viagem vale a ordem do nível 1."""
    if viagens <= 1:
        return [list(ordem)]
    varridas = [_ordenar_vizinho(dist, fatia) for fatia in _fatiar(_varredura(azimutes, list(ordem)), _tamanhos(len(ordem), viagens))]
    candidatas = [varridas]
    if usar_ortools:
        try:
            otimizada = _dividir_ortools(dist, list(ordem), viagens, limite_s, varridas)
        except Exception:
            otimizada = None
        if otimizada:
            candidatas.append([_melhorar_2opt(dist, v) for v in otimizada])
    return min(candidatas, key=lambda d: _pontuar_divisao(dist, setores_dos_pedidos, d))


# ----------------------------------------------------------------------------------------------------------
# Entrada principal
# ----------------------------------------------------------------------------------------------------------
def _motivo_da_violacao(motorista, setores_violados: list, motoristas: list, proibidos: dict) -> str:
    outros = [m for m in motoristas if m.id != motorista.id]
    livres = [m for m in outros if not any(s in (proibidos.get(m.id) or {}) for s in setores_violados)]
    if livres:
        return ("havia outro motorista marcado sem essa restrição, mas a carga de cada motorista é dividida igualmente e a distância total ficou "
                "menor sem a troca")
    return "todos os motoristas marcados já passaram por esse setor em outro turno hoje (ou não há outro motorista marcado)"


def resolver(
    dist: list, dur: list, setores_dos_pedidos: list, motoristas: list, rotas_hoje: Optional[dict] = None,
    proibidos: Optional[dict] = None, limite_s: Optional[float] = None, usar_ortools: bool = True, azimutes: Optional[list] = None,
) -> ResultadoSolver:
    """
    `dist`/`dur`: matrizes (metros / segundos) com o hub no índice 0 e o pedido i no índice i+1. `setores_dos_pedidos[i]`: setor do pedido i.
    `rotas_hoje`: {motorista_id: rotas confirmadas hoje}. `proibidos`: {motorista_id: {setor: [turnos]}} (regra de rotação). `azimutes[i]`: azimute
    loja -> pedido i (sem ele, usa o centro do setor). Devolve as rotas (cada pedido exatamente uma vez), com setores, violações da rotação e avisos.
    Nunca levanta erro por capacidade ou peso.
    """
    n = len(setores_dos_pedidos)
    rotas_hoje, proibidos = rotas_hoje or {}, proibidos or {}
    limite = limite_s if limite_s is not None else limite_de_tempo(n)
    inicio = time.monotonic()
    resultado = ResultadoSolver(rotas=[], metodo="ortools", limite_s=limite)
    if n == 0 or not motoristas:
        return resultado
    if azimutes is None:
        azimutes = [modulo_setores.SETORES.index(s) * 45.0 + 0.001 * i for i, s in enumerate(setores_dos_pedidos)]

    cotas = cotas_por_motorista(n, motoristas, rotas_hoje)
    ativos = [m for m in motoristas if cotas[m.id] > 0]
    viagens_de = {m.id: numero_de_viagens(m, cotas[m.id]) for m in ativos}
    precisam_dividir = [m for m in ativos if viagens_de[m.id] > 1]
    limite_nivel_1 = limite * FATOR_NIVEL_1_COM_VIAGENS if precisam_dividir else limite
    limite_divisao = max(LIMITE_MINIMO_DIVISAO_S, (limite - limite_nivel_1) / max(1, len(precisam_dividir)))

    cargas = None
    if usar_ortools:
        try:
            inicial = _agrupar_reserva(dist, setores_dos_pedidos, azimutes, ativos, cotas, rotas_hoje, proibidos)
            cargas = _agrupar_ortools(dist, setores_dos_pedidos, ativos, cotas, proibidos, limite_nivel_1, inicial)
        except ImportError:
            resultado.motivo_reserva = "o otimizador (OR-Tools) não está disponível neste servidor"
        except Exception:
            resultado.motivo_reserva = "o otimizador não achou uma solução"
        if cargas is None and resultado.motivo_reserva is None:
            resultado.motivo_reserva = "o otimizador não achou uma solução"
    else:
        resultado.motivo_reserva = "otimizador desligado"
    if cargas is None:
        resultado.metodo = "reserva"
        cargas = _agrupar_reserva(dist, setores_dos_pedidos, azimutes, ativos, cotas, rotas_hoje, proibidos)
        resultado.avisos.append(_aviso(
            "reserva", "atencao",
            f"As rotas foram montadas por um método simples (reserva), porque {resultado.motivo_reserva}. Confira o agrupamento antes de usar.",
        ))

    viagens_automaticas_extras = 0
    for m in motoristas:
        if m.id not in cargas:
            continue
        viagens = _dividir_viagens(dist, setores_dos_pedidos, azimutes, cargas[m.id], viagens_de[m.id], limite_divisao, resultado.metodo == "ortools")
        viagens = sorted(viagens, key=lambda v: modulo_setores.SETORES.index(_setor_principal(_setores_da_rota(setores_dos_pedidos, v))))
        vetados = proibidos.get(m.id) or {}
        violados_do_motorista = set()
        for numero, paradas in enumerate(viagens, start=1):
            nos = [0] + [p + 1 for p in paradas] + [0]
            setores = _setores_da_rota(setores_dos_pedidos, paradas)
            violados = sorted((s for s in setores if s in vetados), key=modulo_setores.SETORES.index)
            violados_do_motorista.update(violados)
            resultado.rotas.append(RotaSolver(
                motorista_id=m.id, viagem_num=numero, modal=m.modal, pedidos=list(paradas),
                distancia_m=sum(dist[a][b] for a, b in zip(nos, nos[1:])), duracao_s=sum(dur[a][b] for a, b in zip(nos, nos[1:])),
                setores=setores, violacoes=violados, personalizada=m.viagens is not None, teto_recomendado=m.capacidade,
                viagens_solicitadas=m.viagens,
            ))
        if violados_do_motorista:
            ordenados = sorted(violados_do_motorista, key=modulo_setores.SETORES.index)
            turnos = sorted({tn for s in ordenados for tn in vetados[s]})
            resultado.avisos.append(_aviso(
                "rotacao", "atencao",
                f"{m.nome} foi escalado(a) para o setor {', '.join(ordenados)}, onde já fez rota hoje em outro turno ({', '.join(turnos)}). "
                f"Não foi possível evitar: {_motivo_da_violacao(m, ordenados, motoristas, proibidos)}.",
            ))
        if m.viagens is None:
            viagens_automaticas_extras += max(0, len(viagens) - 1)
        else:
            maior = max(len(v) for v in viagens)
            if m.viagens > cotas[m.id]:
                resultado.avisos.append(_aviso(
                    "viagens_solicitadas_a_menos", "atencao",
                    f"Foram pedidas {m.viagens} viagens para {m.nome}, mas ele(a) leva só {cotas[m.id]} pedido(s) e o sistema não cria viagem vazia: "
                    f"foram criadas {len(viagens)}.",
                ))
            if maior > m.capacidade:
                resultado.avisos.append(_aviso(
                    "rota_personalizada", "atencao",
                    f"Rota personalizada de {m.nome}: {cotas[m.id]} pedidos em {len(viagens)} viagem(ns) (a maior com {maior} pedidos); "
                    f"o teto recomendado do tipo de veículo é {m.capacidade} por viagem.",
                ))

    resultado.viagens_extras = viagens_automaticas_extras
    if viagens_automaticas_extras > 0:
        resultado.avisos.append(_aviso(
            "viagens_extras", "info",
            f"Os {n} pedidos passam do que os {len(motoristas)} motorista(s) marcado(s) levam de uma vez: foram criadas {viagens_automaticas_extras} "
            "viagem(ns) extra(s) para os mesmos motoristas, que voltam à loja entre as viagens.",
        ))
    sem_rota = [m for m in motoristas if m.id not in cargas]
    if sem_rota:
        resultado.avisos.append(_aviso(
            "sem_rota", "info",
            f"{len(sem_rota)} motorista(s) marcado(s) ficaram sem rota: há poucos pedidos para todos ({', '.join(m.nome for m in sem_rota)}).",
        ))
    resultado.tempo_solver_s = round(time.monotonic() - inicio, 2)
    return resultado
