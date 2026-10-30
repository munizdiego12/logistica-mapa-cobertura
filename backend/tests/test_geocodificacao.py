"""Geocodificação com conferência: candidato coerente com cidade, UF e CEP; aproximado nunca vira VALIDO; cache versionado.

Tudo sem rede: Nominatim, BrasilAPI e ViaCEP são respostas montadas aqui, e o banco é um dicionário.
Endereços, CEPs e coordenadas são FICTÍCIOS (o repositório é público).
"""
import asyncio
import logging

import httpx
import pytest

import geocodificacao
import main
import movimentos

TRAVA_ORIGINAL = main._respeitar_rate_limit_nominatim

# Centro fictício do prefixo 99999 (dispersão de 0,8 km -> limite de 1,5 km).
CENTRO_CEP = (-10.0, -50.0)
CEP = "99999-000"
CIDADE = "Cidade Exemplo"
UF = "SP"
RUA = "Rua Exemplo Ficticia"
NUMERO = "123"
BAIRRO = "Bairro Ficticio"


def _candidato(lat, lon, cidade=CIDADE, uf=UF, bairro=None, numero=None):
    endereco = {"city": cidade, "ISO3166-2-lvl4": f"BR-{uf}"}
    if bairro:
        endereco["suburb"] = bairro
    if numero:
        endereco["house_number"] = numero
    return {"lat": str(lat), "lon": str(lon), "address": endereco}


# 6 km ao norte do centro do CEP (bairro errado) e 0,4 km (o certo).
LONGE = _candidato(-10.0 + 0.054, -50.0)
PERTO = _candidato(-10.0 + 0.0036, -50.0)


class _Resposta:
    def __init__(self, dados, status_code=200):
        self.dados, self.status_code = dados, status_code

    def json(self):
        return self.dados


class ClienteFalso:
    """Devolve, em ordem, as listas de candidatos do Nominatim; a BrasilAPI e o ViaCEP devolvem o que for passado."""

    def __init__(self, nominatim=(), brasilapi=None, viacep=None, relogio=None):
        self.nominatim = list(nominatim)
        self.brasilapi, self.viacep, self.relogio = brasilapi, viacep, relogio
        self.chamadas = []
        self.instantes_nominatim = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.chamadas.append((url, dict(params or {})))
        if "nominatim" in url:
            if self.relogio is not None:
                self.instantes_nominatim.append(self.relogio["t"])
            resposta = self.nominatim.pop(0) if self.nominatim else []
            if isinstance(resposta, Exception):
                raise resposta
            return _Resposta(resposta)
        if "brasilapi" in url:
            return _Resposta(self.brasilapi) if self.brasilapi else _Resposta({}, 404)
        if "viacep" in url:
            return _Resposta(self.viacep or {"erro": True})
        raise AssertionError("URL inesperada")

    def quantas(self, servico):
        return sum(1 for url, _ in self.chamadas if servico in url)


@pytest.fixture
def banco(monkeypatch):
    """Banco falso: cache de geocodificação e prefixos de CEP. Limpa os caches em memória do processo."""
    estado = {"cache": {}, "gravados": [], "lidos": [], "prefixos": {"99999": {"lat": CENTRO_CEP[0], "lon": CENTRO_CEP[1], "dispersao_km": 0.8}}}

    async def cache_get(chave):
        estado["lidos"].append(chave)
        return estado["cache"].get(chave)

    async def cache_set(chave, resultado):
        estado["gravados"].append((chave, resultado))
        estado["cache"][chave] = resultado

    async def consultar_prefixo_cep(prefixo):
        return estado["prefixos"].get(prefixo)

    async def sem_espera():
        return None

    monkeypatch.setattr(main.database, "cache_get", cache_get)
    monkeypatch.setattr(main.database, "cache_set", cache_set)
    monkeypatch.setattr(main.database, "consultar_prefixo_cep", consultar_prefixo_cep)
    monkeypatch.setattr(main, "_respeitar_rate_limit_nominatim", sem_espera)
    main._GEOCODE_CACHE_MEMORIA.clear()
    main._PREFIXOS_MEMORIA.clear()
    main._REGIOES_MEMORIA.clear()
    yield estado
    main._GEOCODE_CACHE_MEMORIA.clear()
    main._PREFIXOS_MEMORIA.clear()
    main._REGIOES_MEMORIA.clear()


