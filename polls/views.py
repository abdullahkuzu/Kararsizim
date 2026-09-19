from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import selectors, services
from .forms import PollForm


def _page_number(request):
    try:
        page = int(request.GET.get("page", 1))
    except ValueError:
        return 1
    return min(max(page, 1), 50)


def index(request):
    tab = request.GET.get("tab", selectors.DEFAULT_TAB)
    if tab not in selectors.TABS:
        tab = selectors.DEFAULT_TAB
    page = _page_number(request)
    polls, has_more = selectors.load_more_page(selectors.feed_queryset(tab), page)
    return render(request, "polls/index.html", {
        "views": services.build_poll_views(polls, request.user, request.session),
        "tabs": selectors.TABS,
        "tab": tab,
        "has_more": has_more,
        "next_page": page + 1,
    })


def detail(request, public_id):
    poll = get_object_or_404(selectors.poll_queryset(), public_id=public_id)
    view = services.build_poll_views([poll], request.user, request.session)[0]
    return render(request, "polls/detail.html", {"view": view})


@login_required
def create(request):
    form = PollForm(request.POST) if request.method == "POST" else PollForm()
    if request.method == "POST" and form.is_valid():
        try:
            poll = services.create_poll(
                request.user,
                form.cleaned_data["question"],
                form.cleaned_data["description"],
                form.options,
            )
        except services.DailyLimitReached:
            form.add_error(None, f"Bir günde en fazla {services.DAILY_POLL_LIMIT} anket açabilirsin. Yarın tekrar dene.")
        else:
            messages.success(request, "Anketin yayında.")
            return redirect(poll)
    return render(request, "polls/create.html", {"form": form})


def profile(request, username):
    author = selectors.get_profile_user(username)
    if author is None:
        raise Http404
    page = _page_number(request)
    polls, has_more = selectors.load_more_page(selectors.author_queryset(author), page)
    return render(request, "polls/profile.html", {
        "author": author,
        "stats": selectors.profile_stats(author),
        "views": services.build_poll_views(polls, request.user, request.session),
        "has_more": has_more,
        "next_page": page + 1,
    })
