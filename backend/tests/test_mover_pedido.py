"""Etapa 10b: mover um pedido entre rotas antes de confirmar (ordem reotimizada, métricas recalculadas, versão, desfazer, confirmar a nova divisão)."""
import asyncio
import logging
import math

import pytest
from fastapi.testclient import TestClient

import main
import matriz
import movimentos
import setores
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite

HUB = (-23.5505, -46.6333)
CARRO = "Carro de passeio"
MSG_INDISPONIVEL = "Este resultado não está mais disponível. Gere as rotas de novo."


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


def _ponto(setor, km):
    graus = setores.SETORES.index(setor) * 45.0
    dlat = km / 111.195 * math.cos(math.radians(graus))
    dlon = km / (111.195 * math.cos(math.radians(HUB[0]))) * math.sin(math.radians(graus))
    return (HUB[0] + dlat, HUB[1] + dlon)


# 3 pedidos perto da loja (norte) e 3 longe (sul)
PONTOS = [_ponto("N", 1.0), _ponto("N", 1.5), _ponto("NE", 1.2), _ponto("S", 8.0), _ponto("S", 9.0), _ponto("SO", 8.5)]


@pytest.fixture
def api(monkeypatch):
    banco = criar_banco_sqlite()
    banco.ana = banco.inserir_motorista("Ana", CARRO)
    banco.beto = banco.inserir_motorista("Beto", CARRO)

    async def get_pool():
        return FakePool(banco)

    async def osrm_falso(client, pontos):
        return 1.0, 1, [[a, b] for a, b in pontos]

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    guardados = dict(main.JOBS)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()
    main.JOBS.clear()
    main.JOBS.update(guardados)


def _resultado(monkeypatch, banco, viagens=None, motoristas=None):
    """Resultado realista de uma roteirização (job concluído em JOBS) com os 6 pedidos e os motoristas dados."""
    pedidos = [{"id": f"PED-{i + 1}", "Endereco": f"Rua Sigilosa {i + 1}", "Numero": str(i + 1), "Bairro": "Bairro Secreto", "CEP": "01310100",
                "Cidade": "São Paulo", "UF": "SP", "Volume": 1, "Cliente": "Fulano Reservado"} for i in range(len(PONTOS))]
    coordenadas = {p["id"]: pt for p, pt in zip(pedidos, PONTOS)}

    async def geocode_falso(client, *a, **k):
        return HUB[0], HUB[1], "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO"

    async def lote_falso(lista):
        return {main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p.get("Bairro", ""), cep=p.get("CEP", ""), cidade=p.get("Cidade", ""), uf=p.get("UF", "")):
                (*coordenadas[p["id"]], "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO") for p in lista}

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    motoristas = motoristas or [(banco.ana, "Ana"), (banco.beto, "Beto")]
    frota_usar = [main.MotoristaItem(id=i, motorista=n, modal=CARRO, custo_rota=130.0) for i, n in motoristas]
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos, turno="tarde")
    job_id = main._novo_job()
    asyncio.run(main._processar_otimizacao(job_id, req, frota_usar, {}, None,
                                           {"turno": "tarde", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {}, "viagens": viagens or {}}))
    assert main.JOBS[job_id]["status"] == "concluido", main.JOBS[job_id]["erro"]
    return job_id, main.JOBS[job_id]["resultado"]


def _ids(rota):
    return [p["id"] for p in rota["paradas"]]


def _rota_de(resultado, pedido_id):
    return next(r for r in resultado["rotas"] if pedido_id in _ids(r))


def _mover(cliente, job_id, pedido_id, destino, versao):
    return cliente.post(f"/api/otimizar/{job_id}/mover", json={"pedido_id": pedido_id, "rota_destino": destino, "versao": versao})