def _geocodificar(cliente, rua=RUA, numero=NUMERO, bairro=BAIRRO, cep=CEP, cidade=CIDADE, uf=UF):
    return asyncio.run(main.geocode_async(cliente, rua, numero, bairro, cep, cidade, uf))


# ---------------------------------------------------------------- funções puras
def test_limite_usa_a_dispersao_com_minimo_e_maximo():
    assert geocodificacao.limite_km(0.2) == 1.5
    assert geocodificacao.limite_km(None) == 1.5
    assert geocodificacao.limite_km(4.0) == 5.0
    assert geocodificacao.limite_km(40) == 15.0


def test_escolhe_o_mais_proximo_e_nao_o_primeiro():
    medio = _candidato(-10.0 + 0.009, -50.0)  # 1 km
    ponto = geocodificacao.escolher_por_referencia([LONGE, medio, PERTO], CIDADE, UF, CENTRO_CEP, 1.5)
    assert ponto == geocodificacao.coordenada(PERTO)


def test_candidato_de_outra_cidade_ou_uf_e_descartado_mesmo_perto():
    outra_cidade = _candidato(-10.001, -50.0, cidade="Outra Cidade")
    outra_uf = _candidato(-10.001, -50.0, uf="RJ")
    assert geocodificacao.escolher_por_referencia([outra_cidade, outra_uf], CIDADE, UF, CENTRO_CEP, 1.5) is None
    # Sem diferença de maiúsculas e acentos.
    mesma = _candidato(-10.001, -50.0, cidade="CIDADE EXEMPLO")
    assert geocodificacao.escolher_por_referencia([mesma], "cidade exêmplo", "sp", CENTRO_CEP, 1.5) is not None


def test_coordenada_fora_do_brasil_e_descartada():
    assert geocodificacao.coordenada({"lat": "40.7", "lon": "-74.0"}) is None
    assert geocodificacao.coordenada({"lat": "x", "lon": "1"}) is None


def test_cache_em_memoria_expira_so_o_que_nao_e_valido():
    relogio = {"t": 0.0}
    cache = geocodificacao.CacheComValidade(relogio=lambda: relogio["t"])
    cache.set("a", (1, 2, "", "", "", "", "VALIDO"))
    cache.set("b", (1, 2, "", "", "", "", "ALERTA_APROXIMADO"))
    relogio["t"] = geocodificacao.TTL_NAO_VALIDO_S + 1
    assert cache.get("a") is not None and cache.get("b") is None


# ---------------------------------------------------------------- geocode_async
def test_primeiro_resultado_longe_do_cep_e_rejeitado_e_o_certo_e_escolhido(banco):
    cliente = ClienteFalso(nominatim=[[LONGE, _candidato(-10.0 + 0.03, -50.0), PERTO]])
    lat, lon, *_, status = _geocodificar(cliente)
    assert (lat, lon) == geocodificacao.coordenada(PERTO) and status == "VALIDO"
    assert cliente.quantas("nominatim") == 1 and cliente.quantas("brasilapi") == 0
    params = cliente.chamadas[0][1]
    assert params["street"] == f"{NUMERO} {RUA}" and params["city"] == CIDADE and params["state"] == UF
    assert params["countrycodes"] == "br" and params["addressdetails"] == 1 and params["limit"] == 5
    assert "postalcode" not in params


