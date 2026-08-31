import psycopg2

DATABASE_URL = "postgresql://routeflow_db_tvnb_user:TwIdM5qME7Fsf9r4nXtEmpBTYvD6jTVh@dpg-da7fc0oae00c73bm74e0-a.ohio-postgres.render.com/routeflow_db_tvnb"

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