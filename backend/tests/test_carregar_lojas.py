"""Script de carga de lojas: resumo antes de gravar, confirmação digitada, conexão só quando precisa e proteção das edições."""
import asyncio
import importlib.util
from pathlib import Path

import asyncpg
import pytest

import lojas
from backend.tests.fakes_asyncpg import criar_banco_sqlite

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_lojas_teste", RAIZ / "scripts" / "carregar_lojas.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CSV = (
    "Nome;Estado;Endereço;Latitude;Longitude\n"
    '"Atacadão Guarujá";SP;"Av. Santos Dumont, 100";"-23,9930";"-46,2564"\n'
    "Atacadão Campinas;SP;;-22,9099;-47,0626\n"
    "Atacadão Trocada;SP;;-46,6333;-23,5505\n"
    "Atacadão Ruim;SP;;abc;-46\n"
)
OPERADOR_TELA = "Maria Souza (maria@zubale.com)"


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "lojas.csv"
    caminho.write_bytes(CSV.encode("utf-8"))
    return str(caminho)


def _sem_banco(monkeypatch):
    async def proibido(dsn):
        raise AssertionError("não era para conectar no banco")

    monkeypatch.setattr(script, "conectar", proibido)


@pytest.fixture
def banco_falso(monkeypatch):
    """Cada conexão do script é uma conexão nova sobre o MESMO banco SQLite (o Neon derruba conexão ociosa)."""
    banco = criar_banco_sqlite()
    conexoes = []

    async def conectar(dsn):
        conexoes.append(dsn)
        return banco

    monkeypatch.setattr(script, "conectar", conectar)
    monkeypatch.setenv("DATABASE_URL", "postgres://usuario:segredo@host.neon.tech/db?sslmode=require&channel_binding=require")
    banco.conexoes = conexoes
    return banco


