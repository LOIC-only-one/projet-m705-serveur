"""api-catalogue : catalogue de films (importé de TMDB), exemplaires des utilisateurs et emprunts."""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from datetime import datetime, timedelta, timezone

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

TMDB_MAX_PAGES = 500  # limite maximale de pagination imposée par TMDB
DUREE_EMPRUNT = timedelta(days=14)
DUREE_PROLONGATION = timedelta(days=7)
MAX_EMPRUNTS = 5

#### Définition de l'application Flask
app = APIFlask(__name__, title="api-catalogue", docs_path="/api/catalogue/docs", spec_path="/api/catalogue/openapi.json",)
app.config.from_object("config")
app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
init_errors(app, jwt)
#### Fin de la définition de l'application Flask

"""
Endpoints (tous authentifiés sauf /health) :
GET    /api/films?q=...&genre=...      : catalogue filtré (titre, genre) + liste des genres.
GET    /api/films/<tmdb_id>            : fiche d'un film.
GET    /api/exemplaires                : mes exemplaires (mon catalogue privé).
POST   /api/exemplaires                : je déclare posséder un film (une fois par film).
DELETE /api/exemplaires/<id>           : je retire un exemplaire (propriétaire ou admin, s'il n'est pas prêté).
GET    /api/emprunts                   : mes emprunts, en cours puis rendus (historique).
POST   /api/emprunts                   : j'emprunte un film (un exemplaire libre d'un autre utilisateur).
POST   /api/emprunts/<id>/prolongation : +7 jours, une seule fois, avant la date prévue (emprunteur).
POST   /api/emprunts/<id>/retour       : rendre un emprunt (emprunteur, propriétaire ou admin).

Règles d'emprunt : pas son propre film, pas deux fois le même film, MAX_EMPRUNTS en cours,
et aucun emprunt tant qu'un film est en retard.
"""


#### Import du catalogue depuis TMDB
def tmdb_get(path, **params):
    """Interroge TMDB avec un token v4 ("Bearer ...") ou une clé API v3."""
    token = app.config["TMDB_API_KEY"].strip()
    url = f"https://api.themoviedb.org/3/{path}"
    if token.lower().startswith("bearer "):
        response = requests.get(url, headers={"Authorization": token}, params=params, timeout=10)
    else:
        response = requests.get(url, params={"api_key": token, **params}, timeout=10)
    response.raise_for_status()
    return response.json()


def importer_catalogue():
    """Copie toutes les pages de films populaires de TMDB dans la base."""
    for g in tmdb_get("genre/movie/list", language="fr-FR").get("genres", []):
        Genre.objects(tmdb_id=g["id"]).update_one(set__nom=g["name"], upsert=True)
    genres = {g.tmdb_id: g for g in Genre.objects}

    premiere_page = tmdb_get("movie/popular", language="fr-FR", page=1)
    total_pages = min(premiere_page.get("total_pages", 1), TMDB_MAX_PAGES)
    for page in range(1, total_pages + 1):
        resultat = premiere_page if page == 1 else tmdb_get(
            "movie/popular", language="fr-FR", page=page
        )
        for f in resultat.get("results", []):
            annee = f.get("release_date", "")[:4]
            if not annee.isdigit() or int(annee) < 1888:
                continue
            Film.objects(tmdb_id=f["id"]).update_one(
                set__titre=f["title"],
                set__synopsis=f.get("overview", ""),
                set__annee=int(annee),
                set__affiche=f"https://image.tmdb.org/t/p/w500{f['poster_path']}" if f.get("poster_path") else None,
                set__genres=[genres[i] for i in f.get("genre_ids", []) if i in genres],
                upsert=True,
            )


#### Fonctions utilitaires
def est_admin():
    """Le rôle est lu dans le jeton d'accès, émis par api-auth."""
    return get_jwt().get("role") == "admin"


def refuser(message="Accès refusé.", code="ACCES_REFUSE", status=403):
    abort(status, message, extra_data={"code": code})


def trouver(modele, id, code):
    """Renvoie le document, ou 404 si l'id est mal formé ou inconnu."""
    doc = modele.objects(id=id).first() if ObjectId.is_valid(id) else None
    if doc is None:
        refuser(f"{modele.__name__} introuvable.", code, 404)
    return doc


def trouver_film(tmdb_id):
    film = Film.objects(tmdb_id=tmdb_id).first()
    if film is None:
        refuser("Film introuvable.", "FILM_INTROUVABLE", 404)
    return film


def films_ou(champ, moi):
    """ObjectId des films dont je suis propriétaire (champ="proprietaire_id") ou emprunteur ("emprunteur_id")."""
    return set(Exemplaire._get_collection().distinct("film", {champ: moi}))


def statut_films(moi):
    """Renvoie une fonction film -> données du film + statut pour moi (une seule série de requêtes pour toute la liste)."""
    libres = Exemplaire.objects(emprunteur_id=None, proprietaire_id__ne=moi)
    disponibles = {r["_id"]: r["n"] for r in libres.aggregate([{"$group": {"_id": "$film", "n": {"$sum": 1}}}])}
    possedes, empruntes = films_ou("proprietaire_id", moi), films_ou("emprunteur_id", moi)
    return lambda f: {**film_json(f), "disponibles": disponibles.get(f.id, 0),
                      "possede": f.id in possedes, "emprunte": f.id in empruntes}


