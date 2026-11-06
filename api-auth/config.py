"""Configuration de l'application Flask, chargée par app.config.from_object("config")."""

import os
from datetime import timedelta

from sqlalchemy import URL


def read_secret(name):
    """Lit un secret Docker (fichier dont le chemin est dans la variable <NAME>_FILE)."""
    with open(os.environ[f"{name}_FILE"]) as f:
        return f.read()


SQLALCHEMY_DATABASE_URI = URL.create(
    "mysql+pymysql",
    username=os.environ.get("DB_USER", "auth"),
    password=read_secret("DB_PASSWORD").strip(),
    host=os.environ.get("DB_HOST", "db"),
    port=int(os.environ.get("DB_PORT", "3306")),
    database=os.environ.get("DB_NAME", "videotheque"),
)
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
VALIDATION_ERROR_STATUS_CODE = 400

# Jetons JWT signés en RS256 : la clé privée n'existe que dans api-auth
JWT_ALGORITHM = "RS256"
JWT_PRIVATE_KEY = read_secret("JWT_PRIVATE_KEY")
JWT_PUBLIC_KEY = read_secret("JWT_PUBLIC_KEY")
JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)

# Jeton de rafraîchissement dans un cookie HttpOnly, envoyé seulement à /api/auth
JWT_TOKEN_LOCATION = ["cookies"]
JWT_REFRESH_COOKIE_NAME = "refresh_token"
JWT_REFRESH_COOKIE_PATH = "/api/auth"
JWT_SESSION_COOKIE = False
JWT_COOKIE_SECURE = True
JWT_COOKIE_SAMESITE = "Strict"
JWT_COOKIE_CSRF_PROTECT = False
