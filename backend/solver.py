"""
Solver de rotas (Etapa 8): agrupa os pedidos em viagens, ordena as paradas e sugere QUEM faz cada rota. Só trabalha com matrizes e dados
simples (sem rede, sem banco), então é testável sozinho. O resultado é uma SUGESTÃO: o operador ajusta depois e o sistema nunca recusa.

Dois passos:
  1) OR-Tools (Routing): um depósito (a loja) e n pedidos. As "vagas de viagem" são `R` rodadas x cada motorista marcado, com a capacidade
     do tipo de veículo medida em NÚMERO de pedidos (o PESO não entra: é só informativo, nunca restrição nem aviso). Se os pedidos passam do
     que todos levam de uma vez, nascem viagens extras para os mesmos motoristas (que voltam à loja entre as viagens). Minimiza a distância
     total e equilibra o número de pedidos entre as rotas (limite superior suave por rota).
  2) Atribuição rota -> motorista (CP-SAT pequeno): cada rota vai para um motorista do mesmo tipo de veículo. Pesa, nesta ordem:
     a regra de ROTAÇÃO (o mesmo motorista não repete a mesma região em turnos diferentes no mesmo dia; forte, mas NUNCA bloqueante: se não
     der, a rota sai assim mesmo e o resultado avisa com o motivo), a JUSTIÇA (prefere quem fez menos rotas confirmadas no dia) e viagens
     do mesmo motorista em setores diferentes (de preferência, opostos).
Sem ortools (ou sem solução), uma reserva gulosa monta as rotas e o resultado avisa.

Gancho para depois (os pedidos ainda não trazem SKU): o peso de referência do veículo poderia entrar como guia de equilíbrio, NUNCA como
restrição. Hoje nada aqui lê peso.
"""
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import setores as modulo_setores

LIMITE_MINIMO_S = 2.0
LIMITE_MAXIMO_S = 10.0
LIMITE_ATRIBUICAO_S = 2.0
PESO_ROTACAO = 1000  # por parada em setor que o motorista já fez em outro turno hoje
PESO_JUSTICA = 10  # por nível de "rotas já feitas hoje"
PESO_SETOR_REPETIDO = 50  # por setor em comum entre duas viagens do mesmo motorista
PESO_SETOR_PROXIMO = 1  # por setor de distância a menos de 4 (oposto custa 0)


@dataclass
class MotoristaSolver:
    id: int
    nome: str
    modal: str
    capacidade: int  # teto de PEDIDOS por viagem do tipo de veículo


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
# Vagas de viagem e meta de equilíbrio
# ----------------------------------------------------------------------------------------------------------
def montar_vagas(motoristas: list, n_pedidos: int) -> list:
    """
    Vagas de viagem: `R` rodadas x cada motorista, com `R = ceil(n / soma das capacidades de uma rodada)` (pelo menos 1). Cada vaga é
    (modal, capacidade). Os mesmos motoristas aparecem de novo nas rodadas seguintes: o motorista volta à loja entre as viagens.
    """
    por_rodada = sum(max(1, m.capacidade) for m in motoristas)
    rodadas = max(1, math.ceil(n_pedidos / por_rodada)) if por_rodada else 1
    return [(m.modal, max(1, m.capacidade)) for _ in range(rodadas) for m in motoristas]


def rotas_ativas(vagas: list, n_pedidos: int, n_motoristas: int) -> int:
    """Quantas rotas devem existir: o maior entre (motoristas, limitado ao número de pedidos) e o menor número de viagens que a capacidade exige."""
    capacidades = sorted((c for _, c in vagas), reverse=True)
    acumulado, minimo = 0, 0
    for c in capacidades:
        minimo += 1
        acumulado += c
        if acumulado >= n_pedidos:
            break
    return max(min(n_motoristas, n_pedidos), minimo, 1)


def meta_por_rota(vagas: list, n_pedidos: int, n_motoristas: int) -> int:
    """Quantos pedidos cada rota deveria levar para ficar equilibrada: `ceil(n / rotas ativas)`."""
    return max(1, math.ceil(n_pedidos / rotas_ativas(vagas, n_pedidos, n_motoristas)))


