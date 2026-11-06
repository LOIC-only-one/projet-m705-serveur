"""api-auth : inscription, connexion, renouvellement et révocation des jetons."""

import hashlib
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone

import jwt
import pymysql
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import Flask, g, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
REFRESH_COOKIE = "refresh_token"
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,50}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

ph = PasswordHasher()  # argon2id, paramètres par défaut d'argon2-cffi
# Hash factice : un email inconnu coûte le même temps qu'un mauvais mot de passe.
DUMMY_HASH = ph.hash("compte-inexistant")


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def read_secret(name):
    with open(os.environ[f"{name}_FILE"]) as f:
        return f.read().strip()


def sha256(token):
    return hashlib.sha256(token.encode()).hexdigest()


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "CORPS_INVALIDE", "Le corps doit être un objet JSON.")
    return data


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DB_HOST=os.environ.get("DB_HOST", "db"),
        DB_PORT=int(os.environ.get("DB_PORT", "3306")),
        DB_NAME=os.environ.get("DB_NAME", "videotheque"),
        DB_USER=os.environ.get("DB_USER", "auth"),
        DB_PASSWORD=read_secret("DB_PASSWORD"),
        JWT_PRIVATE_KEY=read_secret("JWT_PRIVATE_KEY"),
        RATELIMIT_ENABLED=True,
    )
    app.config.update(config or {})
    # Derrière Caddy : l'IP du client vient de X-Forwarded-For (un seul proxy de confiance).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    # shortcut: compteur en mémoire, propre à chaque worker ; passer à Redis si la limite doit être exacte.
    # Attaché à l'app car Flask-Limiter n'en garde qu'une référence faible.
    app.limiter = limiter = Limiter(
        get_remote_address, app=app, storage_uri="memory://"
    )

    def db():
        if "db" not in g:
            g.db = pymysql.connect(
                host=app.config["DB_HOST"],
                port=app.config["DB_PORT"],
                user=app.config["DB_USER"],
                password=app.config["DB_PASSWORD"],
                database=app.config["DB_NAME"],
                cursorclass=pymysql.cursors.DictCursor,
            )
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def issue_tokens(cur, user):
        """Signe le jeton d'accès, enregistre un jeton de rafraîchissement et valide la transaction."""
        now = datetime.now(timezone.utc)
        access = jwt.encode(
            {
                "sub": str(user["id"]),
                "role": user["role"],
                "date_naissance": user["date_naissance"].isoformat(),
                "iat": now,
                "exp": now + ACCESS_TTL,
            },
            app.config["JWT_PRIVATE_KEY"],
            algorithm="RS256",
        )
        refresh = secrets.token_urlsafe(32)
        cur.execute(
            "DELETE FROM refresh_token WHERE utilisateur_id = %s AND expire_le < UTC_TIMESTAMP()",
            (user["id"],),
        )
        cur.execute(
            "INSERT INTO refresh_token (utilisateur_id, token_hash, expire_le) VALUES (%s, %s, %s)",
            (user["id"], sha256(refresh), (now + REFRESH_TTL).replace(tzinfo=None)),
        )
        db().commit()
        resp = jsonify(
            access_token=access,
            token_type="Bearer",
            expires_in=int(ACCESS_TTL.total_seconds()),
        )
        resp.set_cookie(
            REFRESH_COOKIE,
            refresh,
            max_age=REFRESH_TTL,
            httponly=True,
            secure=True,
            samesite="Strict",
            path="/api/auth",
        )
        return resp

    @app.get("/health")
    def health():
        with db().cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/api/auth/register")
    def register():
        data = json_body()
        username, email = data.get("username"), data.get("email")
        password, naissance = data.get("password"), data.get("date_naissance")
        if not (isinstance(username, str) and USERNAME_RE.fullmatch(username)):
            raise ApiError(
                400, "USERNAME_INVALIDE", "3 à 50 caractères : lettres, chiffres, _ . -"
            )
        if not (
            isinstance(email, str)
            and len(email) <= 255
            and EMAIL_RE.fullmatch(email.strip())
        ):
            raise ApiError(400, "EMAIL_INVALIDE", "Adresse mail invalide.")
        if not (isinstance(password, str) and 12 <= len(password) <= 1024):
            raise ApiError(
                400,
                "MOT_DE_PASSE_INVALIDE",
                "Le mot de passe doit faire au moins 12 caractères.",
            )
        try:
            naissance = date.fromisoformat(naissance)
        except (TypeError, ValueError):
            raise ApiError(
                400, "DATE_INVALIDE", "date_naissance doit être au format AAAA-MM-JJ."
            ) from None
        if not date(1900, 1, 1) <= naissance < date.today():
            raise ApiError(400, "DATE_INVALIDE", "date_naissance n'est pas plausible.")

        email = email.strip().lower()
        # Le rôle n'est jamais lu depuis le corps : toute inscription crée un "user".
        with db().cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO utilisateur (username, email, password_hash, date_naissance)"
                    " VALUES (%s, %s, %s, %s)",
                    (username, email, ph.hash(password), naissance),
                )
            except pymysql.err.IntegrityError:
                db().rollback()
                raise ApiError(
                    409, "COMPTE_EXISTANT", "Email ou nom d'utilisateur déjà utilisé."
                ) from None
            db().commit()
            user_id = cur.lastrowid
        return {
            "id": user_id,
            "username": username,
            "email": email,
            "role": "user",
        }, 201

    @app.post("/api/auth/login")
    @limiter.limit("5 per minute")
    def login():
        data = json_body()
        email, password = data.get("email"), data.get("password")
        if not (isinstance(email, str) and isinstance(password, str)):
            raise ApiError(
                400, "CHAMPS_MANQUANTS", "email et password sont obligatoires."
            )
        with db().cursor() as cur:
            cur.execute(
                "SELECT id, role, date_naissance, password_hash FROM utilisateur WHERE email = %s",
                (email.strip().lower(),),
            )
            user = cur.fetchone()
            try:
                ph.verify(user["password_hash"] if user else DUMMY_HASH, password)
            except (VerificationError, InvalidHashError):
                user = None
            if user is None:
                raise ApiError(
                    401, "IDENTIFIANTS_INVALIDES", "Email ou mot de passe incorrect."
                )
            return issue_tokens(cur, user)

    @app.post("/api/auth/refresh")
    def refresh():
        token = request.cookies.get(REFRESH_COOKIE)
        if not token:
            raise ApiError(401, "JETON_ABSENT", "Jeton de rafraîchissement absent.")
        with db().cursor() as cur:
            # FOR UPDATE : deux refresh simultanés avec le même jeton ne peuvent pas réussir tous les deux.
            cur.execute(
                "SELECT rt.id AS rt_id, u.id, u.role, u.date_naissance"
                " FROM refresh_token rt JOIN utilisateur u ON u.id = rt.utilisateur_id"
                " WHERE rt.token_hash = %s AND rt.expire_le > UTC_TIMESTAMP() FOR UPDATE",
                (sha256(token),),
            )
            row = cur.fetchone()
            if row is None:
                db().rollback()
                raise ApiError(
                    401,
                    "JETON_INVALIDE",
                    "Jeton de rafraîchissement invalide ou expiré.",
                )
            # Rotation : l'ancien jeton est supprimé, un nouveau est émis.
            cur.execute("DELETE FROM refresh_token WHERE id = %s", (row["rt_id"],))
            return issue_tokens(cur, row)

    @app.post("/api/auth/logout")
    def logout():
        # La session, c'est le jeton de rafraîchissement : on n'exige pas un jeton d'accès encore valide.
        token = request.cookies.get(REFRESH_COOKIE)
        if token:
            with db().cursor() as cur:
                cur.execute(
                    "DELETE FROM refresh_token WHERE token_hash = %s", (sha256(token),)
                )
            db().commit()
        resp = app.response_class(status=204)
        resp.delete_cookie(
            REFRESH_COOKIE,
            path="/api/auth",
            secure=True,
            httponly=True,
            samesite="Strict",
        )
        return resp

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error={"code": e.code, "message": e.message}), e.status

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify(
            error={"code": e.name.upper().replace(" ", "_"), "message": e.description}
        ), e.code

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception("Erreur non gérée")
        return jsonify(
            error={"code": "ERREUR_INTERNE", "message": "Erreur interne du serveur."}
        ), 500

    return app