def film_json(film):
    return {"id": film.tmdb_id, "titre": film.titre, "synopsis": film.synopsis, "annee": film.annee,
            "affiche": film.affiche, "genres": [g.nom for g in film.genres]}


def trouver_bande_annonce(film):
    """Récupère et mémorise la première bande-annonce YouTube officielle."""
    if film.bande_annonce:
        return film.bande_annonce
    try:
        videos = tmdb_get(f"movie/{film.tmdb_id}/videos", language="fr-FR").get("results", [])
    except requests.RequestException:
        return None
    candidates = [
        video for video in videos
        if video.get("site") == "YouTube" and video.get("type") == "Trailer"
    ]
    candidates.sort(key=lambda video: (
        not video.get("official", False),
        video.get("iso_639_1") != "fr",
    ))
    if not candidates:
        return None
    film.bande_annonce = f"https://www.youtube.com/embed/{candidates[0]['key']}"
    film.save()
    return film.bande_annonce


def emprunt_json(emprunt):
    aujourdhui = datetime.now(timezone.utc).date()
    return {"id": str(emprunt.id), "film": film_json(emprunt.exemplaire.film),
            "date_emprunt": emprunt.date_emprunt.date().isoformat(),
            "date_retour_prevue": emprunt.date_retour_prevue.date().isoformat(),
            "date_retour": emprunt.date_retour.date().isoformat() if emprunt.date_retour else None,
            "en_retard": emprunt.date_retour is None and emprunt.date_retour_prevue.date() < aujourdhui,
            "prolonge": emprunt.prolonge}


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
    """Catalogue filtré. "disponibles" = exemplaires d'autres utilisateurs non prêtés."""
    if Film.objects.count() == 0:
        try:
            importer_catalogue()
        except requests.RequestException:
            refuser("TMDB indisponible, catalogue vide.", "TMDB_INDISPONIBLE", 502)

    films = Film.objects(titre__icontains=query["q"])  # icontains échappe la regex
    if query["genre"]:
        genre = Genre.objects(nom=query["genre"]).first()
        films = films.filter(genres=genre) if genre else films.none()
    statut = statut_films(get_jwt_identity())
    return {"films": [statut(f) for f in films.order_by("-annee", "titre")],
            "genres": [g.nom for g in Genre.objects.order_by("nom")]}


@app.get("/api/films/<int:tmdb_id>")
@jwt_required()
@app.doc(security="BearerAuth")
def obtenir_film(tmdb_id):
    """Fiche d'un film, avec son statut pour moi."""
    film = trouver_film(tmdb_id)
    resultat = statut_films(get_jwt_identity())(film)
    resultat["bande_annonce"] = trouver_bande_annonce(film)
    return resultat


@app.get("/api/exemplaires")
@jwt_required()
@app.doc(security="BearerAuth")
def mes_exemplaires():
    """Mon catalogue privé, avec la date de retour prévue des exemplaires prêtés."""
    exemplaires = list(Exemplaire.objects(proprietaire_id=get_jwt_identity()))
    prets = {e.exemplaire.id: emprunt_json(e) for e in Emprunt.objects(exemplaire__in=exemplaires, date_retour=None)}
    return {"exemplaires": [
        {"id": str(ex.id), "film": film_json(ex.film), "date_achat": ex.date_achat.isoformat(),
         "prete_jusquau": prets[ex.id]["date_retour_prevue"] if ex.id in prets else None,
         "en_retard": prets[ex.id]["en_retard"] if ex.id in prets else False}
        for ex in exemplaires
    ]}


@app.post("/api/exemplaires")
@jwt_required()
@app.input(FilmIdIn, arg_name="data")
@app.doc(security="BearerAuth")
def ajouter_exemplaire(data):
    """Déclare que je possède un exemplaire de ce film."""
    moi = get_jwt_identity()
    film = trouver_film(data["film_id"])
    if Exemplaire.objects(film=film, emprunteur_id=moi).first():
        refuser("Vous empruntez ce film : rendez-le avant de le déclarer.", "FILM_DEJA_EMPRUNTE", 409)
    try:
        ex = Exemplaire(film=film, proprietaire_id=moi).save()
    except NotUniqueError:  # index unique (proprietaire_id, film)
        refuser("Ce film est déjà dans votre vidéothèque.", "FILM_DEJA_POSSEDE", 409)
    return {"id": str(ex.id), "film": film_json(film), "date_achat": ex.date_achat.isoformat(),
            "prete_jusquau": None, "en_retard": False}, 201


