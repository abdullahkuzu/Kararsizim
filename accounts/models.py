from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

username_validator = RegexValidator(
    regex=r"^[a-zA-Z0-9_]{3,20}$",
    message="Kullanıcı adı 3–20 karakter olmalı; sadece harf, rakam ve alt çizgi içerebilir.",
)


class CaseInsensitiveUserManager(UserManager):
    def get_by_natural_key(self, username):
        return self.get(username__iexact=username)


class User(AbstractUser):
    objects = CaseInsensitiveUserManager()

    username = models.CharField(
        max_length=20,
        unique=True,
        validators=[username_validator],
        error_messages={"unique": "Bu kullanıcı adı alınmış."},
    )
    email = models.EmailField(
        unique=True,
        error_messages={"unique": "Bu e-posta ile zaten bir hesap var."},
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="uniq_username_ci"),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)
