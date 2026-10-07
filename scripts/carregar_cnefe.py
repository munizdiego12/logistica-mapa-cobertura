"""
Carga offline do CNEFE 2022 (IBGE) por prefixo de CEP de 5 dígitos (Etapa 2b), uma UF por vez.

Para cada UF: baixa o CSV (data/cnefe/, fora do git), agrega por partes (memória baixa, mesmo em SP),
grava na tabela cep_prefixos com upsert pela chave (prefixo) e APAGA o arquivo baixado. Nunca apaga a
tabela nem linhas existentes. Para sozinho se a tabela passar do limite de tamanho (padrão 100 MB).

Uso:
    python scripts/carregar_cnefe.py --uf AC --sqlite data/cnefe/teste_ac.db   # teste local em SQLite
    python scripts/carregar_cnefe.py --uf AC DF                                # uma ou mais UFs no Postgres
    python scripts/carregar_cnefe.py --todas --pular AC DF                     # Brasil, das menores para as maiores

A URL do Postgres NUNCA deve ficar escrita em arquivo. Configure só na sessão:
    $env:DATABASE_URL = "postgresql://usuario:senha@host/nome_do_banco"   (PowerShell)

Fonte dos dados: IBGE, CNEFE 2022. Exportações que usem esta tabela devem trazer essa atribuição.
"""
import argparse
import os
import sqlite3
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backend.cnefe import (  # noqa: E402
    COLUNAS_CNEFE,
    LIMITE_AVISO_ENDERECOS_FORA_DA_UF,
    LimiteExcedido,
    agregar_prefixos,
    gravar_postgres,
    gravar_sqlite,
    tamanho_tabela_postgres,
    tamanho_tabela_sqlite,
)

URL_BASE = (
    "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
    "Censo_Demografico_2022/Arquivos_CNEFE/CSV/UF/"
)
CODIGOS_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22,
    "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32,
    "RJ": 33, "SP": 35, "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}
# Tamanho do download de cada UF (MB, listagem do IBGE). Define a ordem: das menores para as maiores.
TAMANHO_DOWNLOAD_MB = {
    "RR": 4.3, "AP": 5.2, "AC": 6.7, "TO": 15, "RO": 16, "DF": 19, "SE": 20, "AL": 28, "AM": 28, "MS": 28,
    "PI": 33, "RN": 33, "MT": 36, "PB": 39, "ES": 40, "MA": 74, "PA": 98, "SC": 113, "GO": 115, "CE": 132,
    "PE": 144, "PR": 231, "RS": 236, "RJ": 322, "BA": 380, "MG": 512, "SP": 1024,
}
# Prefixos de 5 dígitos que a lista oficial de CEPs do IBGE tem em cada UF (faixas de CEP dos Correios).
# Serve de conferência: a carga avisa se o resultado ficar longe disso.
PREFIXOS_ESPERADOS = {
    "RR": 43, "AP": 44, "AC": 45, "TO": 238, "RO": 139, "DF": 755, "SE": 174, "AL": 208, "AM": 209, "MS": 308,
    "PI": 344, "RN": 326, "MT": 407, "PB": 390, "ES": 421, "MA": 360, "PA": 490, "SC": 734, "GO": 1034, "CE": 1118,
    "PE": 852, "PR": 1438, "RS": 1726, "RJ": 1542, "BA": 1500, "MG": 2477, "SP": 7327,
}
RAIZ = Path(__file__).resolve().parent.parent
PASTA_PADRAO = RAIZ / "data" / "cnefe"
LINHAS_POR_BLOCO = 250_000
LIMITE_PADRAO_MB = 100
LIMITE_FORA_DA_UF = 0.01  # acima de 1% dos endereços com CEP de outra UF, a carga da UF é recusada


def ordem_ufs(ufs=None, pular=()) -> list:
    """UFs do menor para o maior download (empate pela sigla). `ufs` None = todas; `pular` tira UFs da lista."""
    escolhidas = set(CODIGOS_UF if ufs is None else ufs) - set(pular)
    return sorted(escolhidas, key=lambda uf: (TAMANHO_DOWNLOAD_MB[uf], uf))


def pico_memoria_mb():
    """Pico de memória do processo em MB (None se não der para medir neste sistema)."""
    try:
        import resource  # Linux/macOS

        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return pico / (1e6 if sys.platform == "darwin" else 1e3)
    except ImportError:
        pass
    try:  # Windows
        import ctypes
        from ctypes import wintypes

        class Contadores(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
        k.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        c = Contadores()
        c.cb = ctypes.sizeof(c)
        return c.PeakWorkingSetSize / 1e6 if k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb) else None
    except Exception:
        return None


