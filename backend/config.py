import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

# ==============================
# VARIÁVEIS DE AMBIENTE E SEGURANÇA
# ==============================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY", "chave_secreta_padrao_dev_123")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# Código de convite exigido para criar uma conta de operador (Etapa 1 —
# Autenticação). Sem essa variável configurada no ambiente, o cadastro
# fica bloqueado por padrão (mais seguro do que deixar aberto por engano).
OPERATOR_INVITE_CODE = os.getenv("OPERATOR_INVITE_CODE")

# ==============================
# CONFIGURAÇÃO DE LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)

# ==============================
# PARÂMETROS OPERACIONAIS E FINANCEIROS
# ==============================
PRECO_GASOLINA_LITRO = 5.80
CUSTO_HOMEM_HORA = 25.00
TEMPO_PARADA_MINUTOS = 12.0
VELOCIDADE_MEDIA_URBANA_KMH = 20.0
FATOR_MALHA_URBANA_SP = 1.35

# Bounding Box de SP Capital (Latitude / Longitude)
BBOX_SP = {
    "lat_min": -24.05,
    "lat_max": -23.35,
    "lon_min": -46.90,
    "lon_max": -46.30
}

@dataclass(frozen=True)
class ModalConfig:
    capacidade: int
    consumo_km_l: float
    manutencao_km: float

MODAIS = {
    "Carro de Passeio": ModalConfig(capacidade=5, consumo_km_l=10.5, manutencao_km=0.30),
    "Fiorino / Utilitário": ModalConfig(capacidade=12, consumo_km_l=9.0, manutencao_km=0.45),
    "Motocicleta": ModalConfig(capacidade=3, consumo_km_l=30.0, manutencao_km=0.15)
}

# Endereço e CEP Padrão da Loja/CD
ORIGEM_PADRAO = {
    "logradouro": "Avenida Paulista",
    "numero": "1000",
    "bairro": "Bela Vista",
    "cep": "01310-100"
}