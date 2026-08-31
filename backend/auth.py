import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database import get_db, Operador

# Contexto para hashing de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Rota utilizada para obter o token no FastAPI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verificar_senha_hash(senha_plana: str, senha_hash: str) -> bool:
    """Verifica se a senha em texto puro corresponde ao hash salvo."""
    return pwd_context.verify(senha_plana, senha_hash)


def gerar_hash_senha(senha: str) -> str:
    """Gera o hash Bcrypt da senha."""
    return pwd_context.hash(senha)


def criar_token_acesso(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Gera o token JWT de acesso."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def obter_operador_atual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Operador:
    """Valida o token JWT e retorna o operador logado no banco de dados."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais de autenticação inválidas ou expiradas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    operador = db.query(Operador).filter(Operador.email == email, Operador.ativo == True).first()
    if operador is None:
        raise credentials_exception
    return operador