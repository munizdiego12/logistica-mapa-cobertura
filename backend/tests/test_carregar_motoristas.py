"""Script de carga de motoristas (6b): tipos, lojas, códigos, telefone (só contagens e códigos), confirmação e proteção das edições."""
import asyncio
import importlib.util
import re
from pathlib import Path

import asyncpg
import pytest

from backend import carga_motoristas as carga
from backend.tests.fakes_asyncpg import criar_banco_sqlite

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_motoristas_teste", RAIZ / "scripts" / "carregar_motoristas.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

OPERADOR_TELA = "Maria Souza (maria@zubale.com)"
CABECALHO = "Código;Nome;Tipo de veículo;Lojas;Diária;Telefone\n"
CSV = CABECALHO + (
    "MOT-0001;João Silva;Utilitário;Atacadão Guarujá;260,50;(11) 91234-5678\n"
    "MOT-0002;João Silva;Passeio;Atacadão Guarujá | Atacadão Campinas;130.5;\n"
    "MOT-0003;Ana Souza;Fiorino;Atacadão Inexistente;;+55 21 98888-7777\n"
    "MOT-0004;Beto;Moto;;;\n"
    ";Sem Código;Passeio;;;\n"
    "MOT-0006;Carla;Carro de passeio;;;91234-5678\n"
    "MOT-0007;Davi;Fiorino/Utilitário;;;(11) 3123-4567\n"
)


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "motoristas.csv"
    caminho.write_bytes(CSV.encode("utf-8"))
    return str(caminho)


def _escrever(tmp_path, texto, nome="m.csv"):
    caminho = tmp_path / nome
    caminho.write_bytes(texto.encode("utf-8"))
    return str(caminho)


def _sem_banco(monkeypatch):
    async def proibido(dsn):
        raise AssertionError("não era para conectar no banco")

    monkeypatch.setattr(script, "conectar", proibido)


def _lojas(banco):
    banco.db.execute("INSERT INTO lojas (nome, lat, lng) VALUES ('Atacadão Guarujá', -23.9, -46.2)")
    banco.db.execute("INSERT INTO lojas (nome, lat, lng) VALUES ('Atacadão Campinas', -22.9, -47.0)")
    banco.db.execute("INSERT INTO lojas (nome, lat, lng, ativo) VALUES ('Atacadão Fechada', -22.9, -47.0, 0)")


@pytest.fixture
def banco_falso(monkeypatch):
    """Cada conexão do script é uma conexão nova sobre o MESMO banco SQLite (o Neon derruba conexão ociosa)."""
    banco = criar_banco_sqlite()
    _lojas(banco)
    conexoes = []

    async def conectar(dsn):
        conexoes.append(dsn)
        return banco

    monkeypatch.setattr(script, "conectar", conectar)
    monkeypatch.setenv("DATABASE_URL", "postgres://usuario:segredo@host.neon.tech/db?sslmode=require&channel_binding=require")
    banco.conexoes = conexoes
    return banco


# ----------------------------------------------------------------------------------------------------------
# Leitura e classificação
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    ("Passeio", "Carro de passeio"), ("passeio", "Carro de passeio"), ("Carro de passeio", "Carro de passeio"), ("CARRO", "Carro de passeio"),
    ("Carro Passeio", "Carro de passeio"), ("carro de passeio ", "Carro de passeio"),
    ("Utilitário", "Fiorino/Utilitário"), ("utilitario", "Fiorino/Utilitário"), ("Fiorino", "Fiorino/Utilitário"),
    ("FIORINO/UTILITÁRIO", "Fiorino/Utilitário"), ("Fiorino / Utilitario", "Fiorino/Utilitário"), ("Utilitário/Fiorino", "Fiorino/Utilitário"),
    ("Moto", None), ("Caminhão", None), ("", None), ("Passeio e Fiorino", None), (None, None),
])
def test_reconhecer_tipo(texto, esperado):
    assert carga.reconhecer_tipo(texto) == esperado


