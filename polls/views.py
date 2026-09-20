from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import selectors, services
from .forms import PollForm
from .models import Poll
from .utils import client_ip_hash, get_voter_key


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
    query = selectors.clean_query(request.GET.get("q"))
    page = _page_number(request)
    polls, has_more = selectors.load_more_page(selectors.feed_queryset(tab, query), page)
    return render(request, "polls/index.html", {
        "views": services.build_poll_views(polls, request.user, request.session),
        "tabs": selectors.TABS,
        "tab": tab,
        "q": query,
        "has_more": has_more,
        "next_page": page + 1,
    })


def _render_detail(request, poll, status=200):
    services.close_if_expired(poll)
    view = services.build_poll_views([poll], request.user, request.session)[0]
    reported = not view.is_owner and selectors.has_reported(poll.pk, request.user, request.session)
    return render(request, "polls/detail.html", {"view": view, "reported": reported}, status=status)


def detail(request, public_id):
    poll = get_object_or_404(selectors.poll_queryset(), public_id=public_id)
    return _render_detail(request, poll)


def _wants_json(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _mark_voted(session, poll_id):
    voted = session.get("voted_polls", [])
    if poll_id not in voted:
        session["voted_polls"] = [*voted, poll_id]


VOTE_ERRORS = {
    services.PollClosed: (403, "Bu anket kapandı."),
    services.InvalidOption: (400, "Geçersiz seçenek."),
    services.AlreadyVoted: (409, "Bu ankete zaten oy verdin."),
}


@require_POST
def vote(request, public_id):
    poll = get_object_or_404(selectors.poll_queryset(), public_id=public_id)
    voted_hint = poll.pk in request.session.get("voted_polls", [])

    try:
        option_id = int(request.POST.get("option_id", ""))
    except ValueError:
        option_id = None
    option = next((o for o in poll.options.all() if o.pk == option_id), None)

    services.close_if_expired(poll)
    error = None
    retry_after = None
    try:
        services.cast_vote(
            poll, option, request.user, get_voter_key(request, create=True), voted_hint,
            ip_hash=client_ip_hash(request),
        )
    except services.RateLimited as exc:
        error = (429, "Çok fazla oy kullandın. Biraz sonra tekrar dene.")
        retry_after = exc.retry_after
    except tuple(VOTE_ERRORS) as exc:
        error = VOTE_ERRORS[type(exc)]
    else:
        _mark_voted(request.session, poll.pk)

    if error and error[0] == 409:
        _mark_voted(request.session, poll.pk)

    response = _vote_response(request, poll, error)
    if retry_after:
        response["Retry-After"] = str(retry_after)
    return response


def _vote_response(request, poll, error):
    if not _wants_json(request):
        if error is None:
            messages.success(request, "Oyun kaydedildi.")
            return redirect(poll)
        if error[0] == 400:
            return HttpResponse(error[1], status=400, content_type="text/plain; charset=utf-8")
        messages.error(request, error[1])
        poll = selectors.poll_queryset().get(pk=poll.pk)
        return _render_detail(request, poll, status=error[0])

    if error and error[0] == 400:
        return JsonResponse({"error": error[1]}, status=400)
    poll = selectors.poll_queryset().get(pk=poll.pk)
    view = services.build_poll_views([poll], request.user, request.session)[0]
    payload = services.results_payload(view)
    if error:
        return JsonResponse({"error": error[1], **payload}, status=error[0])
    return JsonResponse({"ok": True, **payload})


@require_GET
@never_cache
def results(request, public_id):
    poll = get_object_or_404(selectors.poll_queryset(), public_id=public_id)
    services.close_if_expired(poll)
    view = services.build_poll_views([poll], request.user, request.session)[0]
    return JsonResponse(services.results_payload(view))


@require_POST
def report(request, public_id):
    poll = get_object_or_404(Poll, public_id=public_id)
    try:
        services.report_poll(
            poll, request.user, get_voter_key(request, create=True), ip_hash=client_ip_hash(request)
        )
    except services.OwnPoll:
        messages.error(request, "Kendi anketini bildiremezsin.")
    except services.AlreadyReported:
        messages.info(request, "Bu anketi zaten bildirdin.")
    except services.RateLimited:
        messages.error(request, "Çok fazla bildirim gönderdin. Biraz sonra tekrar dene.")
    else:
        messages.success(request, "Bildirimin alındı. Teşekkürler.")
    return redirect(poll)


def _owned_poll_or_403(request, public_id):
    poll = get_object_or_404(Poll, public_id=public_id)
    if poll.author_id != request.user.id:
        raise PermissionDenied
    return poll


@login_required
@require_POST
def close(request, public_id):
    poll = _owned_poll_or_403(request, public_id)
    services.close_poll(poll)
    messages.success(request, "Anket kapatıldı.")
    return redirect(poll)


@login_required
def delete(request, public_id):
    poll = _owned_poll_or_403(request, public_id)
    if request.method == "POST":
        poll.delete()
        messages.success(request, "Anket silindi.")
        return redirect("polls:index")
    return render(request, "polls/delete.html", {"poll": poll})


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
