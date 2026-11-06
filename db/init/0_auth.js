// Exécuté une seule fois par l'image mongo, au premier démarrage (base vide).
// Crée le compte de api-auth, limité en lecture/écriture à la base videotheque.
db.getSiblingDB("videotheque").createUser({
  user: "auth",
  pwd: process.env.AUTH_DB_PASSWORD,
  roles: [{ role: "readWrite", db: "videotheque" }],
});
