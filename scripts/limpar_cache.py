import os
import sys
import psycopg2

# A URL de conexão NUNCA deve ficar escrita no código-fonte.
# Configure a variável de ambiente DATABASE_URL antes de rodar este script, ex:
#   export DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"   (Linux/macOS)
#   $env:DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"     (PowerShell)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERRO: a variável de ambiente DATABASE_URL não está definida.")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def limpar_tabela_cache():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Limpa a tabela de cache de coordenadas
    cur.execute("TRUNCATE TABLE geocode_cache;")
    conn.commit()

    cur.close()
    conn.close()
    print("Sucesso: Tabela de cache de coordenadas limpa com sucesso!")

if __name__ == "__main__":
    limpar_tabela_cache()