def test_separar_lojas_por_ponto_e_virgula_ou_barra():
    assert carga.separar_lojas("Atacadão A; Atacadão B | Atacadão C ;;  ") == ["Atacadão A", "Atacadão B", "Atacadão C"]
    assert carga.separar_lojas("Atacadão A;atacadao a") == ["Atacadão A"]  # mesma loja (sem acento/maiúsculas): uma só
    assert carga.separar_lojas("") == [] and carga.separar_lojas(None) == []


def test_cabecalhos_por_nome_sem_diferenca_de_maiusculas_acentos_ou_espacos(tmp_path):
    caminho = _escrever(tmp_path, "TELEFONE,diaria,TIPO DE VEICULO,Nome,codigo,LOJAS\n(11) 91234-5678,\"150,5\",Passeio,Ana,mot-1,Loja X\n")
    r = carga.ler_csv_motoristas(caminho)
    assert r.delimitador == "," and len(r.linhas) == 1
    l = r.linhas[0]
    assert (l.codigo, l.nome, l.tipo, l.lojas_nomes, str(l.valor), l.telefone, l.status) == ("MOT-1", "Ana", "Carro de passeio", ["Loja X"], "150.50", "11912345678", "valida")


def test_sem_a_coluna_codigo_o_arquivo_e_recusado_com_mensagem_clara(tmp_path):
    with pytest.raises(ValueError, match="Código"):
        carga.ler_csv_motoristas(_escrever(tmp_path, "Nome;Tipo de veículo\nAna;Passeio\n"))
    with pytest.raises(ValueError, match="colunas de motoristas"):
        carga.ler_csv_motoristas(_escrever(tmp_path, "A;B\n1;2\n", "x.csv"))


def test_classificacao_das_linhas(arquivo):
    r = carga.ler_csv_motoristas(arquivo)
    por_codigo = {l.codigo or "": l for l in r.linhas}
    assert por_codigo["MOT-0001"].status == "valida" and por_codigo["MOT-0001"].telefone == "11912345678"
    assert por_codigo["MOT-0001"].tipo == "Fiorino/Utilitário" and str(por_codigo["MOT-0001"].valor) == "260.50"
    assert str(por_codigo["MOT-0002"].valor) == "130.50" and por_codigo["MOT-0002"].lojas_nomes == ["Atacadão Guarujá", "Atacadão Campinas"]
    assert por_codigo["MOT-0003"].status == "valida" and por_codigo["MOT-0003"].telefone == "21988887777"
    assert por_codigo["MOT-0004"].status == "invalida" and por_codigo["MOT-0004"].problemas == ["tipo"]
    assert por_codigo[""].status == "invalida" and "sem_codigo" in por_codigo[""].problemas
    assert por_codigo["MOT-0006"].status == "invalida" and por_codigo["MOT-0006"].problemas == ["telefone"] and por_codigo["MOT-0006"].telefone is None
    assert por_codigo["MOT-0007"].status == "valida" and por_codigo["MOT-0007"].telefone == "1131234567"


def test_nomes_repetidos_sao_aceitos_com_codigos_diferentes(arquivo):
    r = carga.ler_csv_motoristas(arquivo)
    joao = [l for l in r.linhas if l.nome == "João Silva"]
    assert [l.status for l in joao] == ["valida", "valida"]
    assert carga.resumir(r)["nomes_repetidos"] == 1


def test_codigo_repetido_no_arquivo_vale_a_ultima_e_e_avisado(tmp_path):
    caminho = _escrever(tmp_path, CABECALHO + "MOT-1;Ana;Passeio;;;\nmót-1;Ana Maria;Utilitário;;;\nMOT-2;Beto;Passeio;;;\n")
    r = carga.ler_csv_motoristas(caminho)
    assert [l.status for l in r.linhas] == ["duplicada_ignorada", "valida", "valida"]
    resumo = carga.resumir(r)
    assert resumo["repetidos"] == [("MOT-1", [2, 3])]
    assert [l.nome for l in carga.para_gravar(r)] == ["Ana Maria", "Beto"]


