"""
Conferência SOMENTE LEITURA da cobertura no banco apontado por DATABASE_URL (só executa SELECT).

Roda a mesma consulta que o endpoint /api/cobertura-ceps usa (prefixos do CNEFE + faixas manuais) para
alguns hubs e imprime as contagens, para comparar com o esperado antes de publicar.

Uso (PowerShell, na raiz do projeto; a string do banco só na sessão, nunca em arquivo ou no chat):
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/conferir_cobertura.py
    Remove-Item Env:DATABASE_URL
"""
import asyncio
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERRO: defina DATABASE_URL (Postgres) antes de rodar.")

import cobertura  # noqa: E402
import database  # noqa: E402

RAIO_KM = 30.0
HUBS = {
    "DF - Plano Piloto (Rodoviária)": (-15.7942, -47.8822),
    "SP - Av. Paulista": (-23.5613, -46.6565),
    "RJ - Av. Atlântica (Copacabana)": (-22.9714, -43.1852),
    "SC - Florianópolis": (-27.5954, -48.5480),
    "AC - Rio Branco (centro)": (-9.9754, -67.8249),
}


async def main():
    ufs = await database.ufs_com_prefixos()
    print(f"UFs com prefixos no banco: {sorted(ufs)}")
    for nome, (lat, lon) in HUBS.items():
        prefixos = await database.consultar_prefixos_por_raio(lat, lon, RAIO_KM)
        faixas = await database.consultar_ceps_por_raio(lat, lon, RAIO_KM)
        pontos = cobertura.combinar_cobertura(prefixos, faixas, ufs, RAIO_KM)
        resumo = cobertura.resumir_cobertura(pontos)
        origem = dict(collections.Counter((p["uf"], p["precisao"]) for p in pontos))
        print(f"\n{nome} (raio {RAIO_KM:.0f} km)")
        print(f"  prefixos na consulta: {len(prefixos)} | faixas na consulta antiga: {len(faixas)}")
        print(f"  resultado: {len(pontos)} pontos -> Total {resumo['total']}, Parcial {resumo['parcial']}")
        print(f"  por origem: {origem}")
        if not pontos:
            print("  -> sem pontos: o endpoint devolve o aviso de região sem cobertura")
    if database._pool is not None:
        await database._pool.close()


asyncio.run(main())
