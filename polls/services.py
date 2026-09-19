from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import F

from . import selectors
from .models import Option, Poll, Vote

MIN_OPTIONS = 2
MAX_OPTIONS = 5
DAILY_POLL_LIMIT = 10


class DailyLimitReached(Exception):
    pass


class PollClosed(Exception):
    pass


class InvalidOption(Exception):
    pass


class AlreadyVoted(Exception):
    pass


def create_poll(author, question, description, option_texts):
    if selectors.count_polls_created_today(author) >= DAILY_POLL_LIMIT:
        raise DailyLimitReached
    with transaction.atomic():
        poll = Poll.objects.create(author=author, question=question, description=description)
        Option.objects.bulk_create(
            [Option(poll=poll, text=text, position=position) for position, text in enumerate(option_texts)]
        )
    return poll


def _already_voted(poll, user, voter_key):
    if user.is_authenticated:
        return Vote.objects.filter(poll=poll, user=user).exists()
    return Vote.objects.filter(poll=poll, voter_key=voter_key, user__isnull=True).exists()


def cast_vote(poll, option, user, voter_key, voted_hint=False):
    """Oy kullanır. `voted_hint`: oturumda bu anket zaten oy verilmiş olarak işaretli."""
    if not poll.is_open:
        raise PollClosed
    if option is None or option.poll_id != poll.pk:
        raise InvalidOption
    if voted_hint or _already_voted(poll, user, voter_key):
        raise AlreadyVoted
    try:
        with transaction.atomic():
            Vote.objects.create(
                poll=poll,
                option=option,
                user=user if user.is_authenticated else None,
                voter_key=voter_key,
            )
            Option.objects.filter(pk=option.pk).update(vote_count=F("vote_count") + 1)
            Poll.objects.filter(pk=poll.pk).update(total_votes=F("total_votes") + 1)
    except IntegrityError:
        raise AlreadyVoted from None


def close_poll(poll):
    if poll.status != Poll.Status.CLOSED:
        poll.status = Poll.Status.CLOSED
        poll.save(update_fields=["status"])


def compute_percents(counts):
    """Yüzdeleri yuvarlar; toplam 100 değilse farkı en büyük seçeneğe ekler."""
    total = sum(counts)
    if total == 0:
        return [0] * len(counts)
    percents = [round(count * 100 / total) for count in counts]
    diff = 100 - sum(percents)
    if diff:
        percents[counts.index(max(counts))] += diff
    return percents


def decision_badge(total, percents):
    if total == 0:
        return "İlk oyu sen ver"
    top = sorted(percents, reverse=True)
    gap = top[0] - (top[1] if len(top) > 1 else 0)
    if gap <= 5:
        return "Kalabalık da kararsız"
    if gap <= 20:
        return "Az farkla önde"
    return "Karar net"


@dataclass
class OptionRow:
    option: Option
    index: int
    # Sonuçlar gizliyken sayı ve yüzde hiç taşınmaz; şablona sızması mümkün olmasın.
    count: int | None = None
    percent: int | None = None


@dataclass
class PollView:
    poll: Poll
    is_open: bool
    is_owner: bool
    has_voted: bool
    voted_option_id: int | None
    show_results: bool
    rows: list[OptionRow] = field(default_factory=list)
    badge: str = ""

    @property
    def total(self):
        return self.poll.total_votes

    @property
    def can_vote(self):
        return self.is_open and not self.has_voted

    @property
    def bar_active(self):
        return self.show_results and self.total > 0


def build_poll_view(poll, user, votes):
    """`votes`: selectors.votes_by_poll çıktısı."""
    is_open = poll.is_open
    is_owner = poll.author_id == user.id
    has_voted = poll.pk in votes
    show_results = not is_open or is_owner or has_voted

    options = list(poll.options.all())
    if show_results:
        counts = [option.vote_count for option in options]
        percents = compute_percents(counts)
        rows = [OptionRow(option, i, count, percent) for i, (option, count, percent) in enumerate(zip(options, counts, percents))]
        badge = decision_badge(poll.total_votes, percents)
    else:
        rows = [OptionRow(option, i) for i, option in enumerate(options)]
        badge = "İlk oyu sen ver" if poll.total_votes == 0 else "Sonuçlar oy verince açılır"
    return PollView(
        poll=poll,
        is_open=is_open,
        is_owner=is_owner,
        has_voted=has_voted,
        voted_option_id=votes.get(poll.pk),
        show_results=show_results,
        rows=rows,
        badge=badge,
    )


def build_poll_views(polls, user, session):
    votes = selectors.votes_by_poll(user, session, [poll.pk for poll in polls])
    return [build_poll_view(poll, user, votes) for poll in polls]


def results_payload(view):
    options = []
    for row in view.rows:
        item = {"id": row.option.pk, "text": row.option.text}
        if view.show_results:
            item.update(count=row.count, percent=row.percent)
        options.append(item)
    return {
        "total": view.total,
        "options": options,
        "voted_option_id": view.voted_option_id,
        "is_open": view.is_open,
        "badge": view.badge,
    }
