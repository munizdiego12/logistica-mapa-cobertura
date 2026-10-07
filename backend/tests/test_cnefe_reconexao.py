"""Conexão com o banco na carga do CNEFE: só abre depois da agregação e reconecta se cair (sem duplicar)."""
import importlib.util
import sqlite3
import sys
import zipfile
from pathlib import Path

import psycopg2
import pytest

from backend.cnefe import LimiteExcedido

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_cnefe_reconexao", RAIZ / "scripts" / "carregar_cnefe.py")
carregar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(carregar)

LIMITE = 100_000_000
SSL_CAIU = "SSL connection has been closed unexpectedly"


def _zip_falso(pasta, uf="AC"):
    cod = carregar.CODIGOS_UF[uf]
    linhas = ["COD_MUNICIPIO;CEP;LATITUDE;LONGITUDE;NV_GEO_COORD;DSC_LOCALIDADE"]
    linhas += [f"1200401;699001{i:02d};-9.9{i};-67.8{i};1;BOSQUE" for i in range(10)]
    caminho = Path(pasta) / f"{cod}_{uf}.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(f"{cod}_{uf}.csv", "\n".join(linhas))
    return caminho


def _sem_espera(esperas_registradas=None):
    return (lambda segundos: esperas_registradas.append(segundos)) if esperas_registradas is not None else (lambda s: None)


