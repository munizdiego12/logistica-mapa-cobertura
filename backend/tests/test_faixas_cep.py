import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend import faixas_cep
from backend.faixas_cep import COLUNAS_CSV, ler_faixas_csv, validar_faixas

RAIZ = Path(__file__).resolve().parents[2]


def _faixa(**sobrescrever):
    base = {
        "cep_inicial": "01000000", "cep_final": "01999999", "uf": "SP",
        "cidade": "São Paulo", "bairro": "Centro", "lat": "-23.5505", "lon": "-46.6333",
    }
    base.update(sobrescrever)
    return base


def test_csv_de_faixas_e_valido():
    assert validar_faixas(ler_faixas_csv()) == []


def test_csv_une_os_dois_scripts_antigos():
    faixas = ler_faixas_csv()
    ufs = {f["uf"] for f in faixas}
    assert {"SP", "PR", "CE", "PE", "BA", "RJ", "MG", "RS", "DF", "GO"} <= ufs
    assert any(f["cidade"] == "Paranaguá" for f in faixas)
    assert len(faixas) == 76


def test_validador_aceita_faixas_adjacentes():
    assert validar_faixas([_faixa(), _faixa(cep_inicial="02000000", cep_final="02999999")]) == []


def test_validador_detecta_sobreposicao():
    erros = validar_faixas([_faixa(), _faixa(cep_inicial="01500000", cep_final="02999999")])
    assert len(erros) == 1 and "sobrepõe" in erros[0]


def test_validador_detecta_faixa_duplicada():
    erros = validar_faixas([_faixa(), _faixa()])
    assert any("sobrepõe" in e for e in erros)


def test_validador_detecta_cep_malformado_e_invertido():
    assert any("8 dígitos" in e for e in validar_faixas([_faixa(cep_inicial="1000000")]))
    assert any("8 dígitos" in e for e in validar_faixas([_faixa(cep_final="0199999A")]))
    assert any("maior que" in e for e in validar_faixas([_faixa(cep_inicial="02000000", cep_final="01000000")]))


def test_validador_detecta_uf_texto_e_coordenada_invalidos():
    assert any("UF inválida" in e for e in validar_faixas([_faixa(uf="XX")]))
    assert any("bairro vazio" in e for e in validar_faixas([_faixa(bairro=" ")]))
    assert any("fora do Brasil" in e for e in validar_faixas([_faixa(lat="48.85", lon="2.35")]))
    assert any("não numéricas" in e for e in validar_faixas([_faixa(lat="abc")]))


def test_cabecalho_invalido_levanta_erro(tmp_path):
    arquivo = tmp_path / "faixas.csv"
    arquivo.write_text("cep,uf\n01000000,SP\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ler_faixas_csv(arquivo)


def test_carga_nunca_apaga_a_tabela():
    sql = " ".join(faixas_cep.SCHEMA_CEPS_REAIS + [faixas_cep.INDICE_UNICO_CEPS_REAIS, faixas_cep.UPSERT_CEPS_REAIS])
    carregador = (RAIZ / "scripts" / "carregar_faixas.py").read_text(encoding="utf-8")
    for texto in (sql, carregador):
        assert "DROP" not in texto.upper().replace("DROP NOT NULL", "")
        assert "TRUNCATE" not in texto.upper()
    assert "ON CONFLICT (cep_inicial, cep_final) DO UPDATE" in faixas_cep.UPSERT_CEPS_REAIS


def test_carregador_valida_sem_banco():
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "carregar_faixas.py"), "--validar"],
        capture_output=True, text=True, encoding="utf-8", env={**{k: v for k, v in os.environ.items() if k != "DATABASE_URL"}, "PYTHONIOENCODING": "utf-8"},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "CSV válido: 76 faixas" in resultado.stdout


def test_colunas_do_csv_batem_com_o_cabecalho():
    primeira_linha = (RAIZ / "scripts" / "data" / "faixas_cep.csv").read_text(encoding="utf-8").splitlines()[0]
    assert primeira_linha.split(",") == COLUNAS_CSV