def baixar_uf(uf: str, pasta: Path) -> Path:
    nome = f"{CODIGOS_UF[uf]}_{uf}.zip"
    destino = pasta / nome
    if destino.exists():
        print(f"  usando arquivo já baixado: {destino}")
        return destino
    pasta.mkdir(parents=True, exist_ok=True)
    print(f"  baixando {nome} (~{TAMANHO_DOWNLOAD_MB[uf]:g} MB) ...")
    parcial = destino.with_suffix(".zip.parcial")
    try:
        urllib.request.urlretrieve(URL_BASE + nome, parcial)
        parcial.replace(destino)
    finally:
        parcial.unlink(missing_ok=True)
    return destino


def ler_blocos(arquivo_zip: Path):
    with zipfile.ZipFile(arquivo_zip) as z:
        nome_csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome_csv) as f:
            yield from pd.read_csv(
                f, sep=";", dtype=str, usecols=COLUNAS_CNEFE, encoding="utf-8", chunksize=LINHAS_POR_BLOCO
            )


class DestinoSqlite:
    descricao = "SQLite"

    def __init__(self, caminho: str):
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho)
        self.descricao = f"SQLite {caminho}"

    def tamanho_atual(self) -> int:
        existe = self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'cep_prefixos'").fetchone()
        return tamanho_tabela_sqlite(self.conn) if existe else 0

    def gravar(self, linhas, limite_bytes, relatorio):
        return gravar_sqlite(self.conn, linhas, limite_bytes, relatorio)

    def fechar(self):
        self.conn.close()


class DestinoPostgres:
    descricao = "Postgres (DATABASE_URL)"

    def __init__(self, url: str):
        import psycopg2

        self.conn = psycopg2.connect(url)

    def tamanho_atual(self) -> int:
        return tamanho_tabela_postgres(self.conn)

    def gravar(self, linhas, limite_bytes, relatorio):
        return gravar_postgres(self.conn, linhas, limite_bytes, relatorio)

    def fechar(self):
        self.conn.close()


def processar_uf(uf: str, pasta: Path, abrir_destino, limite_bytes: int, manter_download: bool) -> dict:
    """Baixa, agrega, grava e apaga o download de uma UF. Levanta LimiteExcedido se a tabela passar do limite."""
    inicio = time.time()
    destino = abrir_destino()
    try:
        atual = destino.tamanho_atual()
        if atual > limite_bytes:
            raise LimiteExcedido(atual, limite_bytes)  # já passou do limite: nem baixa a próxima UF

        arquivo = baixar_uf(uf, pasta)
        linhas, est = agregar_prefixos(ler_blocos(arquivo), uf)
        if not linhas:
            raise RuntimeError(f"{uf}: nenhum prefixo calculado; nada foi gravado")
        if est["enderecos_fora_da_uf"] > LIMITE_FORA_DA_UF * est["linhas_lidas"]:
            raise RuntimeError(
                f"{uf}: {est['enderecos_fora_da_uf']:,} endereços ({est['enderecos_fora_da_uf'] / est['linhas_lidas']:.1%}) "
                "têm CEP fora da faixa da UF; arquivo errado ou tabela de faixas desatualizada. Nada foi gravado"
            )

        relatorio = {}
        novas, atualizadas = destino.gravar(linhas, limite_bytes, relatorio)
    finally:
        destino.fechar()

    if not manter_download:  # só chega aqui se gravou: em caso de erro o arquivo fica para tentar de novo
        arquivo.unlink(missing_ok=True)
    return {
        "uf": uf, "enderecos": est["linhas_lidas"], "descartados": est["linhas_descartadas"], "prefixos": len(linhas),
        "sem_ponto_exato": est["prefixos_sem_ponto_exato"], "fora_da_uf": est["prefixos_fora_da_uf"], "novas": novas, "atualizadas": atualizadas,
        "mantidas": relatorio["mantidas"], "conflitos": relatorio["conflitos"],
        "tamanho_mb": relatorio["tamanho_bytes"] / 1e6, "segundos": time.time() - inicio,
        "apagado": not manter_download
    }