def test_texto_livre_e_tentado_quando_a_estruturada_nao_serve(banco):
    cliente = ClienteFalso(nominatim=[[LONGE], [PERTO]])
    *_, status = _geocodificar(cliente)
    assert status == "VALIDO" and cliente.quantas("nominatim") == 2
    assert "q" in cliente.chamadas[1][1] and cliente.chamadas[1][1]["limit"] == 5


def test_nenhum_candidato_serve_cai_no_centro_do_cep_como_aproximado(banco):
    cliente = ClienteFalso(nominatim=[[LONGE], [LONGE]])
    lat, lon, *_, status = _geocodificar(cliente)
    assert (lat, lon) == CENTRO_CEP and status == "ALERTA_APROXIMADO"
    # Pior caso com CEP: 2 buscas no Nominatim e 1 consulta de CEP (paralela).
    assert cliente.quantas("nominatim") == 2 and cliente.quantas("brasilapi") == 1


def test_aproximado_usa_o_cep_completo_se_ele_estiver_dentro_do_prefixo(banco):
    dentro = {"location": {"coordinates": {"latitude": -10.002, "longitude": -50.001}}}
    lat, lon, *_, status = _geocodificar(ClienteFalso(nominatim=[[], []], brasilapi=dentro))
    assert (lat, lon) == (-10.002, -50.001) and status == "ALERTA_APROXIMADO"
    fora = {"location": {"coordinates": {"latitude": -10.2, "longitude": -50.0}}}
    main._GEOCODE_CACHE_MEMORIA.clear()
    lat, lon, *_, status = _geocodificar(ClienteFalso(nominatim=[[], []], brasilapi=fora))
    assert (lat, lon) == CENTRO_CEP and status == "ALERTA_APROXIMADO"


def test_cidade_diferente_e_rejeitada(banco):
    perto_outra_cidade = _candidato(-10.0005, -50.0, cidade="Outra Cidade")
    *_, status = _geocodificar(ClienteFalso(nominatim=[[perto_outra_cidade], [perto_outra_cidade]]))
    assert status == "ALERTA_APROXIMADO"


def test_prefixo_fora_da_base_usa_o_cep_completo_com_limite_de_2_km(banco):
    banco["prefixos"].clear()
    cep_completo = {"location": {"coordinates": {"latitude": -10.0, "longitude": -50.0}}}
    a_1_7_km = _candidato(-10.0 + 0.0153, -50.0)
    lat, lon, *_, status = _geocodificar(ClienteFalso(nominatim=[[LONGE, a_1_7_km]], brasilapi=cep_completo))
    assert status == "VALIDO" and (lat, lon) == geocodificacao.coordenada(a_1_7_km)
    main._GEOCODE_CACHE_MEMORIA.clear()
    a_2_5_km = _candidato(-10.0 + 0.0225, -50.0)
    lat, lon, *_, status = _geocodificar(ClienteFalso(nominatim=[[a_2_5_km], [a_2_5_km]], brasilapi=cep_completo), rua="Rua Outra Ficticia")
    assert status == "ALERTA_APROXIMADO" and (lat, lon) == (-10.0, -50.0)


def test_sem_cep_bairro_igual_e_valido(banco):
    certo = _candidato(-12.0, -48.0, bairro="bairro fictício")
    cliente = ClienteFalso(nominatim=[[_candidato(-12.1, -48.0, bairro="Outro"), certo]])
    lat, lon, *_, status = _geocodificar(cliente, cep="")
    assert status == "VALIDO" and (lat, lon) == (-12.0, -48.0) and cliente.quantas("nominatim") == 1


def test_sem_cep_bairro_diferente_e_longe_do_bairro_e_aproximado_no_centro_do_bairro(banco):
    errado = _candidato(-12.1, -48.0, bairro="Outro Bairro")
    centro_bairro = _candidato(-12.0, -48.0)
    cliente = ClienteFalso(nominatim=[[errado], [errado], [centro_bairro]])
    lat, lon, *_, status = _geocodificar(cliente, cep="")
    assert status == "ALERTA_APROXIMADO" and (lat, lon) == (-12.0, -48.0)
    # Pior caso sem CEP: 3 buscas (estruturada, texto livre e centro do bairro).
    assert cliente.quantas("nominatim") == 3


