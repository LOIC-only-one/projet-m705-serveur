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
    os.environ.setdefault("DB_PORT", "3307")
    os.environ["DB_PASSWORD_FILE"] = str(d / "db")
    os.environ["JWT_PRIVATE_KEY_FILE"] = str(d / "jwt")
    os.environ["JWT_PUBLIC_KEY_FILE"] = str(d / "jwt.pub")
    return private.public_key()


@pytest.fixture
def client(keys):
    from app import RefreshToken, Utilisateur, app, db, limiter

    limiter.reset()
    with app.app_context():
        db.session.execute(db.delete(RefreshToken))
        db.session.execute(db.delete(Utilisateur))
        db.session.commit()
    # use_cookies=False : on passe le cookie à la main pour contrôler ce qui est envoyé.
    return app.test_client(use_cookies=False)


VALID = {
    "username": "dupont",
    "email": "a@b.fr",
    "password": "motdepasse-solide",
    "date_naissance": "2010-05-14",
}


def register(client, **override):
    return client.post("/api/auth/register", json={**VALID, **override})


def login(client, email="a@b.fr", password="motdepasse-solide"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def cookie_of(resp):
    return resp.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]


def with_cookie(token):
    return {"Cookie": f"refresh_token={token}"}


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
        {"date_naissance": "2999-01-01"},
        {"date_naissance": "14/05/2010"},
        {"date_naissance": 2010},
    ],
)
def test_register_corps_invalide_400(client, override):
    resp = register(client, **override)
    assert resp.status_code == 400
    assert set(resp.json["error"]) == {"code", "message", "details"}


def test_register_sans_json_400(client):
    assert client.post("/api/auth/register", data="x").status_code == 400


def test_login_emet_jwt_rs256_et_cookie_securise(client, keys):
    user_id = register(client).json["id"]
    resp = login(client, email="A@b.fr")
    assert resp.status_code == 200
    claims = jwt.decode(resp.json["access_token"], keys, algorithms=["RS256"])
    assert claims["sub"] == str(user_id)
    assert claims["role"] == "user"
    assert claims["date_naissance"] == "2010-05-14"
    assert claims["exp"] - claims["iat"] == 15 * 60
    cookie = resp.headers["Set-Cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/api/auth"):
        assert flag in cookie


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
    old = cookie_of(login(client))
    resp = client.post("/api/auth/refresh", headers=with_cookie(old))
    assert resp.status_code == 200
    jwt.decode(resp.json["access_token"], keys, algorithms=["RS256"])
    assert cookie_of(resp) != old
    # L'ancien jeton a été consommé : le rejouer échoue.
    assert client.post("/api/auth/refresh", headers=with_cookie(old)).status_code == 401


def test_refresh_sans_cookie_401(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revoque_le_jeton(client):
    register(client)
    token = cookie_of(login(client))
    resp = client.post("/api/auth/logout", headers=with_cookie(token))
    assert resp.status_code == 204
    assert "refresh_token=;" in resp.headers["Set-Cookie"]
    assert (
        client.post("/api/auth/refresh", headers=with_cookie(token)).status_code == 401
    )


def test_login_limite_a_5_par_minute(client):
    codes = [login(client, "x@y.fr", "n-importe-quoi").status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_doc_openapi_publiee(client):
    assert "/api/auth/register" in client.get("/api/auth/openapi.json").json["paths"]


def test_route_inconnue_format_erreur_commun(client):
    resp = client.get("/api/auth/nope")
    assert resp.status_code == 404
    assert resp.json["error"]["code"] == "NOT_FOUND"
