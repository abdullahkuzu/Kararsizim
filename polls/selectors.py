from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Poll, Vote
from .utils import voter_key_for

PAGE_SIZE = 20
POPULAR_WINDOW_DAYS = 7

TABS = {
    "yeni": "Yeni",
    "populer": "Popüler",
    "kapananlar": "Kapananlar",
}
DEFAULT_TAB = "yeni"


def poll_queryset():
    return Poll.objects.select_related("author").prefetch_related("options")


def _open_filter(now):
    return Q(status=Poll.Status.ACTIVE) & (Q(closes_at__isnull=True) | Q(closes_at__gt=now))


def feed_queryset(tab):
    now = timezone.now()
    qs = poll_queryset()
    if tab == "kapananlar":
        return qs.exclude(_open_filter(now))
    qs = qs.filter(_open_filter(now))
    if tab == "populer":
        since = now - timedelta(days=POPULAR_WINDOW_DAYS)
        return qs.annotate(
            recent_votes=Count("votes", filter=Q(votes__created_at__gte=since))
        ).order_by("-recent_votes", "-created_at")
    return qs.order_by("-created_at")


def author_queryset(user):
    return poll_queryset().filter(author=user).order_by("-created_at")


def load_more_page(queryset, page):
    """`page` sayfa kadar kaydı birikimli döner; bir fazla çekerek devamı olup olmadığını anlar."""
    limit = PAGE_SIZE * page
    items = list(queryset[: limit + 1])
    return items[:limit], len(items) > limit


def get_profile_user(username):
    return get_user_model().objects.filter(username__iexact=username).first()


def profile_stats(user):
    totals = user.polls.aggregate(polls=Count("id"), votes=Sum("total_votes"))
    return {"polls": totals["polls"], "votes": totals["votes"] or 0}


def votes_by_poll(user, session, poll_ids):
    """{poll_id: option_id | None}. Oturumdaki `voted_polls` ipucu seçeneği bilmez (None), DB kaydı bilir."""
    votes = {poll_id: None for poll_id in session.get("voted_polls", []) if poll_id in poll_ids}
    if not poll_ids:
        return votes
    if user.is_authenticated:
        rows = Vote.objects.filter(user=user, poll_id__in=poll_ids)
    elif session.session_key:
        rows = Vote.objects.filter(
            voter_key=voter_key_for(session.session_key), user__isnull=True, poll_id__in=poll_ids
        )
    else:
        return votes
    votes.update(rows.values_list("poll_id", "option_id"))
    return votes


def count_polls_created_today(user):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return Poll.objects.filter(author=user, created_at__gte=start).count()