def test_sem_cep_bairro_diferente_mas_perto_do_bairro_e_valido(banco):
    perto = _candidato(-12.005, -48.0, bairro="Nome Diferente No Mapa")
    cliente = ClienteFalso(nominatim=[[perto], [], [_candidato(-12.0, -48.0)]])
    lat, lon, *_, status = _geocodificar(cliente, cep="")
    assert status == "VALIDO" and (lat, lon) == (-12.005, -48.0)


def test_sem_cep_e_sem_bairro_so_e_valido_com_o_numero_da_porta(banco):
    sem_porta = _candidato(-12.0, -48.0)
    *_, status = _geocodificar(ClienteFalso(nominatim=[[sem_porta], [sem_porta]]), cep="", bairro="")
    assert status == "ALERTA_APROXIMADO"
    main._GEOCODE_CACHE_MEMORIA.clear()
    com_porta = _candidato(-12.0, -48.0, numero=NUMERO)
    *_, status = _geocodificar(ClienteFalso(nominatim=[[com_porta]]), cep="", bairro="")
    assert status == "VALIDO"


def test_nada_encontrado_e_erro_sem_coordenada(banco):
    banco["prefixos"].clear()
    lat, lon, *_, status = _geocodificar(ClienteFalso(nominatim=[[], [], []]))
    assert (lat, lon, status) == (None, None, "ERRO_CEP_INVALIDO")


def test_so_valido_vai_para_o_banco_com_a_chave_versionada(banco):
    _geocodificar(ClienteFalso(nominatim=[[LONGE], [LONGE]]))  # aproximado
    banco["prefixos"].clear()
    main._PREFIXOS_MEMORIA.clear()
    _geocodificar(ClienteFalso(), rua="Rua Outra Ficticia")  # erro
    assert banco["gravados"] == []
    _geocodificar(ClienteFalso(nominatim=[[PERTO]]), cep="", bairro="", rua="Rua Terceira Ficticia", numero="")
    assert banco["gravados"] == []  # sem CEP, sem bairro e sem número: aproximado
    banco["prefixos"]["99999"] = {"lat": CENTRO_CEP[0], "lon": CENTRO_CEP[1], "dispersao_km": 0.8}
    main._PREFIXOS_MEMORIA.clear()
    _geocodificar(ClienteFalso(nominatim=[[PERTO]]), rua="Rua Quarta Ficticia")
    assert len(banco["gravados"]) == 1
    chave, resultado = banco["gravados"][0]
    assert chave.startswith("v2|") and resultado[6] == "VALIDO"


def test_entrada_antiga_do_cache_e_ignorada(banco):
    chave_antiga = main._chave_cache(RUA, NUMERO, BAIRRO, CEP, CIDADE, UF)
    banco["cache"][chave_antiga] = (-15.0, -47.0, CIDADE, UF, "99999000", BAIRRO, "VALIDO")  # ponto errado de antes
    cliente = ClienteFalso(nominatim=[[PERTO]])
    lat, lon, *_ = _geocodificar(cliente)
    assert (lat, lon) == geocodificacao.coordenada(PERTO) and cliente.quantas("nominatim") == 1
    assert banco["lidos"] == ["v2|" + chave_antiga] and chave_antiga in banco["cache"]  # nada apagado


