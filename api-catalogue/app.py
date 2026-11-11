"""api-catalogue : catalogue de films (importé de TMDB), exemplaires des utilisateurs et emprunts.

Endpoints (tous demandent un jeton d'accès "Authorization: Bearer ...", sauf /health) :
GET    /api/films?q=&genre=&page=&per_page= : catalogue filtré + liste des genres.
GET    /api/films/<tmdb_id>                 : fiche d'un film.
GET    /api/exemplaires                     : mes exemplaires (les films que je possède).
POST   /api/exemplaires                     : je déclare posséder un film.
DELETE /api/exemplaires/<id>                : je retire un exemplaire (propriétaire ou admin, s'il n'est pas prêté).
GET    /api/emprunts                        : mes emprunts, en cours puis rendus.
POST   /api/emprunts                        : j'emprunte un film (un exemplaire libre d'un autre utilisateur).
POST   /api/emprunts/<id>/prolongation      : +7 jours, une seule fois, avant la date prévue.
POST   /api/emprunts/<id>/retour            : rendre un emprunt (emprunteur, propriétaire ou admin).

Règles d'emprunt : pas son propre film, pas deux fois le même film, pas un film pas encore sorti,
MAX_EMPRUNTS en cours au maximum, et aucun emprunt tant qu'un film est en retard.
"""

from datetime import datetime, timedelta, timezone
from math import ceil

import requests
from apiflask import APIFlask, abort
from bson import ObjectId
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required
from mongoengine import NotUniqueError, connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import Emprunt, Exemplaire, Film, Genre
from schemas import FilmIdIn, FilmsQuery

PAGES_TMDB = 20  # 20 pages x 20 films = 400 films importés
DUREE_EMPRUNT = timedelta(days=14)
DUREE_PROLONGATION = timedelta(days=7)
MAX_EMPRUNTS = 5

app = APIFlask(__name__, title="api-catalogue", docs_path="/api/catalogue/docs", spec_path="/api/catalogue/openapi.json")
app.config.from_object("config")
app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
init_errors(app, jwt)


def maintenant():
    return datetime.now(timezone.utc)


def refuser(status, code, message):
    abort(status, message, extra_data={"code": code})


#### Import depuis TMDB
def tmdb_get(chemin, **params):
    """GET sur l'API TMDB. Le secret contient "Bearer <token v4>"."""
    reponse = requests.get(f"https://api.themoviedb.org/3/{chemin}", params={"language": "fr-FR", **params},
                           headers={"Authorization": app.config["TMDB_API_KEY"].strip()}, timeout=10)
    reponse.raise_for_status()
    return reponse.json()


def importer_catalogue():
    """Copie les genres puis les PAGES_TMDB premières pages des films populaires dans MongoDB.

    update_one(upsert=True) : crée le film s'il n'existe pas, le met à jour sinon. Deux imports en même temps
    ne créent donc pas de doublons.
    """
    for g in tmdb_get("genre/movie/list")["genres"]:
        Genre.objects(tmdb_id=g["id"]).update_one(set__nom=g["name"], upsert=True)
    genres = {genre.tmdb_id: genre for genre in Genre.objects}

    for page in range(1, PAGES_TMDB + 1):
        for f in tmdb_get("movie/popular", page=page)["results"]:
            annee = f.get("release_date", "")[:4]
            if not annee.isdigit():  # film sans date de sortie : ignoré
                continue
            Film.objects(tmdb_id=f["id"]).update_one(
                set__titre=f["title"],
                set__synopsis=f.get("overview", ""),
                set__annee=int(annee),
                set__affiche=f"https://image.tmdb.org/t/p/w500{f['poster_path']}" if f.get("poster_path") else None,
                set__genres=[genres[i] for i in f.get("genre_ids", []) if i in genres],
                upsert=True,
            )


def bande_annonce(film):
    """URL YouTube de la première bande-annonce trouvée sur TMDB, gardée en base après le premier appel."""
    if film.bande_annonce is None:
        try:
            videos = tmdb_get(f"movie/{film.tmdb_id}/videos")["results"]
        except requests.RequestException:
            return None
        for video in videos:
            if video["site"] == "YouTube" and video["type"] == "Trailer":
                film.bande_annonce = f"https://www.youtube.com/embed/{video['key']}"
                film.save()
                break
    return film.bande_annonce


#### Conversion des documents en JSON
def film_json(film):
    return {"id": film.tmdb_id, "titre": film.titre, "synopsis": film.synopsis, "annee": film.annee,
            "affiche": film.affiche, "genres": [genre.nom for genre in film.genres],
            "empruntable": film.annee <= maintenant().year}


