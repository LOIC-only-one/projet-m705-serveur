"""api-auth : inscription, connexion, renouvellement et révocation des jetons."""

import os
from datetime import date, timedelta

from apiflask import APIFlask, Schema, abort
from apiflask.fields import Date, Email, Integer, String
from apiflask.validators import Length, Regexp
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
from flask_sqlalchemy import SQLAlchemy
from marshmallow import EXCLUDE, ValidationError
from sqlalchemy import URL, text
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix


def read_secret(name):
    """Lit un secret Docker (fichier dont le chemin est dans la variable <NAME>_FILE)."""
    with open(os.environ[f"{name}_FILE"]) as f:
        return f.read()


app = APIFlask(
    __name__,
    title="api-auth",
    docs_path="/api/auth/docs",
    spec_path="/api/auth/openapi.json",
)
app.config.update(
    SQLALCHEMY_DATABASE_URI=URL.create(
        "mysql+pymysql",
        username=os.environ.get("DB_USER", "auth"),
        password=read_secret("DB_PASSWORD").strip(),
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "3306")),
        database=os.environ.get("DB_NAME", "videotheque"),
    ),
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    VALIDATION_ERROR_STATUS_CODE=400,
    JWT_ALGORITHM="RS256",
    JWT_PRIVATE_KEY=read_secret("JWT_PRIVATE_KEY"),
    JWT_PUBLIC_KEY=read_secret("JWT_PUBLIC_KEY"),
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=7),
    JWT_TOKEN_LOCATION=["cookies"],  # api-auth ne lit que le jeton de rafraîchissement
    JWT_REFRESH_COOKIE_NAME="refresh_token",
    JWT_REFRESH_COOKIE_PATH="/api/auth",
    JWT_SESSION_COOKIE=False,
    JWT_COOKIE_SECURE=True,
    JWT_COOKIE_SAMESITE="Strict",
    # SameSite=Strict et front servi sur la même origine : le double cookie anti-CSRF est inutile.
    JWT_COOKIE_CSRF_PROTECT=False,
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # IP du client transmise par Caddy
db = SQLAlchemy(app)
jwt = JWTManager(app)
# shortcut: compteur en mémoire propre à chaque worker ; passer à Redis si la limite doit être exacte.
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
ph = PasswordHasher()  # argon2id
# Hash factice : un email inconnu coûte le même temps qu'un mauvais mot de passe.
DUMMY_HASH = ph.hash("compte-inexistant")


class Utilisateur(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    date_naissance = db.Column(db.Date, nullable=False)
    role = db.Column(db.Enum("user", "admin"), nullable=False, default="user")


class RefreshToken(db.Model):
    """Jetons de rafraîchissement encore valides : supprimer la ligne révoque le jeton."""

    jti = db.Column(db.String(36), primary_key=True)
    utilisateur_id = db.Column(
        db.ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False
    )


def date_passee(d):
    # marshmallow 4 : un validateur doit lever l'erreur, renvoyer False ne suffit plus.
    if d >= date.today():
        raise ValidationError("La date de naissance doit être dans le passé.")


class RegisterIn(Schema):
    class Meta:
        unknown = EXCLUDE  # un champ "role" envoyé par le client est ignoré

    username = String(required=True, validate=Regexp(r"^[A-Za-z0-9_.-]{3,50}$"))
    email = Email(required=True, validate=Length(max=255))
    password = String(required=True, validate=Length(12, 1024))
    date_naissance = Date(required=True, validate=date_passee)


class LoginIn(Schema):
    email = String(required=True)
    password = String(required=True)


class UserOut(Schema):
    id = Integer()
    username = String()
    email = String()
    role = String()


def error(status, code, message):
    return {"error": {"code": code, "message": message}}, status


@app.error_processor
def format_error(e):
    """Toutes les erreurs (validation, 404, 429, 500...) au format { "error": {code, message} }."""
    body, status = error(
        e.status_code,
        e.extra_data.get("code", e.message.upper().replace(" ", "_")),
        e.message,
    )
    if e.detail:
        body["error"]["details"] = e.detail
    return body, status, e.headers


@jwt.unauthorized_loader
@jwt.invalid_token_loader
def jeton_invalide(reason):
    return error(401, "JETON_INVALIDE", reason)


@jwt.expired_token_loader
def jeton_expire(_header, _payload):
    return error(401, "JETON_EXPIRE", "Jeton de rafraîchissement expiré.")


def issue_tokens(user):
    """Émet le jeton d'accès (corps) et le jeton de rafraîchissement (cookie HttpOnly)."""
    identity = str(user.id)
    claims = {"role": user.role, "date_naissance": user.date_naissance.isoformat()}
    access = create_access_token(identity, additional_claims=claims)
    refresh = create_refresh_token(identity)
    db.session.add(RefreshToken(jti=get_jti(refresh), utilisateur_id=user.id))
    db.session.commit()
    resp = jsonify(
        access_token=access,
        token_type="Bearer",
        expires_in=int(app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()),
    )
    set_refresh_cookies(resp, refresh)
    return resp


@app.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/auth/register")
@app.input(RegisterIn, arg_name="data")
@app.output(UserOut, status_code=201)
def register(data):
    """Crée un compte. Le rôle est toujours "user"."""
    user = Utilisateur(
        username=data["username"],
        email=data["email"].lower(),
        password_hash=ph.hash(data["password"]),
        date_naissance=data["date_naissance"],
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
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
    user = db.session.scalar(
        db.select(Utilisateur).filter_by(email=data["email"].lower())
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
    deleted = db.session.execute(
        db.delete(RefreshToken).filter_by(jti=get_jwt()["jti"])
    ).rowcount
    if not deleted:
        abort(
            401,
            "Jeton de rafraîchissement révoqué.",
            extra_data={"code": "JETON_REVOQUE"},
        )
    return issue_tokens(db.session.get(Utilisateur, int(get_jwt_identity())))


@app.post("/api/auth/logout")
@jwt_required(refresh=True)
def logout():
    """Révoque le jeton de rafraîchissement et efface le cookie."""
    db.session.execute(db.delete(RefreshToken).filter_by(jti=get_jwt()["jti"]))
    db.session.commit()
    resp = app.response_class(status=204)
    unset_refresh_cookies(resp)
    return resp
