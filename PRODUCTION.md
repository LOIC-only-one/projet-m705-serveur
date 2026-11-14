# Déploiement production avec Docker Swarm

Le fichier [stack.production.yml](./stack.production.yml) déploie MongoDB, les trois API,
le front et Caddy sur un cluster Swarm.

## Préparation des nœuds

- Docker installé, l'utilisateur de déploiement dans le groupe `docker` (`sudo usermod -aG docker <user>`).
- Un nom d'hôte unique par nœud (`sudo hostnamectl set-hostname …`) : des VM clonées gardent
  le même nom, ce qui rend les étiquettes de nœud ambiguës.
- Ports 80/443 libres sur le nœud edge : un Apache livré avec l'image système empêche Caddy
  de démarrer (`sudo systemctl disable --now apache2`).

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

## Déploiement continu (doco-cd)

[doco-cd](https://doco.cd) tourne sur le manager et interroge ce dépôt toutes les 2 minutes
(polling : aucun port à ouvrir, fonctionne derrière un NAT). La configuration du déploiement est
dans [.doco-cd.yml](./.doco-cd.yml) : nom du stack, fichier compose, `SITE_ADDRESS`.

```bash
git clone https://github.com/LOIC-only-one/projet-m705-serveur.git
docker compose -f projet-m705-serveur/deploy/doco-cd.yml up -d
docker logs -f doco-cd
```

Il redéploie quand :

- un commit sur `main` modifie le stack ou sa configuration ;
- une image `videotheque-*:latest` change sur GHCR (`force_image_pull`), y compris celle du
  front publiée par le dépôt client. Un push sur l'un ou l'autre dépôt arrive donc en production
  au plus 2 minutes après la fin de la CI.

`SITE_ADDRESS` vaut `:80` (HTTP sur l'IP du nœud edge). Avec un domaine dont le DNS pointe vers le
nœud edge, y mettre le domaine : Caddy obtient alors le certificat HTTPS automatiquement.

## Déploiement manuel

Sans doco-cd, depuis une copie du dépôt sur le manager :

```bash
SITE_ADDRESS=:80 docker stack deploy --with-registry-auth -c stack.production.yml videotheque
docker stack services videotheque
```

Les tags d'image se choisissent avec `API_AUTH_TAG`, `API_USER_TAG`, `API_CATALOGUE_TAG` et
`FRONT_INDEX_TAG` (défaut `latest`).

Ne pas supprimer le volume `mongo_data` pendant une mise à jour.
