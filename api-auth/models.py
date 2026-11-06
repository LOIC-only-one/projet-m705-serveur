"""Tables utilisées par api-auth (schéma créé par db/init/0_auth.sql)."""

## Comparatif avec django il s'agit d'un équivalent de models.py, mais pour Flask

from flask_sqlalchemy import SQLAlchemy

db_connexion = SQLAlchemy()
class Utilisateur(db_connexion.Model):
    id = db_connexion.Column(db_connexion.Integer, primary_key=True)
    username = db_connexion.Column(db_connexion.String(50), unique=True, nullable=False)
    email = db_connexion.Column(db_connexion.String(255), unique=True, nullable=False)
    password_hash = db_connexion.Column(db_connexion.String(255), nullable=False)
    date_naissance = db_connexion.Column(db_connexion.Date, nullable=False)
    role = db_connexion.Column(db_connexion.Enum("user", "admin"), nullable=False, default="user")

class RefreshToken(db_connexion.Model):
    """Jetons de rafraîchissement encore valides : supprimer la ligne révoque le jeton."""
    jti = db_connexion.Column(db_connexion.String(36), primary_key=True)
    utilisateur_id = db_connexion.Column(db_connexion.ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False)
