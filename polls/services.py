from dataclasses import dataclass, field

from django.db import transaction

from . import selectors
from .models import Option, Poll

MIN_OPTIONS = 2
MAX_OPTIONS = 5
DAILY_POLL_LIMIT = 10


class DailyLimitReached(Exception):
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


def can_see_results(poll, user, voted_ids):
    return not poll.is_open or poll.author_id == user.id or poll.pk in voted_ids


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
    show_results: bool
    rows: list[OptionRow] = field(default_factory=list)
    badge: str = ""

    @property
    def total(self):
        return self.poll.total_votes

    @property
    def bar_active(self):
        return self.show_results and self.total > 0


def build_poll_view(poll, show_results):
    options = list(poll.options.all())
    if show_results:
        counts = [option.vote_count for option in options]
        percents = compute_percents(counts)
        rows = [OptionRow(option, i, count, percent) for i, (option, count, percent) in enumerate(zip(options, counts, percents))]
        badge = decision_badge(poll.total_votes, percents)
    else:
        rows = [OptionRow(option, i) for i, option in enumerate(options)]
        badge = "İlk oyu sen ver" if poll.total_votes == 0 else "Sonuçlar oy verince açılır"
    return PollView(poll=poll, show_results=show_results, rows=rows, badge=badge)


def build_poll_views(polls, user, session):
    voted_ids = selectors.voted_poll_ids(user, session, [poll.pk for poll in polls])
    return [build_poll_view(poll, can_see_results(poll, user, voted_ids)) for poll in polls]
