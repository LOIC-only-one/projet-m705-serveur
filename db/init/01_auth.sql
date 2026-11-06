-- Tables utilisées par api-auth. Les tables du catalogue viendront avec api-catalogue.
CREATE TABLE utilisateur (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(50)  NOT NULL UNIQUE,
    email          VARCHAR(255) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    date_naissance DATE         NOT NULL,
    role           ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    photo_profil   VARCHAR(255) NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- On stocke le SHA-256 du jeton de rafraîchissement, jamais le jeton lui-même.
CREATE TABLE refresh_token (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    utilisateur_id INT      NOT NULL,
    token_hash     CHAR(64) NOT NULL UNIQUE,
    expire_le      DATETIME NOT NULL,
    FOREIGN KEY (utilisateur_id) REFERENCES utilisateur (id) ON DELETE CASCADE
);
