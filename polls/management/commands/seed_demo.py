import hashlib
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from polls.models import Option, Poll, Vote

DEMO_USERS = ["demo_ayse", "demo_mert", "demo_deniz"]

DEMO_POLLS = [
    ("Bugün sinemaya mı gitsem, restorana mı?", ["Sinema", "Restoran"]),
    ("Hafta sonu tatili için hangisi?", ["Deniz kenarı", "Dağ evi", "Şehir turu"]),
    ("Yeni telefon alırken en çok neye bakmalı?", ["Kamera", "Pil ömrü", "Fiyat", "Performans", "Tasarım"]),
    ("Sabah kahvesi mi, çay mı?", ["Kahve", "Çay"]),
    ("Kedi mi köpek mi?", ["Kedi", "Köpek", "İkisi de", "Hiçbiri"]),
    ("Bu akşam ne yemeli?", ["Pizza", "Lahmacun", "Makarna", "Salata"]),
    ("Ders çalışmaya sabah mı akşam mı daha uygun?", ["Sabah", "Akşam"]),
    ("Yaz tatilinde hangi şehre gitmeli?", ["İzmir", "Antalya", "Bodrum", "Çeşme", "Muğla"]),
    ("Yeni bir dil öğrenecek olsan hangisi?", ["İspanyolca", "Almanca", "Japonca"]),
    ("Toplantıya kamera açık mı kapalı mı katılmalı?", ["Açık", "Kapalı"]),
    ("İlk maaşla ne alınır?", ["Kulaklık", "Ayakkabı", "Tatil", "Birikim"]),
    ("Dizi mi film mi izlesem?", ["Dizi", "Film"]),
]

CLOSED_POLL_INDEXES = {3, 9}


class Command(BaseCommand):
    help = "Demo kullanıcıları, anketleri ve rastgele oyları oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Önce demo kullanıcıların anketlerini siler.")
        parser.add_argument("--password", help="Demo kullanıcılar için parola (verilmezse giriş yapılamaz).")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        demo_polls = Poll.objects.filter(author__username__in=DEMO_USERS)
        if demo_polls.exists():
            if not options["reset"]:
                raise CommandError("Demo anketler zaten var. Yeniden üretmek için --reset kullan.")
            demo_polls.delete()

        users = []
        for name in DEMO_USERS:
            user, created = User.objects.get_or_create(username=name, defaults={"email": f"{name}@example.com"})
            if options["password"]:
                user.set_password(options["password"])
                user.save()
            elif created:
                user.set_unusable_password()
                user.save()
            users.append(user)

        rng = random.Random(42)
        now = timezone.now()
        votes = []
        vote_times = []

        for index, (question, texts) in enumerate(DEMO_POLLS):
            poll = Poll.objects.create(
                question=question,
                author=users[index % len(users)],
                status=Poll.Status.CLOSED if index in CLOSED_POLL_INDEXES else Poll.Status.ACTIVE,
            )
            created_at = now - timedelta(days=rng.randint(0, 9), hours=rng.randint(0, 23))
            Poll.objects.filter(pk=poll.pk).update(created_at=created_at)
            options = Option.objects.bulk_create(
                [Option(poll=poll, text=text, position=position) for position, text in enumerate(texts)]
            )
            weights = [rng.randint(1, 10) for _ in options]

            voting_users = rng.sample(users, rng.randint(0, len(users)))
            for user in voting_users:
                votes.append(Vote(poll=poll, option=rng.choices(options, weights)[0], user=user, voter_key=f"user-{user.pk}"))
                vote_times.append(created_at)
            for n in range(rng.randint(0, 50)):
                key = hashlib.sha256(f"seed-{poll.pk}-{n}".encode()).hexdigest()
                votes.append(Vote(poll=poll, option=rng.choices(options, weights)[0], voter_key=key))
                vote_times.append(created_at)

        created_votes = Vote.objects.bulk_create(votes)
        span = timedelta(hours=6)
        for vote, base in zip(created_votes, vote_times):
            vote.created_at = min(base + span * rng.random() * 4, now)
        Vote.objects.bulk_update(created_votes, ["created_at"])

        for row in Vote.objects.values("option_id").annotate(n=Count("id")):
            Option.objects.filter(pk=row["option_id"]).update(vote_count=row["n"])
        for row in Vote.objects.values("poll_id").annotate(n=Count("id")):
            Poll.objects.filter(pk=row["poll_id"]).update(total_votes=row["n"])

        self.stdout.write(self.style.SUCCESS(
            f"{len(users)} kullanıcı, {len(DEMO_POLLS)} anket, {len(created_votes)} oy oluşturuldu."
        ))