def _conferir_rota(rota, resultado):
    """Métricas da rota coerentes com a matriz de linha reta e a ordem das paradas."""
    n = len(rota["paradas"])
    assert rota["qtd_pedidos"] == n
    assert [p["ordem"] for p in rota["paradas"]] == list(range(1, n + 1))
    if n == 0:
        assert rota["km_total"] == 0 and rota["geometria"] == [] and rota["tempo_min"] == 0
        return
    pontos = [HUB] + [(p["lat"], p["lon"]) for p in rota["paradas"]] + [HUB]
    dist, dur = matriz.matriz_linha_reta(pontos)
    trechos = [round(dist[i][i + 1] / 1000, 2) for i in range(n + 1)]
    assert rota["distancias_trechos_km"] == trechos and len(rota["tempos_trechos_s"]) == n + 1
    assert rota["km_total"] == pytest.approx(sum(dist[i][i + 1] for i in range(n + 1)) / 1000, abs=0.02)
    assert rota["tempo_paradas_min"] == n * 10 and rota["tempo_min"] == rota["tempo_deslocamento_min"] + rota["tempo_paradas_min"]
    esperados = {setores.setor_do_pedido(*HUB, p["lat"], p["lon"]) for p in rota["paradas"]}
    assert set(rota["setores"]) == esperados
    assert rota["geometria"] == [list(p) for p in pontos]
    assert rota["custo_total"] == 130.0 and rota["custo_por_pedido"] == round(130.0 / n, 2)
    assert rota["link_maps"].count("/") >= n + 2


