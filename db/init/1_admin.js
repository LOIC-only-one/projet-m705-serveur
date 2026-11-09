// Exécuté une seule fois par l'image mongo, au premier démarrage (base vide).
// Crée le compte administrateur de l'application (email admin@gmail.com, mot de passe "admin").
// mongosh ne sait pas calculer d'argon2 : le hash est précalculé avec
//   python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('admin'))"

db.getSiblingDB("videotheque").utilisateur.insertOne({
  username: "admin",
  email: "admin@gmail.com",
  password_hash: "$argon2id$v=19$m=65536,t=3,p=4$O6MAcv5sXRPHosPtpxu1pw$+ausKIyCkOT52uUKHjQ99/G/4gem9ynujsGsRrA4iSM",
  date_naissance: new Date("2000-01-01"),
  role: "admin",
  photo_profil: "https://cdn-icons-png.flaticon.com/512/149/149071.png",
  created_at: new Date(),
});
