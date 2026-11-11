import os

import jwt
import pytest
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def keys(tmp_path_factory):
    """Écrit les secrets de test là où l'app les lit, et renvoie la clé publique."""
    d = tmp_path_factory.mktemp("secrets")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "jwt").write_bytes(
        private.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
    )
    (d / "jwt.pub").write_bytes(
        private.public_key().public_bytes(
            s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo
        )
    )
    (d / "db").write_text("test")
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "27018")
    os.environ["DB_PASSWORD_FILE"] = str(d / "db")
    os.environ["JWT_PRIVATE_KEY_FILE"] = str(d / "jwt")
    os.environ["JWT_PUBLIC_KEY_FILE"] = str(d / "jwt.pub")
    return private.public_key()


@pytest.fixture
def client(keys):
    from app import app, limiter
    from models import RefreshToken, Utilisateur

    limiter.reset()
    RefreshToken.objects.delete()
    Utilisateur.objects.delete()
    return app.test_client()


VALID = {
    "username": "dupont",
    "email": "a@b.fr",
    "password": "motdepasse-solide",
    "birthdate": "2010-05-14",
}


def register(client, **override):
    return client.post("/api/auth/register", json={**VALID, **override})


def login(client, email="a@b.fr", password="motdepasse-solide"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_register_cree_un_user_meme_si_role_admin_demande(client):
    resp = register(client, role="admin", email="A@B.fr")
    assert resp.status_code == 201
    assert resp.json == {
        "id": resp.json["id"],
        "username": "dupont",
        "email": "a@b.fr",
        "role": "user",
    }


@pytest.mark.parametrize(
    "override", [{"email": "a@b.fr", "username": "autre"}, {"email": "x@y.fr"}]
)
def test_register_doublon_409(client, override):
    register(client)
    resp = register(client, **override)
    assert resp.status_code == 409
    assert resp.json["error"]["code"] == "COMPTE_EXISTANT"


@pytest.mark.parametrize(
    "override",
    [
        {"password": "trop-court"},
        {"email": "pas-un-mail"},
        {"username": "a"},
        {"username": None},
        {"birthdate": "2999-01-01"},
        {"birthdate": "14/05/2010"},
        {"birthdate": 2010},
    ],
)
def test_register_corps_invalide_400(client, override):
    resp = register(client, **override)
    assert resp.status_code == 400
    assert set(resp.json["error"]) == {"code", "message", "details"}


def test_register_sans_json_400(client):
    assert client.post("/api/auth/register", data="x").status_code == 400


def test_login_emet_deux_jwt_rs256(client, keys):
    user_id = register(client).json["id"]
    resp = login(client, email="A@b.fr")
    assert resp.status_code == 200
    claims = jwt.decode(resp.json["access_token"], keys, algorithms=["RS256"])
    assert claims["sub"] == str(user_id)
    assert claims["role"] == "user"
    assert claims["date_naissance"] == "2010-05-14"
    assert claims["exp"] - claims["iat"] == 15 * 60
    assert jwt.decode(resp.json["refresh_token"], keys, algorithms=["RS256"])["type"] == "refresh"


@pytest.mark.parametrize(
    "email,password",
    [("a@b.fr", "mauvais-mot-de-passe"), ("inconnu@b.fr", "motdepasse-solide")],
)
def test_login_refuse_meme_erreur(client, email, password):
    register(client)
    resp = login(client, email, password)
    assert resp.status_code == 401
    assert resp.json["error"]["code"] == "IDENTIFIANTS_INVALIDES"


def test_refresh_fait_tourner_le_jeton(client, keys):
    register(client)
    old = login(client).json["refresh_token"]
    resp = client.post("/api/auth/refresh", headers=bearer(old))
    assert resp.status_code == 200
    jwt.decode(resp.json["access_token"], keys, algorithms=["RS256"])
    assert resp.json["refresh_token"] != old
    # L'ancien jeton a été consommé : le rejouer échoue.
    assert client.post("/api/auth/refresh", headers=bearer(old)).status_code == 401


def test_refresh_refuse_un_access_token(client):
    register(client)
    access = login(client).json["access_token"]
    assert client.post("/api/auth/refresh", headers=bearer(access)).status_code == 401


def test_refresh_sans_jeton_401(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revoque_le_jeton(client):
    register(client)
    token = login(client).json["refresh_token"]
    assert client.post("/api/auth/logout", headers=bearer(token)).status_code == 204
    assert client.post("/api/auth/refresh", headers=bearer(token)).status_code == 401


def test_login_limite_a_5_par_minute(client):
    codes = []
    for _ in range(6):
        codes.append(login(client, "x@y.fr", "n-importe-quoi").status_code)
    assert codes == [401] * 5 + [429]


def test_doc_openapi_publiee(client):
    assert "/api/auth/register" in client.get("/api/auth/openapi.json").json["paths"]


def test_route_inconnue_format_erreur_commun(client):
    resp = client.get("/api/auth/nope")
    assert resp.status_code == 404
    assert resp.json["error"]["code"] == "NOT_FOUND"
