import os
import time
from datetime import date
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def private_key(tmp_path_factory):
    """Écrit les secrets de test là où l'app les lit, et renvoie la clé privée (qui joue le rôle d'api-auth)."""
    d = tmp_path_factory.mktemp("secrets")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "jwt.pub").write_bytes(
        private.public_key().public_bytes(
            s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo
        )
    )
    (d / "db").write_text("test")
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "27018")
    os.environ["DB_PASSWORD_FILE"] = str(d / "db")
    os.environ["JWT_PUBLIC_KEY_FILE"] = str(d / "jwt.pub")
    return private


@pytest.fixture
def client(private_key):
    from app import app
    from models import RefreshToken, Utilisateur

    RefreshToken.objects.delete()
    Utilisateur.objects.delete()
    return app.test_client()


@pytest.fixture
def auth(private_key):
    """Fabrique l'en-tête Authorization d'un utilisateur, comme le ferait api-auth."""

    def _auth(user, expires_in=900):
        now = int(time.time())
        claims = {
            "sub": str(user.id),
            "role": user.role,
            "type": "access",
            "fresh": False,
            "jti": uuid4().hex,
            "iat": now,
            "nbf": now,
            "exp": now + expires_in,
        }
        token = jwt.encode(claims, private_key, algorithm="RS256")
        return {"Authorization": f"Bearer {token}"}

    return _auth


def make_user(username="dupont", role="user"):
    from models import Utilisateur

    return Utilisateur(
        username=username,
        email=f"{username}@b.fr",
        password_hash="x",
        date_naissance=date(2010, 5, 14),
        role=role,
    ).save()


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_sans_jeton_401(client):
    resp = client.get("/api/users")
    assert resp.status_code == 401
    assert resp.json["error"]["code"] == "JETON_INVALIDE"


def test_jeton_expire_401(client, auth):
    user = make_user()
    resp = client.get(f"/api/users/{user.id}", headers=auth(user, expires_in=-10))
    assert resp.status_code == 401
    assert resp.json["error"]["code"] == "JETON_EXPIRE"


def test_liste_reservee_aux_admins(client, auth):
    user = make_user()
    admin = make_user("admin", role="admin")
    assert client.get("/api/users", headers=auth(user)).status_code == 403
    resp = client.get("/api/users", headers=auth(admin))
    assert resp.status_code == 200
    assert sorted(resp.json["ids"]) == sorted([str(user.id), str(admin.id)])


def test_get_proprietaire_ok_sans_password_hash(client, auth):
    user = make_user()
    resp = client.get(f"/api/users/{user.id}", headers=auth(user))
    assert resp.status_code == 200
    assert resp.json["id"] == str(user.id)
    assert resp.json["birthdate"] == "2010-05-14"
    assert "password_hash" not in resp.json


def test_get_autre_utilisateur_403_mais_admin_ok(client, auth):
    user = make_user()
    autre = make_user("autre")
    admin = make_user("admin", role="admin")
    resp = client.get(f"/api/users/{autre.id}", headers=auth(user))
    assert resp.status_code == 403
    assert resp.json["error"]["code"] == "ACCES_REFUSE"
    assert client.get(f"/api/users/{user.id}", headers=auth(admin)).status_code == 200


@pytest.mark.parametrize("id", ["pas-un-objectid", "0" * 24])
def test_get_introuvable_404(client, auth, id):
    admin = make_user("admin", role="admin")
    resp = client.get(f"/api/users/{id}", headers=auth(admin))
    assert resp.status_code == 404
    assert resp.json["error"]["code"] == "UTILISATEUR_INTROUVABLE"


def test_patch_modifie_et_normalise_l_email(client, auth):
    user = make_user()
    resp = client.patch(
        f"/api/users/{user.id}",
        headers=auth(user),
        json={"username": "nouveau", "email": "N@B.fr", "birthdate": "2009-01-02"},
    )
    assert resp.status_code == 200
    assert resp.json["username"] == "nouveau"
    assert resp.json["email"] == "n@b.fr"
    assert resp.json["birthdate"] == "2009-01-02"


def test_patch_role_reserve_aux_admins(client, auth):
    user = make_user()
    admin = make_user("admin", role="admin")
    resp = client.patch(f"/api/users/{user.id}", headers=auth(user), json={"role": "admin"})
    assert resp.status_code == 403
    resp = client.patch(f"/api/users/{user.id}", headers=auth(admin), json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json["role"] == "admin"


def test_patch_role_inchange_accepte_pour_un_user(client, auth):
    user = make_user()
    resp = client.patch(
        f"/api/users/{user.id}", headers=auth(user), json={"role": "user", "username": "nouveau"}
    )
    assert resp.status_code == 200
    assert resp.json["role"] == "user"
    assert resp.json["username"] == "nouveau"


@pytest.mark.parametrize(
    "body",
    [{}, {"password_hash": "x"}, {"username": "a"}, {"birthdate": "2999-01-01"}, {"email": "pas-un-mail"}],
)
def test_patch_corps_invalide_400(client, auth, body):
    user = make_user()
    resp = client.patch(f"/api/users/{user.id}", headers=auth(user), json=body)
    assert resp.status_code == 400


def test_patch_doublon_409(client, auth):
    user = make_user()
    make_user("autre")
    resp = client.patch(f"/api/users/{user.id}", headers=auth(user), json={"username": "autre"})
    assert resp.status_code == 409
    assert resp.json["error"]["code"] == "COMPTE_EXISTANT"


def test_delete_supprime_le_compte_et_ses_jetons(client, auth):
    from models import RefreshToken, Utilisateur

    user = make_user()
    RefreshToken(jti="un-jti", utilisateur=user).save()
    resp = client.delete(f"/api/users/{user.id}", headers=auth(user))
    assert resp.status_code == 204
    assert Utilisateur.objects(id=user.id).first() is None
    assert RefreshToken.objects.count() == 0


def test_delete_autre_utilisateur_403(client, auth):
    user = make_user()
    autre = make_user("autre")
    assert client.delete(f"/api/users/{autre.id}", headers=auth(user)).status_code == 403


def test_doc_openapi_publiee(client):
    assert "/api/users" in client.get("/api/users/openapi.json").json["paths"]