# ---------------------------------------------------------------------------------------------------------------------------
# Mover entre motoristas e entre viagens
# ---------------------------------------------------------------------------------------------------------------------------
def test_mover_entre_motoristas_reotimiza_e_recalcula_tudo(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    origem = _rota_de(resultado, "PED-4")
    destino = next(r for r in resultado["rotas"] if r is not origem)
    km_total_antes = resultado["kpis"]["km_total"]

    r = _mover(cliente, job_id, "PED-4", destino["id"], 0)
    assert r.status_code == 200, r.text
    corpo = r.json()
    novo = corpo["resultado"]
    assert novo["versao"] == 1 and corpo["pode_desfazer"] is True
    nova_origem = next(x for x in novo["rotas"] if x["id"] == origem["id"])
    novo_destino = next(x for x in novo["rotas"] if x["id"] == destino["id"])
    assert "PED-4" in _ids(novo_destino) and "PED-4" not in _ids(nova_origem)
    assert nova_origem["movida"] and novo_destino["movida"]
    for rota in (nova_origem, novo_destino):
        _conferir_rota(rota, novo)
    parada = next(p for p in novo_destino["paradas"] if p["id"] == "PED-4")
    assert parada["motorista_alocado"] == novo_destino["motorista_base"]
    assert corpo["movimento"]["rota_origem"] == origem["id"] and corpo["movimento"]["rota_destino"] == destino["id"]
    assert corpo["movimento"]["depois"][str(destino["id"])]["qtd_pedidos"] == destino["qtd_pedidos"] + 1
    assert novo["kpis"]["total_pedidos"] == 6 and novo["kpis"]["km_total"] != km_total_antes
    assert novo["kpis"]["km_total"] == pytest.approx(sum(x["km_total"] for x in novo["rotas"]), abs=0.01)
    # o status devolve a mesma divisão (é ela que o confirmar grava)
    status = cliente.get(f"/api/otimizar/status/{job_id}").json()
    assert status["resultado"]["versao"] == 1 and [_ids(x) for x in status["resultado"]["rotas"]] == [_ids(x) for x in novo["rotas"]]


def test_ordem_das_paradas_e_reotimizada(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    perto = _rota_de(resultado, "PED-1")
    longe_id = next(i for i in ("PED-4", "PED-5", "PED-6") if i not in _ids(perto))
    corpo = _mover(cliente, job_id, longe_id, perto["id"], 0).json()
    rota = next(x for x in corpo["resultado"]["rotas"] if x["id"] == perto["id"])
    # nenhuma ordem alternativa (troca de duas paradas) encurta a rota
    pontos = [HUB] + [(p["lat"], p["lon"]) for p in rota["paradas"]]
    dist, _ = matriz.matriz_linha_reta(pontos)

    def total(ordem):
        nos = [0] + ordem + [0]
        return sum(dist[a][b] for a, b in zip(nos, nos[1:]))

    atual = list(range(1, len(pontos)))
    for i in range(len(atual)):
        for j in range(i + 1, len(atual)):
            trocada = list(atual)
            trocada[i], trocada[j] = trocada[j], trocada[i]
            assert total(atual) <= total(trocada) + 1


def test_mover_entre_viagens_do_mesmo_motorista(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco, viagens={banco.ana: 2}, motoristas=[(banco.ana, "Ana")])
    assert len(resultado["rotas"]) == 2 and {r["motorista_id"] for r in resultado["rotas"]} == {banco.ana}
    v1, v2 = sorted(resultado["rotas"], key=lambda r: r["viagem_num"])
    pedido = _ids(v2)[0]
    corpo = _mover(cliente, job_id, pedido, v1["id"], 0).json()
    rotas = {r["id"]: r for r in corpo["resultado"]["rotas"]}
    assert pedido in _ids(rotas[v1["id"]]) and len(rotas[v1["id"]]["paradas"]) == len(v1["paradas"]) + 1
    assert rotas[v1["id"]]["motorista"] == "Ana • Viagem 1" and rotas[v2["id"]]["motorista"] == "Ana • Viagem 2"
    for r in rotas.values():
        _conferir_rota(r, corpo["resultado"])


def test_mover_a_ultima_parada_deixa_a_rota_vazia_renumera_e_o_confirmar_ignora(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco, viagens={banco.ana: 2}, motoristas=[(banco.ana, "Ana")])
    v1, v2 = sorted(resultado["rotas"], key=lambda r: r["viagem_num"])
    versao = 0
    for pedido in list(_ids(v1)):  # esvazia a 1ª viagem
        r = _mover(cliente, job_id, pedido, v2["id"], versao)
        assert r.status_code == 200, r.text
        versao = r.json()["resultado"]["versao"]
    novo = r.json()["resultado"]
    rotas = {x["id"]: x for x in novo["rotas"]}
    vazia, cheia = rotas[v1["id"]], rotas[v2["id"]]
    assert len(novo["rotas"]) == 2  # a rota não some: o número dela não muda
    assert vazia["paradas"] == [] and vazia["qtd_pedidos"] == 0 and vazia["custo_total"] == 0 and vazia["motorista"] == "Ana"
    _conferir_rota(vazia, novo)
    assert cheia["qtd_pedidos"] == 6 and cheia["viagem_num"] == 1 and cheia["motorista"] == "Ana"
    assert all(p["viagem_alocada"] == 1 for p in cheia["paradas"])
    assert novo["kpis"]["total_rotas_viagens"] == 1 and novo["kpis"]["total_pedidos"] == 6
    # a rota vazia continua como destino possível
    assert _mover(cliente, job_id, "PED-1", vazia["id"], versao).status_code == 200
    _mover(cliente, job_id, "PED-1", cheia["id"], versao + 1)
    # confirmar grava só a rota com pedidos
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id})
    assert r.status_code == 200, r.text
    linhas = banco.db.execute("SELECT numero_rota, qtd_pedidos FROM rotas_realizadas WHERE execucao_id = ?", (job_id,)).fetchall()
    assert [tuple(l) for l in linhas] == [(cheia["id"], 6)]