def film_pour_moi(film, moi):
    """film_json + ce qui concerne l'utilisateur connecté."""
    # shortcut: 3 petites requêtes par film (60 pour une page de 20) ; passer à une agrégation si ça devient lent.
    resultat = film_json(film)
    resultat["disponibles"] = Exemplaire.objects(film=film, emprunteur_id=None, proprietaire_id__ne=moi).count()
    resultat["possede"] = Exemplaire.objects(film=film, proprietaire_id=moi).count() > 0
    resultat["emprunte"] = Exemplaire.objects(film=film, emprunteur_id=moi).count() > 0
    return resultat


def en_retard(emprunt):
    return emprunt.date_retour is None and emprunt.date_retour_prevue.date() < maintenant().date()


def emprunt_json(emprunt):
    return {"id": str(emprunt.id), "film": film_json(emprunt.exemplaire.film),
            "date_emprunt": emprunt.date_emprunt.date().isoformat(),
            "date_retour_prevue": emprunt.date_retour_prevue.date().isoformat(),
            "date_retour": emprunt.date_retour.date().isoformat() if emprunt.date_retour else None,
            "en_retard": en_retard(emprunt), "prolonge": emprunt.prolonge}


def exemplaire_json(ex):
    emprunt = Emprunt.objects(exemplaire=ex, date_retour=None).first() if ex.emprunteur_id else None
    return {"id": str(ex.id), "film": film_json(ex.film), "date_achat": ex.date_achat.isoformat(),
            "prete_jusquau": emprunt.date_retour_prevue.date().isoformat() if emprunt else None,
            "en_retard": en_retard(emprunt) if emprunt else False}


#### Recherche d'un document (404 si absent)
def trouver_film(tmdb_id):
    film = Film.objects(tmdb_id=tmdb_id).first()
    if film is None:
        refuser(404, "FILM_INTROUVABLE", "Film introuvable.")
    return film


def trouver_exemplaire(id):
    ex = Exemplaire.objects(id=id).first() if ObjectId.is_valid(id) else None
    if ex is None:
        refuser(404, "EXEMPLAIRE_INTROUVABLE", "Exemplaire introuvable.")
    return ex


def trouver_emprunt(id):
    emprunt = Emprunt.objects(id=id).first() if ObjectId.is_valid(id) else None
    if emprunt is None:
        refuser(404, "EMPRUNT_INTROUVABLE", "Emprunt introuvable.")
    return emprunt


#### Routes
@app.get("/health")
def health():
    get_db().command("ping")
    return {"status": "ok"}


@app.get("/api/films")
@jwt_required()
@app.input(FilmsQuery, location="query", arg_name="query")
@app.doc(security="BearerAuth")
def lister_films(query):
    if Film.objects.count() == 0:  # premier lancement : base vide
        try:
            importer_catalogue()
        except requests.RequestException:
            refuser(502, "TMDB_INDISPONIBLE", "TMDB indisponible, catalogue vide.")

    films = Film.objects(titre__icontains=query["q"])  # icontains échappe le texte : pas d'injection de regex
    if query["genre"]:
        genre = Genre.objects(nom=query["genre"]).first()
        films = films.filter(genres=genre) if genre else films.none()
    total = films.count()
    page, per_page = query["page"], query["per_page"]
    films = films.order_by("-annee", "titre").skip((page - 1) * per_page).limit(per_page)
    moi = get_jwt_identity()
    return {"films": [film_pour_moi(f, moi) for f in films],
            "genres": [g.nom for g in Genre.objects.order_by("nom")],
            "page": page, "per_page": per_page, "total": total, "pages": ceil(total / per_page)}


@app.get("/api/films/<int:tmdb_id>")
@jwt_required()
@app.doc(security="BearerAuth")
def obtenir_film(tmdb_id):
    film = trouver_film(tmdb_id)
    resultat = film_pour_moi(film, get_jwt_identity())
    resultat["bande_annonce"] = bande_annonce(film)
    return resultat


@app.get("/api/exemplaires")
@jwt_required()
@app.doc(security="BearerAuth")
def mes_exemplaires():
    return {"exemplaires": [exemplaire_json(ex) for ex in Exemplaire.objects(proprietaire_id=get_jwt_identity())]}


@app.post("/api/exemplaires")
@jwt_required()
@app.input(FilmIdIn, arg_name="data")
@app.doc(security="BearerAuth")
def ajouter_exemplaire(data):
    moi = get_jwt_identity()
    film = trouver_film(data["film_id"])
    if Exemplaire.objects(film=film, emprunteur_id=moi).count():
        refuser(409, "FILM_DEJA_EMPRUNTE", "Vous empruntez ce film : rendez-le avant de le déclarer.")
    try:
        ex = Exemplaire(film=film, proprietaire_id=moi).save()
    except NotUniqueError:  # index unique (proprietaire_id, film)
        refuser(409, "FILM_DEJA_POSSEDE", "Ce film est déjà dans votre vidéothèque.")
    return exemplaire_json(ex), 201


