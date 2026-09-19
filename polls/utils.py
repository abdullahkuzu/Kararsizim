import hashlib
import secrets
import string

from django.conf import settings

_ALPHABET = string.ascii_letters + string.digits
PUBLIC_ID_LENGTH = 10


def generate_public_id():
    return "".join(secrets.choice(_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))


def voter_key_for(session_key):
    return hashlib.sha256((session_key + settings.VOTER_KEY_SALT).encode()).hexdigest()


def get_voter_key(request, create=False):
    if request.session.session_key is None:
        if not create:
            return None
        request.session.save()
    return voter_key_for(request.session.session_key)
