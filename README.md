# Vidéothèque · back-end (microservices)

**Application de prêt de films entre membres, découpée en trois API Flask (authentification, utilisateurs, catalogue), MongoDB et un reverse proxy Caddy, déployée sur Docker Swarm par une chaîne CI/CD GitHub Actions → GHCR.**

[![ci-cd](https://github.com/LOIC-only-one/projet-m705-serveur/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/LOIC-only-one/projet-m705-serveur/actions/workflows/ci-cd.yml)
![Python](https://img.shields.io/badge/Python-APIFlask-3776AB?style=flat-square&logo=python&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-8.2-47A248?style=flat-square&logo=mongodb&logoColor=white)
![JWT](https://img.shields.io/badge/JWT-RS256-000000?style=flat-square&logo=jsonwebtokens&logoColor=white)
![Caddy](https://img.shields.io/badge/Caddy-HTTPS-1F88C0?style=flat-square&logo=caddy&logoColor=white)
![Docker Swarm](https://img.shields.io/badge/Docker-Swarm-2496ED?style=flat-square&logo=docker&logoColor=white)

Projet du module M705. Front-end : [projet-m705-client](https://github.com/LOIC-only-one/projet-m705-client).

---

## Architecture

```mermaid
flowchart LR
    NAV([Navigateur]) -->|HTTPS| CAD[Caddy<br/>reverse proxy + en-têtes de sécurité]
    CAD -->|/| FR[front-index<br/>Flask + Jinja]
    CAD -->|/api/auth/*| AU[api-auth]
    CAD -->|/api/users*| US[api-user]
    CAD -->|/api/films, exemplaires, emprunts| CA[api-catalogue]
    FR -->|Bearer JWT| AU
    FR -->|Bearer JWT| US
    FR -->|Bearer JWT| CA
    AU --> DB[(MongoDB<br/>videotheque)]
    US --> DB
    CA --> DB
    CA -->|import des films| TMDB[(API TMDB)]
```

- Le navigateur ne parle qu'au front ; les API ne renvoient que du JSON, avec des erreurs toujours au format `{"error": {"code", "message"}}`.
- Chaque API publie sa documentation OpenAPI (`/api/auth/docs`, `/api/catalogue/docs`).
- Le détail des échanges et des collections est dans [MODELISATION.md](MODELISATION.md).

## Authentification

```mermaid
sequenceDiagram
    participant N as Navigateur
    participant F as front-index
    participant A as api-auth (clé privée)
    participant C as api-catalogue (clé publique)
    N->>F: POST /login
    F->>A: POST /api/auth/login
    A-->>F: access_token (15 min) + refresh_token (7 j)
    F-->>N: cookies HttpOnly
    N->>F: POST /emprunts
    F->>C: POST /api/emprunts + Bearer
    Note over C: vérifie la signature RS256<br/>sans appeler api-auth
    C-->>F: 201 ou 409
    Note over F,A: jeton expiré : POST /api/auth/refresh<br/>(rotation, l'ancien refresh est révoqué)
```

- **RS256** : seul `api-auth` détient la clé privée ; les autres services vérifient les jetons avec la clé publique.
- **Mots de passe** hachés avec Argon2 ; limitation de débit sur les routes d'authentification (Flask-Limiter).
- **Refresh tokens** stockés par `jti` : déconnexion = révocation, et chaque refresh n'est utilisable qu'une fois.

## Modèle de données

```mermaid
erDiagram
    UTILISATEUR ||--o{ REFRESH_TOKEN : possede
    UTILISATEUR ||--o{ EXEMPLAIRE : proprietaire
    FILM ||--o{ EXEMPLAIRE : copie
    GENRE }o--o{ FILM : classe
    EXEMPLAIRE ||--o{ EMPRUNT : historique
    UTILISATEUR ||--o{ EMPRUNT : emprunteur
```

Un **film** est la fiche commune (importée de TMDB) ; un **exemplaire** est la copie d'un membre. L'emprunt réserve un exemplaire libre en une seule opération atomique : deux demandes simultanées ne peuvent pas prendre la même copie.

**Règles d'emprunt** : pas son propre film, pas deux fois le même, pas un film pas encore sorti, 5 emprunts maximum, aucun nouvel emprunt en cas de retard, 14 jours prolongeables une fois de 7 jours.

## API

| Service | Routes |
|---|---|
| `api-auth` | `POST /api/auth/register` · `login` · `refresh` · `logout` |
| `api-user` | `GET /api/users` (admin) · `GET/PATCH/DELETE /api/users/<id>` · `POST /api/users/<id>/password` |
| `api-catalogue` | `GET /api/films` · `GET /api/films/<tmdb_id>` · `GET/POST /api/exemplaires` · `DELETE /api/exemplaires/<id>` · `GET/POST /api/emprunts` · `POST /api/emprunts/<id>/prolongation` · `POST /api/emprunts/<id>/retour` |

Chaque service expose aussi `GET /health`.

---

## Lancer en local

Les deux dépôts doivent être clonés côte à côte (`compose.test.yml` construit le front depuis `../projet-m705-client`).

```bash
git clone https://github.com/LOIC-only-one/projet-m705-serveur.git
git clone https://github.com/LOIC-only-one/projet-m705-client.git
cd projet-m705-serveur
./secrets/generer.sh                               # clés JWT et mot de passe de test
docker compose -f compose.test.yml up -d --build
```

Application : http://localhost:8080 · documentation de l'API d'authentification : http://localhost:8080/api/auth/docs

Tests (chaque API a son dossier `tests/`, exécutés avec pytest contre une base jetable) :

```bash
docker compose -f compose.test.yml up -d db-test
cd api-auth && pip install -r requirements.txt pytest && python -m pytest
```

## Déploiement

```mermaid
flowchart LR
    P[push sur main] --> GA[GitHub Actions<br/>build matrix ×3]
    GA -->|images :sha + :latest| GH[(GHCR)]
    GH -->|polling 2 min| DC[doco-cd<br/>.doco-cd.yml]
    DC -->|docker stack deploy| SW[Docker Swarm<br/>stack.production.yml]
```

Préparation du cluster, secrets Swarm et premier administrateur : [PRODUCTION.md](PRODUCTION.md).

---

Projet réalisé à deux : [Loïc Maurer](https://github.com/LOIC-only-one) et [NTQQQQ](https://github.com/NTQQQQ). Sources et usage de l'IA documentés dans [source.md](source.md).
