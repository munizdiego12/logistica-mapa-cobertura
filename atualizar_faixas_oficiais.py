import psycopg2
from psycopg2.extras import execute_values

# Sua External Database URL do Render
DATABASE_URL = "postgresql://routeflow_db_tvnb_user:TwIdM5qME7Fsf9r4nXtEmpBTYvD6jTVh@dpg-da7fc0oae00c73bm74e0-a.ohio-postgres.render.com/routeflow_db_tvnb"

# Tabela oficial de Faixas e Distritos do Brasil (Macro e Micro ranges)
FAIXAS_OFICIAIS_BRASIL = [
    # SP - Capital por Zonas
    ("01000000", "01999999", "SP", "São Paulo", "Centro / Região Central", -23.5505, -46.6333),
    ("02000000", "02999999", "SP", "São Paulo", "Zona Norte / Santana / Tucuruvi", -23.4980, -46.6230),
    ("03000000", "03999999", "SP", "São Paulo", "Zona Leste / Tatuapé / Mooca", -23.5400, -46.5750),
    ("04000000", "04999999", "SP", "São Paulo", "Zona Sul / Moema / Santo Amaro", -23.6062, -46.6653),
    ("05000000", "05999999", "SP", "São Paulo", "Zona Oeste / Pinheiros / Lapa", -23.5670, -46.6940),
    ("08000000", "08499999", "SP", "São Paulo", "Zona Leste Extrema / Itaquera", -23.5350, -46.4520),

    # Grande SP / Região Metropolitana
    ("06000000", "06299999", "SP", "Osasco", "Sede / Centro / Bairros", -23.5329, -46.7916),
    ("06300000", "06399999", "SP", "Carapicuíba", "Sede / Centro", -23.5222, -46.8356),
    ("06400000", "06499999", "SP", "Barueri / Alphaville", "Sede / Alphaville", -23.5105, -46.8761),
    ("06500000", "06549999", "SP", "Santana de Parnaíba", "Sede / Centro", -23.4442, -46.9178),
    ("06700000", "06729999", "SP", "Cotia", "Sede / Granja Viana", -23.6039, -46.9190),
    ("06750000", "06799999", "SP", "Taboão da Serra", "Sede / Centro", -23.6019, -46.7578),
    ("06800000", "06849999", "SP", "Embu das Artes", "Sede / Centro", -23.6492, -46.8525),
    ("06850000", "06899999", "SP", "Itapecerica da Serra", "Sede / Centro", -23.7169, -46.8497),
    ("07000000", "07399999", "SP", "Guarulhos", "Sede / Centro / Aeroporto", -23.4542, -46.5333),
    ("07400000", "07499999", "SP", "Arujá", "Sede / Centro", -23.3967, -46.3211),
    ("07500000", "07599999", "SP", "Santa Isabel", "Sede / Centro", -23.3161, -46.2236),
    ("07600000", "07699999", "SP", "Mairiporã", "Sede / Centro", -23.3186, -46.5867),
    ("07700000", "07749999", "SP", "Caieiras", "Sede / Centro", -23.3644, -46.7408),
    ("07750000", "07799999", "SP", "Franco da Rocha", "Sede / Centro", -23.3283, -46.7269),
    ("07800000", "07899999", "SP", "Francisco Morato", "Sede / Centro", -23.2817, -46.7439),
    ("08500000", "08549999", "SP", "Ferraz de Vasconcelos", "Sede / Centro", -23.5414, -46.3686),
    ("08550000", "08569999", "SP", "Poá", "Sede / Centro", -23.5336, -46.3439),
    ("08570000", "08599999", "SP", "Itaquaquecetuba", "Sede / Centro", -23.4861, -46.3483),
    ("08600000", "08699999", "SP", "Suzano", "Sede / Centro", -23.5425, -46.3108),
    ("08700000", "08899999", "SP", "Mogi das Cruzes", "Sede / Centro / Distritos", -23.5206, -46.1856),
    ("09000000", "09299999", "SP", "Santo André", "Sede / Bairros", -23.6639, -46.5383),
    ("09300000", "09399999", "SP", "Mauá", "Sede / Centro", -23.6678, -46.4614),
    ("09400000", "09449999", "SP", "Ribeirão Pires", "Sede / Centro", -23.7142, -46.4136),
    ("09450000", "09499999", "SP", "Rio Grande da Serra", "Sede / Centro", -23.7436, -46.3986),
    ("09500000", "09599999", "SP", "São Caetano do Sul", "Sede / Bairros", -23.6228, -46.5547),
    ("09600000", "09899999", "SP", "São Bernardo do Campo", "Sede / Rudge Ramos / Bairros", -23.6914, -46.5647),
    ("09900000", "09999999", "SP", "Diadema", "Sede / Centro / Bairros", -23.6865, -46.6228),

    # Curitiba e Região
    ("80000000", "82999999", "PR", "Curitiba", "Sede / Bairros / Distritos", -25.4284, -49.2733),
    ("83000000", "83099999", "PR", "São José dos Pinhais", "Sede / Centro", -25.5347, -49.2064),
    ("83200000", "83299999", "PR", "Paranaguá", "Sede / Litoral", -25.5205, -48.5095),
    ("83300000", "83399999", "PR", "Piraquara", "Sede / Centro", -25.4419, -49.0628),
    ("83400000", "83499999", "PR", "Colombo", "Sede / Centro", -25.2917, -49.2242),
    ("83600000", "83699999", "PR", "Campo Largo", "Sede / Centro", -25.4597, -49.5278),
    ("83700000", "83799999", "PR", "Araucária", "Sede / Centro", -25.5928, -49.4103),

    # Fortaleza e Região
    ("60000000", "60999999", "CE", "Fortaleza", "Sede / Bairros / Distritos", -3.7319, -38.5267),
    ("61600000", "61699999", "CE", "Caucaia", "Sede / Litoral", -3.7361, -38.6531),
    ("61900000", "61999999", "CE", "Maracanaú", "Sede / Centro", -3.8767, -38.6256),
    ("61760000", "61799999", "CE", "Eusébio", "Sede / Centro", -3.8906, -38.4528),
    ("61800000", "61899999", "CE", "Aquiraz", "Sede / Centro", -3.9011, -38.3911)
]

def recarregar_faixas():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("""
        DROP TABLE IF EXISTS ceps_reais;
        CREATE TABLE ceps_reais (
            id SERIAL PRIMARY KEY,
            cep_inicial VARCHAR(8) NOT NULL,
            cep_final VARCHAR(8) NOT NULL,
            uf VARCHAR(2) NOT NULL,
            cidade VARCHAR(100) NOT NULL,
            bairro VARCHAR(100) NOT NULL,
            lat NUMERIC(10, 7) NOT NULL,
            lon NUMERIC(10, 7) NOT NULL
        );
        CREATE INDEX idx_ceps_coords ON ceps_reais(lat, lon);
    """)
    
    query = """
        INSERT INTO ceps_reais (cep_inicial, cep_final, uf, cidade, bairro, lat, lon)
        VALUES %s;
    """
    
    execute_values(cur, query, FAIXAS_OFICIAIS_BRASIL)
    conn.commit()
    cur.close()
    conn.close()
    print("Sucesso: Tabela atualizada com as Faixas Oficiais de CEP (DNE)!")

if __name__ == "__main__":
    recarregar_faixas()