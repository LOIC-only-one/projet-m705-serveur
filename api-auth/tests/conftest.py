import os

import pymysql
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def keys(tmp_path_factory):
    """Clé RSA de test, écrite là où l'app lit ses secrets Docker."""
    d = tmp_path_factory.mktemp("secrets")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "jwt").write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (d / "db").write_text(os.environ.get("TEST_DB_PASSWORD", "test"))
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "3307")
    os.environ["DB_PASSWORD_FILE"] = str(d / "db")
    os.environ["JWT_PRIVATE_KEY_FILE"] = str(d / "jwt")
    return private.public_key()


@pytest.fixture
def make_app(keys):
    from app import create_app

    def make(**config):
        app = create_app({"RATELIMIT_ENABLED": False, **config})
        conn = pymysql.connect(
            host=app.config["DB_HOST"],
            port=app.config["DB_PORT"],
            user=app.config["DB_USER"],
            password=app.config["DB_PASSWORD"],
            database=app.config["DB_NAME"],
        )
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM refresh_token")
            cur.execute("DELETE FROM utilisateur")
            conn.commit()
        return app

    return make


@pytest.fixture
def client(make_app):
    # use_cookies=False : on passe le cookie à la main pour contrôler exactement ce qui est envoyé.
    return make_app().test_client(use_cookies=False)
