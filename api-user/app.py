"""api-user : Gestion des comptes, administration"""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import jsonify
from flask_jwt_extended import (
    JWTManager,
    verify_jwt_in_request,
    get_jti,
    get_jwt,
    get_jwt_identity,
    jwt_required
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

#from errors import init_errors
from models import Utilisateur, RefreshToken
from schemas import UserOut, UserIdsout, UserPatchIn

#### Définition de l'application Flask
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
@app.get("/users") : Renvoie tous les ID des utilisateurs
@app.get("/users/{id}") : Renvoie tous les champs d'un user spécifique
@app.patch("/users/{id}") : Modifie certains éléments d'un user
@app.delete("/users/{id}") : Supprime un user.
"""

def checkAuthToken():
    """Vérifie que le refresh token du cookie existe en base. Retourne le document ou None."""
    try:
        verify_jwt_in_request(refresh=True)  # signature + expiration + type "refresh"
    except Exception:
        return None
    return RefreshToken.objects(
        jti=get_jwt()["jti"],
        utilisateur=ObjectId(get_jwt_identity()),
    ).first()


def isAdmin():
    return get_jwt().get("role") == "admin"


def accessVerified(id):
    """Autorise l'admin ou le propriétaire du compte."""
    if not (isAdmin() or get_jwt_identity() == id):
        abort(403, "Accès refusé")


def findUser(id):
    if not ObjectId.is_valid(id):
        abort(404, "Utilisateur introuvable")
    user = Utilisateur.objects(id=id).first()
    if user is None:
        abort(404, "Utilisateur introuvable")
    return user


#### Endpoints
@app.get("/users")
@app.output(UserIdsOut)
@jwt_required()
def listUser():
    """Renvoie tous les ID des utilisateurs (admin uniquement)."""
    if not isAdmin():
        abort(403, "Accès refusé")
    return {"ids": [str(u.id) for u in Utilisateur.objects.only("id")]}


@app.get("/users/<id>")
@app.output(UserOut)
@jwt_required()
def obtenir_user(id):
    """Renvoie tous les champs d'un utilisateur."""
    accessVerified(id)
    return findUser(id)


@app.patch("/users/<id>")
@app.input(UserPatchIn(partial=True), location="json")
@app.output(UserOut)
@jwt_required()
def modifier_user(id, json_data):
    """Modifie certains champs d'un utilisateur."""
    accessVerified(id)
    if not json_data:
        abort(400, "Aucun champ à modifier")
    if "role" in json_data and not isAdmin():
        abort(403, "Seul un admin peut modifier le rôle")

    user = findUser(id)
    for champ, valeur in json_data.items():
        setattr(user, champ, valeur)
    try:
        user.save()
    except NotUniqueError:
        abort(409, "Nom d'utilisateur ou email déjà utilisé")
    return user


@app.delete("/users/<id>")
@app.output({}, status_code=204)
@jwt_required()
def supprimer_user(id):
    """Supprime un utilisateur et révoque ses refresh tokens."""
    accessVerified(id)
    user = findUser(id)
    RefreshToken.objects(utilisateur=user).delete()
    user.delete()
    return ""