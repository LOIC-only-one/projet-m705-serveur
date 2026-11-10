"""Tests d'api-catalogue contre la base de test (docker compose -f compose.test.yml up -d db-test)."""

import os
from datetime import datetime
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa

FILM_ID = 999999001  # id TMDB fictif : la base n'est jamais vide, donc pas d'appel à TMDB


@pytest.fixture(scope="session")
def private_key(tmp_path_factory):
    """Écrit les secrets de test là où l'app les lit, et renvoie la clé privée (qui joue le rôle d'api-auth)."""
    d = tmp_path_factory.mktemp("secrets")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "jwt.pub").write_bytes(private.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo))
    (d / "db").write_text("test")
    (d / "tmdb").write_text("inutile")
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "27018")
    os.environ["DB_PASSWORD_FILE"] = str(d / "db")
    os.environ["JWT_PUBLIC_KEY_FILE"] = str(d / "jwt.pub")
    os.environ["TMDB_API_KEY_FILE"] = str(d / "tmdb")
    return private


@pytest.fixture
def client(private_key):
    from app import app
    from models import Emprunt, Exemplaire, Film

    Emprunt.objects.delete()
    Exemplaire.objects.delete()
    film = Film(tmdb_id=FILM_ID, titre="Zzz Film De Test", annee=2000).save()
    yield app.test_client()
    Emprunt.objects.delete()
    Exemplaire.objects.delete()
    film.delete()


@pytest.fixture
def auth(private_key):
    """En-tête Authorization d'un utilisateur, comme le ferait api-auth."""

    def _auth(sub, role="user"):
        now = int(time.time())
        claims = {"sub": sub, "role": role, "type": "access", "fresh": False, "jti": uuid4().hex,
                  "iat": now, "nbf": now, "exp": now + 900}
        return {"Authorization": "Bearer " + jwt.encode(claims, private_key, algorithm="RS256")}

    return _auth


def disponibles(client, headers):
    films = client.get("/api/films?q=zzz film", headers=headers).json["films"]
    return [f["disponibles"] for f in films if f["id"] == FILM_ID]


def test_sans_jeton_401(client):
    assert client.get("/api/films").status_code == 401


def test_recherche(client, auth):
    assert disponibles(client, auth("alice")) == [0]
    assert client.get("/api/films?q=pas-un-titre-xyz", headers=auth("alice")).json["films"] == []
    assert client.get("/api/films?q=.*", headers=auth("alice")).json["films"] == []  # pas d'injection regex


def test_pret_complet(client, auth):
    alice, bob, carol = auth("alice"), auth("bob"), auth("carol")

    ex = client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=alice)
    assert ex.status_code == 201
    assert client.get("/api/exemplaires", headers=alice).json["exemplaires"][0]["id"] == ex.json["id"]
    assert client.get("/api/exemplaires", headers=bob).json["exemplaires"] == []
    assert disponibles(client, alice) == [0]  # on n'emprunte pas son propre film
    assert disponibles(client, bob) == [1]

    assert client.post("/api/emprunts", json={"film_id": FILM_ID}, headers=alice).status_code == 409
    emp = client.post("/api/emprunts", json={"film_id": FILM_ID}, headers=bob)
    assert emp.status_code == 201
    assert client.post("/api/emprunts", json={"film_id": FILM_ID}, headers=carol).status_code == 409
    assert disponibles(client, carol) == [0]
    assert client.get("/api/emprunts", headers=bob).json["emprunts"][0]["id"] == emp.json["id"]
    assert client.get("/api/exemplaires", headers=alice).json["exemplaires"][0]["prete_jusquau"]

    # pas de suppression pendant le prêt, retour réservé à l'emprunteur / au propriétaire
    assert client.delete(f"/api/exemplaires/{ex.json['id']}", headers=alice).status_code == 409
    assert client.delete(f"/api/exemplaires/{ex.json['id']}", headers=bob).status_code == 403
    assert client.post(f"/api/emprunts/{emp.json['id']}/retour", headers=carol).status_code == 403
    assert client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=bob).status_code == 409
    assert client.post(f"/api/emprunts/{emp.json['id']}/retour", headers=bob).status_code == 200
    assert client.post(f"/api/emprunts/{emp.json['id']}/retour", headers=alice).status_code == 409
    assert client.get("/api/emprunts", headers=bob).json["emprunts"][0]["date_retour"]  # passé dans l'historique
    assert disponibles(client, carol) == [1]

    assert client.delete(f"/api/exemplaires/{ex.json['id']}", headers=alice).status_code == 204
    assert client.get("/api/exemplaires", headers=alice).json["exemplaires"] == []


