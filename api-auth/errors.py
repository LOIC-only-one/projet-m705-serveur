"""Gestion des erreurs : toutes les réponses d'erreur ont le format { "error": {code, message} }."""


def error(status, code, message):
    """Renvoie un corps JSON d'erreur et le code HTTP correspondant"""
    return {"error": {"code": code, "message": message}}, status


def format_error(error_response):
    """Erreurs APIFlask : validation, abort(), 404, 405, 429, 500..."""
    body, status = error(error_response.status_code, error_response.extra_data.get("code", error_response.message.upper().replace(" ", "_")), error_response.message,)
    if error_response.detail:
        body["error"]["details"] = error_response.detail
    return body, status, error_response.headers


def jeton_invalide(reason):
    """Jeton JWT absent ou mal formé / mauvaise signature."""
    return error(401, "JETON_INVALIDE", reason)


def jeton_expire(_header, _payload):
    """Jeton JWT dont la date d'expiration est dépassée."""
    return error(401, "JETON_EXPIRE", "Jeton de rafraîchissement expiré.")


def init_errors(app, jwt):
    """Branche les handlers sur l'app APIFlask et sur Flask-JWT-Extended."""
    app.error_processor(format_error)
    jwt.unauthorized_loader(jeton_invalide)
    jwt.invalid_token_loader(jeton_invalide)
    jwt.expired_token_loader(jeton_expire)
