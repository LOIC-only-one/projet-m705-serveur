"""Formats JSON acceptés par l'API (validation des entrées)."""

## Comparatif avec django il s'agit d'un équivalent de serializers.py, mais pour Flask

from apiflask import Schema
from apiflask.fields import Integer, String
from apiflask.validators import Length, Range


class FilmsQuery(Schema):
    """Paramètres de GET /api/films : q = recherche dans le titre, genre = nom exact d'un genre."""
    q = String(load_default="", validate=Length(max=100))
    genre = String(load_default="", validate=Length(max=50))


class FilmIdIn(Schema):
    """Corps de POST /api/exemplaires et POST /api/emprunts : l'id TMDB du film."""
    film_id = Integer(required=True, validate=Range(min=1))
