"""
Roteirização (Etapa 8): orquestra matriz de distâncias, solver, setores, tempos e avisos, e devolve as viagens já com ordem das paradas,
distâncias entre paradas, tempo e setores. `main.py` só formata (custos, link do Maps, geometria) e grava o resultado do job.

Entradas: hub (loja, coordenada cadastrada), pedidos JÁ geocodificados (só os marcados da loja e sem erro de endereço), motoristas marcados
(ativos, cada um com seu tipo de veículo), o TURNO escolhido manualmente pelo operador (nunca inferido do relógio) e o tempo por parada.
Capacidade por NÚMERO de pedidos por viagem; o peso nunca entra. Tudo é SUGESTÃO: o sistema nunca recusa.
Pedidos são dado pessoal: nada daqui vai para log; os avisos só falam de motoristas, setores, contagens e do método.
"""
import asyncio
import unicodedata
from typing import Awaitable, Callable, Optional

import setores as modulo_setores
import solver as modulo_solver

TURNOS = ("manha", "tarde", "noite")
ROTULOS_DOS_TURNOS = {"manha": "manhã", "tarde": "tarde", "noite": "noite"}
TEMPO_POR_PARADA_PADRAO_MIN = 10
MSG_ESCOLHA_O_TURNO = "Escolha o turno (manhã, tarde ou noite)."
MSG_TEMPO_POR_PARADA = "O tempo por parada precisa ficar entre 1 e 60 minutos."
MSG_VIAGENS = "O número de rotas do motorista precisa ser 1, 2, 3 ou 4 (ou automático)."
MSG_VIAGENS_MOTORISTA_FORA = "O número de rotas foi informado para um motorista que não está marcado na roteirização."
VIAGENS_MAXIMAS = 10  # a tela oferece 1 a 4; o servidor aceita até 10
CAPACIDADE_PADRAO = 6


def normalizar_turno(valor) -> str:
    """'Manhã', 'manha', ' TARDE ' -> 'manha'/'tarde'/'noite'. ValueError (em linguagem do operador) se vazio ou desconhecido."""
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode("ascii").strip().lower()
    if texto not in TURNOS:
        raise ValueError(MSG_ESCOLHA_O_TURNO)
    return texto


