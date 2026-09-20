from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import selectors, services
from .models import Option, Poll, RateLimitHit, Report, Vote
from .tests import PASSWORD, make_poll
from .utils import client_ip_hash

User = get_user_model()

JSON_HEADERS = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}


def vote_url(poll):
    return f"/anket/{poll.public_id}/oy/"


def report_url(poll):
    return f"/anket/{poll.public_id}/bildir/"


def cast(poll, client=None, index=0, **extra):
    client = client or Client()
    option = poll.options.all()[index]
    return client.post(vote_url(poll), {"option_id": option.pk}, **JSON_HEADERS, **extra)


class RateLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.member = User.objects.create_user("uye", "uye@example.com", PASSWORD)

    def polls(self, n):
        return [make_poll(self.author, f"Hız sınırı deneme anketi numara {i}?", counts=(0, 0)) for i in range(n)]

    def test_thirty_anonymous_votes_pass_and_thirty_first_is_429(self):
        limit = services.RATE_LIMITS["vote"][0]
        polls = self.polls(limit + 1)
        for poll in polls[:limit]:
            self.assertEqual(cast(poll).status_code, 200)
        response = cast(polls[limit])
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "Çok fazla oy kullandın. Biraz sonra tekrar dene.")
        polls[limit].refresh_from_db()
        self.assertEqual(polls[limit].total_votes, 0)
        self.assertEqual(Vote.objects.filter(poll=polls[limit]).count(), 0)

    def test_retry_after_header_is_reasonable(self):
        limit, window = services.RATE_LIMITS["vote"]
        polls = self.polls(limit + 1)
        for poll in polls[:limit]:
            cast(poll)
        response = cast(polls[limit])
        retry_after = int(response["Retry-After"])
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, window)

    def test_old_hits_do_not_count(self):
        limit, window = services.RATE_LIMITS["vote"]
        ip_hash = client_ip_hash(mock.Mock(META={"REMOTE_ADDR": "127.0.0.1"}))
        RateLimitHit.objects.bulk_create([RateLimitHit(scope="vote", ip_hash=ip_hash) for _ in range(limit)])
        RateLimitHit.objects.update(created_at=timezone.now() - timedelta(seconds=window + 60))
        self.assertEqual(cast(self.polls(1)[0]).status_code, 200)

    def test_rejected_attempts_do_not_consume_budget(self):
        poll = self.polls(1)[0]
        client = Client()
        self.assertEqual(cast(poll, client).status_code, 200)
        self.assertEqual(cast(poll, client).status_code, 409)
        self.assertEqual(client.post(vote_url(poll), {"option_id": "x"}, **JSON_HEADERS).status_code, 400)
        closed = make_poll(self.author, "Kapalı anket sorusu burada?", status=Poll.Status.CLOSED)
        self.assertEqual(cast(closed).status_code, 403)
        self.assertEqual(RateLimitHit.objects.filter(scope="vote").count(), 1)

    def test_each_ip_has_its_own_budget(self):
        limit = services.RATE_LIMITS["vote"][0]
        polls = self.polls(limit + 1)
        for poll in polls[:limit]:
            cast(poll, REMOTE_ADDR="10.0.0.1")
        self.assertEqual(cast(polls[limit], REMOTE_ADDR="10.0.0.1").status_code, 429)
        self.assertEqual(cast(polls[limit], REMOTE_ADDR="10.0.0.2").status_code, 200)

    def test_logged_in_users_are_not_limited_or_counted(self):
        limit = services.RATE_LIMITS["vote"][0]
        polls = self.polls(limit + 2)
        client = Client()
        client.force_login(self.member)
        for poll in polls:
            self.assertEqual(cast(poll, client).status_code, 200)
        self.assertEqual(RateLimitHit.objects.count(), 0)

    def test_limited_voter_can_still_see_results_of_closed_poll(self):
        limit = services.RATE_LIMITS["vote"][0]
        for poll in self.polls(limit):
            cast(poll)
        closed = make_poll(self.author, "Kapalı ve sonuçlu anket sorusu?", counts=(3, 1), status=Poll.Status.CLOSED)
        self.assertContains(Client().get(closed.get_absolute_url()), "%75")

    def test_non_json_429_renders_page_with_message(self):
        limit = services.RATE_LIMITS["vote"][0]
        polls = self.polls(limit + 1)
        for poll in polls[:limit]:
            cast(poll)
        response = Client().post(vote_url(polls[limit]), {"option_id": polls[limit].options.first().pk})
        self.assertContains(response, "Çok fazla oy kullandın.", status_code=429)
        self.assertIn("Retry-After", response)

    def test_raw_ip_is_never_stored(self):
        cast(self.polls(1)[0], REMOTE_ADDR="203.0.113.77")
        hit = RateLimitHit.objects.get()
        self.assertEqual(len(hit.ip_hash), 64)
        self.assertNotIn("203.0.113.77", hit.ip_hash)
        for value in (hit.scope, hit.ip_hash):
            self.assertNotIn("203.0.113", value)
        self.assertEqual(Vote.objects.get().voter_key.count("."), 0)

    def test_forwarded_header_is_ignored_unless_trusted(self):
        limit = services.RATE_LIMITS["vote"][0]
        polls = self.polls(limit + 1)
        for i, poll in enumerate(polls[:limit]):
            cast(poll, HTTP_X_FORWARDED_FOR=f"198.51.100.{i}")
        # Sahte başlıkla IP değiştirmeye çalışmak sınırı sıfırlamaz.
        self.assertEqual(cast(polls[limit], HTTP_X_FORWARDED_FOR="198.51.100.250").status_code, 429)

    @override_settings(CLIENT_IP_HEADER="HTTP_X_FORWARDED_FOR")
    def test_forwarded_header_is_used_when_trusted(self):
        request = mock.Mock(META={"HTTP_X_FORWARDED_FOR": "198.51.100.9, 10.0.0.1", "REMOTE_ADDR": "10.0.0.1"})
        same = mock.Mock(META={"HTTP_X_FORWARDED_FOR": "198.51.100.9", "REMOTE_ADDR": "10.9.9.9"})
        other = mock.Mock(META={"HTTP_X_FORWARDED_FOR": "198.51.100.10", "REMOTE_ADDR": "10.0.0.1"})
        self.assertEqual(client_ip_hash(request), client_ip_hash(same))
        self.assertNotEqual(client_ip_hash(request), client_ip_hash(other))

    def test_missing_ip_skips_limit(self):
        self.assertIsNone(client_ip_hash(mock.Mock(META={})))
        services.check_rate_limit("vote", None)
        services.record_hit("vote", None)
        self.assertEqual(RateLimitHit.objects.count(), 0)

    def test_old_hits_are_cleaned_up_lazily(self):
        RateLimitHit.objects.create(scope="vote", ip_hash="a" * 64)
        RateLimitHit.objects.update(created_at=timezone.now() - timedelta(days=3))
        with mock.patch.object(services.random, "random", return_value=0.0):
            services.record_hit("vote", "b" * 64)
        self.assertEqual(list(RateLimitHit.objects.values_list("ip_hash", flat=True)), ["b" * 64])

    def test_vote_still_recorded_atomically_with_hit(self):
        poll = self.polls(1)[0]
        cast(poll)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(RateLimitHit.objects.count(), 1)


class ReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.member = User.objects.create_user("uye", "uye@example.com", PASSWORD)
        cls.other = User.objects.create_user("diger", "diger@example.com", PASSWORD)

    def setUp(self):
        self.poll = make_poll(self.author, "Bildirilecek anket sorusu burada?", counts=(1, 1))

    def test_anonymous_can_report_once(self):
        response = self.client.post(report_url(self.poll), follow=True)
        self.assertRedirects(response, self.poll.get_absolute_url())
        self.assertContains(response, "Bildirimin alındı.")
        report = Report.objects.get()
        self.assertIsNone(report.user)
        self.assertEqual(len(report.reporter_key), 64)
        again = self.client.post(report_url(self.poll), follow=True)
        self.assertContains(again, "Bu anketi zaten bildirdin.")
        self.assertEqual(Report.objects.count(), 1)

    def test_different_anonymous_visitors_each_count(self):
        self.client.post(report_url(self.poll))
        Client().post(report_url(self.poll))
        self.assertEqual(Report.objects.count(), 2)

    def test_logged_in_user_reports_once_across_sessions(self):
        first, second = Client(), Client()
        first.force_login(self.member)
        second.force_login(self.member)
        first.post(report_url(self.poll))
        second.post(report_url(self.poll))
        self.assertEqual(Report.objects.filter(user=self.member).count(), 1)

    def test_owner_cannot_report_own_poll(self):
        self.client.force_login(self.author)
        response = self.client.post(report_url(self.poll), follow=True)
        self.assertContains(response, "Kendi anketini bildiremezsin.")
        self.assertEqual(Report.objects.count(), 0)

    def test_report_button_visibility(self):
        page = self.client.get(self.poll.get_absolute_url())
        self.assertContains(page, "Uygunsuz olarak bildir")
        self.client.force_login(self.author)
        self.assertNotContains(self.client.get(self.poll.get_absolute_url()), "Uygunsuz olarak bildir")

    def test_button_replaced_after_reporting(self):
        self.client.post(report_url(self.poll))
        page = self.client.get(self.poll.get_absolute_url())
        self.assertContains(page, "Bu anketi bildirdin.")
        self.assertNotContains(page, "Uygunsuz olarak bildir")

    def test_anonymous_report_spam_is_rate_limited(self):
        limit = services.RATE_LIMITS["report"][0]
        polls = [make_poll(self.author, f"Bildirim spam anketi numara {i}?") for i in range(limit + 1)]
        for poll in polls[:limit]:
            Client().post(report_url(poll))
        response = Client().post(report_url(polls[limit]), follow=True)
        self.assertContains(response, "Çok fazla bildirim gönderdin.")
        self.assertEqual(Report.objects.filter(poll=polls[limit]).count(), 0)

    def test_report_requires_post_csrf_and_existing_poll(self):
        self.assertEqual(self.client.get(report_url(self.poll)).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(report_url(self.poll)).status_code, 403)
        self.assertEqual(self.client.post("/anket/yokboyleid1/bildir/").status_code, 404)
        self.assertEqual(Report.objects.count(), 0)

    def test_database_rejects_duplicate_reports(self):
        Report.objects.create(poll=self.poll, user=self.member, reporter_key="k1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(poll=self.poll, user=self.member, reporter_key="k2")
        Report.objects.create(poll=self.poll, reporter_key="anon")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(poll=self.poll, reporter_key="anon")

    def test_reports_disappear_with_poll_and_survive_user_deletion(self):
        Report.objects.create(poll=self.poll, user=self.member, reporter_key="k1")
        self.member.delete()
        self.assertIsNone(Report.objects.get().user)
        self.poll.delete()
        self.assertEqual(Report.objects.count(), 0)

    def test_no_reporter_identity_on_public_pages(self):
        self.client.force_login(self.member)
        self.client.post(report_url(self.poll))
        for url in (self.poll.get_absolute_url(), "/", "/kullanici/yazar/"):
            html = Client().get(url).content.decode()
            self.assertNotIn("uye@example.com", html)
            self.assertNotIn("@uye", html)


class ReportAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("yonetici", "yonetici@example.com", PASSWORD)
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.reported = make_poll(cls.author, "Çok bildirilen anket sorusu?")
        cls.clean = make_poll(cls.author, "Hiç bildirilmeyen anket sorusu?")
        Report.objects.create(poll=cls.reported, reporter_key="a")
        Report.objects.create(poll=cls.reported, reporter_key="b")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_poll_list_shows_report_counts(self):
        response = self.client.get("/admin/polls/poll/?o=-5")
        self.assertEqual(response.status_code, 200)
        counts = {p.question: p._report_count for p in response.context["cl"].result_list}
        self.assertEqual(counts[self.reported.question], 2)
        self.assertEqual(counts[self.clean.question], 0)

    def test_reports_list_and_poll_change_page_render(self):
        self.assertEqual(self.client.get("/admin/polls/report/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/polls/poll/{self.reported.pk}/change/").status_code, 200)

    def test_close_action_closes_selected_polls(self):
        response = self.client.post("/admin/polls/poll/", {
            "action": "close_polls", "_selected_action": [self.reported.pk],
        }, follow=True)
        self.assertContains(response, "1 anket kapatıldı.")
        self.reported.refresh_from_db()
        self.assertEqual(self.reported.status, Poll.Status.CLOSED)

    def test_non_staff_cannot_open_admin(self):
        client = Client()
        client.force_login(self.author)
        self.assertEqual(client.get("/admin/polls/report/").status_code, 302)


class LazyCloseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)

    def expired(self, **kwargs):
        return make_poll(self.author, "Süresi dolmuş anket sorusu burada?", counts=(2, 1),
                         closes_at=timezone.now() - timedelta(minutes=5), **kwargs)

    def status(self, poll):
        return Poll.objects.get(pk=poll.pk).status

    def test_detail_persists_closed_status(self):
        poll = self.expired()
        self.assertEqual(self.status(poll), Poll.Status.ACTIVE)
        self.client.get(poll.get_absolute_url())
        self.assertEqual(self.status(poll), Poll.Status.CLOSED)

    def test_vote_on_expired_poll_is_403_and_closes_it(self):
        poll = self.expired()
        response = cast(poll)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.status(poll), Poll.Status.CLOSED)
        self.assertEqual(Vote.objects.count(), 0)

    def test_results_endpoint_closes_and_reveals(self):
        poll = self.expired()
        data = self.client.get(f"/anket/{poll.public_id}/sonuc/").json()
        self.assertFalse(data["is_open"])
        self.assertEqual(data["options"][0]["percent"], 67)
        self.assertEqual(self.status(poll), Poll.Status.CLOSED)

    def test_future_deadline_and_no_deadline_stay_open(self):
        future = make_poll(self.author, "Süresi dolmamış anket sorusu?", closes_at=timezone.now() + timedelta(hours=1))
        forever = make_poll(self.author, "Süresiz anket sorusu burada?")
        for poll in (future, forever):
            self.client.get(poll.get_absolute_url())
            self.assertEqual(self.status(poll), Poll.Status.ACTIVE)

    def test_already_closed_poll_is_untouched(self):
        poll = self.expired(status=Poll.Status.CLOSED)
        with CaptureQueriesContext(connection) as ctx:
            services.close_if_expired(Poll.objects.get(pk=poll.pk))
        self.assertFalse([q for q in ctx.captured_queries if q["sql"].startswith("UPDATE")])

    def test_close_if_expired_is_idempotent(self):
        poll = self.expired()
        services.close_if_expired(poll)
        services.close_if_expired(poll)
        self.assertEqual(self.status(poll), Poll.Status.CLOSED)


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.istanbul = make_poll(cls.author, "İstanbul'a mı gitsem, Ankara'ya mı?", counts=(3, 1))
        cls.sehir = make_poll(cls.author, "Şehir mi köy mü daha iyi?")
        cls.cpp = make_poll(cls.author, "C++ mı Java mı öğrenmeli?")
        cls.closed = make_poll(cls.author, "Kapalı istanbul anket sorusu?", status=Poll.Status.CLOSED)

    def found(self, query, tab="yeni"):
        response = self.client.get("/", {"q": query, "tab": tab})
        self.assertEqual(response.status_code, 200)
        return [v.poll for v in response.context["views"]]

    def test_case_insensitive_substring(self):
        for query in ("istanbul", "ISTANBUL", "İstanbul", "İSTANBUL", "ıstanbul", "stanbul"):
            with self.subTest(query=query):
                self.assertEqual(self.found(query), [self.istanbul])

    def test_turkish_letters(self):
        for query in ("şehir", "ŞEHİR", "Şehir", "sehir".replace("s", "ş")):
            with self.subTest(query=query):
                self.assertEqual(self.found(query), [self.sehir])

    def test_regex_characters_are_literal(self):
        self.assertEqual(self.found("c++"), [self.cpp])
        for nasty in ("(", "[a", ".*", "\\", "a{2", "|"):
            with self.subTest(query=nasty):
                self.assertEqual(self.client.get("/", {"q": nasty}).status_code, 200)

    def test_search_respects_tab(self):
        self.assertEqual(self.found("istanbul", tab="kapananlar"), [self.closed])
        self.assertEqual(self.found("istanbul", tab="yeni"), [self.istanbul])

    def test_blank_and_whitespace_queries_list_everything(self):
        everything = self.found("")
        self.assertEqual(self.found("   "), everything)
        self.assertEqual(len(everything), 3)

    def test_query_is_cleaned_and_truncated(self):
        self.assertEqual(selectors.clean_query("  ankara   mı  "), "ankara mı")
        self.assertEqual(len(selectors.clean_query("a" * 200)), selectors.SEARCH_MAX_LENGTH)
        self.assertEqual(selectors.clean_query(None), "")
        self.assertEqual(self.found("Ankara'ya   mı"), [self.istanbul])

    def test_empty_result_message_and_clear_link(self):
        response = self.client.get("/", {"q": "yokboyleşey"})
        self.assertContains(response, "ile eşleşen anket yok.")
        self.assertContains(response, "Aramayı temizle")
        self.assertNotContains(response, "Henüz anket yok.")

    def test_query_is_escaped_in_page(self):
        response = self.client.get("/", {"q": "<script>alert(1)</script>"})
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_tabs_and_load_more_keep_the_query(self):
        for i in range(25):
            make_poll(self.author, f"Aranan kelime içeren anket sorusu {i:02d}?")
        response = self.client.get("/", {"q": "aranan kelime"})
        self.assertContains(response, "q=aranan%20kelime&amp;page=2")
        self.assertContains(response, 'href="?tab=populer&amp;q=aranan%20kelime"')
        self.assertEqual(len(self.client.get("/", {"q": "aranan kelime", "page": 2}).context["views"]), 25)

    def test_search_does_not_leak_results_to_non_voters(self):
        response = self.client.get("/", {"q": "istanbul"})
        self.assertNotContains(response, "%75")
        self.assertContains(response, "Sonuçlar oy verince açılır")

    def test_search_query_count_is_constant(self):
        def count(query):
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/", {"q": query})
            return len(ctx)
        small = count("istanbul")
        for i in range(10):
            make_poll(self.author, f"İstanbul hakkında başka anket sorusu {i}?")
        self.assertEqual(count("istanbul"), small)

    def test_search_form_is_accessible(self):
        html = self.client.get("/").content.decode()
        self.assertIn('role="search"', html)
        self.assertIn('for="search-q"', html)
        self.assertIn('type="search"', html)


class SharingAndCardMarkupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, "Paylaşılacak anket sorusu burada?", counts=(3, 1))

    def test_share_button_is_hidden_until_javascript_runs(self):
        html = self.client.get(self.poll.get_absolute_url()).content.decode()
        self.assertRegex(html, r"<button[^>]*data-share[^>]*hidden")
        self.assertIn('data-share-url="http://testserver' + self.poll.get_absolute_url(), html)
        self.assertIn("js/share.js", html)
        self.assertIn("js/result-card.js", html)

    def test_card_button_only_eligible_when_results_are_visible(self):
        html = self.client.get(self.poll.get_absolute_url()).content.decode()
        self.assertNotIn("data-eligible", html)
        self.client.force_login(self.author)
        self.assertIn("data-eligible", self.client.get(self.poll.get_absolute_url()).content.decode())

    def test_card_button_not_eligible_without_votes(self):
        empty = make_poll(self.author, "Kimse oy vermemiş anket sorusu?", counts=(0, 0))
        self.client.force_login(self.author)
        self.assertNotIn("data-eligible", self.client.get(empty.get_absolute_url()).content.decode())

    def test_javascript_assets_exist(self):
        from django.contrib.staticfiles import finders
        for name in ("share.js", "result-card.js"):
            self.assertIsNotNone(finders.find(f"js/{name}"))

    def test_card_script_has_no_raw_colors(self):
        import re
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / "static" / "js" / "result-card.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", source))
        self.assertIsNone(re.search(r"rgba?\(", source))


class ServiceUnitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)

    def test_cast_vote_without_ip_hash_skips_rate_limit(self):
        from django.contrib.auth.models import AnonymousUser
        poll = make_poll(self.author, "Doğrudan servis çağrısı anket sorusu?", counts=(0, 0))
        services.cast_vote(poll, poll.options.first(), AnonymousUser(), "k" * 64)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(RateLimitHit.objects.count(), 0)

    def test_votes_by_poll_returns_option_ids(self):
        poll = make_poll(self.author, "Seçici testi için anket sorusu?", counts=(0, 0))
        member = User.objects.create_user("uye", "uye@example.com", PASSWORD)
        option = poll.options.last()
        Vote.objects.create(poll=poll, option=option, user=member, voter_key="k")
        self.assertEqual(selectors.votes_by_poll(member, {}, [poll.pk]), {poll.pk: option.pk})
        self.assertEqual(selectors.votes_by_poll(member, {}, []), {})

    def test_profile_load_more(self):
        for i in range(25):
            make_poll(self.author, f"Profil sayfalama anket sorusu {i:02d}?")
        first = self.client.get("/kullanici/yazar/")
        self.assertEqual(len(first.context["views"]), 20)
        self.assertContains(first, "Daha fazla göster")
        self.assertEqual(len(self.client.get("/kullanici/yazar/?page=2").context["views"]), 25)
