# Sources

## Utilisation d'une IA

## Application Flask (`app.py`, `config.py`)

- Configuration chargée depuis un module (`app.config.from_object`) :
  https://flask.palletsprojects.com/en/stable/config/
- Lancement avec gunicorn au lieu du serveur de développement :
  https://flask.palletsprojects.com/en/stable/deploying/gunicorn/
- `ProxyFix`, pour lire l'IP réelle du client derrière Caddy :
  https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/
- Limitation des tentatives de connexion (Flask-Limiter) :
  https://flask-limiter.readthedocs.io/en/stable/

## Validation et documentation de l'API (`schemas.py`, `errors.py`)

- Schémas d'entrée et de sortie APIFlask (`@app.input`, `@app.output`) :
  https://apiflask.com/schema/
- Format d'erreur personnalisé (`error_processor`, `abort` avec `extra_data`) :
  https://apiflask.com/error-handling/
- Documentation OpenAPI générée (`/api/auth/docs`) :
  https://apiflask.com/openapi/
- marshmallow (champs, validateurs, `unknown = EXCLUDE`) :
  https://marshmallow.readthedocs.io/en/stable/quickstart.html
- marshmallow 4 : un validateur doit lever `ValidationError`, renvoyer `False` ne suffit plus :
  https://marshmallow.readthedocs.io/en/latest/upgrading.html

## Jetons JWT (`app.py`, `config.py`, `errors.py`)

- Options de Flask-JWT-Extended (RS256, durées de vie) :
  https://flask-jwt-extended.readthedocs.io/en/stable/options.html
- Emplacement des jetons (en-tête Authorization) :
  https://flask-jwt-extended.readthedocs.io/en/stable/token_locations.html
- Renouvellement des jetons :
  https://flask-jwt-extended.readthedocs.io/en/stable/refreshing_tokens.html
- Réponses d'erreur personnalisées (`unauthorized_loader`, `expired_token_loader`...) :
  https://flask-jwt-extended.readthedocs.io/en/stable/changing_default_behavior.html
- Standard JWT (RFC 7519) :
  https://datatracker.ietf.org/doc/html/rfc7519
- Rotation des jetons de rafraîchissement (OAuth 2.0 Security Best Current Practice, RFC 9700) :
  https://datatracker.ietf.org/doc/html/rfc9700
- Attributs de cookie `HttpOnly`, `Secure`, `SameSite=Strict` :
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie

## Mots de passe

- argon2-cffi (`PasswordHasher`, argon2id) :
  https://argon2-cffi.readthedocs.io/en/stable/api.html
- Standard Argon2 (RFC 9106) :
  https://datatracker.ietf.org/doc/html/rfc9106
- Stockage des mots de passe (OWASP) :
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- Même message et même temps de réponse pour un email inconnu ou un mauvais mot de passe (OWASP) :
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

## Base de données (`models.py`, `db/init`)

- Modèles Flask-SQLAlchemy :
  https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
- URL de connexion (`URL.create`) et `pool_pre_ping` :
  https://docs.sqlalchemy.org/en/20/core/engines.html
- Scripts d'initialisation `/docker-entrypoint-initdb.d` de l'image MariaDB :
  https://hub.docker.com/_/mariadb

## Conteneurs et CI/CD (`Dockerfile`, `.github/workflows/ci-cd.yml`)

- Référence Dockerfile (`USER`, `HEALTHCHECK`, `COPY`) :
  https://docs.docker.com/reference/dockerfile/
- Secrets Docker lus depuis des fichiers (`*_FILE`) :
  https://docs.docker.com/engine/swarm/secrets/
- Registry GitHub (ghcr.io) :
  https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- Action `docker/build-push-action` :
  https://github.com/docker/build-push-action

## Tests (`tests/test_auth.py`)

- Fixtures pytest :
  https://docs.pytest.org/en/stable/how-to/fixtures.html