def interpretar_tempo_por_parada(valor) -> int:
    """Vazio vale 10 minutos; precisa ser um número inteiro de 1 a 60."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return TEMPO_POR_PARADA_PADRAO_MIN
    try:
        if isinstance(valor, bool):
            raise ValueError
        numero = float(str(valor).replace(",", "."))
    except ValueError:
        raise ValueError(MSG_TEMPO_POR_PARADA) from None
    if numero != int(numero) or not 1 <= numero <= 60:
        raise ValueError(MSG_TEMPO_POR_PARADA)
    return int(numero)


def interpretar_viagens(valor, ids_marcados) -> dict:
    """
    `{id do motorista: n | null}` -> `{id: n}` só com os motoristas de número definido (null/vazio = automático). ValueError (em linguagem do
    operador) se o valor não for um inteiro de 1 a 10 ou se o motorista não estiver entre os marcados.
    """
    saida = {}
    for chave, bruto in (valor or {}).items():
        if bruto is None or (isinstance(bruto, str) and not bruto.strip()):
            continue
        try:
            if isinstance(bruto, bool):
                raise ValueError
            numero = float(str(bruto).replace(",", "."))
            identificador = int(str(chave).strip())
        except ValueError:
            raise ValueError(MSG_VIAGENS) from None
        if numero != int(numero) or not 1 <= numero <= VIAGENS_MAXIMAS:
            raise ValueError(MSG_VIAGENS)
        if identificador not in ids_marcados:
            raise ValueError(MSG_VIAGENS_MOTORISTA_FORA)
        saida[identificador] = int(numero)
    return saida


def formatar_tempo(minutos: int) -> str:
    return f"{minutos // 60}h {minutos % 60}m" if minutos >= 60 else f"{minutos} min"


async def executar(
    *, pedidos: list, hub: tuple, motoristas: list, capacidades: dict, turno: str, tempo_por_parada_min: int,
    rotas_hoje: Optional[dict], proibidos: Optional[dict],
    obter_matriz: Callable[[list], Awaitable[dict]], progresso: Optional[Callable[[str], None]] = None,
    limite_s: Optional[float] = None, usar_ortools: bool = True, viagens_por_motorista: Optional[dict] = None,
) -> dict:
    """
    `pedidos`: dicts com lat e lon (e o que mais a tela usa). `motoristas`: objetos com id, motorista (nome) e modal. `capacidades`:
    {tipo de veículo: teto de pedidos por viagem}. `obter_matriz(pontos)` devolve a matriz (OSRM ou linha reta, com aviso).
    Devolve {"viagens", "avisos", "origem_distancias", "metodo", "parametros"}; cada pedido de `pedidos` aparece exatamente uma vez.
    """
    avisos = []
    parametros = {"tempo_por_parada_min": tempo_por_parada_min, "turno": turno}
    if not pedidos:
        return {"viagens": [], "avisos": avisos, "origem_distancias": None, "metodo": None, "parametros": parametros}

    if progresso:
        progresso("Calculando distâncias entre as paradas...")
    pontos = [hub] + [(p["lat"], p["lon"]) for p in pedidos]
    matriz = await obter_matriz(pontos)
    if matriz.get("aviso"):
        avisos.append({"tipo": "linha_reta", "gravidade": "atencao", "mensagem": matriz["aviso"]})
    dist, dur = matriz["distancias_m"], matriz["duracoes_s"]
    setor_de = [modulo_setores.setor_do_pedido(hub[0], hub[1], p["lat"], p["lon"]) for p in pedidos]
    azimutes = [modulo_setores.azimute(hub[0], hub[1], p["lat"], p["lon"]) for p in pedidos]
    viagens_por_motorista = viagens_por_motorista or {}

    if progresso:
        progresso("Otimizando as rotas...")
    solver_motoristas = [
        modulo_solver.MotoristaSolver(id=int(m.id), nome=m.motorista, modal=m.modal, capacidade=int(capacidades.get(m.modal, CAPACIDADE_PADRAO)),
                                      viagens=viagens_por_motorista.get(int(m.id)))
        for m in motoristas
    ]
    # O solver é CPU puro e tem limite de tempo; roda numa thread para não travar as consultas de andamento.
    resultado = await asyncio.to_thread(
        modulo_solver.resolver, dist, dur, setor_de, solver_motoristas, rotas_hoje, proibidos, limite_s, usar_ortools, azimutes
    )
    avisos.extend(resultado.avisos)
    parametros.update({"limite_solver_s": resultado.limite_s, "tempo_solver_s": resultado.tempo_solver_s})

    viagens = []
    for rota in resultado.rotas:
        nos = [0] + [i + 1 for i in rota.pedidos] + [0]
        trechos_km = [round(dist[a][b] / 1000.0, 2) for a, b in zip(nos, nos[1:])]
        tempos_trechos_s = [int(round(dur[a][b])) for a, b in zip(nos, nos[1:])]  # tempo de cada trecho (a tela estima as chegadas por parada)
        deslocamento_min = round(rota.duracao_s / 60)
        paradas_min = len(rota.pedidos) * tempo_por_parada_min
        paradas = []
        for ordem, indice in enumerate(rota.pedidos, start=1):
            parada = dict(pedidos[indice])
            parada.update({"ordem": ordem, "setor": setor_de[indice], "distancia_anterior_km": trechos_km[ordem - 1]})
            paradas.append(parada)
        viagens.append({
            "motorista_id": rota.motorista_id, "viagem_num": rota.viagem_num, "modal": rota.modal, "pedidos": paradas,
            "km_total": round(rota.distancia_m / 1000.0, 2), "distancias_trechos_km": trechos_km, "tempos_trechos_s": tempos_trechos_s, "distancia_retorno_km": trechos_km[-1],
            "tempo_deslocamento_min": deslocamento_min, "tempo_paradas_min": paradas_min, "tempo_min": deslocamento_min + paradas_min,
            "setores": [s for s in modulo_setores.SETORES if s in rota.setores], "violacoes_rotacao": rota.violacoes,
            "personalizada": rota.personalizada, "teto_recomendado": rota.teto_recomendado, "viagens_solicitadas": rota.viagens_solicitadas,
        })
    return {"viagens": viagens, "avisos": avisos, "origem_distancias": matriz["origem"], "metodo": resultado.metodo, "parametros": parametros}
