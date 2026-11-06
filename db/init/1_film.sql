CREATE TABLE film (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    tmdb_id          INT UNIQUE NOT NULL,
    imdb_id          VARCHAR(12) NULL,
    titre            VARCHAR(255) NOT NULL,
    date_sortie      DATE NULL,
    synopsis         TEXT NOT NULL,
    note_tmdb        DECIMAL(3,1) NOT NULL,
    certification_fr VARCHAR(5) NULL,
    affiche_path     VARCHAR(255) NULL,
    bande_annonce    VARCHAR(255) NULL,
    synchro_le       DATETIME NOT NULL
);
