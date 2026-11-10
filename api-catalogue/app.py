"""api-catalogue : consultation, modification et suppression des catalogues."""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from flask import request
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required
from mongoengine import connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import Emprunt, Exemplaire, Film, Genre

### Définitions des variables globales pour l'initialisation du catalogue
MAX_PAGES = 5  # nombre de pages de films à récupérer depuis l'API

#### Définition de l'application Flask
app = APIFlask(__name__, title="api-catalogue", docs_path="/api/catalogue/docs", spec_path="/api/catalogue/openapi.json",)
app.config.from_object("config")
app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
connect(host=app.config["MONGODB_URI"])
jwt = JWTManager(app)
init_errors(app, jwt)
#### Fin de la définition de l'application Flask

@app.get("/health")
def health():
    get_db().command("ping")
    return {"status": "ok"}

@jwt_required()
def est_admin():
    """Le rôle est lu dans le jeton d'accès, émis par api-auth."""
    return get_jwt().get("role") == "admin"

@jwt_required()
def verifier_acces(id):
    """Autorise l'admin ou le propriétaire du compte (l'identité du jeton est str(user.id))."""
    if not (est_admin() or get_jwt_identity() == id):
        abort(403, "Accès refusé.", extra_data={"code": "ACCES_REFUSE"})

#### Ajout du fetch vers l'api de TMDB pour récupérer les genres et les films, et les stocker dans la base MongoDB de api-catalogue.

def fetch_tmdb_genres(tmdb_api_key):
    """Récupère la liste des genres depuis l'API TMDB et les stocke dans la base MongoDB."""
    import requests

    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={tmdb_api_key}&language=fr-FR"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    genres_data = response.json().get("genres", [])
    for genre_data in genres_data:
        Genre.objects(tmdb_id=genre_data["id"]).update_one(
            set__tmdb_id=genre_data["id"],
            set__nom=genre_data["name"],
            upsert=True,
        )

def fetch_tmdb_films(tmdb_api_key, page=1):
    """Récupère la liste des films depuis l'API TMDB et les stocke dans la base MongoDB."""
    import requests

    url = f"https://api.themoviedb.org/3/movie/popular?api_key={tmdb_api_key}&language=fr-FR&page={page}"

    ## Traitement des données du catalogue : on ne stocke que les champs pertinents dans la base MongoDB de api-catalogue.
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    films_data = response.json().get("results", [])

    ## On stocke les films dans la base MongoDB de api-catalogue, en créant les genres si nécessaire.
    for film_data in films_data:
        genres = []
        for genre_id in film_data.get("genre_ids", []):
            genre = Genre.objects(tmdb_id=genre_id).first()
            if genre:
                genres.append(genre)
        release_date = film_data.get("release_date", "")
        year = int(release_date[:4]) if release_date[:4].isdigit() else None
        if year is None or year < 1888:
            continue
        Film.objects(tmdb_id=film_data["id"]).update_one(
            set__tmdb_id=film_data["id"],
            set__titre=film_data["title"],
            set__synopsis=film_data.get("overview", ""),
            set__annee=year,
            set__affiche=f"https://image.tmdb.org/t/p/w500{film_data.get('poster_path')}" if film_data.get("poster_path") else None,
            set__genres=genres,
            upsert=True
        )

def initialize_catalog(tmdb_api_key):
    """Initialise le catalogue en récupérant les genres et les films depuis l'API TMDB."""
    fetch_tmdb_genres(tmdb_api_key)
    for page in range(1, MAX_PAGES + 1):
        fetch_tmdb_films(tmdb_api_key, page)
    return {"status": "catalogue successfully initialized"}

def statistic(tmdb_api_key):
    """Récupère les statistiques du catalogue depuis l'API TMDB."""
    import requests

    url = f"https://api.themoviedb.org/3/movie/popular?api_key={tmdb_api_key}&language=fr-FR&page=1"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    films_data = response.json().get("results", [])
    return {
        "total_films": len(films_data),
        "total_genres": Genre.objects.count(),
        "total_exemplaires": Exemplaire.objects.count(),
        "total_emprunts": Emprunt.objects.count()
    }


@app.get("/api/tmdb/genres")
@jwt_required()
def tmdb_genres():
    fetch_tmdb_genres(app.config["TMDB_API_KEY"])
    return {"status": "genres successfully fetched", "total_genres": Genre.objects.count()}


@app.get("/api/tmdb/films")
@jwt_required()
def tmdb_films():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        abort(400, "Le numéro de page doit être positif.")
    fetch_tmdb_films(app.config["TMDB_API_KEY"], page)
    return {"status": "films successfully fetched", "page": page, "total_films": Film.objects.count()}


@app.post("/api/tmdb/initialize")
@jwt_required()
def tmdb_initialize():
    return initialize_catalog(app.config["TMDB_API_KEY"])


@app.get("/api/tmdb/statistics")
@jwt_required()
def tmdb_statistics():
    return statistic(app.config["TMDB_API_KEY"])