def test_sem_gravar_mostra_o_resumo_e_nem_conecta_no_banco(arquivo, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "LOJAS VÁLIDAS (serão gravadas): 2" in texto and "sem endereço: 1" in texto
    assert "COM COORDENADA SUSPEITA (NÃO serão gravadas): 1" in texto and "TROCADAS" in texto and "Atacadão Trocada" in texto
    assert "INVÁLIDAS (ignoradas): 1" in texto and "DUPLICADAS" in texto
    assert "Nada foi gravado (nem conectei no banco)" in texto


def test_gravar_sem_database_url_para_com_mensagem_clara(arquivo, monkeypatch):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", arquivo, "--gravar"])
    assert "DATABASE_URL" in str(erro.value)


def test_arquivo_que_nao_existe_e_formato_errado_param_com_mensagem(tmp_path, monkeypatch):
    _sem_banco(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", str(tmp_path / "nao-existe.csv")])
    assert "não achei" in str(erro.value)
    ruim = tmp_path / "ruim.csv"
    ruim.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", str(ruim)])
    assert "Nome, Estado, Endereço, Latitude e Longitude" in str(erro.value)


def test_sem_a_confirmacao_digitada_nada_e_gravado(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "gravar")  # minúsculas não valem
    script.main(["--csv", arquivo, "--gravar"])
    assert banco_falso.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 0
    assert "Cancelado: nada foi gravado" in capsys.readouterr().out
    assert len(banco_falso.conexoes) == 1  # só a previsão abriu conexão


def test_gravar_com_confirmacao_grava_so_as_validas_e_usa_conexoes_novas(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    texto = capsys.readouterr().out
    assert "lojas novas: 2" in texto and "Gravado: 2 loja(s) nova(s)" in texto
    linhas = banco_falso.db.execute("SELECT nome, uf, endereco, lat, lng, atualizado_por FROM lojas ORDER BY nome").fetchall()
    assert [tuple(l) for l in linhas] == [
        ("Atacadão Campinas", "SP", None, -22.9099, -47.0626, lojas.OPERADOR_CARGA_INICIAL),
        ("Atacadão Guarujá", "SP", "Av. Santos Dumont, 100", -23.993, -46.2564, lojas.OPERADOR_CARGA_INICIAL),
    ]
    assert len(banco_falso.conexoes) == 2  # uma conexão para a previsão e outra, nova, para gravar


def test_repetir_a_carga_e_seguro_e_nao_sobrescreve_loja_editada_na_tela(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    # um operador edita a loja na tela
    banco_falso.db.execute("UPDATE lojas SET endereco = 'Endereço corrigido', lat = -23.5, atualizado_por = ? WHERE nome = 'Atacadão Guarujá'", (OPERADOR_TELA,))
    capsys.readouterr()
    script.main(["--csv", arquivo, "--gravar"])
    texto = capsys.readouterr().out
    assert "lojas PRESERVADAS (um operador editou na tela): 1" in texto and "lojas já existentes que serão atualizadas: 1" in texto
    assert banco_falso.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 2  # nada duplicado
    editada = banco_falso.db.execute("SELECT endereco, lat, atualizado_por FROM lojas WHERE nome = 'Atacadão Guarujá'").fetchone()
    assert tuple(editada) == ("Endereço corrigido", -23.5, OPERADOR_TELA)


def test_sobrescrever_editados_so_com_a_opcao(arquivo, banco_falso, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    banco_falso.db.execute("UPDATE lojas SET lat = -23.5, atualizado_por = ? WHERE nome = 'Atacadão Guarujá'", (OPERADOR_TELA,))
    script.main(["--csv", arquivo, "--gravar", "--sobrescrever-editados", "--sim"])
    assert banco_falso.db.execute("SELECT lat FROM lojas WHERE nome = 'Atacadão Guarujá'").fetchone()[0] == -23.993


def test_carga_em_loja_existente_nao_apaga_endereco_nem_estado_com_celula_em_branco(banco_falso, monkeypatch, tmp_path):
    primeira = tmp_path / "a.csv"
    primeira.write_text('Nome;Estado;Endereço;Latitude;Longitude\nLoja X;SP;"Rua A, 1";-23,5;-46,6\n', encoding="utf-8")
    segunda = tmp_path / "b.csv"
    segunda.write_text("Nome;Estado;Endereço;Latitude;Longitude\nLoja X;SP;;-23,6;-46,7\n", encoding="utf-8")
    script.main(["--csv", str(primeira), "--gravar", "--sim"])
    script.main(["--csv", str(segunda), "--gravar", "--sim"])
    linha = banco_falso.db.execute("SELECT endereco, lat, lng FROM lojas").fetchone()
    assert tuple(linha) == ("Rua A, 1", -23.6, -46.7)  # coordenada atualizada, endereço em branco no CSV não apaga


def test_my_maps_entra_sem_estado_e_o_resumo_conta(tmp_path, banco_falso, monkeypatch, capsys):
    caminho = tmp_path / "mymaps.csv"
    caminho.write_bytes('WKT,name,description\n"POINT (-46.2564 -23.9930)",Atacadão Guarujá,"Av. Santos Dumont, 100"\n'.encode("cp1252"))
    script.main(["--csv", str(caminho), "--gravar", "--sim"])
    texto = capsys.readouterr().out
    assert "Google My Maps" in texto and "sem Estado: 1" in texto and "windows-1252" in texto
    assert tuple(banco_falso.db.execute("SELECT nome, uf, lat, lng FROM lojas").fetchone()) == ("Atacadão Guarujá", None, -23.993, -46.2564)


def test_conexao_que_cai_reconecta_sem_duplicar(arquivo, monkeypatch):
    banco = criar_banco_sqlite()
    tentativas = []

    async def conectar(dsn):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise asyncpg.PostgresConnectionError("SSL connection has been closed unexpectedly")
        return banco

    async def sem_espera(segundos):
        return None

    monkeypatch.setattr(script, "conectar", conectar)
    linhas = lojas.para_gravar(lojas.ler_csv_lojas(arquivo))
    feito = asyncio.run(script.com_conexao("dsn", lambda c: lojas.gravar_carga(c, linhas), dormir=sem_espera))
    assert feito["novas"] == 2 and len(tentativas) == 2
    assert banco.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 2


def test_resumo_mostra_as_colunas_reconhecidas_e_quantas_lojas_estao_sem_cidade_e_sem_endereco(tmp_path, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    caminho = tmp_path / "lojas.csv"
    caminho.write_bytes(
        ("Nome,UF,Endereço Completo,Cidade,Latitude,Longitude\n"
         '"Atacadão Guarujá",SP,"Av. Santos Dumont, 100, Guarujá, SP, Brazil",Guarujá,"-23,9930","-46,2564"\n'
         "Atacadão Campinas,SP,,,-22.9099,-47.0626\n").encode("utf-8"))
    script.main(["--csv", str(caminho)])
    texto = capsys.readouterr().out
    assert 'colunas reconhecidas: Nome <- "Nome"; UF <- "UF"; Endereço <- "Endereço Completo"; Cidade <- "Cidade"; Latitude <- "Latitude"; Longitude <- "Longitude"' in texto
    assert "sem endereço: 1" in texto and "sem cidade: 1" in texto
    assert "NÃO encontradas" not in texto


def test_resumo_avisa_as_colunas_que_nao_foram_encontradas(tmp_path, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    caminho = tmp_path / "lojas.csv"
    caminho.write_bytes("LOJA;ESTADO;LAT;LNG\nAtacadão X;SP;-23,5;-46,6\n".encode("utf-8"))
    script.main(["--csv", str(caminho)])
    texto = capsys.readouterr().out
    assert 'Nome <- "LOJA"' in texto and 'Latitude <- "LAT"' in texto and 'Longitude <- "LNG"' in texto
    assert "colunas NÃO encontradas (ficam em branco): Endereço, Cidade" in texto
    assert "sem cidade: 1" in texto and "sem endereço: 1" in texto


def test_gravar_guarda_a_cidade_e_celula_em_branco_nao_apaga_a_cidade_ja_cadastrada(banco_falso, tmp_path):
    primeira = tmp_path / "a.csv"
    primeira.write_text("Nome,UF,Endereço Completo,Cidade,Latitude,Longitude\nLoja X,SP,Rua A,São Paulo,-23.5,-46.6\n", encoding="utf-8")
    segunda = tmp_path / "b.csv"
    segunda.write_text("Nome,UF,Endereço Completo,Cidade,Latitude,Longitude\nLoja X,SP,,,-23.6,-46.7\n", encoding="utf-8")
    script.main(["--csv", str(primeira), "--gravar", "--sim"])
    assert tuple(banco_falso.db.execute("SELECT cidade, endereco FROM lojas").fetchone()) == ("São Paulo", "Rua A")
    script.main(["--csv", str(segunda), "--gravar", "--sim"])
    assert tuple(banco_falso.db.execute("SELECT cidade, endereco, lat FROM lojas").fetchone()) == ("São Paulo", "Rua A", -23.6)
