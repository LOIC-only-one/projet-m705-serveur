"""Collections MongoDB utilisées par api-auth (index uniques créés par MongoEngine au premier accès)."""

## Comparatif avec django il s'agit d'un équivalent de models.py, mais pour Flask
## Permet de définir les champs, types et contraintes des documents stockés dans MongoDB, ainsi que les relations entre eux.

from datetime import datetime, timezone

from mongoengine import CASCADE, DateField, DateTimeField, Document, ReferenceField, StringField


class Utilisateur(Document):
    meta = {"collection": "utilisateur"}
    username = StringField(required=True, unique=True, max_length=50)
    email = StringField(required=True, unique=True, max_length=255)
    password_hash = StringField(required=True)
    date_naissance = DateField(required=True)
    role = StringField(required=True, choices=("user", "admin"), default="user")
    photo_profil = StringField()
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))


class RefreshToken(Document):
    """Jetons de rafraîchissement encore valides : supprimer le document révoque le jeton."""
    meta = {"collection": "refresh_token"}
    jti = StringField(primary_key=True)
    utilisateur = ReferenceField(Utilisateur, required=True, reverse_delete_rule=CASCADE)
