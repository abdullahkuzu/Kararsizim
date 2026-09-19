import secrets
import string

_ALPHABET = string.ascii_letters + string.digits
PUBLIC_ID_LENGTH = 10


def generate_public_id():
    return "".join(secrets.choice(_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))
