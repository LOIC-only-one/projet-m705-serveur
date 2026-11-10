"""Collections MongoDB utilisées par api-catalogue (index uniques créés par MongoEngine au premier accès)."""

from datetime import date, datetime, timezone

from mongoengine import CASCADE, PULL, BooleanField, DateField, DateTimeField, Document, IntField, ListField, ReferenceField, StringField

# Les utilisateurs vivent dans la base d'api-auth : on stocke leur id (le "sub" du JWT), pas une référence.


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
    bande_annonce = StringField()  # URL d'intégration YouTube
    genres = ListField(ReferenceField(Genre, reverse_delete_rule=PULL))


class Exemplaire(Document):
    """Copie d'un film possédée par un utilisateur : son catalogue privé."""
    # unique : un utilisateur déclare chaque film une seule fois (même en cas de double clic simultané)
    meta = {"collection": "exemplaire", "indexes": [{"fields": ["proprietaire_id", "film"], "unique": True}, "film"]}
    film = ReferenceField(Film, required=True)
    proprietaire_id = StringField(required=True)
    date_achat = DateField(default=date.today)
    # Rempli pendant un emprunt : une mise à jour atomique de ce champ empêche deux emprunts simultanés.
    emprunteur_id = StringField()


class Emprunt(Document):
    """Historique des emprunts (date_retour vide = en cours)."""
    meta = {"collection": "emprunt", "indexes": ["utilisateur_id"]}
    exemplaire = ReferenceField(Exemplaire, required=True, reverse_delete_rule=CASCADE)
    utilisateur_id = StringField(required=True)
    date_emprunt = DateTimeField(default=lambda: datetime.now(timezone.utc))
    date_retour_prevue = DateTimeField(required=True)
    date_retour = DateTimeField()
    prolonge = BooleanField(default=False)  # une seule prolongation par emprunt
