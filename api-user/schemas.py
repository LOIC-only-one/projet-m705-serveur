from apiflask import Schema
from apiflask.fields import Date, DateTime, Email, List, String
from apiflask.validators import Length, OneOf


class UserOut(Schema):
    id = String()
    username = String()
    email = String()
    date_naissance = Date()
    role = String()
    photo_profil = String(allow_none=True)
    created_at = DateTime()


class UserIdsOut(Schema):
    ids = List(String())


class UserPatchIn(Schema):
    username = String(validate=Length(min=1, max=50))
    email = Email(validate=Length(max=255))
    date_naissance = Date()
    photo_profil = String(allow_none=True)
    role = String(validate=OneOf(["user", "admin"]))