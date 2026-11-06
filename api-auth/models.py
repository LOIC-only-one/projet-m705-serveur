"""Tables utilisées par api-auth (schéma créé par db/init/0_auth.sql)."""

## Comparatif avec django il s'agit d'un équivalent de models.py, mais pour Flask

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
class Utilisateur(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    date_naissance = db.Column(db.Date, nullable=False)
    role = db.Column(db.Enum("user", "admin"), nullable=False, default="user")


class RefreshToken(db.Model):
    """Jetons de rafraîchissement encore valides : supprimer la ligne révoque le jeton."""
    jti = db.Column(db.String(36), primary_key=True)
    utilisateur_id = db.Column(db.ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False)
