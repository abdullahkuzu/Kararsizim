from django.conf import settings
from django.core.validators import MaxValueValidator, MinLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .utils import generate_public_id


class Poll(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Açık"
        CLOSED = "closed", "Kapalı"

    public_id = models.CharField(max_length=12, unique=True, default=generate_public_id, editable=False)
    question = models.CharField(max_length=140, validators=[MinLengthValidator(10)])
    description = models.CharField(max_length=280, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="polls")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    total_votes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    closes_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.question

    @property
    def is_open(self):
        return self.status == self.Status.ACTIVE and (self.closes_at is None or self.closes_at > timezone.now())

    def get_absolute_url(self):
        return f"/anket/{self.public_id}/"


class Option(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=80)
    position = models.PositiveSmallIntegerField(validators=[MaxValueValidator(4)])
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["poll", "position"], name="uniq_option_position_per_poll"),
        ]

    def __str__(self):
        return self.text


class Vote(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(Option, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="votes"
    )
    voter_key = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "user"], condition=Q(user__isnull=False), name="uniq_vote_per_user"
            ),
            models.UniqueConstraint(
                fields=["poll", "voter_key"], condition=Q(user__isnull=True), name="uniq_vote_per_anon"
            ),
        ]


class RateLimitHit(models.Model):
    """Hız sınırı sayacı. Ham IP saklanmaz, tuzlanmış özet (ip_hash) saklanır."""

    scope = models.CharField(max_length=20)
    ip_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["scope", "ip_hash", "created_at"], name="ratelimit_lookup")]


class Report(models.Model):
    """Bir anketin "uygunsuz" olarak işaretlenmesi; kişi başına anket başına bir kez."""

    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports"
    )
    reporter_key = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "bildirim"
        verbose_name_plural = "bildirimler"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "user"], condition=Q(user__isnull=False), name="uniq_report_per_user"
            ),
            models.UniqueConstraint(
                fields=["poll", "reporter_key"], condition=Q(user__isnull=True), name="uniq_report_per_anon"
            ),
        ]