def test_aproximado_gravado_com_a_chave_nova_tambem_e_ignorado(banco):
    chave = "v2|" + main._chave_cache(RUA, NUMERO, BAIRRO, CEP, CIDADE, UF)
    banco["cache"][chave] = (-15.0, -47.0, CIDADE, UF, "99999000", BAIRRO, "ALERTA_APROXIMADO")
    cliente = ClienteFalso(nominatim=[[PERTO]])
    *_, status = _geocodificar(cliente)
    assert status == "VALIDO" and cliente.quantas("nominatim") == 1


def test_cache_em_memoria_evita_nova_busca(banco):
    cliente = ClienteFalso(nominatim=[[PERTO]])
    _geocodificar(cliente)
    _geocodificar(cliente)
    assert cliente.quantas("nominatim") == 1


def test_trava_de_uma_chamada_por_segundo_no_nominatim(banco, monkeypatch):
    relogio = {"t": 1000.0}

    class TempoFalso:
        @staticmethod
        def monotonic():
            return relogio["t"]

    dormir_de_verdade = asyncio.sleep

    async def dormir_falso(segundos):
        relogio["t"] += max(0.0, segundos)
        await dormir_de_verdade(0)

    monkeypatch.setattr(main, "_respeitar_rate_limit_nominatim", TRAVA_ORIGINAL)
    monkeypatch.setattr(main, "time", TempoFalso)
    monkeypatch.setattr(main.asyncio, "sleep", dormir_falso)
    monkeypatch.setattr(main, "_nominatim_ultima_chamada", 0.0)
    cliente = ClienteFalso(nominatim=[[LONGE]] * 6, relogio=relogio)

    async def varios():
        main._nominatim_lock = asyncio.Lock()
        return await asyncio.gather(*[
            main.geocode_async(cliente, f"Rua Ficticia {i}", str(i), BAIRRO, CEP, CIDADE, UF) for i in range(3)
        ])

    monkeypatch.setattr(main, "_nominatim_lock", main._nominatim_lock)
    resultados = asyncio.run(varios())
    assert all(r[6] == "ALERTA_APROXIMADO" for r in resultados)
    instantes = cliente.instantes_nominatim
    assert len(instantes) == 6
    assert all(b - a >= 1.05 - 1e-9 for a, b in zip(instantes, instantes[1:]))


