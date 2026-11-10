# Déploiement production avec Docker Swarm

Le fichier [stack.production.yml](./stack.production.yml) déploie MongoDB, les trois API,
le front et Caddy sur un cluster Swarm.

## Préparation du cluster

Initialiser Swarm sur le nœud manager :

```bash
docker swarm init --advertise-addr <IP_MANAGER>
```

Ajouter les nœuds workers avec la commande affichée par Docker, puis étiqueter les
nœuds qui hébergent les données et le point d'entrée :

```bash
docker node update --label-add videotheque.db=true <NOM_NOEUD_DB>
docker node update --label-add videotheque.edge=true <NOM_NOEUD_EDGE>
```

Les volumes nommés sont locaux au nœud. MongoDB doit donc rester sur un nœud avec
un disque persistant et sauvegardé. Caddy est également fixé sur le nœud edge pour
conserver ses certificats. Les scripts d'initialisation MongoDB et le Caddyfile sont
distribués comme configs Swarm : le dépôt n'a pas besoin d'être présent sur les workers.

## Secrets

Créer les secrets une seule fois sur le manager. Les fichiers ne sont jamais commités :

```bash
docker secret create db_password ./secrets/db_password
docker secret create jwt_private_key ./secrets/jwt_private_key.pem
docker secret create jwt_public_key ./secrets/jwt_public_key.pem
docker secret create tmdb_api_key ./secrets/api-key.txt
```

Le mot de passe de `db_password` sert à la fois au compte MongoDB `root` et au compte
applicatif `auth`. Utiliser une valeur forte et ne pas réutiliser celle de test.

Le compte administrateur de test n'est volontairement pas créé par le stack
production. Pour créer le premier administrateur, générer un hash Argon2 avec un
mot de passe choisi par l'exploitant, puis insérer l'utilisateur dans MongoDB
avec un accès administrateur temporaire. Ne réutiliser ni le mot de passe `admin`
du script de test ni son hash.

## Images et déploiement

Les variables de déploiement sont regroupées dans
[.env.production.example](./.env.production.example). Créer le fichier local
`.env.production` et le garder hors du dépôt :

```bash
cp .env.production.example .env.production
# Modifier .env.production avec le domaine et les tags réels.
set -a
. ./.env.production
set +a
docker stack deploy --with-registry-auth -c stack.production.yml videotheque
```

Les images `videotheque-*` doivent être publiées sur GHCR avant le déploiement.
Utiliser de préférence des tags immuables correspondant aux commits de chaque dépôt.

Contrôler le déploiement :

```bash
docker stack services videotheque
docker stack ps videotheque
```

Le DNS du domaine doit pointer vers le nœud edge et les ports TCP 80/443 doivent
être ouverts. Caddy obtiendra alors automatiquement le certificat HTTPS.

## Mise à jour

Publier les nouvelles images avec un nouveau tag, puis relancer :

````bash
Modifier les tags dans `.env.production`, puis recharger le fichier :

```bash
set -a
. ./.env.production
set +a
docker stack deploy --with-registry-auth -c stack.production.yml videotheque
````

Ne pas supprimer le volume `mongo_data` pendant une mise à jour.