# ----------------------------------------------------------------------------------------------------------
# Passo 1: agrupar e ordenar (OR-Tools) e a reserva gulosa
# ----------------------------------------------------------------------------------------------------------
def _agrupar_ortools(dist: list, n: int, vagas: list, meta: int, ativas: int, limite_s: float, n_motoristas: int) -> Optional[list]:
    """Rotas por vaga (lista de listas de índices de pedido, na ordem das paradas) ou None se o solver não achou solução."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # importado aqui: o app sobe mesmo sem o ortools

    gerente = pywrapcp.RoutingIndexManager(n + 1, len(vagas), 0)
    roteamento = pywrapcp.RoutingModel(gerente)

    def distancia(de, para):
        return dist[gerente.IndexToNode(de)][gerente.IndexToNode(para)]

    indice_distancia = roteamento.RegisterTransitCallback(distancia)
    roteamento.SetArcCostEvaluatorOfAllVehicles(indice_distancia)

    def demanda(de):
        return 0 if gerente.IndexToNode(de) == 0 else 1  # NÚMERO de pedidos; peso nunca entra

    indice_demanda = roteamento.RegisterUnaryTransitCallback(demanda)
    roteamento.AddDimensionWithVehicleCapacity(indice_demanda, 0, [c for _, c in vagas], True, "Pedidos")
    contagem = roteamento.GetDimensionOrDie("Pedidos")
    # Equilíbrio: passar da meta por rota custa o equivalente a uma boa parte da distância média até a loja (suave: nunca impede uma solução).
    distancias_ate_loja = [dist[0][i] for i in range(1, n + 1)] or [1000]
    penalidade = max(600, int(2.5 * sum(distancias_ate_loja) / len(distancias_ate_loja)))
    piso = n // ativas
    # Rotas que devem existir: a 1ª viagem de cada motorista (as primeiras vagas da lista) e, se a capacidade exige mais, as maiores vagas restantes.
    maiores = list(range(min(ativas, n_motoristas)))
    maiores += sorted(range(n_motoristas, len(vagas)), key=lambda v: -vagas[v][1])[:max(0, ativas - len(maiores))]
    if n >= ativas:  # com pedidos para todos, cada rota ativa leva pelo menos um pedido (todos os motoristas marcados trabalham)
        for v in maiores:
            roteamento.solver().Add(roteamento.NextVar(roteamento.Start(v)) != roteamento.End(v))
    for v in range(len(vagas)):
        contagem.SetCumulVarSoftUpperBound(roteamento.End(v), meta, penalidade)
        if v in maiores and piso > 0:  # as rotas ativas não ficam abaixo do piso (usa todos os motoristas quando há pedidos para isso)
            contagem.SetCumulVarSoftLowerBound(roteamento.End(v), piso, penalidade)

    parametros = pywrapcp.DefaultRoutingSearchParameters()
    parametros.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parametros.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parametros.time_limit.FromMilliseconds(int(limite_s * 1000))
    solucao = roteamento.SolveWithParameters(parametros)
    if solucao is None:
        return None
    rotas = []
    for v in range(len(vagas)):
        indice = roteamento.Start(v)
        paradas = []
        while not roteamento.IsEnd(indice):
            no = gerente.IndexToNode(indice)
            if no != 0:
                paradas.append(no - 1)
            indice = solucao.Value(roteamento.NextVar(indice))
        rotas.append(paradas)
    return rotas


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
        # volta ao laço enquanto houver melhora
    return paradas


def _agrupar_reserva(dist: list, n: int, vagas: list, meta: int) -> list:
    """
    Reserva gulosa (sem ortools ou sem solução): por vaga, parte do pedido mais longe da loja entre os que sobraram e vai pegando o
    vizinho mais próximo até a meta (ou a capacidade); depois melhora a ordem com 2-opt. Nunca deixa pedido de fora.
    """
    restantes = list(range(n))
    rotas = [[] for _ in vagas]
    ordem_das_vagas = sorted(range(len(vagas)), key=lambda v: -vagas[v][1])
    for ciclo in range(2):  # 1º ciclo até a meta; 2º ciclo (se sobrar) até a capacidade
        for v in ordem_das_vagas:
            teto = min(vagas[v][1], meta) if ciclo == 0 else vagas[v][1]
            while restantes and len(rotas[v]) < teto:
                atual = rotas[v][-1] + 1 if rotas[v] else 0
                if rotas[v]:
                    proximo = min(restantes, key=lambda p: dist[atual][p + 1])
                else:
                    proximo = max(restantes, key=lambda p: dist[0][p + 1])
                rotas[v].append(proximo)
                restantes.remove(proximo)
    return [_melhorar_2opt(dist, r) for r in rotas]


# ----------------------------------------------------------------------------------------------------------
# Passo 2: quem faz cada rota
# ----------------------------------------------------------------------------------------------------------
def _custo_rotacao(setores_da_rota: dict, proibidos: dict) -> int:
    return sum(paradas for setor, paradas in setores_da_rota.items() if setor in (proibidos or {}))


def _custo_par(a: dict, b: dict) -> int:
    """Custo de duas viagens do MESMO motorista: setores em comum pesam muito; setores próximos pesam pouco (opostos não pesam)."""
    comuns = len(set(a) & set(b))
    principal_a = max(a, key=lambda s: (a[s], s)) if a else "N"
    principal_b = max(b, key=lambda s: (b[s], s)) if b else "N"
    proximidade = 4 - modulo_setores.distancia_circular(principal_a, principal_b)
    return PESO_SETOR_REPETIDO * comuns + PESO_SETOR_PROXIMO * proximidade


def _atribuir_cp_sat(rotas: list, motoristas: list, rotas_hoje: dict, proibidos: dict) -> Optional[list]:
    from ortools.sat.python import cp_model  # importado aqui: o app sobe mesmo sem o ortools

    modelo = cp_model.CpModel()
    x = {}
    for t, r in enumerate(rotas):
        candidatos = [m for m in motoristas if m.modal == r["modal"]]
        if not candidatos:
            return None
        for m in candidatos:
            x[t, m.id] = modelo.NewBoolVar(f"x_{t}_{m.id}")
        modelo.AddExactlyOne(x[t, m.id] for m in candidatos)
    # Com pelo menos uma rota para cada motorista do tipo, todos os motoristas marcados trabalham (a justiça decide só as rotas extras).
    for modal in {r["modal"] for r in rotas}:
        deste_tipo = [m for m in motoristas if m.modal == modal]
        if sum(1 for r in rotas if r["modal"] == modal) >= len(deste_tipo):
            for m in deste_tipo:
                modelo.Add(sum(x[t, m.id] for t in range(len(rotas)) if (t, m.id) in x) >= 1)
    custo = []
    for (t, d), var in x.items():
        custo.append(PESO_ROTACAO * _custo_rotacao(rotas[t]["setores"], proibidos.get(d)) * var)
    for m in motoristas:
        trechos = [(t, m.id) for t in range(len(rotas)) if (t, m.id) in x]
        if not trechos:
            continue
        base = int(rotas_hoje.get(m.id, 0))
        degraus = [modelo.NewBoolVar(f"z_{m.id}_{j}") for j in range(len(trechos))]
        modelo.Add(sum(x[k] for k in trechos) <= sum(degraus))
        for j, degrau in enumerate(degraus):  # a j-ésima rota extra custa (rotas já feitas + j): o motorista com menos rotas pega primeiro
            custo.append(PESO_JUSTICA * (base + j + 1) * degrau)
    for t in range(len(rotas)):
        for u in range(t + 1, len(rotas)):
            if rotas[t]["modal"] != rotas[u]["modal"]:
                continue
            custo_do_par = _custo_par(rotas[t]["setores"], rotas[u]["setores"])
            if custo_do_par <= 0:
                continue
            for m in motoristas:
                if (t, m.id) in x and (u, m.id) in x:
                    junto = modelo.NewBoolVar(f"y_{t}_{u}_{m.id}")
                    modelo.Add(junto >= x[t, m.id] + x[u, m.id] - 1)
                    custo.append(custo_do_par * junto)
    modelo.Minimize(sum(custo))
    resolvedor = cp_model.CpSolver()
    resolvedor.parameters.max_time_in_seconds = LIMITE_ATRIBUICAO_S
    resolvedor.parameters.num_workers = 1
    resolvedor.parameters.random_seed = 7
    estado = resolvedor.Solve(modelo)
    if estado not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    escolhidos = []
    for t in range(len(rotas)):
        escolhidos.append(next(m.id for m in motoristas if (t, m.id) in x and resolvedor.Value(x[t, m.id])))
    return escolhidos


def _atribuir_reserva(rotas: list, motoristas: list, rotas_hoje: dict, proibidos: dict) -> list:
    feitas = {m.id: int(rotas_hoje.get(m.id, 0)) for m in motoristas}
    levadas = {m.id: [] for m in motoristas}
    escolhidos = [None] * len(rotas)
    for t in sorted(range(len(rotas)), key=lambda i: -sum(rotas[i]["setores"].values())):
        candidatos = [m for m in motoristas if m.modal == rotas[t]["modal"]] or list(motoristas)
        ociosos = [m for m in candidatos if not levadas[m.id]]
        candidatos = ociosos or candidatos  # quem ainda não tem rota vem primeiro: todos os motoristas marcados trabalham

        def custo(m):
            repetido = sum(_custo_par(rotas[t]["setores"], rotas[u]["setores"]) for u in levadas[m.id])
            return (PESO_ROTACAO * _custo_rotacao(rotas[t]["setores"], proibidos.get(m.id)) + PESO_JUSTICA * feitas[m.id] + repetido, m.id)

        escolhido = min(candidatos, key=custo)
        escolhidos[t] = escolhido.id
        feitas[escolhido.id] += 1
        levadas[escolhido.id].append(t)
    return escolhidos


def _motivo_da_violacao(motorista, setores_violados: list, motoristas: list, proibidos: dict, modal: str) -> str:
    outros = [m for m in motoristas if m.modal == modal and m.id != motorista.id]
    livres = [m for m in outros if not any(s in (proibidos.get(m.id) or {}) for s in setores_violados)]
    if livres:
        return ("havia outro motorista marcado sem essa restrição, mas ele já estava com as viagens previstas para manter a distribuição justa "
                "e a capacidade dos veículos")
    return "todos os motoristas marcados deste tipo de veículo já passaram por esse setor em outro turno hoje (ou não há outro motorista deste tipo marcado)"


# ----------------------------------------------------------------------------------------------------------
# Entrada principal
# ----------------------------------------------------------------------------------------------------------
def resolver(
    dist: list, dur: list, setores_dos_pedidos: list, motoristas: list, rotas_hoje: Optional[dict] = None,
    proibidos: Optional[dict] = None, limite_s: Optional[float] = None, usar_ortools: bool = True,
) -> ResultadoSolver:
    """
    `dist`/`dur`: matrizes (metros / segundos) com o hub no índice 0 e o pedido i no índice i+1. `setores_dos_pedidos[i]`: setor do pedido i.
    `rotas_hoje`: {motorista_id: rotas confirmadas hoje}. `proibidos`: {motorista_id: {setor: [turnos]}} (regra de rotação).
    Devolve as rotas (cada pedido exatamente uma vez), com setores, violações da rotação e avisos. Nunca levanta erro por capacidade ou peso.
    """
    n = len(setores_dos_pedidos)
    rotas_hoje, proibidos = rotas_hoje or {}, proibidos or {}
    limite = limite_s if limite_s is not None else limite_de_tempo(n)
    inicio = time.monotonic()
    resultado = ResultadoSolver(rotas=[], metodo="ortools", limite_s=limite)
    if n == 0 or not motoristas:
        return resultado

    vagas = montar_vagas(motoristas, n)
    meta = meta_por_rota(vagas, n, len(motoristas))
    ativas = rotas_ativas(vagas, n, len(motoristas))

    agrupadas = None
    if usar_ortools:
        try:
            agrupadas = _agrupar_ortools(dist, n, vagas, meta, ativas, limite, len(motoristas))
        except ImportError:
            resultado.motivo_reserva = "o otimizador (OR-Tools) não está disponível neste servidor"
        except Exception:
            resultado.motivo_reserva = "o otimizador não achou uma solução"
        if agrupadas is None and resultado.motivo_reserva is None:
            resultado.motivo_reserva = "o otimizador não achou uma solução"
    else:
        resultado.motivo_reserva = "otimizador desligado"
    if agrupadas is None:
        resultado.metodo = "reserva"
        agrupadas = _agrupar_reserva(dist, n, vagas, meta)
        resultado.avisos.append(_aviso(
            "reserva", "atencao",
            f"As rotas foram montadas por um método simples (reserva), porque {resultado.motivo_reserva}. Confira o agrupamento antes de usar.",
        ))

    # rotas não vazias, com setores e modal da vaga
    rotas = []
    for v, paradas in enumerate(agrupadas):
        if not paradas:
            continue
        contagem = Counter(setores_dos_pedidos[p] for p in paradas)
        rotas.append({"modal": vagas[v][0], "paradas": paradas, "setores": dict(contagem)})

    # passo 2: quem faz cada rota
    escolhidos = None
    if resultado.metodo == "ortools":
        try:
            escolhidos = _atribuir_cp_sat(rotas, motoristas, rotas_hoje, proibidos)
        except Exception:
            escolhidos = None
    if escolhidos is None:
        escolhidos = _atribuir_reserva(rotas, motoristas, rotas_hoje, proibidos)

    por_id = {m.id: m for m in motoristas}
    viagens_por_motorista = Counter()
    ordenadas = sorted(range(len(rotas)), key=lambda t: (escolhidos[t], modulo_setores.SETORES.index(max(rotas[t]["setores"], key=lambda s: (rotas[t]["setores"][s], s)))))
    for t in ordenadas:
        r = rotas[t]
        motorista = por_id[escolhidos[t]]
        viagens_por_motorista[motorista.id] += 1
        nos = [0] + [p + 1 for p in r["paradas"]] + [0]
        violados = sorted((s for s in r["setores"] if s in (proibidos.get(motorista.id) or {})), key=modulo_setores.SETORES.index)
        resultado.rotas.append(RotaSolver(
            motorista_id=motorista.id, viagem_num=viagens_por_motorista[motorista.id], modal=r["modal"], pedidos=list(r["paradas"]),
            distancia_m=sum(dist[a][b] for a, b in zip(nos, nos[1:])), duracao_s=sum(dur[a][b] for a, b in zip(nos, nos[1:])),
            setores=dict(r["setores"]), violacoes=violados,
        ))
        if violados:
            turnos = sorted({tn for s in violados for tn in (proibidos[motorista.id][s])})
            resultado.avisos.append(_aviso(
                "rotacao", "atencao",
                f"{motorista.nome} foi escalado(a) para o setor {', '.join(violados)}, onde já fez rota hoje em outro turno ({', '.join(turnos)}). "
                f"Não foi possível evitar: {_motivo_da_violacao(motorista, violados, motoristas, proibidos, r['modal'])}.",
            ))

    resultado.viagens_extras = sum(max(0, q - 1) for q in viagens_por_motorista.values())
    if resultado.viagens_extras > 0:
        resultado.avisos.append(_aviso(
            "viagens_extras", "info",
            f"Os {n} pedidos passam do que os {len(motoristas)} motorista(s) marcado(s) levam de uma vez: foram criadas {resultado.viagens_extras} "
            "viagem(ns) extra(s) para os mesmos motoristas, que voltam à loja entre as viagens.",
        ))
    sem_rota = [m for m in motoristas if m.id not in viagens_por_motorista]
    if sem_rota:
        resultado.avisos.append(_aviso(
            "sem_rota", "info",
            f"{len(sem_rota)} motorista(s) marcado(s) ficaram sem rota: há poucos pedidos para todos ({', '.join(m.nome for m in sem_rota)}).",
        ))
    resultado.tempo_solver_s = round(time.monotonic() - inicio, 2)
    return resultado
