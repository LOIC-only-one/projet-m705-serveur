"""api-user : consultation, modification et suppression des comptes."""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from bson import DBRef, ObjectId
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import RefreshToken, Utilisateur
from schemas import PasswordChangeIn, UserDeleteIn, UserListOut, UserOut, UserPatchIn

#### Définition de l'application Flask
app = APIFlask(__name__, title="api-user", docs_path="/api/users/docs", spec_path="/api/users/openapi.json",)
app.config.from_object("config")
app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
ph = PasswordHasher()  # argon2id, comme dans api-auth
init_errors(app, jwt)
#### Fin de la définition de l'application Flask


#### Fonctions utilitaires
"""
Endpoints :
@app.get("/health") : vérifie que la base de données est prête.
@app.get("/api/users") : renvoie la liste des utilisateurs, avec id, username et email (admin).
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


def nettoyer_donnees_catalogue(id):
    """Supprime les copies et emprunts liés à un utilisateur avant son compte."""
    db = get_db()
    exemplaires = db["exemplaire"]
    emprunts = db["emprunt"]
    proprietes = [ex["_id"] for ex in exemplaires.find({"proprietaire_id": id}, {"_id": 1})]
    references = [DBRef("exemplaire", exemplaire_id) for exemplaire_id in proprietes]
    emprunts.delete_many({"$or": [{"utilisateur_id": id}, {"exemplaire": {"$in": references}}]})
    exemplaires.update_many({"emprunteur_id": id}, {"$unset": {"emprunteur_id": ""}})
    exemplaires.delete_many({"proprietaire_id": id})


@app.get("/health")
def health():
    get_db().command("ping")
    return {"status": "ok"}


@app.get("/api/users")
@jwt_required()  # sous la route et avant la validation : l'authentification passe en premier
@app.output(UserListOut)
@app.doc(security="BearerAuth")
def lister_users():
    """Renvoie la liste des utilisateurs, avec id, username et email (admin uniquement)."""
    if not est_admin():
        abort(403, "Accès refusé.", extra_data={"code": "ACCES_REFUSE"})
    # only() : MongoDB ne renvoie que ces champs (l'id est toujours inclus) ; tri par nom, ordre stable
    return {"users": list(Utilisateur.objects.only("username", "email").order_by("username"))}


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
    """Modifie certains champs d'un utilisateur (dont le mot de passe). Seul un admin peut changer le rôle."""
    verifier_acces(id)
    if not data:
        abort(400, "Aucun champ à modifier.", extra_data={"code": "CORPS_VIDE"})

    user = trouver_user(id)
    # Un non-admin peut renvoyer son rôle actuel (Swagger envoie tous les champs), pas le changer.
    if "role" in data and data["role"] != user.role and not est_admin():
        abort(403, "Seul un admin peut modifier le rôle.", extra_data={"code": "ACCES_REFUSE"})
    if "password" in data:  # le mot de passe en clair n'est jamais stocké : seul son hash l'est
        data["password_hash"] = ph.hash(data.pop("password"))
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


@app.post("/api/users/<id>/password")
@jwt_required()
@app.input(PasswordChangeIn, arg_name="data")
@app.doc(security="BearerAuth")
def changer_mot_de_passe(id, data):
    """Change le mot de passe après vérification de l'ancien."""
    verifier_acces(id)
    user = trouver_user(id)
    try:
        ph.verify(user.password_hash, data["current_password"])
    except (VerificationError, InvalidHashError):
        abort(401, "Mot de passe incorrect.", extra_data={"code": "MOT_DE_PASSE_INCORRECT"})
    user.password_hash = ph.hash(data["new_password"])
    user.save()
    return "", 204


@app.delete("/api/users/<id>")
@jwt_required()
@app.input(UserDeleteIn, arg_name="data")
@app.output({}, status_code=204)
@app.doc(security="BearerAuth")
def supprimer_user(id, data):
    """Supprime un utilisateur, ses jetons et ses données de vidéothèque."""
    verifier_acces(id)
    user = trouver_user(id)
    if not est_admin() and "current_password" in data:
        try:
            ph.verify(user.password_hash, data.get("current_password") or "")
        except (VerificationError, InvalidHashError):
            abort(401, "Mot de passe incorrect.", extra_data={"code": "MOT_DE_PASSE_INCORRECT"})
    RefreshToken.objects(utilisateur=user).delete()
    nettoyer_donnees_catalogue(id)
    user.delete()
    return ""
### Fin des définitions des routes de l'API