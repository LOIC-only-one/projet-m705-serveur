"""Formats JSON acceptés et renvoyés par l'API (validation des entrées, filtrage des sorties)."""

## Comparatif avec django il s'agit d'un équivalent de serializers.py, mais pour Flask


from datetime import date
from apiflask import Schema
from apiflask.fields import Date, Email, String
from apiflask.validators import Length, Regexp
from marshmallow import EXCLUDE, ValidationError

def date_passee(d):
    if d >= date.today():
        raise ValidationError("La date de naissance doit être dans le passé.")
class RegisterIn(Schema):
    """Corps attendu par POST /api/auth/register."""
    class Meta:
        unknown = EXCLUDE  # un champ "role" envoyé par le client est ignoré

    username = String(required=True, validate=Regexp(r"^[A-Za-z0-9_.-]{3,50}$"))
    email = Email(required=True, validate=Length(max=255))
    password = String(required=True, validate=Length(12, 1024))
    birthdate = Date(required=True, validate=date_passee)
class LoginIn(Schema):
    """Corps attendu par POST /api/auth/login."""
    email = String(required=True)
    password = String(required=True)


class UserOut(Schema):
    """Champs renvoyés pour un utilisateur : password_hash n'y est pas, il ne sort jamais."""
    id = String()
    username = String()
    email = String()
    role = String()
