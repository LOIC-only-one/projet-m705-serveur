CREATE TABLE exemplaire (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    film_id        INT NOT NULL,
    proprietaire_id INT NOT NULL,
    support        ENUM('physique','numerique') NOT NULL,
    ajoute_le       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (film_id) REFERENCES film (id) ON DELETE CASCADE,
    UNIQUE (proprietaire_id, film_id, support),
    FOREIGN KEY (proprietaire_id) REFERENCES utilisateur (id) ON DELETE CASCADE
);

CREATE TABLE emprunt (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    exemplaire_id  INT NOT NULL,
    emprunteur_id   INT NOT NULL,
    date_emprunt    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_retour     DATETIME NULL,
    FOREIGN KEY (exemplaire_id) REFERENCES exemplaire (id) ON DELETE CASCADE,
    FOREIGN KEY (emprunteur_id) REFERENCES utilisateur (id) ON DELETE CASCADE
);
