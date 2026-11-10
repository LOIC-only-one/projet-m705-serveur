"""Formats JSON acceptés et renvoyés par l'API (validation des entrées, filtrage des sorties)."""

## Comparatif avec django il s'agit d'un équivalent de serializers.py, mais pour Flask


from datetime import date
from apiflask import Schema
from apiflask.fields import Date, DateTime, Email, List, String
from apiflask.validators import Length, OneOf, Regexp
from marshmallow import ValidationError

def date_passee(d):
    if d >= date.today():
        raise ValidationError("La date de naissance doit être dans le passé.")


class UserOut(Schema):
    """Champs renvoyés pour un utilisateur : password_hash n'y est pas, il ne sort jamais."""
    id = String()
    username = String()
    email = String()
    birthdate = Date(attribute="date_naissance")  # même nom qu'à l'inscription
    role = String()
    photo_profil = String(allow_none=True)
    created_at = DateTime()


class UserIdsOut(Schema):
    """Corps renvoyé par GET /api/users."""
    ids = List(String())


class UserPatchIn(Schema):
    """Corps accepté par PATCH /api/users/<id> : tous les champs sont optionnels, les champs inconnus sont refusés."""
    username = String(validate=Regexp(r"^[A-Za-z0-9_.-]{3,50}$"))
    email = Email(validate=Length(max=255))
    birthdate = Date(validate=date_passee)
    password = String(validate=Length(12, 1024), load_only=True)  # même règle qu'à l'inscription, haché dans la route
    photo_profil = String(allow_none=True)
    role = String(validate=OneOf(["user", "admin"]))  # réservé aux admins, vérifié dans la route