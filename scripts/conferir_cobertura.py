"""
Conferência SOMENTE LEITURA da cobertura no banco apontado por DATABASE_URL (só executa SELECT).

1) Lista quantos prefixos de CEP cada UF tem em cep_prefixos e avisa se alguma UF está faltando.
2) Roda a mesma consulta do endpoint /api/cobertura-ceps para alguns hubs e imprime as contagens.

Uso (PowerShell, na raiz do projeto; a string do banco só na sessão, nunca em arquivo ou no chat):
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/conferir_cobertura.py
    Remove-Item Env:DATABASE_URL
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERRO: defina DATABASE_URL (Postgres) antes de rodar.")

import cobertura  # noqa: E402
import database  # noqa: E402

RAIO_KM = 30.0
UFS = (
    "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
)
HUBS = {
    "DF - Plano Piloto (Rodoviária)": (-15.7942, -47.8822),
    "SP - Av. Paulista": (-23.5613, -46.6565),
    "RJ - Av. Atlântica (Copacabana)": (-22.9714, -43.1852),
    "SC - Florianópolis": (-27.5954, -48.5480),
    "AC - Rio Branco (centro)": (-9.9754, -67.8249),
}


async def main():
    pool = await database.get_pool()
    if not pool:
        sys.exit("ERRO: não foi possível conectar ao banco.")
    async with pool.acquire() as conn:
        linhas = await conn.fetch("SELECT uf, COUNT(*) AS n FROM cep_prefixos GROUP BY uf ORDER BY uf")
    por_uf = {r["uf"]: r["n"] for r in linhas}
    print(f"UFs com prefixos no banco: {len(por_uf)} de {len(UFS)} | total de prefixos: {sum(por_uf.values())}")
    print("  " + " ".join(f"{uf}={por_uf[uf]}" for uf in sorted(por_uf)))
    faltando = [uf for uf in UFS if uf not in por_uf]
    print(f"  UFs sem prefixos: {faltando if faltando else 'nenhuma'}")

    for nome, (lat, lon) in HUBS.items():
        prefixos = await database.consultar_prefixos_por_raio(lat, lon, RAIO_KM)
        pontos = cobertura.montar_cobertura(prefixos, RAIO_KM)
        resumo = cobertura.resumir_cobertura(pontos)
        print(f"\n{nome} (raio {RAIO_KM:.0f} km)")
        print(f"  {len(pontos)} prefixos -> Total {resumo['total']}, Parcial {resumo['parcial']}")
        if not pontos:
            print("  -> sem pontos: o endpoint devolve o aviso de região sem cobertura")
    if database._pool is not None:
        await database._pool.close()


asyncio.run(main())
