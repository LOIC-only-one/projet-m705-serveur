# Modélisation et échanges

## Architecture

```
Navigateur ──HTML/cookies──> front-index ──JSON + "Authorization: Bearer"──> api-auth       ┐
                             (Flask, rendu    ──────────────────────────────> api-user       ├─> MongoDB "videotheque"
                              côté serveur)   ──────────────────────────────> api-catalogue  ┘        │
                                                                                   └──> TMDB (import des films)
```

- Le navigateur ne parle **qu'au front**. Le front appelle les API côté serveur.
- Les API ne renvoient que du JSON. Les erreurs ont toujours la forme `{"error": {"code", "message"}}`.
- Caddy (reverse proxy) expose aussi les API sur `/api/...` (doc OpenAPI : `/api/auth/docs`, `/api/catalogue/docs`).

## Collections MongoDB

```
utilisateur ─1───n─ refresh_token                 (api-auth / api-user)

genre ─n───n─ film ─1───n─ exemplaire ─1───n─ emprunt   (api-catalogue)
                           proprietaire_id      utilisateur_id
                           emprunteur_id
```

| Collection | Rôle | Champs clés |
|---|---|---|
| `utilisateur` | compte | `username`, `email` (uniques), `password_hash` (argon2), `role` user/admin |
| `refresh_token` | refresh tokens encore valides | `jti` (id du jeton). Supprimer le document = révoquer le jeton |
| `genre`, `film` | copie locale de TMDB | `tmdb_id` (unique), `film.genres` = liste de références |
| `exemplaire` | « je possède ce film » | `film`, `proprietaire_id`, `emprunteur_id` (rempli pendant un prêt). Unique (`proprietaire_id`, `film`) |
| `emprunt` | historique des prêts | `exemplaire`, `utilisateur_id`, `date_retour_prevue`, `date_retour` (vide = en cours), `prolonge` |

Choix :
- **Film ≠ Exemplaire** : le film est la fiche commune (TMDB), l'exemplaire est la copie physique d'un membre.
  Plusieurs membres peuvent posséder le même film → plusieurs exemplaires empruntables.
- **`exemplaire.emprunteur_id` + collection `emprunt`** : `emprunteur_id` est l'état *actuel* (prêté ou libre),
  `emprunt` garde l'*historique*. L'état actuel sur l'exemplaire permet de réserver un exemplaire libre
  en **une seule opération atomique** (`modify`) : deux emprunts simultanés ne peuvent pas prendre la même copie.
- **Les utilisateurs sont référencés par leur id (chaîne)** dans le catalogue, pas par une référence MongoDB :
  le catalogue ne lit jamais la collection `utilisateur`, il fait confiance au `sub` du jeton JWT.
- **Import TMDB à la demande** : au premier `GET /api/films` sur une base vide, on importe 20 pages (400 films).

## Authentification (JWT RS256)

- `api-auth` a la **clé privée** : lui seul crée des jetons.
- `api-user` et `api-catalogue` n'ont que la **clé publique** : ils vérifient les jetons sans appeler `api-auth`.
- `access_token` (15 min) : contient `sub` (id utilisateur) et `role`. Envoyé à chaque appel d'API.
- `refresh_token` (7 jours) : sert seulement à obtenir un nouveau couple de jetons. Son `jti` est stocké en base
  pour pouvoir le révoquer (logout) ; il est supprimé à chaque utilisation (rotation : un refresh volé ne sert qu'une fois).
- Le front garde les deux jetons dans des **cookies HttpOnly** (illisibles par JavaScript) sur son propre domaine.

### Connexion
```
Navigateur ─POST /login (email, mdp)─> front ─POST /api/auth/login {email, password}─> api-auth
                                             <─ 200 {access_token, refresh_token, expires_in} ─
           <─ 302 / + Set-Cookie access_token, refresh_token ─
```

### Une page normale (ex. emprunter un film)
```
Navigateur ─POST /emprunts (cookie access_token)─> front ─POST /api/emprunts {film_id}──────────> api-catalogue
                                                         Authorization: Bearer <access_token>    vérifie la signature,
                                                   <─ 201 {emprunt} ou 409 {error} ──────────    applique les règles
           <─ 302 page précédente, ou page du film avec le message d'erreur ─
```

### Jeton d'accès expiré
Le cookie `access_token` expire en même temps que le jeton. Avant chaque page, si ce cookie manque mais
que `refresh_token` est là, le front appelle `POST /api/auth/refresh` (refresh en `Bearer`) et repose les deux cookies.
Si `api-auth` refuse (jeton expiré ou révoqué), le front efface les cookies : l'utilisateur est déconnecté.

## Règles d'emprunt (api-catalogue)

Pas son propre film · pas deux fois le même film · pas un film pas encore sorti · 5 emprunts en cours maximum ·
aucun nouvel emprunt si un film est en retard · 14 jours, prolongeable une fois de 7 jours avant l'échéance.
