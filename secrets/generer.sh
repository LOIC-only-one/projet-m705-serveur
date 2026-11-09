#!/bin/sh
# Génère les secrets de test (clé RSA du JWT, mot de passe MongoDB de api-auth). Ne jamais les commiter.
cd "$(dirname "$0")"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt_private_key.pem
openssl pkey -in jwt_private_key.pem -pubout -out jwt_public_key.pem
printf test > db_password # doit correspondre à AUTH_DB_PASSWORD dans compose.test.yml
chmod 644 jwt_private_key.pem # lisible par l'utilisateur non root du conteneur (secrets compose = bind mount)
