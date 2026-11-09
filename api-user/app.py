"""api-user : Gestion des comptes, administration"""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import jsonify
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jti,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_refresh_cookies,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

#from errors import init_errors
from models import Utilisateur
#from schemas import LoginIn, RegisterIn, UserOut

#### Définition de ;l'application Flask
app = APIFlask(__name__,title="api-auth",docs_path="/api/auth/docs",spec_path="/api/auth/openapi.json",)
app.config.from_object("config")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
ph = PasswordHasher()  # argon2id
DUMMY_HASH = ph.hash("compte-inexistant")
init_errors(app, jwt)
#### Fin de la définition de l'application Flask


#### Fonctions utilitaires
"""
Endpoints :
@app.get("/health") : vérifie que la base de données est prête.
@app.post("/api/auth/register") : crée un compte.
@app.post("/api/auth/login") : vérifie email et mot de passe, renvoie le jeton d'accès et pose le cookie de rafraîchissement.
@app.post("/api/auth/refresh") : échange le cookie de rafraîchissement contre un nouveau couple de jetons (rotation).
@app.post("/api/auth/logout") : révoque le jeton de rafraîchissement et efface le cookie.
"""