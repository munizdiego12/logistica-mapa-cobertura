import sqlite3
import logging
from typing import Optional, Tuple

logger = logging.getLogger("CacheDB")

class GeocodingCache:
    def __init__(self, db_path: str = "geocache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Habilita WAL para suportar múltiplos leitores/escritores sem travar o banco
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS geocache (
                    chave TEXT PRIMARY KEY,
                    latitude REAL,
                    longitude REAL,
                    origem_dado TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get(self, chave: str) -> Optional[Tuple[float, float]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT latitude, longitude FROM geocache WHERE chave = ?", (chave.lower().strip(),))
            res = cur.fetchone()
            if res:
                return res[0], res[1]
        return None

    def set(self, chave: str, lat: float, lon: float, origem: str = "nominatim"):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO geocache (chave, latitude, longitude, origem_dado) VALUES (?, ?, ?, ?)",
                (chave.lower().strip(), lat, lon, origem)
            )
            conn.commit()