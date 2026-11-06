CREATE TABLE genre (
    id   INT PRIMARY KEY,
    nom  VARCHAR(50) NOT NULL
);

CREATE TABLE film_genre (
    film_id  INT NOT NULL,
    genre_id INT NOT NULL,
    PRIMARY KEY (film_id, genre_id),
    FOREIGN KEY (film_id) REFERENCES film (id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genre (id) ON DELETE CASCADE
)