def test_virgula_decimal_ponto_decimal_e_diaria_invalida(tmp_path):
    caminho = _escrever(tmp_path, CABECALHO + 'A-1;Ana;Passeio;;"1.234,56";\nA-2;Beto;Passeio;;150.5;\nA-3;Carla;Passeio;;-10;\nA-4;Davi;Passeio;;abc;\nA-5;Eva;Passeio;;;\n')
    r = carga.ler_csv_motoristas(caminho)
    assert [str(l.valor) if l.valor is not None else None for l in r.linhas] == ["1234.56", "150.50", None, None, None]
    assert [l.status for l in r.linhas] == ["valida", "valida", "invalida", "invalida", "valida"]


def test_telefone_nunca_aparece_no_repr_da_linha(arquivo):
    r = carga.ler_csv_motoristas(arquivo)
    assert "11912345678" not in repr(r.linhas[0]) and "91234" not in repr(r)


def test_conferir_lojas_pelo_nome_normalizado_e_desativada_conta_como_nao_achada(arquivo):
    r = carga.ler_csv_motoristas(arquivo)
    carga.conferir_lojas(r, [{"id": 1, "nome": "ATACADÃO GUARUJA", "ativo": True}, {"id": 2, "nome": "Atacadão  Campinas", "ativo": True},
                             {"id": 3, "nome": "Atacadão Inexistente", "ativo": False}])
    por_codigo = {l.codigo: l for l in r.linhas}
    assert por_codigo["MOT-0001"].lojas_ids == [1] and por_codigo["MOT-0002"].lojas_ids == [1, 2]
    assert por_codigo["MOT-0003"].lojas_ids == [] and por_codigo["MOT-0003"].lojas_nao_encontradas == ["Atacadão Inexistente (desativada)"]


# ----------------------------------------------------------------------------------------------------------
# Resumo (script)
# ----------------------------------------------------------------------------------------------------------
def test_resumo_com_banco_lista_tudo_e_nao_grava(arquivo, banco_falso, capsys):
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "linhas lidas: 7" in texto and "MOTORISTAS VÁLIDOS (serão gravados): 4" in texto
    assert "com telefone: 3 | sem telefone: 1" in texto
    assert "SEM CÓDIGO (recusadas): 1 (linhas 6)" in texto
    assert 'TIPO DE VEÍCULO NÃO RECONHECIDO (recusadas): 1' in texto and '"Moto": 1 linha(s)' in texto
    assert "LOJAS NÃO ENCONTRADAS" in texto and '"Atacadão Inexistente": 1 motorista(s)' in texto
    assert "nomes repetidos (aceitos, pois os códigos são diferentes): 1" in texto
    assert "Nada foi gravado" in texto
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motoristas").fetchone()[0] == 0
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motorista_lojas").fetchone()[0] == 0


def test_resumo_lista_os_codigos_das_linhas_com_telefone_invalido_e_nunca_os_numeros(tmp_path, banco_falso, capsys):
    caminho = _escrever(tmp_path, CABECALHO + (
        "MOT-0010;Ana;Passeio;;;(11) 91234-5678\n"
        "MOT-0011;Beto;Passeio;;;91234-5678\n"
        "MOT-0012;Carla;Passeio;;;(00) 91234-5678\n"
        "MOT-0013;Davi;Passeio;;;12345\n"
        ";Eva;Passeio;;;98765-4321\n"
        "MOT-0015;Fábio;Passeio;;;21 3123-4567\n"))
    script.main(["--csv", caminho])
    texto = capsys.readouterr().out
    assert "TELEFONES INVÁLIDOS (linha recusada): 4" in texto
    assert "MOT-0011, MOT-0012, MOT-0013, linha 6" in texto  # a sem código sai pelo número da linha
    assert "com telefone: 2 | sem telefone: 0" in texto
    # nenhum número de telefone (nem pedaço) em lugar nenhum do resumo
    for pedaco in ("91234", "5678", "98765", "4321", "31234", "3123", "11912345678", "12345"):
        assert pedaco not in texto, pedaco
    assert not re.search(r"\d{8,}", texto)