@app.delete("/api/exemplaires/<id>")
@jwt_required()
@app.doc(security="BearerAuth")
def supprimer_exemplaire(id):
    ex = trouver_exemplaire(id)
    if ex.proprietaire_id != get_jwt_identity() and get_jwt().get("role") != "admin":
        refuser(403, "ACCES_REFUSE", "Accès refusé.")
    # emprunteur_id=None dans le filtre : rien n'est supprimé si l'exemplaire est prêté
    if not Exemplaire.objects(id=ex.id, emprunteur_id=None).delete():
        refuser(409, "EXEMPLAIRE_PRETE", "Exemplaire en cours de prêt.")
    return "", 204


@app.get("/api/emprunts")
@jwt_required()
@app.doc(security="BearerAuth")
def mes_emprunts():
    """En cours d'abord (par date de retour prévue), puis les rendus (du plus récent au plus ancien)."""
    moi = get_jwt_identity()
    en_cours = Emprunt.objects(utilisateur_id=moi, date_retour=None).order_by("date_retour_prevue")
    rendus = Emprunt.objects(utilisateur_id=moi, date_retour__ne=None).order_by("-date_retour")
    return {"emprunts": [emprunt_json(e) for e in list(en_cours) + list(rendus)]}


@app.post("/api/emprunts")
@jwt_required()
@app.input(FilmIdIn, arg_name="data")
@app.doc(security="BearerAuth")
def emprunter(data):
    moi = get_jwt_identity()
    film = trouver_film(data["film_id"])
    en_cours = Emprunt.objects(utilisateur_id=moi, date_retour=None)
    if film.annee > maintenant().year:
        refuser(409, "FILM_NON_SORTI", "Ce film ne peut pas être emprunté avant son année de sortie.")
    if Exemplaire.objects(film=film, proprietaire_id=moi).count():
        refuser(409, "FILM_DEJA_POSSEDE", "Ce film est déjà dans votre vidéothèque.")
    if Exemplaire.objects(film=film, emprunteur_id=moi).count():
        refuser(409, "FILM_DEJA_EMPRUNTE", "Vous empruntez déjà ce film.")
    if en_cours.filter(date_retour_prevue__lt=maintenant()).count():
        refuser(409, "EMPRUNT_EN_RETARD", "Rendez vos films en retard avant d'emprunter.")
    if en_cours.count() >= MAX_EMPRUNTS:
        refuser(409, "LIMITE_EMPRUNTS", f"Maximum {MAX_EMPRUNTS} emprunts en cours.")

    # modify() cherche un exemplaire libre ET le réserve en une seule opération MongoDB (atomique) :
    # deux personnes qui empruntent en même temps ne peuvent pas obtenir le même exemplaire.
    ex = Exemplaire.objects(film=film, emprunteur_id=None, proprietaire_id__ne=moi).modify(
        set__emprunteur_id=moi, new=True)
    if ex is None:
        refuser(409, "AUCUN_EXEMPLAIRE_DISPONIBLE", "Aucun exemplaire disponible.")
    emprunt = Emprunt(exemplaire=ex, utilisateur_id=moi, date_retour_prevue=maintenant() + DUREE_EMPRUNT).save()
    return emprunt_json(emprunt), 201


@app.post("/api/emprunts/<id>/prolongation")
@jwt_required()
@app.doc(security="BearerAuth")
def prolonger(id):
    emprunt = trouver_emprunt(id)
    if emprunt.utilisateur_id != get_jwt_identity():
        refuser(403, "ACCES_REFUSE", "Accès refusé.")
    if en_retard(emprunt):
        refuser(409, "EMPRUNT_EN_RETARD", "Emprunt en retard : il ne peut plus être prolongé.")
    if emprunt.prolonge or emprunt.date_retour:
        refuser(409, "PROLONGATION_IMPOSSIBLE", "Emprunt déjà prolongé ou rendu.")
    emprunt.prolonge = True
    emprunt.date_retour_prevue += DUREE_PROLONGATION
    emprunt.save()
    return emprunt_json(emprunt)


@app.post("/api/emprunts/<id>/retour")
@jwt_required()
@app.doc(security="BearerAuth")
def rendre(id):
    emprunt = trouver_emprunt(id)
    moi = get_jwt_identity()
    if moi not in (emprunt.utilisateur_id, emprunt.exemplaire.proprietaire_id) and get_jwt().get("role") != "admin":
        refuser(403, "ACCES_REFUSE", "Accès refusé.")
    if emprunt.date_retour:
        refuser(409, "DEJA_RENDU", "Emprunt déjà rendu.")
    emprunt.date_retour = maintenant()
    emprunt.save()
    Exemplaire.objects(id=emprunt.exemplaire.id).update_one(unset__emprunteur_id=True)  # l'exemplaire redevient libre
    return emprunt_json(emprunt)
