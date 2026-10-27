"""Limpeza dos resultados de roteirização guardados em memória (JOBS): TTL desde o término, limite de quantidade e privacidade do log."""
import logging

import pytest
from fastapi.testclient import TestClient

import config
import main

HORA = 3600.0
AGORA = 1_000_000.0


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture(autouse=True)
def jobs_isolados():
    guardados = dict(main.JOBS)
    main.JOBS.clear()
    yield main.JOBS
    main.JOBS.clear()
    main.JOBS.update(guardados)


@pytest.fixture
def cliente():
    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _job(status, terminado_em=None, criado_em=AGORA - 10 * HORA, resultado=None):
    return {"status": status, "etapa": "", "atual": 0, "total": 1, "resultado": resultado, "erro": None,
            "criado_em": criado_em, "terminado_em": terminado_em}


def test_job_terminado_antigo_e_removido_e_o_recente_fica():
    main.JOBS["velho-ok"] = _job("concluido", AGORA - 9 * HORA)
    main.JOBS["velho-erro"] = _job("erro", AGORA - 8 * HORA)
    main.JOBS["recente"] = _job("concluido", AGORA - 7 * HORA)
    removidos = main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=200)
    assert removidos == 2
    assert set(main.JOBS) == {"recente"}


def test_job_em_andamento_antigo_nunca_e_removido_por_tempo():
    main.JOBS["andando"] = _job("em_andamento", None, criado_em=AGORA - 500 * HORA)
    assert main._limpar_jobs(agora=AGORA, ttl_horas=1, maximo=200) == 0
    assert "andando" in main.JOBS


def test_limite_remove_so_os_terminados_mais_antigos():
    for i in range(5):
        main.JOBS[f"andando-{i}"] = _job("em_andamento", None, criado_em=AGORA - 100 * HORA)
    for i in range(5):
        main.JOBS[f"fim-{i}"] = _job("concluido", AGORA - (5 - i) * 60)  # fim-0 é o mais antigo
    removidos = main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=7)
    assert removidos == 3
    assert {f"fim-{i}" for i in range(3)}.isdisjoint(main.JOBS)
    assert {"fim-3", "fim-4"} | {f"andando-{i}" for i in range(5)} == set(main.JOBS)


def test_limite_nao_remove_em_andamento_mesmo_acima_do_maximo():
    for i in range(4):
        main.JOBS[f"andando-{i}"] = _job("em_andamento")
    main.JOBS["fim"] = _job("erro", AGORA - 60)
    assert main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=2) == 1
    assert set(main.JOBS) == {f"andando-{i}" for i in range(4)}


def test_job_terminado_sem_horario_conta_a_partir_da_limpeza():
    main.JOBS["sem-horario"] = {"status": "concluido", "erro": None, "resultado": {"rotas": []}}
    assert main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=200) == 0
    assert main.JOBS["sem-horario"]["terminado_em"] == AGORA
    assert main._limpar_jobs(agora=AGORA + 8 * HORA, ttl_horas=8, maximo=200) == 1


def test_limpeza_com_jobs_vazio_nao_falha():
    assert main._limpar_jobs() == 0
    assert main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=1) == 0
    assert main.JOBS == {}


def test_limpeza_nunca_derruba_quem_chamou(monkeypatch, caplog):
    main.JOBS["estranho"] = _job("concluido", "não é número")
    with caplog.at_level(logging.WARNING, logger="zubale.jobs"):
        assert main._limpar_jobs(agora=AGORA) == 0
    assert "TypeError" in caplog.text


def test_novo_job_guarda_horarios_e_abre_espaco(monkeypatch):
    monkeypatch.setattr(main, "JOBS_MAX", 3)
    agora = __import__("time").time()
    for i in range(3):
        main.JOBS[f"fim-{i}"] = _job("concluido", agora - (3 - i) * 60)
    job_id = main._novo_job()
    assert len(main.JOBS) == 3 and "fim-0" not in main.JOBS
    job = main.JOBS[job_id]
    assert job["status"] == "em_andamento" and job["terminado_em"] is None and job["criado_em"] > 0


def test_processar_otimizacao_marca_o_termino(monkeypatch):
    import asyncio

    job_id = main._novo_job()

    class Req:
        modais_config = None
        origem_rua = origem_num = origem_bairro = origem_cep = ""

    async def geocode_falha(*a, **k):
        return None, None, None, None, None, None, "ERRO_CEP_INVALIDO"

    monkeypatch.setattr(main, "geocode_async", geocode_falha)
    asyncio.run(main._processar_otimizacao(job_id, Req(), []))
    job = main.JOBS[job_id]
    assert job["status"] == "erro" and job["terminado_em"] is not None


@pytest.mark.parametrize("valor,esperado", [(None, 8.0), ("12", 12.0), ("0,5", 0.5), ("abc", 8.0), ("0", 8.0), ("-3", 8.0), ("inf", 8.0), ("nan", 8.0)])
def test_ttl_configuravel_e_invalido_volta_ao_padrao(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("JOBS_TTL_HORAS", raising=False)
    else:
        monkeypatch.setenv("JOBS_TTL_HORAS", valor)
    assert config.jobs_ttl_horas() == esperado


@pytest.mark.parametrize("valor,esperado", [(None, 200), ("50", 50), ("abc", 200), ("0", 200), ("-1", 200), ("2.5", 200)])
def test_maximo_configuravel_e_invalido_volta_ao_padrao(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("JOBS_MAX", raising=False)
    else:
        monkeypatch.setenv("JOBS_MAX", valor)
    assert config.jobs_max() == esperado


def test_status_de_job_removido_responde_a_mensagem_de_sempre(cliente):
    main.JOBS["sumido"] = _job("concluido", 0.0, resultado={"rotas": []})  # terminou há décadas
    r = cliente.get("/api/otimizar/status/sumido")
    assert r.status_code == 404
    assert r.json()["detail"] == "Cálculo não encontrado (pode ter expirado). Gere as rotas novamente."
    assert "sumido" not in main.JOBS


def test_status_de_job_recente_continua_igual(cliente):
    main.JOBS["vivo"] = _job("concluido", None, resultado={"rotas": []})
    main.JOBS["vivo"]["terminado_em"] = __import__("time").time()
    r = cliente.get("/api/otimizar/status/vivo")
    assert r.status_code == 200
    assert r.json() == {"status": "concluido", "etapa": "", "atual": 0, "total": 1, "resultado": {"rotas": []}}


def test_confirmar_de_job_removido_responde_o_aviso_de_sempre(cliente):
    main.JOBS["sumido"] = _job("concluido", 0.0, resultado={"loja_hub": "L", "rotas": [{"id": 1, "motorista_id": 1}]})
    main._limpar_jobs()
    assert "sumido" not in main.JOBS
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "sumido"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Este resultado não está mais disponível. Gere as rotas de novo."


def test_log_da_limpeza_so_tem_contagens(caplog):
    resultado = {"rotas": [{"paradas": [{"id": "PED-SECRETO-9", "Cliente": "Fulano Sigiloso", "Endereco": "Rua Escondida"}]}]}
    main.JOBS["job-secreto-123"] = _job("concluido", 0.0, resultado=resultado)
    main.JOBS["outro"] = _job("em_andamento")
    with caplog.at_level(logging.INFO, logger="zubale.jobs"):
        assert main._limpar_jobs(agora=AGORA, ttl_horas=8, maximo=200) == 1
    texto = caplog.text
    assert "1 removidos, 1 restantes" in texto
    for segredo in ("PED-SECRETO-9", "Fulano", "Rua Escondida", "job-secreto-123"):
        assert segredo not in texto
