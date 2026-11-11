"""api-auth : inscription, connexion, renouvellement et révocation des jetons.

Endpoints :
POST /api/auth/register : crée un compte (rôle "user").
POST /api/auth/login    : email + mot de passe -> {access_token, refresh_token}.
POST /api/auth/refresh  : refresh_token (en-tête Bearer) -> nouveau couple de jetons.
POST /api/auth/logout   : refresh_token (en-tête Bearer) -> révoqué.

Deux jetons JWT signés en RS256 :
- access_token (15 min) : envoyé aux autres API, qui le vérifient avec la clé publique.
- refresh_token (7 jours) : sert uniquement ici ; son "jti" est stocké en base pour pouvoir le révoquer.
"""

from apiflask import APIFlask, abort
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask_jwt_extended import (JWTManager, create_access_token, create_refresh_token, get_jti, get_jwt,
                                get_jwt_identity, jwt_required)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import RefreshToken, Utilisateur
from schemas import LoginIn, RegisterIn, UserOut

app = APIFlask(__name__, title="api-auth", docs_path="/api/auth/docs", spec_path="/api/auth/openapi.json")
app.config.from_object("config")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # vraie IP du client derrière Caddy (pour le rate limit)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
init_errors(app, jwt)

ph = PasswordHasher()  # argon2id
# Hash factice : on vérifie un mot de passe même si l'email est inconnu, pour que la réponse prenne
# le même temps dans les deux cas (sinon on pourrait deviner quels emails ont un compte).
FAUX_HASH = ph.hash("compte-inexistant")


def creer_jetons(user):
    """Crée le couple access/refresh et enregistre le refresh en base."""
    claims = {"role": user.role, "date_naissance": user.date_naissance.isoformat()}
    access = create_access_token(str(user.id), additional_claims=claims)
    refresh = create_refresh_token(str(user.id))
    RefreshToken(jti=get_jti(refresh), utilisateur=user).save()
    return {"access_token": access, "refresh_token": refresh,
            "expires_in": int(app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds())}


@app.get("/health")
def health():
    get_db().command("ping")
    return {"status": "ok"}


@app.post("/api/auth/register")
@app.input(RegisterIn, arg_name="data")  # corps validé par RegisterIn, sinon 400
@app.output(UserOut, status_code=201)   # réponse filtrée par UserOut (pas de password_hash)
def register(data):
    user = Utilisateur(username=data["username"], email=data["email"].lower(),
                       password_hash=ph.hash(data["password"]), date_naissance=data["birthdate"])
    try:
        user.save()
    except NotUniqueError:  # index unique sur username et email
        abort(409, "Email ou nom d'utilisateur déjà utilisé.", extra_data={"code": "COMPTE_EXISTANT"})
    return user


@app.post("/api/auth/login")
@limiter.limit("5 per minute")  # contre le brute force
@app.input(LoginIn, arg_name="data")
def login(data):
    user = Utilisateur.objects(email=data["email"].lower()).first()
    try:
        ph.verify(user.password_hash if user else FAUX_HASH, data["password"])
    except (VerificationError, InvalidHashError):
        user = None
    if user is None:  # même message que l'email soit inconnu ou le mot de passe faux
        abort(401, "Email ou mot de passe incorrect.", extra_data={"code": "IDENTIFIANTS_INVALIDES"})
    return creer_jetons(user)


@app.post("/api/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    """Rotation : l'ancien refresh_token est supprimé, il ne peut servir qu'une fois."""
    if not RefreshToken.objects(jti=get_jwt()["jti"]).delete():
        abort(401, "Jeton de rafraîchissement révoqué.", extra_data={"code": "JETON_REVOQUE"})
    return creer_jetons(Utilisateur.objects.get(id=get_jwt_identity()))


@app.post("/api/auth/logout")
@jwt_required(refresh=True)
def logout():
    RefreshToken.objects(jti=get_jwt()["jti"]).delete()
    return "", 204