def test_entrees_invalides(client, auth):
    assert client.post("/api/exemplaires", json={}, headers=auth("a")).status_code == 400
    assert client.post("/api/emprunts", json={"film_id": 1}, headers=auth("a")).status_code == 404
    assert client.delete("/api/exemplaires/pas-un-id", headers=auth("a")).status_code == 404


def emprunter(client, headers, film_id=FILM_ID):
    return client.post("/api/emprunts", json={"film_id": film_id}, headers=headers)


def test_doublons(client, auth):
    alice, bob, carol = auth("alice"), auth("bob"), auth("carol")
    assert client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=alice).status_code == 201
    assert client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=alice).json["error"]["code"] == "FILM_DEJA_POSSEDE"
    assert client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=carol).status_code == 201

    assert emprunter(client, bob).status_code == 201
    # une 2e copie est libre chez carol, mais bob a déjà ce film
    assert emprunter(client, bob).json["error"]["code"] == "FILM_DEJA_EMPRUNTE"
    assert client.post("/api/exemplaires", json={"film_id": FILM_ID}, headers=bob).json["error"]["code"] == "FILM_DEJA_EMPRUNTE"

    fiche = client.get(f"/api/films/{FILM_ID}", headers=bob).json
    assert (fiche["emprunte"], fiche["possede"], fiche["disponibles"]) == (True, False, 1)
    fiche = client.get(f"/api/films/{FILM_ID}", headers=alice).json
    assert (fiche["emprunte"], fiche["possede"]) == (False, True)
    assert client.get("/api/films/1", headers=bob).status_code == 404


def test_prolongation_et_retard(client, auth):
    from models import Emprunt, Film

    alice, bob = auth("alice"), auth("bob")
    autre = Film(tmdb_id=FILM_ID + 1, titre="Zzz Autre", annee=2001).save()
    try:
        for film_id in (FILM_ID, FILM_ID + 1):
            client.post("/api/exemplaires", json={"film_id": film_id}, headers=alice)
        emp = emprunter(client, bob).json

        assert client.post(f"/api/emprunts/{emp['id']}/prolongation", headers=alice).status_code == 403
        prolonge = client.post(f"/api/emprunts/{emp['id']}/prolongation", headers=bob).json
        assert prolonge["prolonge"] and prolonge["date_retour_prevue"] > emp["date_retour_prevue"]
        assert client.post(f"/api/emprunts/{emp['id']}/prolongation", headers=bob).status_code == 409

        Emprunt.objects(id=emp["id"]).update_one(set__date_retour_prevue=datetime(2000, 1, 1))
        assert client.get("/api/emprunts", headers=bob).json["emprunts"][0]["en_retard"]
        assert client.get("/api/exemplaires", headers=alice).json["exemplaires"][0]["en_retard"]
        assert emprunter(client, bob, FILM_ID + 1).json["error"]["code"] == "EMPRUNT_EN_RETARD"

        client.post(f"/api/emprunts/{emp['id']}/retour", headers=bob)
        assert emprunter(client, bob, FILM_ID + 1).status_code == 201
        historique = client.get("/api/emprunts", headers=bob).json["emprunts"]
        assert [e["date_retour"] is None for e in historique] == [True, False]  # en cours d'abord
    finally:
        Emprunt.objects.delete()
        from models import Exemplaire
        Exemplaire.objects.delete()
        autre.delete()


def test_filtre_genre(client, auth):
    from models import Film, Genre

    genre = Genre(tmdb_id=999999, nom="Zzz Genre").save()
    try:
        Film.objects(tmdb_id=FILM_ID).update_one(push__genres=genre)
        reponse = client.get("/api/films?genre=Zzz Genre", headers=auth("a")).json
        assert [f["id"] for f in reponse["films"]] == [FILM_ID]
        assert "Zzz Genre" in reponse["genres"]
        assert client.get("/api/films?genre=Inconnu", headers=auth("a")).json["films"] == []
    finally:
        genre.delete()
