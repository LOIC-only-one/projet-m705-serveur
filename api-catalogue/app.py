"""api-catalogue : consultation, modification et suppression des catalogues."""

## Comparatif avec django il s'agit d'un équivalent de views.py, mais pour Flask

from apiflask import APIFlask, abort
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required
from mongoengine import connect
from mongoengine.connection import get_db
from werkzeug.middleware.proxy_fix import ProxyFix

from errors import init_errors
from models import Emprunt, Exemplaire, Film, Genre

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
