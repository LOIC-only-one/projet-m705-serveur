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

CREATE TABLE refresh_token (
    jti            CHAR(36) PRIMARY KEY,
    utilisateur_id INT      NOT NULL,
    FOREIGN KEY (utilisateur_id) REFERENCES utilisateur (id) ON DELETE CASCADE
);