# ---------------------------------------------------------------------------------------------------------------------------
# Erros: pedido, rota, mesma rota, expirado, confirmado, versão
# ---------------------------------------------------------------------------------------------------------------------------
def test_pedido_ou_rota_inexistente_e_mesma_rota_sao_422_em_linguagem_do_operador(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    rota = _rota_de(resultado, "PED-1")
    r = _mover(cliente, job_id, "NAO-EXISTE", rota["id"], 0)
    assert r.status_code == 422 and r.json()["detail"] == movimentos.MSG_PEDIDO_FORA
    r = _mover(cliente, job_id, "PED-1", 99, 0)
    assert r.status_code == 422 and r.json()["detail"] == movimentos.MSG_ROTA_INEXISTENTE
    r = _mover(cliente, job_id, "PED-1", "abc", 0)
    assert r.status_code == 422 and r.json()["detail"] == movimentos.MSG_ROTA_INEXISTENTE
    r = _mover(cliente, job_id, "PED-1", rota["id"], 0)
    assert r.status_code == 422 and r.json()["detail"] == movimentos.MSG_MESMA_ROTA
    assert main.JOBS[job_id]["resultado"]["versao"] == 0  # nada mudou


def test_resultado_expirado_ou_inexistente_responde_a_mensagem_de_sempre(api, monkeypatch):
    cliente, banco = api
    job_id, _ = _resultado(monkeypatch, banco)
    main.JOBS[job_id]["terminado_em"] = 0.0
    main._limpar_jobs()
    for caminho, corpo in ((f"/api/otimizar/{job_id}/mover", {"pedido_id": "PED-1", "rota_destino": 1}),
                           (f"/api/otimizar/{job_id}/desfazer-movimento", {}), (f"/api/otimizar/{job_id}/voltar-ao-original", {}),
                           ("/api/otimizar/nao-existe/mover", {"pedido_id": "PED-1", "rota_destino": 1})):
        r = cliente.post(caminho, json=corpo)
        assert r.status_code == 404 and r.json()["detail"] == MSG_INDISPONIVEL


def test_resultado_ja_confirmado_nao_move_e_depois_de_desfazer_volta_a_mover(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id}).status_code == 200
    r = _mover(cliente, job_id, "PED-1", destino["id"], 0)
    assert r.status_code == 409 and r.json()["detail"] == "Desfaça a confirmação para mover pedidos."
    assert cliente.post(f"/api/otimizar/{job_id}/voltar-ao-original", json={}).status_code == 409
    assert cliente.post(f"/api/rotas-realizadas/{job_id}/desfazer").status_code == 200
    assert _mover(cliente, job_id, "PED-1", destino["id"], 0).status_code == 200


def test_versao_diferente_e_409_e_nada_muda(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    assert _mover(cliente, job_id, "PED-1", destino["id"], 0).status_code == 200
    antes = [_ids(r) for r in main.JOBS[job_id]["resultado"]["rotas"]]
    r = _mover(cliente, job_id, "PED-2", destino["id"], 0)  # outra aba ainda na versão 0
    assert r.status_code == 409 and "outra aba" in r.json()["detail"]
    assert [_ids(r) for r in main.JOBS[job_id]["resultado"]["rotas"]] == antes
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id, "versao": 0})
    assert r.status_code == 409
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 0
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id, "versao": 1}).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------------
# Linha reta, desfazer, voltar ao original
# ---------------------------------------------------------------------------------------------------------------------------
def test_reserva_em_linha_reta_quando_as_distancias_pelas_ruas_falham(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)

    async def matriz_falhou(cliente_http, pontos):
        d, t = matriz.matriz_linha_reta(pontos)
        return {"distancias_m": d, "duracoes_s": t, "origem": "linha_reta", "aviso": matriz.AVISO_LINHA_RETA}

    monkeypatch.setattr(main, "obter_matriz", matriz_falhou)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    corpo = _mover(cliente, job_id, "PED-1", destino["id"], 0).json()
    afetadas = [r for r in corpo["resultado"]["rotas"] if r["movida"]]
    assert afetadas and all(r["origem_distancias"] == "linha_reta" for r in afetadas)
    avisos = [a for a in corpo["resultado"]["avisos"] if a["tipo"] == "linha_reta_ajuste"]
    assert len(avisos) == 1 and "OSRM" not in avisos[0]["mensagem"]
    _mover(cliente, job_id, "PED-2", destino["id"], 1)
    assert len([a for a in main.JOBS[job_id]["resultado"]["avisos"] if a["tipo"] == "linha_reta_ajuste"]) == 1


