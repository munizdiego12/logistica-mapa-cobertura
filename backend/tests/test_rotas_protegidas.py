"""Rotas de negócio exigem login (JWT de verdade, sem trocar a dependência de autenticação); login e cadastro ficam abertos."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import main
from database import Base, Operador, get_db

ABERTAS = {"/api/auth/login", "/api/auth/register"}

# (método, caminho, argumentos do cliente que NÃO disparam trabalho pesado nem rede, status esperado com token válido)
ROTAS = [
    ("post", "/api/cobertura-ceps", {"json": {}}, 422),
    ("post", "/api/exportar-tabela-frete-xlsx", {"json": {}}, 422),
    ("get", "/api/modais", {}, 200),
    ("post", "/api/upload", {}, 422),
    ("post", "/api/otimizar", {"json": {}}, 422),
    ("get", "/api/otimizar/status/inexistente", {}, 404),
    ("get", "/api/modelo-xlsx", {}, 200),
]


@pytest.fixture
def banco():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Sessao = sessionmaker(bind=engine, autoflush=False)

    def _get_db():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _get_db
    yield Sessao
    main.app.dependency_overrides.clear()


@pytest.fixture
def cliente(banco):
    return TestClient(main.app)


def _criar_operador(Sessao, email="maria@zubale.com", senha="senha-forte-1", ativo=True):
    with Sessao() as db:
        db.add(Operador(nome="Maria Souza", email=email, senha_hash=auth.gerar_hash_senha(senha), ativo=ativo))
        db.commit()


def _cabecalho(email="maria@zubale.com", **kw):
    return {"Authorization": f"Bearer {auth.criar_token_acesso({'sub': email}, **kw)}"}


@pytest.mark.parametrize("metodo, caminho, args, _", ROTAS)
def test_sem_token_recebe_401(cliente, metodo, caminho, args, _):
    assert getattr(cliente, metodo)(caminho, **args).status_code == 401


@pytest.mark.parametrize("metodo, caminho, args, _", ROTAS)
def test_token_invalido_recebe_401(cliente, metodo, caminho, args, _):
    r = getattr(cliente, metodo)(caminho, headers={"Authorization": "Bearer lixo"}, **args)
    assert r.status_code == 401


@pytest.mark.parametrize("metodo, caminho, args, esperado", ROTAS)
def test_token_valido_passa(banco, cliente, metodo, caminho, args, esperado):
    _criar_operador(banco)
    r = getattr(cliente, metodo)(caminho, headers=_cabecalho(), **args)
    assert r.status_code == esperado, r.text


def test_token_expirado_recebe_401(banco, cliente):
    _criar_operador(banco)
    r = cliente.get("/api/modais", headers=_cabecalho(expires_delta=timedelta(minutes=-1)))
    assert r.status_code == 401


def test_operador_inativo_recebe_401(banco, cliente):
    _criar_operador(banco, ativo=False)
    assert cliente.get("/api/modais", headers=_cabecalho()).status_code == 401


def test_token_de_operador_inexistente_recebe_401(banco, cliente):
    assert cliente.get("/api/modais", headers=_cabecalho("ninguem@zubale.com")).status_code == 401


def test_toda_rota_da_api_exige_login_menos_login_e_cadastro():
    """Impede esquecer uma rota nova: toda rota /api (fora login/cadastro) tem a dependência de autenticação."""
    desprotegidas = []
    for rota in main.app.routes:
        caminho = getattr(rota, "path", "")
        if not caminho.startswith("/api") or caminho in ABERTAS:
            continue
        dependencias = [d.call for d in rota.dependant.dependencies]
        if auth.obter_operador_atual not in dependencias:
            desprotegidas.append(caminho)
    assert desprotegidas == []


def test_login_e_cadastro_continuam_abertos(banco, cliente, monkeypatch):
    _criar_operador(banco)
    ok = cliente.post("/api/auth/login", data={"username": "maria@zubale.com", "password": "senha-forte-1"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    # o token devolvido pelo login abre as rotas protegidas
    assert cliente.get("/api/modais", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).status_code == 200
    errada = cliente.post("/api/auth/login", data={"username": "maria@zubale.com", "password": "outra"})
    assert errada.status_code == 400  # senha errada não é "sem sessão": o front não pode confundir com 401

    monkeypatch.setattr(main, "OPERATOR_INVITE_CODE", "convite-teste")
    corpo = {"nome": "João", "email": "joao@zubale.com", "senha": "senha-forte-2"}
    assert cliente.post("/api/auth/register", json={**corpo, "codigo_convite": "errado"}).status_code == 403
    assert cliente.post("/api/auth/register", json={**corpo, "codigo_convite": "convite-teste"}).status_code == 200
