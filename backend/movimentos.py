"""
Etapa 10b: mover UM pedido de uma rota para outra no resultado ainda não confirmado. O sistema reordena as paradas das duas rotas afetadas
(mesma ordenação de um veículo do solver) e recalcula trechos, km, tempos, setores, custo, geometria, viagens e kpis. É ajuste, nunca bloqueio:
qualquer rota pode receber o pedido (inclusive outra viagem do mesmo motorista); teto, rotação, km, janela e peso continuam só como aviso.

A rota que perde a última parada fica VAZIA (não some): o número dela não muda, então as trocas de motorista (Etapa 10), a chave da rota no banco
e o desfazer continuam valendo; a rota vazia não é confirmada, não conta viagem e pode receber um pedido de volta.
Privacidade: nada daqui vai para log; erros e avisos falam só de números de rota, contagens e km.
"""
import asyncio
from typing import Awaitable, Callable, Optional

import roteirizacao
import setores as modulo_setores
import solver as modulo_solver

LIMITE_ORDENACAO_S = 1.0
MAX_MOVIMENTOS_GUARDADOS = 20
MSG_PEDIDO_FORA = "Este pedido não está em nenhuma rota deste resultado."
MSG_ROTA_INEXISTENTE = "A rota escolhida não existe neste resultado."
MSG_MESMA_ROTA = "O pedido já está nesta rota."
MSG_NADA_A_DESFAZER = "Não há movimento para desfazer."
AVISO_LINHA_RETA_AJUSTE = (
    "Não foi possível consultar as distâncias pelas ruas para as rotas ajustadas; distâncias e tempos dessas rotas são estimativas em linha reta."
)


def copiar_rotas(rotas: list) -> list:
    """Cópia das rotas para guardar (original e desfazer): paradas copiadas; a geometria é compartilhada porque nunca é alterada, só trocada."""
    return [{**r, "paradas": [dict(p) for p in (r.get("paradas") or [])], "setores": list(r.get("setores") or [])} for r in rotas]


def fotografia(resultado: dict) -> dict:
    return {"rotas": copiar_rotas(resultado.get("rotas") or []), "kpis": dict(resultado.get("kpis") or {}), "avisos": list(resultado.get("avisos") or [])}


def restaurar(resultado: dict, foto: dict) -> None:
    resultado["rotas"] = copiar_rotas(foto["rotas"])
    resultado["kpis"] = dict(foto["kpis"])
    resultado["avisos"] = list(foto["avisos"])


def _rota(resultado: dict, numero) -> Optional[dict]:
    try:
        numero = int(numero)
    except (TypeError, ValueError):
        return None
    return next((r for r in resultado.get("rotas") or [] if r.get("id") == numero), None)


def localizar(resultado: dict, pedido_id) -> Optional[tuple]:
    """(rota, posição) da parada com este id, ou None."""
    alvo = str(pedido_id if pedido_id is not None else "").strip()
    if not alvo:
        return None
    for rota in resultado.get("rotas") or []:
        for posicao, parada in enumerate(rota.get("paradas") or []):
            if str(parada.get("id")).strip() == alvo:
                return rota, posicao
    return None


def _custos(rota: dict) -> None:
    valor = float(rota.get("valor_rota") or 0)
    qtd = rota["qtd_pedidos"]
    rota["custo_total"] = round(valor, 2) if qtd > 0 and valor > 0 else 0.0
    rota["custo_por_pedido"] = round(valor / qtd, 2) if qtd > 0 and valor > 0 else 0.0


def _link_maps(hub: tuple, paradas: list) -> str:
    if not paradas:
        return ""
    meio = "/".join(f"{p['lat']},{p['lon']}" for p in paradas)
    return f"https://www.google.com/maps/dir/{hub[0]},{hub[1]}/{meio}/{hub[0]},{hub[1]}"


