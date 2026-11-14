// Exécuté une seule fois par l'image mongo, au premier démarrage (base vide).
// Crée le compte de api-auth, limité en lecture/écriture à la base videotheque.
const password = process.env.AUTH_DB_PASSWORD ||
  require("fs").readFileSync(process.env.AUTH_DB_PASSWORD_FILE, "utf8").trim(); // mongosh n'a plus cat()

db.getSiblingDB("videotheque").createUser({
  user: "auth",
  pwd: password,
  roles: [{ role: "readWrite", db: "videotheque" }],
});
