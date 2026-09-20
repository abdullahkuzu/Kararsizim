from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

from polls import services
from polls.utils import client_ip_hash


@receiver(user_login_failed)
def record_failed_login(sender, credentials=None, request=None, **kwargs):
    if request is not None:
        services.record_hit("login", client_ip_hash(request))