def test_desfazer_ultimo_e_voltar_ao_original(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    original = [_ids(r) for r in resultado["rotas"]]
    kpis_originais = dict(resultado["kpis"])
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    _mover(cliente, job_id, "PED-1", destino["id"], 0)
    depois_do_primeiro = [_ids(r) for r in main.JOBS[job_id]["resultado"]["rotas"]]
    _mover(cliente, job_id, "PED-2", destino["id"], 1)

    r = cliente.post(f"/api/otimizar/{job_id}/desfazer-movimento", json={"versao": 2})
    assert r.status_code == 200 and r.json()["resultado"]["versao"] == 3
    assert [_ids(x) for x in r.json()["resultado"]["rotas"]] == depois_do_primeiro

    r = cliente.post(f"/api/otimizar/{job_id}/voltar-ao-original", json={"versao": 3})
    assert r.status_code == 200
    novo = r.json()["resultado"]
    assert [_ids(x) for x in novo["rotas"]] == original and novo["versao"] == 4 and r.json()["pode_desfazer"] is False
    assert novo["kpis"] == kpis_originais and not any(x.get("movida") for x in novo["rotas"])
    r = cliente.post(f"/api/otimizar/{job_id}/desfazer-movimento", json={"versao": 4})
    assert r.status_code == 422 and r.json()["detail"] == movimentos.MSG_NADA_A_DESFAZER
    # voltar ao original sem nenhum movimento não quebra
    assert cliente.post(f"/api/otimizar/{job_id}/voltar-ao-original", json={}).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------------
# Confirmar depois de mover, re-confirmar depois de desfazer
# ---------------------------------------------------------------------------------------------------------------------------
def _pedidos_gravados(banco, job_id):
    linhas = banco.db.execute(
        "SELECT r.numero_rota, p.ordem, p.pedido_id FROM rotas_pedidos p JOIN rotas_realizadas r ON r.id = p.rota_id "
        "WHERE r.execucao_id = ? AND r.status = 'confirmada' ORDER BY r.numero_rota, p.ordem", (job_id,)).fetchall()
    divisao = {}
    for numero, _, pedido in linhas:
        divisao.setdefault(numero, []).append(pedido)
    return divisao


def test_confirmar_depois_de_mover_grava_a_nova_divisao(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    novo = _mover(cliente, job_id, "PED-1", destino["id"], 0).json()["resultado"]
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id, "versao": 1})
    assert r.status_code == 200, r.text
    assert _pedidos_gravados(banco, job_id) == {x["id"]: _ids(x) for x in novo["rotas"] if x["paradas"]}
    linhas = banco.db.execute("SELECT numero_rota, qtd_pedidos, distancia_km, setores FROM rotas_realizadas WHERE execucao_id = ?", (job_id,)).fetchall()
    for numero, qtd, km, texto_setores in linhas:
        rota = next(x for x in novo["rotas"] if x["id"] == numero)
        assert qtd == rota["qtd_pedidos"] and km == pytest.approx(rota["km_total"]) and texto_setores == setores.texto_dos_setores(rota["setores"])


def test_desfazer_mover_e_confirmar_de_novo_regrava_os_pedidos(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id}).status_code == 200
    assert cliente.post(f"/api/rotas-realizadas/{job_id}/desfazer").status_code == 200
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    novo = _mover(cliente, job_id, "PED-1", destino["id"], 0).json()["resultado"]
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id, "versao": 1})
    assert r.status_code == 200 and r.json()["ja_confirmada"] is False
    assert _pedidos_gravados(banco, job_id) == {x["id"]: _ids(x) for x in novo["rotas"] if x["paradas"]}


def test_confirmar_duas_vezes_continua_sem_duplicar_os_pedidos(api, monkeypatch):
    cliente, banco = api
    job_id, _ = _resultado(monkeypatch, banco)
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id}).status_code == 200
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": job_id})
    assert r.json()["ja_confirmada"] is True
    assert banco.db.execute("SELECT count(*) FROM rotas_pedidos").fetchone()[0] == 6