def imprimir_resultado(r: dict) -> None:
    esperado = PREFIXOS_ESPERADOS.get(r["uf"])
    aviso = ""
    if esperado and not 0.9 * esperado <= r["prefixos"] <= 1.1 * esperado:
        aviso = f"  ⚠ CONFIRA: esperado ~{esperado} prefixos"
    pico = pico_memoria_mb()
    print(
        f"  {r['uf']}: {r['enderecos']:,} endereços ({r['descartados']:,} descartados) -> {r['prefixos']} prefixos "
        f"(esperado ~{esperado}){aviso}\n"
        f"      gravados: {r['novas']} novos, {r['atualizadas']} atualizados, {r['mantidas']} mantidos de outra UF | "
        f"sem ponto exato: {r['sem_ponto_exato']}\n"
        f"      tabela no banco: {r['tamanho_mb']:.2f} MB | pico de memória do processo: "
        f"{'%.0f MB' % pico if pico else 'n/d'} | {r['segundos']:.0f}s | "
        f"download {'apagado' if r['apagado'] else 'mantido'}"
    )
    if r["fora_da_uf"]:
        print(f"      descartados {len(r['fora_da_uf'])} prefixo(s) com CEP fora da faixa de {r['uf']} (provável erro de digitação no CNEFE):")
        for f in sorted(r["fora_da_uf"], key=lambda f: -f["n_enderecos"])[:5]:
            alerta = "  ⚠ CONFIRA" if f["n_enderecos"] >= LIMITE_AVISO_ENDERECOS_FORA_DA_UF else ""
            print(f"        {f['prefixo']}: {f['n_enderecos']} endereço(s), município {f['cod_municipio']}{alerta}")
    for c in r["conflitos"][:5]:
        destino = "substituído" if c["substitui"] else "mantido"
        print(
            f"      prefixo {c['prefixo']} já estava como {c['uf_existente']} ({c['n_existente']} end.); "
            f"{c['uf_nova']} tem {c['n_novo']} -> {destino}"
        )


def main():
    parser = argparse.ArgumentParser(description="Agrega o CNEFE 2022 por prefixo de CEP e grava com upsert, uma UF por vez.")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--uf", nargs="+", choices=sorted(CODIGOS_UF), metavar="UF", help="uma ou mais UFs")
    grupo.add_argument("--todas", action="store_true", help="todas as UFs, das menores para as maiores")
    parser.add_argument("--pular", nargs="+", default=[], choices=sorted(CODIGOS_UF), metavar="UF", help="UFs a pular (com --todas)")
    parser.add_argument("--sqlite", metavar="ARQUIVO", help="grava num SQLite local em vez do Postgres")
    parser.add_argument("--pasta", default=str(PASTA_PADRAO), help="onde guardar o download (padrão: data/cnefe)")
    parser.add_argument("--limite-mb", type=float, default=LIMITE_PADRAO_MB, help="para se a tabela passar disso (padrão: 100)")
    parser.add_argument("--manter-download", action="store_true", help="não apaga o arquivo baixado depois de gravar")
    args = parser.parse_args()

    if args.sqlite:
        def abrir_destino():
            return DestinoSqlite(args.sqlite)
    else:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            sys.exit("ERRO: defina DATABASE_URL (Postgres) ou use --sqlite ARQUIVO para um teste local.")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        def abrir_destino():
            return DestinoPostgres(database_url)

    ufs = ordem_ufs(None if args.todas else args.uf, args.pular)
    if not ufs:
        sys.exit("Nenhuma UF para processar.")
    limite_bytes = int(args.limite_mb * 1e6)
    total_mb = sum(TAMANHO_DOWNLOAD_MB[u] for u in ufs)
    print(f"{len(ufs)} UF(s), das menores para as maiores: {' '.join(ufs)}")
    print(f"Limite da tabela: {args.limite_mb:g} MB | cada download é apagado depois de gravado (maior: {max(TAMANHO_DOWNLOAD_MB[u] for u in ufs):g} MB; total ~{total_mb:.0f} MB)\n")

    feitas, total_prefixos = [], 0
    for numero, uf in enumerate(ufs, start=1):
        print(f"[{numero}/{len(ufs)}] {uf}")
        try:
            resultado = processar_uf(uf, Path(args.pasta), abrir_destino, limite_bytes, args.manter_download)
        except LimiteExcedido as e:
            print(f"\nPAROU em {uf}: {e}. Nada de {uf} foi gravado; o que veio antes está salvo.")
            print(f"UFs já gravadas nesta execução: {' '.join(feitas) or 'nenhuma'}")
            sys.exit(2)
        imprimir_resultado(resultado)
        feitas.append(uf)
        total_prefixos += resultado["prefixos"]
        print()
    print(f"Concluído: {len(feitas)} UF(s), {total_prefixos} prefixos gravados. Tabela no banco: {resultado['tamanho_mb']:.2f} MB.")


if __name__ == "__main__":
    main()
