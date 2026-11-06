"""api-auth : inscription, connexion, renouvellement et révocation des jetons."""

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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import RefreshToken, Utilisateur, db_connexion
from schemas import LoginIn, RegisterIn, UserOut

#### Définition de ;l'application Flask
app = APIFlask(__name__,title="api-auth",docs_path="/api/auth/docs",spec_path="/api/auth/openapi.json",)
app.config.from_object("config")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
db_connexion.init_app(app)
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

def issue_tokens(user):
    """Émet le jeton d'accès (corps) et le jeton de rafraîchissement (cookie HttpOnly)."""
    identity = str(user.id)
    claims = {"role": user.role, "date_naissance": user.date_naissance.isoformat()}
    access = create_access_token(identity, additional_claims=claims)
    refresh = create_refresh_token(identity)
    db_connexion.session.add(RefreshToken(jti=get_jti(refresh), utilisateur_id=user.id))
    db_connexion.session.commit()
    reponse = jsonify(
        access_token=access,
        token_type="Bearer",
        expires_in=int(app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
    )
    set_refresh_cookies(reponse, refresh)
    return reponse


@app.get("/health")
def health():
    db_connexion.session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/auth/register")
@app.input(RegisterIn, arg_name="data") # Donnée d'entrée validée par le schéma RegisterIn et passée à la fonction dans l'argument "data"
@app.output(UserOut, status_code=201) # Donnée de sortie validée par le schéma UserOut et renvoyée avec le code 201 (Created)
def register(data):
    """Crée un compte. Le rôle est toujours "user"."""
    user = Utilisateur(
        username=data["username"],
        email=data["email"].lower(),
        password_hash=ph.hash(data["password"]),
        date_naissance=data["birthdate"],
    )
    db_connexion.session.add(user)
    try:
        db_connexion.session.commit()
    except IntegrityError:
        db_connexion.session.rollback()
        abort(
            409,
            "Email ou nom d'utilisateur déjà utilisé.",
            extra_data={"code": "COMPTE_EXISTANT"},
        )
    return user


@app.post("/api/auth/login")
@limiter.limit("5 per minute")
@app.input(LoginIn, arg_name="data")
def login(data):
    """Vérifie email et mot de passe, renvoie le jeton d'accès et pose le cookie de rafraîchissement."""
    user = db_connexion.session.scalar(
        db_connexion.select(Utilisateur).filter_by(email=data["email"].lower())
    )
    try:
        ph.verify(user.password_hash if user else DUMMY_HASH, data["password"])
    except (VerificationError, InvalidHashError):
        user = None
    if not user:
        abort(
            401,
            "Email ou mot de passe incorrect.",
            extra_data={"code": "IDENTIFIANTS_INVALIDES"},
        )
    return issue_tokens(user)


@app.post("/api/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    """Échange le cookie de rafraîchissement contre un nouveau couple de jetons (rotation)."""
    # Seule la requête qui supprime effectivement le jeton gagne, même en concurrence.
    deleted = db_connexion.session.execute(
        db_connexion.delete(RefreshToken).filter_by(jti=get_jwt()["jti"])
    ).rowcount
    if not deleted:
        abort(
            401,
            "Jeton de rafraîchissement révoqué.",
            extra_data={"code": "JETON_REVOQUE"},
        )
    return issue_tokens(db_connexion.session.get(Utilisateur, int(get_jwt_identity())))


@app.post("/api/auth/logout")
@jwt_required(refresh=True)
def logout():
    """Révoque le jeton de rafraîchissement et efface le cookie."""
    db_connexion.session.execute(db_connexion.delete(RefreshToken).filter_by(jti=get_jwt()["jti"]))
    db_connexion.session.commit()
    resp = app.response_class(status=204)
    unset_refresh_cookies(resp)
    return resp
### Fin des définitions des routes de l'API
