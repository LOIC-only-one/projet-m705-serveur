"""api-user : consultation, modification et suppression des comptes."""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from bson import ObjectId
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import RefreshToken, Utilisateur
from schemas import UserIdsOut, UserOut, UserPatchIn

#### Définition de l'application Flask
app = APIFlask(__name__, title="api-user", docs_path="/api/users/docs", spec_path="/api/users/openapi.json",)
app.config.from_object("config")
app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
init_errors(app, jwt)
#### Fin de la définition de l'application Flask


#### Fonctions utilitaires
"""
Endpoints :
@app.get("/health") : vérifie que la base de données est prête.
@app.get("/api/users") : renvoie tous les ID des utilisateurs (admin).
@app.get("/api/users/<id>") : renvoie tous les champs d'un utilisateur (admin ou propriétaire).
@app.patch("/api/users/<id>") : modifie certains champs d'un utilisateur (admin ou propriétaire).
@app.delete("/api/users/<id>") : supprime un utilisateur et révoque ses jetons (admin ou propriétaire).
"""

def est_admin():
    """Le rôle est lu dans le jeton d'accès, émis par api-auth."""
    return get_jwt().get("role") == "admin"

@jwt_required()
def verifier_acces(id):
    """Autorise l'admin ou le propriétaire du compte (l'identité du jeton est str(user.id))."""
    if not (est_admin() or get_jwt_identity() == id):
        abort(403, "Accès refusé.", extra_data={"code": "ACCES_REFUSE"})


def trouver_user(id):
    """Renvoie l'utilisateur, ou 404 si l'id est mal formé ou inconnu."""
    user = Utilisateur.objects(id=id).first() if ObjectId.is_valid(id) else None
    if user is None:
        abort(404, "Utilisateur introuvable.", extra_data={"code": "UTILISATEUR_INTROUVABLE"})
    return user


@app.get("/health")
def health():
    get_db().command("ping")
    return {"status": "ok"}


@app.get("/api/users")
@jwt_required()  # sous la route et avant la validation : l'authentification passe en premier
@app.output(UserIdsOut)
@app.doc(security="BearerAuth")
def lister_users():
    """Renvoie tous les ID des utilisateurs (admin uniquement)."""
    if not est_admin():
        abort(403, "Accès refusé.", extra_data={"code": "ACCES_REFUSE"})
    return {"ids": [str(u.id) for u in Utilisateur.objects.only("id")]}


@app.get("/api/users/<id>")
@jwt_required()
@app.output(UserOut)
@app.doc(security="BearerAuth")
def obtenir_user(id):
    """Renvoie tous les champs d'un utilisateur."""
    verifier_acces(id)
    return trouver_user(id)


@app.patch("/api/users/<id>")
@jwt_required()
@app.input(UserPatchIn(partial=True), arg_name="data")
@app.output(UserOut)
@app.doc(security="BearerAuth")
def modifier_user(id, data):
    """Modifie certains champs d'un utilisateur. Seul un admin peut changer le rôle."""
    verifier_acces(id)
    if not data:
        abort(400, "Aucun champ à modifier.", extra_data={"code": "CORPS_VIDE"})

    user = trouver_user(id)
    # Un non-admin peut renvoyer son rôle actuel (Swagger envoie tous les champs), pas le changer.
    if "role" in data and data["role"] != user.role and not est_admin():
        abort(403, "Seul un admin peut modifier le rôle.", extra_data={"code": "ACCES_REFUSE"})
    if "email" in data:
        data["email"] = data["email"].lower()  # comme à l'inscription
    if "birthdate" in data:
        data["date_naissance"] = data.pop("birthdate")
    for champ, valeur in data.items():
        setattr(user, champ, valeur)
    try:
        user.save()
    except NotUniqueError:  # index unique sur username et email
        abort(
            409,
            "Email ou nom d'utilisateur déjà utilisé.",
            extra_data={"code": "COMPTE_EXISTANT"},
        )
    return user


@app.delete("/api/users/<id>")
@jwt_required()
@app.output({}, status_code=204)
@app.doc(security="BearerAuth")
def supprimer_user(id):
    """Supprime un utilisateur et révoque ses jetons de rafraîchissement."""
    verifier_acces(id)
    user = trouver_user(id)
    RefreshToken.objects(utilisateur=user).delete()
    user.delete()
    return ""
### Fin des définitions des routes de l'API
