"""Etapa 11: o resultado ganha `tempos_trechos_s` (aditivo) para a tela estimar as chegadas por parada; o formato antigo continua igual e nada de pedido vai para log."""
import logging

import main
from backend.tests.test_roteirizacao import (  # reaproveita os auxiliares dos testes da roteirização
    CARRO, Mot, _aleatorios, _cluster, _executar, _geocodificar_por_id, _pedidos, _pedidos_do_job, _rodar, _rodar_job,
)


def test_tempos_dos_trechos_batem_com_a_matriz_e_com_o_deslocamento():
    pedidos = _pedidos(_cluster("N", 4))
    for v in _executar(pedidos, [Mot(1, "Ana", CARRO)])["viagens"]:
        n = len(v["pedidos"])
        assert len(v["tempos_trechos_s"]) == n + 1 == len(v["distancias_trechos_km"])  # ida a cada parada + volta
        assert all(isinstance(t, int) and t >= 0 for t in v["tempos_trechos_s"])
        assert abs(sum(v["tempos_trechos_s"]) / 60 - v["tempo_deslocamento_min"]) <= 1  # só o arredondamento


def test_tempos_dos_trechos_vem_da_matriz_incluindo_a_volta():
    pedidos = _pedidos(_cluster("N", 1))

    def fake(pontos):
        return {"distancias_m": [[0, 5000], [7000, 0]], "duracoes_s": [[0, 600], [900, 0]], "origem": "osrm", "aviso": None}

    v = _executar(pedidos[:1], [Mot(1, "Ana", CARRO)], matriz_falsa=fake)["viagens"][0]
    assert v["tempos_trechos_s"] == [600, 900]


def test_o_resultado_da_api_traz_o_campo_novo_e_mantem_todo_o_formato_antigo(monkeypatch):
    frota = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0), main.MotoristaItem(id=2, motorista="Beto", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "tarde", "tempo_por_parada_min": 12, "rotas_hoje": {}, "proibidos": {}}
    r = _rodar_job(monkeypatch, _cluster("N", 3) + _cluster("S", 3), frota, contexto, {CARRO: {"capacidade": 5}})
    for chave in ("id", "motorista", "motorista_base", "motorista_id", "viagem_num", "modal", "cor", "qtd_pedidos", "km_total", "tempo_formatado", "custo_total",
                  "geometria", "paradas", "link_maps", "setores", "tempo_min", "tempo_deslocamento_min", "tempo_paradas_min", "distancias_trechos_km", "distancia_retorno_km"):
        assert all(chave in rota for rota in r["rotas"]), chave
    assert all(len(rota["tempos_trechos_s"]) == rota["qtd_pedidos"] + 1 for rota in r["rotas"])
    assert r["parametros"]["tempo_por_parada_min"] == 12 and r["turno"] == "tarde"


def test_nenhum_dado_de_pedido_em_log_ou_saida(monkeypatch, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    frota = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "manha", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {}}
    _rodar_job(monkeypatch, _cluster("N", 3), frota, contexto, {CARRO: {"capacidade": 5}})
    texto = caplog.text + capsys.readouterr().out
    for segredo in ("Rua Reservada", "Bairro Secreto", "01310100"):
        assert segredo not in texto