def renumerar_viagens(rotas: list, original: Optional[list] = None) -> None:
    """Viagens de cada motorista contadas só nas rotas com pedidos, na ordem em que o sistema as sugeriu; título "Ana • Viagem 2" só com mais de uma."""
    sugerida = {r["id"]: r.get("viagem_num") or 0 for r in (original if original is not None else rotas)}
    com_pedidos = {}
    for r in rotas:
        if r.get("paradas"):
            com_pedidos.setdefault(r.get("motorista_id"), []).append(r)
    for lista in com_pedidos.values():
        lista.sort(key=lambda r: (sugerida.get(r["id"], 0), r["id"]))
        for numero, r in enumerate(lista, start=1):
            base = r.get("motorista_base") or r.get("motorista")
            r["viagem_num"] = numero
            r["motorista"] = f"{base} • Viagem {numero}" if len(lista) > 1 else base
            for p in r["paradas"]:
                p["viagem_alocada"] = numero
    for r in rotas:
        if not r.get("paradas"):
            r["motorista"] = r.get("motorista_base") or r.get("motorista")


def kpis_do_resultado(rotas: list, total_pedidos: int, total_sem_geocodificacao: int) -> dict:
    """Os kpis do resultado (mesmas chaves de sempre), contando só as rotas com pedidos."""
    usadas = [r for r in rotas if r.get("qtd_pedidos")]
    valores_por_tipo = {}
    for rota in usadas:
        chave = (rota["modal"], rota["valor_rota"], rota["origem_valor"])
        item = valores_por_tipo.setdefault(chave, {"tipo": rota["modal"], "valor": rota["valor_rota"], "origem": rota["origem_valor"], "rotas": 0})
        item["rotas"] += 1
    custo = sum(r.get("custo_total") or 0 for r in usadas)
    motoristas = len({r["motorista_id"] for r in usadas})
    return {
        "total_pedidos": total_pedidos, "total_veiculos": motoristas, "total_motoristas": motoristas,
        "total_rotas_viagens": len(usadas), "km_total": round(sum(r.get("km_total") or 0 for r in usadas), 2),
        "custo_total": round(custo, 2), "custo_medio_pedido": round(custo / max(total_pedidos, 1), 2),
        "valores_por_tipo": list(valores_por_tipo.values()),
        "total_pedidos_sem_geocodificacao": total_sem_geocodificacao,
        "tempo_total_min": sum(r.get("tempo_min") or 0 for r in usadas),
    }


def marcar_movidas(rotas: list, original: list) -> None:
    ids_originais = {r["id"]: {str(p.get("id")) for p in r.get("paradas") or []} for r in original}
    for r in rotas:
        r["movida"] = {str(p.get("id")) for p in r.get("paradas") or []} != ids_originais.get(r["id"], set())