def test_privacidade_nenhum_endereco_cep_ou_numero_no_log(banco, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    segredo_rua, segredo_num, segredo_cep = "Rua Sigilosa Ficticia", "4321", "99999-123"
    falha = httpx.ConnectError(f"falhou {segredo_rua} {segredo_num} {segredo_cep}")
    _geocodificar(ClienteFalso(nominatim=[falha, falha, falha]), rua=segredo_rua, numero=segredo_num, cep=segredo_cep)
    _geocodificar(ClienteFalso(nominatim=[[LONGE], [PERTO]]), rua=segredo_rua + " 2", numero=segredo_num, cep=segredo_cep)
    saida = capsys.readouterr()
    texto = caplog.text + saida.out + saida.err
    assert "ConnectError" in caplog.text
    for segredo in (segredo_rua, segredo_num, segredo_cep, "99999123", BAIRRO, CIDADE):
        assert segredo not in texto


# ---------------------------------------------------------------- link do Maps
def test_link_do_maps_loja_por_coordenada_e_paradas_por_endereco():
    paradas = [
        {"Endereco": "Rua Ficticia/Bloco #2", "Numero": "10", "Cidade": CIDADE, "UF": UF, "CEP": CEP, "lat": -10.1, "lon": -50.1},
        {"Endereco": "", "Numero": "5", "Cidade": CIDADE, "UF": UF, "CEP": CEP, "lat": -10.2, "lon": -50.2},
        {"Endereco": "Rua Sem Cidade", "Numero": "1", "Cidade": "", "lat": -10.3, "lon": -50.3},
    ]
    link = movimentos.link_maps((-10.0, -50.0), paradas)
    assert link.startswith("https://www.google.com/maps/dir/-10.0,-50.0/") and link.endswith("/-10.0,-50.0")
    trechos = link[len("https://www.google.com/maps/dir/"):].split("/")
    assert trechos == [
        "-10.0,-50.0",
        "Rua%20Ficticia%2FBloco%20%232,%2010,%20Cidade%20Exemplo%20-%20SP,%2099999-000",
        "-10.2,-50.2",
        "-10.3,-50.3",
        "-10.0,-50.0",
    ]
    assert movimentos.link_maps((-10.0, -50.0), []) == ""


def test_link_do_maps_nunca_leva_o_cliente():
    parada = {"Endereco": "Rua Ficticia", "Numero": "1", "Cidade": CIDADE, "UF": UF, "cliente": "Fulano Ficticio", "lat": -10.1, "lon": -50.1}
    assert "Fulano" not in movimentos.link_maps((-10.0, -50.0), [parada])


# ---------------------------------------------------------------- aviso no resultado da roteirização
def test_texto_do_aviso():
    assert main.texto_localizacao_aproximada(1) == "1 endereço com localização aproximada: confira no mapa."
    assert main.texto_localizacao_aproximada(3) == "3 endereços com localização aproximada: confira no mapa."


def _rodar_otimizacao(monkeypatch, status_por_id):
    pytest.importorskip("ortools")
    hub = (-10.0, -50.0)
    pedidos = [{"id": str(i + 1), "Endereco": f"Rua Ficticia {i + 1}", "Numero": str(i + 1), "Bairro": BAIRRO, "Cidade": CIDADE, "UF": UF, "CEP": CEP, "Volume": 1}
               for i in range(len(status_por_id))]

    async def lote_falso(lista):
        return {
            main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p["Bairro"], cep=p["CEP"], cidade=p["Cidade"], uf=p["UF"]):
                (hub[0] + 0.01 * (i + 1), hub[1], CIDADE, UF, "99999000", BAIRRO, status_por_id[i])
            for i, p in enumerate(lista)
        }

    async def osrm_falso(client, pontos):
        return 1.0, 1, [[a, b] for a, b in pontos]

    async def geocode_proibido(*a, **k):
        raise AssertionError("o hub vem da loja")

    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    monkeypatch.setattr(main, "geocode_async", geocode_proibido)
    frota = [main.MotoristaItem(id=1, motorista="Ana", modal="Carro de passeio", custo_rota=130.0)]
    contexto = {"turno": "tarde", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {}}
    req = main.OtimizarRequest(origem_rua="X", origem_num="1", pedidos=pedidos)
    loja = {"id": 1, "nome": "Loja Ficticia", "endereco": "", "lat": hub[0], "lng": hub[1]}
    main.JOBS["tgeo"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    asyncio.run(main._processar_otimizacao("tgeo", req, frota, {}, loja, contexto))
    job = main.JOBS.pop("tgeo")
    assert job["status"] == "concluido", job["erro"]
    return job["resultado"]


def test_resultado_avisa_quantos_enderecos_estao_aproximados(monkeypatch):
    r = _rodar_otimizacao(monkeypatch, ["VALIDO", "ALERTA_APROXIMADO", "ALERTA_APROXIMADO"])
    avisos = [a for a in r["avisos"] if a["tipo"] == "localizacao_aproximada"]
    assert avisos == [{"tipo": "localizacao_aproximada", "gravidade": "atencao", "mensagem": "2 endereços com localização aproximada: confira no mapa."}]
    assert r["kpis"]["total_pedidos"] == 3  # nada bloqueia
    link = r["rotas"][0]["link_maps"]
    assert "Rua%20Ficticia" in link and link.startswith("https://www.google.com/maps/dir/-10.0,-50.0/")


def test_sem_aproximados_nao_ha_aviso_novo(monkeypatch):
    r = _rodar_otimizacao(monkeypatch, ["VALIDO", "VALIDO"])
    assert not [a for a in r["avisos"] if a["tipo"] == "localizacao_aproximada"]