def _linhas_no_banco(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        return conn.execute("SELECT prefixo, n_enderecos FROM cep_prefixos").fetchall()
    except sqlite3.OperationalError:
        return None  # tabela nem foi criada
    finally:
        conn.close()


def test_banco_nao_fica_conectado_durante_o_download_e_a_agregacao(tmp_path, monkeypatch):
    eventos, abertas = [], []

    class Destino:
        def __init__(self):
            eventos.append("abrir")
            abertas.append(1)

        def tamanho_atual(self):
            eventos.append("tamanho")
            return 0

        def gravar(self, linhas, limite, relatorio):
            eventos.append("gravar")
            relatorio.update(conflitos=[], mantidas=0, tamanho_bytes=1234)
            return len(linhas), 0

        def fechar(self):
            eventos.append("fechar")
            abertas.pop()

    arquivo = _zip_falso(tmp_path)
    agregar_real = carregar.agregar_prefixos

    def baixar(uf, pasta):
        eventos.append(f"baixar(conexoes_abertas={len(abertas)})")
        return arquivo

    def agregar(chunks, uf):
        eventos.append(f"agregar(conexoes_abertas={len(abertas)})")
        return agregar_real(chunks, uf)

    monkeypatch.setattr(carregar, "baixar_uf", baixar)
    monkeypatch.setattr(carregar, "agregar_prefixos", agregar)
    r = carregar.processar_uf("AC", tmp_path, Destino, LIMITE, False, dormir=_sem_espera())

    assert eventos == [
        "abrir", "tamanho", "fechar",                       # confere o tamanho e já fecha
        "baixar(conexoes_abertas=0)", "agregar(conexoes_abertas=0)",  # minutos sem conexão aberta
        "abrir", "gravar", "fechar",                        # abre de novo só para gravar
    ]
    assert r["tentativas_gravacao"] == 1 and r["novas"] == 1 and not arquivo.exists()


class _DestinoSqliteQueCai(carregar.DestinoSqlite):
    """SQLite de verdade, mas as primeiras `falhas` gravações levantam o erro dado (antes ou depois de gravar)."""

    def __init__(self, caminho, controle):
        super().__init__(caminho)
        self.controle = controle
        controle["aberturas"] += 1

    def gravar(self, linhas, limite_bytes, relatorio):
        self.controle["gravacoes"] += 1
        if self.controle["gravacoes"] <= self.controle["falhas"]:
            if self.controle["quando"] == "depois_do_commit":
                super().gravar(linhas, limite_bytes, relatorio)  # gravou e a conexão caiu antes de avisar
            raise self.controle["erro"]
        return super().gravar(linhas, limite_bytes, relatorio)


def _abrir_que_cai(tmp_path, falhas, erro, quando="antes"):
    controle = {"aberturas": 0, "gravacoes": 0, "falhas": falhas, "erro": erro, "quando": quando}
    return (lambda: _DestinoSqliteQueCai(str(tmp_path / "t.db"), controle)), controle


@pytest.mark.parametrize("quando", ["antes", "depois_do_commit"])
def test_reconecta_e_grava_sem_duplicar_quando_a_conexao_cai(tmp_path, quando):
    _zip_falso(tmp_path)
    abrir, controle = _abrir_que_cai(tmp_path, 2, psycopg2.OperationalError(SSL_CAIU), quando)
    esperas = []
    r = carregar.processar_uf("AC", tmp_path, abrir, LIMITE, False, esperas=(2, 5), dormir=_sem_espera(esperas))

    assert controle["gravacoes"] == 3 and r["tentativas_gravacao"] == 3
    assert esperas == [2, 5]  # espera crescente entre as tentativas
    assert _linhas_no_banco(tmp_path) == [("69900", 10)]  # uma linha só: nada duplicado, mesmo se já tinha gravado
    assert r["prefixos"] == 1 and r["apagado"] is True


def test_connection_already_closed_tambem_e_repetido(tmp_path):
    _zip_falso(tmp_path)
    abrir, controle = _abrir_que_cai(tmp_path, 1, psycopg2.InterfaceError("connection already closed"))
    r = carregar.processar_uf("AC", tmp_path, abrir, LIMITE, False, dormir=_sem_espera())
    assert controle["gravacoes"] == 2 and r["tentativas_gravacao"] == 2
    assert _linhas_no_banco(tmp_path) == [("69900", 10)]


def test_desiste_depois_de_3_tentativas_sem_gravar_e_guarda_o_download(tmp_path):
    arquivo = _zip_falso(tmp_path)
    abrir, controle = _abrir_que_cai(tmp_path, 99, psycopg2.OperationalError(SSL_CAIU))
    with pytest.raises(psycopg2.OperationalError, match="SSL connection"):
        carregar.processar_uf("AC", tmp_path, abrir, LIMITE, False, dormir=_sem_espera())
    assert controle["gravacoes"] == 3  # exatamente 3 tentativas de gravar
    assert controle["aberturas"] == 1 + 3  # 1 conferência do tamanho + 3 conexões novas para gravar
    assert arquivo.exists()  # não gravou: o arquivo fica para repetir sem baixar de novo
    assert not _linhas_no_banco(tmp_path)  # nenhuma linha gravada (a tabela nem chegou a ser criada)


def test_falha_ao_abrir_a_conexao_tambem_e_repetida(tmp_path):
    _zip_falso(tmp_path)
    chamadas = {"n": 0}

    def abrir():
        chamadas["n"] += 1
        if chamadas["n"] == 2:  # 1ª = conferência do tamanho; 2ª = 1ª tentativa de gravar (Neon acordando)
            raise psycopg2.OperationalError("could not connect to server")
        return carregar.DestinoSqlite(str(tmp_path / "t.db"))

    r = carregar.processar_uf("AC", tmp_path, abrir, LIMITE, False, dormir=_sem_espera())
    assert r["tentativas_gravacao"] == 2 and _linhas_no_banco(tmp_path) == [("69900", 10)]


@pytest.mark.parametrize("erro", [LimiteExcedido(200, 100), ValueError("dado inválido"), RuntimeError("outro erro")])
def test_erros_que_nao_sao_de_conexao_nao_sao_repetidos(tmp_path, erro):
    _zip_falso(tmp_path)
    abrir, controle = _abrir_que_cai(tmp_path, 99, erro)
    with pytest.raises(type(erro)):
        carregar.processar_uf("AC", tmp_path, abrir, LIMITE, False, dormir=_sem_espera())
    assert controle["gravacoes"] == 1


def test_erro_ao_fechar_conexao_quebrada_nao_atrapalha(tmp_path):
    _zip_falso(tmp_path)
    controle = {"gravacoes": 0}

    class Destino(carregar.DestinoSqlite):
        def gravar(self, linhas, limite_bytes, relatorio):
            controle["gravacoes"] += 1
            if controle["gravacoes"] == 1:
                raise psycopg2.OperationalError(SSL_CAIU)
            return super().gravar(linhas, limite_bytes, relatorio)

        def fechar(self):
            super().fechar()
            if controle["gravacoes"] == 1:
                raise psycopg2.InterfaceError("connection already closed")  # fechar uma conexão já morta

    r = carregar.processar_uf("AC", tmp_path, lambda: Destino(str(tmp_path / "t.db")), LIMITE, False, dormir=_sem_espera())
    assert r["tentativas_gravacao"] == 2 and _linhas_no_banco(tmp_path) == [("69900", 10)]


def test_executar_com_reconexao_devolve_resultado_e_numero_da_tentativa():
    estado = {"n": 0}

    def operacao(destino):
        estado["n"] += 1
        if estado["n"] < 3:
            raise psycopg2.OperationalError(SSL_CAIU)
        return "ok"

    class D:
        def fechar(self):
            pass

    assert carregar.executar_com_reconexao(D, operacao, dormir=_sem_espera()) == ("ok", 3)


def test_main_explica_o_que_fazer_quando_a_conexao_nao_volta(tmp_path, monkeypatch, capsys):
    def sempre_cai(*args, **kwargs):
        raise psycopg2.OperationalError(SSL_CAIU)

    monkeypatch.setattr(carregar, "processar_uf", sempre_cai)
    monkeypatch.setattr(sys, "argv", ["carregar_cnefe.py", "--uf", "AC", "--sqlite", str(tmp_path / "t.db")])
    with pytest.raises(SystemExit) as saida:
        carregar.main()
    assert saida.value.code == 3
    texto = capsys.readouterr().out
    assert "PAROU em AC" in texto and "3 tentativas" in texto and "Nada de AC foi gravado" in texto
    assert "--pular" in texto and "arquivo baixado foi mantido" in texto