async def mover(
    resultado: dict, pedido_id, rota_destino, *, original: list,
    obter_matriz: Callable[[list], Awaitable[dict]], obter_geometria: Callable[[list], Awaitable[list]],
    proibidos: Optional[dict] = None, usar_ortools: bool = True,
) -> dict:
    """
    Move o pedido para `rota_destino`, alterando `resultado` no lugar. ValueError (em linguagem do operador) se o pedido não estiver em nenhuma rota,
    se a rota não existir ou se for a mesma. `original`: as rotas como o sistema sugeriu (para a marca `movida`). `obter_matriz(pontos)` e
    `obter_geometria(pontos)` vêm do servidor. Devolve o resumo do movimento (só números de rota, quantidades e km).
    """
    achado = localizar(resultado, pedido_id)
    if achado is None:
        raise ValueError(MSG_PEDIDO_FORA)
    destino = _rota(resultado, rota_destino)
    if destino is None:
        raise ValueError(MSG_ROTA_INEXISTENTE)
    origem, posicao = achado
    if origem is destino:
        raise ValueError(MSG_MESMA_ROTA)
    antes = {r["id"]: {"qtd_pedidos": r.get("qtd_pedidos") or 0, "km_total": r.get("km_total") or 0} for r in (origem, destino)}

    # Trabalha em cópias: se algo falhar no meio, o resultado guardado fica como estava.
    nova_origem = {**origem, "paradas": [dict(p) for p in origem.get("paradas") or []]}
    novo_destino = {**destino, "paradas": [dict(p) for p in destino.get("paradas") or []]}
    parada = nova_origem["paradas"].pop(posicao)
    parada.update({"modal_alocado": destino.get("modal"), "motorista_alocado": destino.get("motorista_base") or destino.get("motorista")})
    novo_destino["paradas"].append(parada)

    origem_hub = resultado.get("origem") or {}
    hub = (float(origem_hub["lat"]), float(origem_hub["lon"]))
    tempo_por_parada = (resultado.get("parametros") or {}).get("tempo_por_parada_min") or roteirizacao.TEMPO_POR_PARADA_PADRAO_MIN
    todas = nova_origem["paradas"] + novo_destino["paradas"]
    matriz = await obter_matriz([hub] + [(p["lat"], p["lon"]) for p in todas])
    dist, dur = matriz["distancias_m"], matriz["duracoes_s"]

    inicio = 0
    for rota in (nova_origem, novo_destino):
        pedidos = rota["paradas"]
        nos = [0] + [inicio + i + 1 for i in range(len(pedidos))]
        sub_dist = [[dist[a][b] for b in nos] for a in nos]
        sub_dur = [[dur[a][b] for b in nos] for a in nos]
        inicio += len(pedidos)
        ordem = await asyncio.to_thread(modulo_solver.ordenar_uma_rota, sub_dist, list(range(len(pedidos))), LIMITE_ORDENACAO_S, usar_ortools) if pedidos else []
        setor_de = [modulo_setores.setor_do_pedido(hub[0], hub[1], p["lat"], p["lon"]) for p in pedidos]
        metricas = roteirizacao.metricas_da_rota(sub_dist, sub_dur, ordem, pedidos, tempo_por_parada, setor_de)
        rota.update(metricas)
        rota["qtd_pedidos"] = len(rota["paradas"])
        rota["tempo_formatado"] = roteirizacao.formatar_tempo(rota["tempo_min"])
        rota["origem_distancias"] = matriz.get("origem")
        proibidos_do_motorista = (proibidos or {}).get(rota.get("motorista_id")) or {}
        rota["violacoes_rotacao"] = [s for s in rota["setores"] if s in proibidos_do_motorista]
        _custos(rota)
        rota["link_maps"] = _link_maps(hub, rota["paradas"])
        rota["geometria"] = await obter_geometria([hub] + [(p["lat"], p["lon"]) for p in rota["paradas"]] + [hub]) if rota["paradas"] else []

    # Tudo calculado: aplica de uma vez.
    rotas = [nova_origem if r is origem else novo_destino if r is destino else r for r in resultado["rotas"]]
    renumerar_viagens(rotas, original)
    marcar_movidas(rotas, original)
    resultado["rotas"] = rotas
    kpis = resultado.get("kpis") or {}
    resultado["kpis"] = kpis_do_resultado(rotas, kpis.get("total_pedidos", sum(r["qtd_pedidos"] for r in rotas)), kpis.get("total_pedidos_sem_geocodificacao", 0))
    if matriz.get("origem") == "linha_reta":
        avisos = resultado.setdefault("avisos", [])
        if not any(a.get("tipo") == "linha_reta_ajuste" for a in avisos):
            avisos.append({"tipo": "linha_reta_ajuste", "gravidade": "atencao", "mensagem": AVISO_LINHA_RETA_AJUSTE})
    depois = {r["id"]: {"qtd_pedidos": r["qtd_pedidos"], "km_total": r["km_total"]} for r in (nova_origem, novo_destino)}
    return {"rota_origem": origem["id"], "rota_destino": destino["id"], "antes": antes, "depois": depois}
