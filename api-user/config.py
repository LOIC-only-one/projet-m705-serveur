"""Configuration de l'application Flask, chargée par app.config.from_object("config")."""

## Comparatif avec django il s'agit d'un équivalent de settings.py, mais pour Flask

import os
from urllib.parse import quote_plus


def read_secret(name):
    """Lit un secret Docker (fichier dont le chemin est dans la variable <NAME>_FILE)."""
    with open(os.environ[f"{name}_FILE"]) as f:
        return f.read()


# Connexion MongoDB : le compte "auth" est créé dans la base videotheque par db/init/0_auth.js
MONGODB_URI = "mongodb://{user}:{password}@{host}:{port}/{db}".format(
    user=os.environ.get("DB_USER", "auth"),
    password=quote_plus(read_secret("DB_PASSWORD").strip()),  # quote_plus : un mot de passe avec @ ou : casserait l'URI
    host=os.environ.get("DB_HOST", "db"),
    port=os.environ.get("DB_PORT", "27017"),
    db=os.environ.get("DB_NAME", "videotheque"),
)
VALIDATION_ERROR_STATUS_CODE = 400 # Permet de renvoyer un code 400 (Bad Request) au lieu de 422 (Unprocessable Entity) pour les erreurs de validation des entrées. Cela est plus conforme aux bonnes pratiques REST.