def test_resumo_so_tem_contagens_de_telefone(arquivo, banco_falso, capsys):
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "91234" not in texto and "98888" not in texto and "3123-4567" not in texto and "21988887777" not in texto


def test_sem_database_url_o_resumo_avisa_e_segue_sem_conferir_as_lojas(arquivo, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "DATABASE_URL" in texto and "NÃO foram conferidas" in texto and "LOJAS NÃO ENCONTRADAS" not in texto
    assert "MOTORISTAS VÁLIDOS (serão gravados): 4" in texto


def test_sem_nomes_de_loja_no_arquivo_nem_conecta_para_conferir(tmp_path, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:s@h/db")
    script.main(["--csv", _escrever(tmp_path, CABECALHO + "MOT-1;Ana;Passeio;;;\n")])
    assert "MOTORISTAS VÁLIDOS (serão gravados): 1" in capsys.readouterr().out


def test_a_conferencia_das_lojas_e_so_leitura(arquivo, banco_falso, capsys):
    script.main(["--csv", arquivo])
    escritas = [s for s in banco_falso.sqls if re.match(r"\s*(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)", s, re.IGNORECASE)]
    assert escritas == []


# ----------------------------------------------------------------------------------------------------------
# Gravação
# ----------------------------------------------------------------------------------------------------------
def test_gravar_pede_confirmacao_e_cancela_sem_gravar(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "não")
    script.main(["--csv", arquivo, "--gravar"])
    assert "Cancelado" in capsys.readouterr().out
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motoristas").fetchone()[0] == 0


def test_gravar_com_confirmacao_digitada(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    texto = capsys.readouterr().out
    assert "motoristas novos: 4" in texto and "Gravado: 4 motorista(s) novo(s), 0 atualizado(s), 0 preservado(s), 3 vínculo(s)" in texto
    linhas = banco_falso.db.execute("SELECT codigo, nome, tipo_veiculo, valor_rota, telefone, ativo, atualizado_por FROM motoristas ORDER BY codigo").fetchall()
    assert [tuple(l) for l in linhas] == [
        ("MOT-0001", "João Silva", "Fiorino/Utilitário", 260.5, "11912345678", 1, "carga inicial (script)"),
        ("MOT-0002", "João Silva", "Carro de passeio", 130.5, None, 1, "carga inicial (script)"),
        ("MOT-0003", "Ana Souza", "Fiorino/Utilitário", None, "21988887777", 1, "carga inicial (script)"),
        ("MOT-0007", "Davi", "Fiorino/Utilitário", None, "1131234567", 1, "carga inicial (script)"),
    ]
    vinculos = banco_falso.db.execute(
        "SELECT m.codigo, l.nome FROM motorista_lojas ml JOIN motoristas m ON m.id = ml.motorista_id JOIN lojas l ON l.id = ml.loja_id ORDER BY m.codigo, l.nome").fetchall()
    assert [tuple(v) for v in vinculos] == [("MOT-0001", "Atacadão Guarujá"), ("MOT-0002", "Atacadão Campinas"), ("MOT-0002", "Atacadão Guarujá")]
    assert "91234" not in texto and "98888" not in texto


def test_gravar_duas_vezes_nao_duplica(arquivo, banco_falso):
    script.main(["--csv", arquivo, "--gravar", "--sim"])
    script.main(["--csv", arquivo, "--gravar", "--sim"])
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motoristas").fetchone()[0] == 4
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motorista_lojas").fetchone()[0] == 3


def test_upsert_nao_sobrescreve_o_que_o_operador_editou_na_tela(arquivo, banco_falso, tmp_path, capsys):
    script.main(["--csv", arquivo, "--gravar", "--sim"])
    banco_falso.db.execute("UPDATE motoristas SET nome = 'Nome Corrigido', atualizado_por = ? WHERE codigo = 'MOT-0001'", (OPERADOR_TELA,))
    segundo = _escrever(tmp_path, CABECALHO + "MOT-0001;Nome Do Arquivo;Passeio;Atacadão Campinas;100;\nMOT-0002;João Silva Novo;Passeio;;;\n", "segundo.csv")
    script.main(["--csv", segundo, "--gravar", "--sim"])
    texto = capsys.readouterr().out
    assert "1 preservado(s)" in texto and "1 atualizado(s)" in texto
    nomes = dict(banco_falso.db.execute("SELECT codigo, nome FROM motoristas").fetchall())
    assert nomes["MOT-0001"] == "Nome Corrigido" and nomes["MOT-0002"] == "João Silva Novo"
    # o vínculo novo do motorista preservado também não entra
    assert banco_falso.db.execute("SELECT COUNT(*) FROM motorista_lojas ml JOIN motoristas m ON m.id = ml.motorista_id WHERE m.codigo = 'MOT-0001'").fetchone()[0] == 1
    script.main(["--csv", segundo, "--gravar", "--sim", "--sobrescrever-editados"])
    assert dict(banco_falso.db.execute("SELECT codigo, nome FROM motoristas").fetchall())["MOT-0001"] == "Nome Do Arquivo"


def test_motorista_desativado_nao_e_reativado_e_campos_em_branco_nao_apagam(arquivo, banco_falso, tmp_path):
    script.main(["--csv", arquivo, "--gravar", "--sim"])
    banco_falso.db.execute("UPDATE motoristas SET ativo = 0 WHERE codigo = 'MOT-0001'")  # atualizado_por segue sendo a carga
    segundo = _escrever(tmp_path, CABECALHO + "MOT-0001;João Silva;Utilitário;;;\n", "segundo.csv")
    script.main(["--csv", segundo, "--gravar", "--sim"])
    linha = banco_falso.db.execute("SELECT ativo, telefone, valor_rota FROM motoristas WHERE codigo = 'MOT-0001'").fetchone()
    assert tuple(linha) == (0, "11912345678", 260.5)


def test_codigo_do_arquivo_acha_o_motorista_sem_diferenca_de_maiusculas_ou_espacos(banco_falso, tmp_path):
    script.main(["--csv", _escrever(tmp_path, CABECALHO + "MOT-0001;Ana;Passeio;;;\n"), "--gravar", "--sim"])
    script.main(["--csv", _escrever(tmp_path, CABECALHO + "mot-0001;Ana Maria;Passeio;;;\n", "b.csv"), "--gravar", "--sim"])
    assert [tuple(l) for l in banco_falso.db.execute("SELECT codigo, nome FROM motoristas").fetchall()] == [("MOT-0001", "Ana Maria")]


def test_sem_database_url_gravar_para_com_mensagem(arquivo, monkeypatch):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as saida:
        script.main(["--csv", arquivo, "--gravar"])
    assert "DATABASE_URL" in str(saida.value)


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
    linhas = carga.para_gravar(carga.ler_csv_motoristas(arquivo))
    feito = asyncio.run(script.com_conexao("dsn", lambda c: carga.gravar_carga(c, linhas), dormir=sem_espera))
    assert feito["novos"] == 4 and len(tentativas) == 2
    assert banco.db.execute("SELECT count(*) FROM motoristas").fetchone()[0] == 4


def test_arquivo_inexistente_e_mensagem_clara(tmp_path):
    with pytest.raises(SystemExit) as saida:
        script.main(["--csv", str(tmp_path / "nao_existe.csv")])
    assert "não achei" in str(saida.value)


def test_pasta_de_dados_dos_motoristas_esta_no_gitignore():
    assert "data/motoristas/" in (RAIZ / ".gitignore").read_text(encoding="utf-8")
