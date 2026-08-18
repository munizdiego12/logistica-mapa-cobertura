import re
import pandas as pd
import logging

logger = logging.getLogger("Validator")

COLUNAS_OBRIGATORIAS = ["ID Pedido", "Cliente", "Logradouro", "Numero", "Bairro", "CEP"]

def sanitizar_cep(cep_raw) -> str:
    if pd.isna(cep_raw):
        return ""
    apenas_numeros = re.sub(r"\D", "", str(cep_raw))
    return apenas_numeros.zfill(8) if len(apenas_numeros) <= 8 else apenas_numeros[:8]

def validar_e_higienizar_dataframe(df_raw: pd.DataFrame, limite_max_linhas: int = 500) -> pd.DataFrame:
    """Valida esquema, remove linhas vazias e higieniza colunas obrigatórias."""
    faltantes = [col for col in COLUNAS_OBRIGATORIAS if col not in df_raw.columns]
    if faltantes:
        raise KeyError(f"Colunas ausentes no arquivo: {', '.join(faltantes)}")

    if len(df_raw) > limite_max_linhas:
        raise ValueError(f"O arquivo excede o limite máximo permitido de {limite_max_linhas} pedidos por lote.")

    # Remover linhas onde campos essenciais de localização estejam em branco
    df = df_raw.dropna(subset=["Logradouro", "Bairro", "CEP"]).copy()
    
    # Remove também registros com strings vazias
    df = df[df["Logradouro"].astype(str).str.strip() != ""]
    df = df[df["CEP"].astype(str).str.strip() != ""]

    if df.empty:
        raise ValueError("O arquivo não contém registros válidos preenchidos.")

    df["CEP_LIMPO"] = df["CEP"].apply(sanitizar_cep)
    return df

def carregar_e_validar_csv(caminho_csv: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(caminho_csv)
    except Exception as e:
        logger.error(f"Erro ao abrir CSV '{caminho_csv}': {e}")
        raise ValueError(f"Não foi possível ler o arquivo: {e}")

    return validar_e_higienizar_dataframe(df)