@app.delete("/api/exemplaires/<id>")
@jwt_required()
@app.doc(security="BearerAuth")
def supprimer_exemplaire(id):
    """Retire un exemplaire de mon catalogue (son historique d'emprunts part avec lui)."""
    ex = trouver(Exemplaire, id, "EXEMPLAIRE_INTROUVABLE")
    if ex.proprietaire_id != get_jwt_identity() and not est_admin():
        refuser()
    # filtre emprunteur_id=None : rien n'est supprimé si un emprunt vient d'arriver entre-temps
    if not Exemplaire.objects(id=ex.id, emprunteur_id=None).delete():
        refuser("Exemplaire en cours de prêt.", "EXEMPLAIRE_PRETE", 409)
    return "", 204


@app.get("/api/emprunts")
@jwt_required()
@app.doc(security="BearerAuth")
def mes_emprunts():
    """Mes emprunts : en cours d'abord (par date de retour), puis l'historique (du plus récent au plus ancien)."""
    moi = get_jwt_identity()
    en_cours = Emprunt.objects(utilisateur_id=moi, date_retour=None).order_by("date_retour_prevue")
    rendus = Emprunt.objects(utilisateur_id=moi, date_retour__ne=None).order_by("-date_retour")
    return {"emprunts": [emprunt_json(e) for e in [*en_cours, *rendus]]}


@app.post("/api/emprunts")
@jwt_required()
@app.input(FilmIdIn, arg_name="data")
@app.doc(security="BearerAuth")
def emprunter(data):
    """Emprunte un exemplaire libre du film, appartenant à un autre utilisateur."""
    moi = get_jwt_identity()
    film = trouver_film(data["film_id"])
    if Exemplaire.objects(film=film, proprietaire_id=moi).first():
        refuser("Ce film est déjà dans votre vidéothèque.", "FILM_DEJA_POSSEDE", 409)
    # shortcut: ces vérifications puis la réservation ne sont pas atomiques ensemble ; deux requêtes simultanées
    # du même utilisateur peuvent passer. Passer à une transaction MongoDB si c'est un vrai problème.
    if Exemplaire.objects(film=film, emprunteur_id=moi).first():
        refuser("Vous empruntez déjà ce film.", "FILM_DEJA_EMPRUNTE", 409)
    en_cours = Emprunt.objects(utilisateur_id=moi, date_retour=None)
    if en_cours.filter(date_retour_prevue__lt=datetime.now(timezone.utc)).first():
        refuser("Rendez vos films en retard avant d'emprunter.", "EMPRUNT_EN_RETARD", 409)
    if en_cours.count() >= MAX_EMPRUNTS:
        refuser(f"Maximum {MAX_EMPRUNTS} emprunts en cours.", "LIMITE_EMPRUNTS", 409)
    # modify = findAndModify : réservation atomique, deux emprunts simultanés ne prennent pas la même copie
    ex = Exemplaire.objects(film=film, emprunteur_id=None, proprietaire_id__ne=moi).modify(set__emprunteur_id=moi, new=True)
    if ex is None:
        refuser("Aucun exemplaire disponible.", "AUCUN_EXEMPLAIRE_DISPONIBLE", 409)
    emprunt = Emprunt(exemplaire=ex, utilisateur_id=moi,
                      date_retour_prevue=datetime.now(timezone.utc) + DUREE_EMPRUNT).save()
    return emprunt_json(emprunt), 201


@app.post("/api/emprunts/<id>/prolongation")
@jwt_required()
@app.doc(security="BearerAuth")
def prolonger(id):
    """Repousse la date de retour de DUREE_PROLONGATION, une seule fois et avant la date prévue."""
    emprunt = trouver(Emprunt, id, "EMPRUNT_INTROUVABLE")
    if emprunt.utilisateur_id != get_jwt_identity():
        refuser()
    if emprunt.date_retour is None and emprunt.date_retour_prevue.date() < datetime.now(timezone.utc).date():
        refuser("Emprunt en retard : il ne peut plus être prolongé.", "EMPRUNT_EN_RETARD", 409)
    # prolonge__ne=True couvre aussi les emprunts créés avant l'ajout du champ
    emprunt = Emprunt.objects(id=emprunt.id, date_retour=None, prolonge__ne=True).modify(
        set__prolonge=True, set__date_retour_prevue=emprunt.date_retour_prevue + DUREE_PROLONGATION, new=True)
    if emprunt is None:
        refuser("Emprunt déjà prolongé ou rendu.", "PROLONGATION_IMPOSSIBLE", 409)
    return emprunt_json(emprunt)


@app.post("/api/emprunts/<id>/retour")
@jwt_required()
@app.doc(security="BearerAuth")
def rendre(id):
    """Clôt un emprunt et rend l'exemplaire disponible."""
    emprunt = trouver(Emprunt, id, "EMPRUNT_INTROUVABLE")
    moi = get_jwt_identity()
    if moi not in (emprunt.utilisateur_id, emprunt.exemplaire.proprietaire_id) and not est_admin():
        refuser()
    emprunt = Emprunt.objects(id=emprunt.id, date_retour=None).modify(set__date_retour=datetime.now(timezone.utc), new=True)
    if emprunt is None:
        refuser("Emprunt déjà rendu.", "DEJA_RENDU", 409)
    Exemplaire.objects(id=emprunt.exemplaire.id).update_one(unset__emprunteur_id=True)
    return emprunt_json(emprunt)