# ---------------------------------------------------------------------------------------------------------------------------
# Privacidade e compatibilidade
# ---------------------------------------------------------------------------------------------------------------------------
def test_logs_e_erros_sem_id_endereco_nem_cliente(api, monkeypatch, caplog, capsys):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    with caplog.at_level(logging.DEBUG):
        _mover(cliente, job_id, "PED-1", destino["id"], 0)
        erro = _mover(cliente, job_id, "PED-XYZ", destino["id"], 1).json()["detail"]

        async def explode(*a, **k):
            raise RuntimeError("Rua Sigilosa 2 PED-2 Fulano Reservado")

        monkeypatch.setattr(main, "obter_matriz", explode)
        r = _mover(cliente, job_id, "PED-2", destino["id"], 1)
    assert r.status_code == 500 and "Sigilosa" not in r.json()["detail"]
    assert main.JOBS[job_id]["resultado"]["versao"] == 1 and "PED-2" not in _ids(next(x for x in main.JOBS[job_id]["resultado"]["rotas"] if x["id"] == destino["id"]))
    texto = caplog.text + capsys.readouterr().out + erro
    for segredo in ("PED-1", "PED-2", "PED-XYZ", "Sigilosa", "Fulano", "Secreto"):
        assert segredo not in texto
    assert "RuntimeError" in texto


def test_formato_das_rotas_continua_compativel(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    chaves_antigas = {"id", "motorista", "motorista_base", "motorista_id", "viagem_num", "modal", "cor", "qtd_pedidos", "km_total", "tempo_formatado",
                      "tempo_min", "tempo_deslocamento_min", "tempo_paradas_min", "setores", "distancias_trechos_km", "tempos_trechos_s", "distancia_retorno_km",
                      "violacoes_rotacao", "rota_personalizada", "teto_recomendado", "viagens_solicitadas", "custo_total", "custo_por_pedido", "valor_rota",
                      "origem_valor", "geometria", "paradas", "link_maps"}
    assert resultado["versao"] == 0 and all(chaves_antigas <= set(r) for r in resultado["rotas"])
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    novo = _mover(cliente, job_id, "PED-1", destino["id"], 0).json()["resultado"]
    assert all(chaves_antigas <= set(r) for r in novo["rotas"])
    assert set(resultado["kpis"]) == set(novo["kpis"])
    assert {"execucao_id", "loja_hub", "origem", "rotas", "kpis", "turno", "avisos", "parametros"} <= set(novo)
    parada_chaves = {"id", "Endereco", "Numero", "Bairro", "Volume", "lat", "lon", "ordem", "setor", "distancia_anterior_km"}
    assert all(parada_chaves <= set(p) for r in novo["rotas"] for p in r["paradas"])


def test_rotacao_e_recalculada_nas_rotas_movidas(api, monkeypatch):
    cliente, banco = api
    job_id, resultado = _resultado(monkeypatch, banco)
    destino = next(r for r in resultado["rotas"] if "PED-1" not in _ids(r))
    # o motorista do destino já fez o setor N de manhã (rota confirmada de outra roteirização)
    banco.db.execute("INSERT INTO rotas_realizadas (execucao_id, numero_rota, motorista_id, data, turno, qtd_pedidos, distancia_km, status, criado_por, setores) "
                     "VALUES ('outra', 1, ?, ?, 'manha', 1, 1, 'confirmada', 'x', 'N')", (destino["motorista_id"], main.rotas_realizadas.hoje_em_brasilia().isoformat()))
    novo = _mover(cliente, job_id, "PED-1", destino["id"], 0).json()["resultado"]
    rota = next(x for x in novo["rotas"] if x["id"] == destino["id"])
    assert "N" in rota["violacoes_rotacao"]


def test_kpis_do_resultado_ignoram_rotas_vazias():
    rotas = [{"modal": CARRO, "valor_rota": 130.0, "origem_valor": "padrão", "motorista_id": 1, "qtd_pedidos": 2, "km_total": 3.0, "custo_total": 130.0, "tempo_min": 30},
             {"modal": CARRO, "valor_rota": 130.0, "origem_valor": "padrão", "motorista_id": 2, "qtd_pedidos": 0, "km_total": 0.0, "custo_total": 0.0, "tempo_min": 0}]
    kpis = movimentos.kpis_do_resultado(rotas, 2, 1)
    assert kpis["total_rotas_viagens"] == 1 and kpis["total_motoristas"] == 1 and kpis["valores_por_tipo"][0]["rotas"] == 1
    assert kpis["total_pedidos_sem_geocodificacao"] == 1 and kpis["custo_medio_pedido"] == 65.0
