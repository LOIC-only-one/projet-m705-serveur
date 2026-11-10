"""Collections MongoDB utilisées par api-catalogue (index uniques créés par MongoEngine au premier accès)."""

from datetime import datetime, timezone

from mongoengine import DENY, PULL, DateField, DateTimeField, Document, IntField, ListField, ReferenceField, StringField

class Genre(Document):
    meta = {"collection": "genre"}
    tmdb_id = IntField(required=True, unique=True)
    nom = StringField(required=True, unique=True, max_length=50)


class Film(Document):  # Document = une collection MongoDB (équivalent d'une table)
    meta = {"collection": "film"}
    tmdb_id = IntField(required=True, unique=True)  # les identifiants TMDB sont des entiers
    titre = StringField(required=True, max_length=255)
    synopsis = StringField()
    annee = IntField(required=True, min_value=1888)
    affiche = StringField()  # URL de l'affiche
    genres = ListField(ReferenceField(Genre, reverse_delete_rule=PULL))


class Exemplaire(Document):
    """Copie physique d'un film. Sa disponibilité se déduit des emprunts (date_retour vide = emprunté)."""
    meta = {"collection": "exemplaire"}
    film = ReferenceField(Film, required=True, reverse_delete_rule=DENY)
    date_achat = DateField(required=True)


class Emprunt(Document):
    meta = {"collection": "emprunt"}
    # DENY : on garde l'historique, impossible de supprimer un exemplaire déjà emprunté
    exemplaire = ReferenceField(Exemplaire, required=True, reverse_delete_rule=DENY)
    # L'utilisateur vit dans la base d'api-auth : on stocke son id (le "sub" du JWT), pas une référence
    utilisateur_id = StringField(required=True)
    date_emprunt = DateTimeField(default=lambda: datetime.now(timezone.utc))
    date_retour_prevue = DateTimeField(required=True)
    date_retour = DateTimeField()  # None tant que le film n'est pas rendu
