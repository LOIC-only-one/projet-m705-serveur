// Exécuté une seule fois par l'image mongo, au premier démarrage (base vide).
// Crée le compte de api-auth, limité en lecture/écriture à la base videotheque.
const password = process.env.AUTH_DB_PASSWORD ||
  cat(process.env.AUTH_DB_PASSWORD_FILE).trim();

db.getSiblingDB("videotheque").createUser({
  user: "auth",
  pwd: password,
  roles: [{ role: "readWrite", db: "videotheque" }],
});
