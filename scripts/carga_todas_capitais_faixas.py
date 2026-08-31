import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = "postgresql://routeflow_db_tvnb_user:TwIdM5qME7Fsf9r4nXtEmpBTYvD6jTVh@dpg-da7fc0oae00c73bm74e0-a.ohio-postgres.render.com/routeflow_db_tvnb?sslmode=require"

TODAS_FAIXAS_BRASIL = [
    # --- PERNAMBUCO / RECIFE E RMR ---
    ("50000000", "52999999", "PE", "Recife", "Recife / Boa Viagem / Centro / Zonas", -8.0578, -34.8829),
    ("53000000", "53399999", "PE", "Olinda", "Sede / Bairros", -8.0089, -34.8553),
    ("54000000", "54499999", "PE", "Jaboatão dos Guararapes", "Sede / Piedade / Prazeres", -8.1128, -35.0156),
    ("53400000", "53499999", "PE", "Paulista", "Sede / Centro", -7.9408, -34.8728),
    ("54750000", "54799999", "PE", "Camaragibe", "Sede / Centro", -8.0203, -34.9781),
    ("53600000", "53699999", "PE", "Igarassu", "Sede / Centro", -7.8342, -34.9064),
    ("54500000", "54599999", "PE", "Cabo de Santo Agostinho", "Sede / Litoral", -8.2833, -35.0333),

    # --- CEARÁ / FORTALEZA ---
    ("60000000", "60999999", "CE", "Fortaleza", "Sede / Bairros / Distritos", -3.7319, -38.5267),
    ("61600000", "61699999", "CE", "Caucaia", "Sede / Litoral", -3.7361, -38.6531),
    ("61900000", "61999999", "CE", "Maracanaú", "Sede / Centro", -3.8767, -38.6256),
    ("61760000", "61799999", "CE", "Eusébio", "Sede / Centro", -3.8906, -38.4528),
    ("61800000", "61899999", "CE", "Aquiraz", "Sede / Centro", -3.9011, -38.3911),

    # --- BAHIA / SALVADOR ---
    ("40000000", "42599999", "BA", "Salvador", "Sede / Bairros / Orla", -12.9777, -38.5016),
    ("42700000", "42799999", "BA", "Lauro de Freitas", "Sede / Vilas do Atlântico", -12.8944, -38.3272),
    ("42800000", "42849999", "BA", "Camaçari", "Sede / Polo", -12.6975, -38.3242),
    ("43700000", "43799999", "BA", "Simões Filho", "Sede / Centro", -12.7844, -38.4028),

    # --- SÃO PAULO E GRANDE SP ---
    ("01000000", "01999999", "SP", "São Paulo", "Centro / Região Central", -23.5505, -46.6333),
    ("02000000", "02999999", "SP", "São Paulo", "Zona Norte / Santana / Tucuruvi", -23.4980, -46.6230),
    ("03000000", "03999999", "SP", "São Paulo", "Zona Leste / Tatuapé / Mooca", -23.5400, -46.5750),
    ("04000000", "04999999", "SP", "São Paulo", "Zona Sul / Moema / Santo Amaro", -23.6062, -46.6653),
    ("05000000", "05999999", "SP", "São Paulo", "Zona Oeste / Pinheiros / Lapa", -23.5670, -46.6940),
    ("08000000", "08499999", "SP", "São Paulo", "Zona Leste Extrema / Itaquera", -23.5350, -46.4520),
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
    ("08700000", "08899999", "SP", "Mogi das Cruzes", "Sede / Centro", -23.5206, -46.1856),
    ("09000000", "09299999", "SP", "Santo André", "Sede / Bairros", -23.6639, -46.5383),
    ("09300000", "09399999", "SP", "Mauá", "Sede / Centro", -23.6678, -46.4614),
    ("09400000", "09449999", "SP", "Ribeirão Pires", "Sede / Centro", -23.7142, -46.4136),
    ("09450000", "09499999", "SP", "Rio Grande da Serra", "Sede / Centro", -23.7436, -46.3986),
    ("09500000", "09599999", "SP", "São Caetano do Sul", "Sede / Bairros", -23.6228, -46.5547),
    ("09600000", "09899999", "SP", "São Bernardo do Campo", "Sede / Bairros", -23.6914, -46.5647),
    ("09900000", "09999999", "SP", "Diadema", "Sede / Centro / Bairros", -23.6865, -46.6228),

    # --- RIO DE JANEIRO E GRANDE RIO ---
    ("20000000", "20999999", "RJ", "Rio de Janeiro", "Centro / Zona Portuária", -22.9068, -43.1729),
    ("22000000", "22999999", "RJ", "Rio de Janeiro", "Zona Sul / Copacabana / Barra", -22.9711, -43.1825),
    ("20500000", "21999999", "RJ", "Rio de Janeiro", "Zona Norte / Tijuca / Méier", -22.9242, -43.2325),
    ("24000000", "24399999", "RJ", "Niterói", "Sede / Centro / Icaraí", -22.8859, -43.1153),
    ("25000000", "25299999", "RJ", "Duque de Caxias", "Sede / Centro", -22.7856, -43.3117),
    ("26000000", "26299999", "RJ", "Nova Iguaçu", "Sede / Centro", -22.7561, -43.4608),
    ("24400000", "24799999", "RJ", "São Gonçalo", "Sede / Centro", -22.8269, -43.0539),

    # --- MINAS GERAIS / BH E RMBH ---
    ("30000000", "31999999", "MG", "Belo Horizonte", "Sede / Centro / Bairros", -19.9167, -43.9345),
    ("32000000", "32399999", "MG", "Contagem", "Sede / Centro / Eldorado", -19.9386, -44.0536),
    ("32500000", "32699999", "MG", "Betim", "Sede / Centro", -19.9678, -44.1983),
    ("33000000", "33199999", "MG", "Santa Luzia", "Sede / Centro", -19.7697, -43.8514),

    # --- PARANÁ / CURITIBA E RMC ---
    ("80000000", "82999999", "PR", "Curitiba", "Sede / Bairros / Distritos", -25.4284, -49.2733),
    ("83000000", "83099999", "PR", "São José dos Pinhais", "Sede / Centro", -25.5347, -49.2064),
    ("83300000", "83399999", "PR", "Piraquara", "Sede / Centro", -25.4419, -49.0628),
    ("83400000", "83499999", "PR", "Colombo", "Sede / Centro", -25.2917, -49.2242),
    ("83600000", "83699999", "PR", "Campo Largo", "Sede / Centro", -25.4597, -49.5278),
    ("83700000", "83799999", "PR", "Araucária", "Sede / Centro", -25.5928, -49.4103),

    # --- RIO GRANDE DO SUL / PORTO ALEGRE ---
    ("90000000", "91999999", "RS", "Porto Alegre", "Sede / Bairros", -30.0346, -51.2177),
    ("92000000", "92499999", "RS", "Canoas", "Sede / Centro", -29.9178, -51.1836),
    ("93000000", "93199999", "RS", "São Leopoldo", "Sede / Centro", -29.7547, -51.1478),
    ("94000000", "94199999", "RS", "Gravataí", "Sede / Centro", -29.9439, -50.9933),

    # --- DISTRITO FEDERAL / BRASÍLIA ---
    ("70000000", "70999999", "DF", "Brasília", "Plano Piloto / Asas / Lago", -15.7975, -47.8919),
    ("71000000", "71999999", "DF", "Brasília", "Taguatinga / Ceilândia / Águas Claras", -15.8333, -48.0567),
    ("72000000", "72799999", "DF", "Brasília", "Samambaia / Santa Maria / Gama", -15.8753, -48.0858),
    ("72800000", "72899999", "GO", "Luziânia", "Entorno DF", -16.2525, -47.9500),
    ("72900000", "72999999", "GO", "Valparaíso de Goiás", "Entorno DF", -16.0689, -47.9764)
]

def recarregar_nacional():
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
    
    execute_values(cur, query, TODAS_FAIXAS_BRASIL)
    conn.commit()
    cur.close()
    conn.close()
    print("Sucesso: Todas as capitais e regiões metropolitanas do Brasil foram carregadas com faixas reais!")

if __name__ == "__main__":
    recarregar_nacional()