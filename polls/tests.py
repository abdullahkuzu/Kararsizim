from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Option, Poll, Vote
from .templatetags.polls_extras import time_ago

User = get_user_model()

PASSWORD = "gizli-parola-2026"
CREATE_URL = "/anket/olustur/"


def make_poll(author, question="Bugün sinemaya mı gitsem?", counts=(0, 0), **kwargs):
    poll = Poll.objects.create(author=author, question=question, total_votes=sum(counts), **kwargs)
    Option.objects.bulk_create(
        [Option(poll=poll, text=f"Seçenek {chr(65 + i)}", position=i, vote_count=c) for i, c in enumerate(counts)]
    )
    return poll


def make_vote(poll, index, **kwargs):
    option = poll.options.all()[index]
    return Vote.objects.create(poll=poll, option=option, voter_key=kwargs.pop("voter_key", "anon"), **kwargs)


class CreatePollTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("ali", "ali@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, options, **overrides):
        data = {"question": "Bugün sinemaya mı gitsem, restorana mı?", "description": ""}
        data.update(overrides)
        data["option"] = options
        return self.client.post(CREATE_URL, data)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for method in (self.client.get, self.client.post):
            response = method(CREATE_URL)
            self.assertRedirects(response, "/giris/?next=/anket/olustur/", fetch_redirect_response=False)

    def test_valid_poll_is_created(self):
        response = self.post(["Sinema", "Restoran", "", "", ""], description="Akşam için")
        poll = Poll.objects.get()
        self.assertRedirects(response, poll.get_absolute_url())
        self.assertEqual(poll.author, self.user)
        self.assertEqual(poll.description, "Akşam için")
        self.assertEqual([(o.position, o.text) for o in poll.options.all()], [(0, "Sinema"), (1, "Restoran")])
        self.assertEqual(len(poll.public_id), 10)

    def test_five_options_allowed(self):
        self.post(["A", "B", "C", "D", "E"])
        self.assertEqual(Option.objects.count(), 5)

    def test_options_are_stripped_and_blank_rows_ignored(self):
        self.post(["  Sinema  ", "", "Restoran", " ", ""])
        self.assertEqual([o.text for o in Poll.objects.get().options.all()], ["Sinema", "Restoran"])

    def assertOptionsError(self, response, message):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, message)
        self.assertEqual(Poll.objects.count(), 0)
        self.assertEqual(Option.objects.count(), 0)

    def test_single_option_rejected(self):
        self.assertOptionsError(self.post(["Sinema", "", "", "", ""]), "En az 2 seçenek gerekli.")

    def test_no_options_rejected(self):
        self.assertOptionsError(self.post(["", "", "", "", ""]), "En az 2 seçenek gerekli.")

    def test_six_options_rejected(self):
        self.assertOptionsError(self.post(["A", "B", "C", "D", "E", "F"]), "En fazla 5 seçenek ekleyebilirsin.")

    def test_duplicate_options_rejected_case_insensitively(self):
        self.assertOptionsError(self.post(["Sinema", "SİNEMA".replace("İ", "i")]), "Aynı seçeneği iki kez yazamazsın.")
        self.assertOptionsError(self.post(["Sinema", " sinema "]), "Aynı seçeneği iki kez yazamazsın.")

    def test_option_too_long_rejected(self):
        self.assertOptionsError(self.post(["A" * 81, "B"]), "Her seçenek en fazla 80 karakter olabilir.")

    def test_question_length_limits(self):
        for question in ["Kısa soru", "s" * 141, ""]:
            with self.subTest(question=question):
                response = self.post(["A", "B"], question=question)
                self.assertIn("question", response.context["form"].errors)
        self.assertEqual(Poll.objects.count(), 0)

    def test_description_max_length(self):
        response = self.post(["A", "B"], description="d" * 281)
        self.assertIn("description", response.context["form"].errors)

    def test_form_keeps_submitted_options_on_error(self):
        response = self.post(["Sinema", "", "Tiyatro", "", ""], question="kısa")
        self.assertEqual(response.context["form"].option_rows, ["Sinema", "", "Tiyatro", "", ""])
        self.assertContains(response, 'value="Tiyatro"')

    def test_page_renders_five_option_inputs_without_js(self):
        response = self.client.get(CREATE_URL)
        self.assertContains(response, 'name="option"', count=5)

    def test_daily_limit(self):
        for i in range(services.DAILY_POLL_LIMIT):
            self.assertEqual(self.post([f"A{i}", f"B{i}"]).status_code, 302)
        response = self.post(["X", "Y"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bir günde en fazla 10 anket açabilirsin.")
        self.assertEqual(Poll.objects.count(), services.DAILY_POLL_LIMIT)

    def test_daily_limit_ignores_previous_days(self):
        for i in range(services.DAILY_POLL_LIMIT):
            make_poll(self.user)
        Poll.objects.update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self.post(["A", "B"]).status_code, 302)

    def test_daily_limit_is_per_user(self):
        other = User.objects.create_user("veli", "veli@example.com", PASSWORD)
        for i in range(services.DAILY_POLL_LIMIT):
            make_poll(other)
        self.assertEqual(self.post(["A", "B"]).status_code, 302)


class FeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)

    def test_empty_state(self):
        response = self.client.get("/")
        self.assertContains(response, "Henüz anket yok. İlk kararsızlığını sen paylaş.")

    def test_first_page_has_20_and_load_more(self):
        for i in range(25):
            make_poll(self.author, f"Anket sorusu numara {i:02d}?")
        response = self.client.get("/")
        self.assertEqual(len(response.context["views"]), 20)
        self.assertContains(response, "Daha fazla göster")
        self.assertContains(response, "?tab=yeni&amp;page=2")

    def test_load_more_shows_all_and_hides_button(self):
        for i in range(25):
            make_poll(self.author, f"Anket sorusu numara {i:02d}?")
        response = self.client.get("/?tab=yeni&page=2")
        self.assertEqual(len(response.context["views"]), 25)
        self.assertNotContains(response, "Daha fazla göster")

    def test_exactly_20_has_no_load_more(self):
        for i in range(20):
            make_poll(self.author, f"Anket sorusu numara {i:02d}?")
        self.assertNotContains(self.client.get("/"), "Daha fazla göster")

    def test_invalid_page_and_tab_fall_back(self):
        make_poll(self.author)
        for query in ["?page=abc", "?page=-3", "?tab=yok"]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/" + query).status_code, 200)

    def test_newest_first(self):
        old = make_poll(self.author, "Eski anket sorusu burada?")
        Poll.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))
        new = make_poll(self.author, "Yeni anket sorusu burada?")
        questions = [v.poll for v in self.client.get("/").context["views"]]
        self.assertEqual(questions, [new, old])

    def test_closed_polls_only_in_closed_tab(self):
        open_poll = make_poll(self.author, "Açık anket sorusu burada?")
        closed = make_poll(self.author, "Kapalı anket sorusu burada?", status=Poll.Status.CLOSED)
        expired = make_poll(self.author, "Süresi dolmuş anket sorusu?", closes_at=timezone.now() - timedelta(hours=1))
        new_tab = [v.poll for v in self.client.get("/?tab=yeni").context["views"]]
        closed_tab = [v.poll for v in self.client.get("/?tab=kapananlar").context["views"]]
        self.assertEqual(new_tab, [open_poll])
        self.assertCountEqual(closed_tab, [closed, expired])
        self.assertContains(self.client.get("/?tab=kapananlar"), "Kapandı")

    def test_popular_orders_by_votes_in_last_7_days(self):
        quiet = make_poll(self.author, "Sessiz anket sorusu burada?", counts=(1, 0))
        busy = make_poll(self.author, "Hareketli anket sorusu burada?", counts=(2, 0))
        stale = make_poll(self.author, "Eskiden popüler anket sorusu?", counts=(50, 0))
        make_vote(quiet, 0, voter_key="a")
        make_vote(busy, 0, voter_key="a")
        make_vote(busy, 0, voter_key="b")
        for n in range(3):
            make_vote(stale, 0, voter_key=f"s{n}")
        Vote.objects.filter(poll=stale).update(created_at=timezone.now() - timedelta(days=8))
        popular = [v.poll for v in self.client.get("/?tab=populer").context["views"]]
        self.assertEqual(popular[:2], [busy, quiet])
        self.assertEqual(popular[2], stale)

    def test_active_tab_is_marked(self):
        response = self.client.get("/?tab=populer")
        self.assertContains(response, 'aria-current="page"', count=1)

    def query_count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx)

    def test_feed_query_count_does_not_grow_with_poll_count(self):
        for i in range(2):
            make_poll(self.author, f"Az sayıda anket sorusu {i}?", counts=(1, 2, 3))
        small = self.query_count("/")
        for i in range(18):
            make_poll(self.author, f"Çok sayıda anket sorusu {i}?", counts=(1, 2, 3))
        self.assertEqual(self.query_count("/"), small)
        self.assertEqual(self.query_count("/?tab=populer") - self.query_count("/?tab=yeni"), 0)

    def test_feed_query_count_constant_when_logged_in(self):
        self.client.force_login(self.author)
        for i in range(2):
            make_poll(self.author, f"Az sayıda anket sorusu {i}?", counts=(1, 2))
        small = self.query_count("/")
        for i in range(18):
            make_poll(self.author, f"Çok sayıda anket sorusu {i}?", counts=(1, 2))
        self.assertEqual(self.query_count("/"), small)

    def test_profile_query_count_constant(self):
        make_poll(self.author, "İlk anket sorusu burada?", counts=(1, 2))
        small = self.query_count("/kullanici/yazar/")
        for i in range(15):
            make_poll(self.author, f"Başka anket sorusu {i}?", counts=(1, 2))
        self.assertEqual(self.query_count("/kullanici/yazar/"), small)


class ResultVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.viewer = User.objects.create_user("izleyici", "izleyici@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, counts=(3, 7))

    def urls(self):
        return ["/", "/?tab=yeni", self.poll.get_absolute_url()]

    def assertHidden(self, response):
        self.assertNotContains(response, "%70")
        self.assertNotContains(response, "%30")
        self.assertNotContains(response, "width: 70%")
        self.assertContains(response, "10 kişi oy verdi")
        self.assertContains(response, "Sonuçlar oy verince açılır")

    def assertShown(self, response):
        self.assertContains(response, "%70")
        self.assertContains(response, "%30")

    def test_anonymous_non_voter_sees_no_numbers(self):
        for url in self.urls():
            with self.subTest(url=url):
                self.assertHidden(self.client.get(url))

    def test_logged_in_non_voter_sees_no_numbers(self):
        self.client.force_login(self.viewer)
        for url in self.urls():
            with self.subTest(url=url):
                self.assertHidden(self.client.get(url))

    def test_owner_sees_results(self):
        self.client.force_login(self.author)
        self.assertShown(self.client.get(self.poll.get_absolute_url()))

    def test_anonymous_voter_in_session_sees_results(self):
        session = self.client.session
        session["voted_polls"] = [self.poll.pk]
        session.save()
        for url in self.urls():
            with self.subTest(url=url):
                self.assertShown(self.client.get(url))

    def test_logged_in_voter_sees_results(self):
        make_vote(self.poll, 0, user=self.viewer, voter_key="k")
        self.client.force_login(self.viewer)
        self.assertShown(self.client.get(self.poll.get_absolute_url()))

    def test_closed_poll_shows_results_to_everyone(self):
        self.poll.status = Poll.Status.CLOSED
        self.poll.save()
        self.assertShown(self.client.get(self.poll.get_absolute_url()))

    def test_expired_poll_shows_results_to_everyone(self):
        self.poll.closes_at = timezone.now() - timedelta(minutes=1)
        self.poll.save()
        self.assertShown(self.client.get(self.poll.get_absolute_url()))

    def test_zero_votes_badge_shown_to_everyone(self):
        empty = make_poll(self.author, "Kimse oy vermemiş anket sorusu?", counts=(0, 0))
        response = self.client.get(empty.get_absolute_url())
        self.assertContains(response, "İlk oyu sen ver")
        self.assertContains(response, "Henüz oy yok")

    def test_badge_shown_after_reveal(self):
        self.client.force_login(self.author)
        self.assertContains(self.client.get("/"), "Karar net")


class ServiceLogicTests(TestCase):
    def test_percents_always_sum_to_100(self):
        for counts in [[1, 1, 1], [3, 7], [3, 7, 7], [1, 2, 4, 8, 16], [5, 5, 5, 5, 5], [1, 0, 0], [2, 1], [7, 7, 7, 7, 3]]:
            with self.subTest(counts=counts):
                percents = services.compute_percents(counts)
                self.assertEqual(sum(percents), 100)
                self.assertTrue(all(p >= 0 for p in percents))

    def test_percents_zero_votes(self):
        self.assertEqual(services.compute_percents([0, 0, 0]), [0, 0, 0])

    def test_rounding_remainder_goes_to_largest(self):
        self.assertEqual(services.compute_percents([1, 1, 1]), [34, 33, 33])
        self.assertEqual(services.compute_percents([3, 7]), [30, 70])

    def test_badge_thresholds(self):
        cases = [
            (0, [0, 0], "İlk oyu sen ver"),
            (10, [50, 50], "Kalabalık da kararsız"),
            (10, [52, 48], "Kalabalık da kararsız"),
            (10, [53, 47], "Az farkla önde"),
            (10, [60, 40], "Az farkla önde"),
            (10, [61, 39], "Karar net"),
            (10, [100, 0], "Karar net"),
        ]
        for total, percents, expected in cases:
            with self.subTest(percents=percents):
                self.assertEqual(services.decision_badge(total, percents), expected)

    def test_badge_uses_top_two_options(self):
        self.assertEqual(services.decision_badge(10, [40, 38, 22]), "Kalabalık da kararsız")


class TimeAgoTests(TestCase):
    def test_units(self):
        now = timezone.now()
        cases = [
            (timedelta(seconds=10), "az önce"),
            (timedelta(minutes=5), "5 dakika önce"),
            (timedelta(hours=3, minutes=20), "3 saat önce"),
            (timedelta(days=2, hours=5), "2 gün önce"),
        ]
        for delta, expected in cases:
            with self.subTest(delta=delta):
                self.assertEqual(time_ago(now - delta), expected)

    def test_old_dates_use_calendar_format(self):
        value = timezone.now() - timedelta(days=90)
        self.assertRegex(time_ago(value), r"^\d{2}\.\d{2}\.\d{4}$")


class DetailAndProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "gizli-yazar@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, "Hafta sonu ne yapmalı?", counts=(2, 1), description="Açıklama metni")

    def test_detail_renders(self):
        response = self.client.get(self.poll.get_absolute_url())
        self.assertContains(response, "Hafta sonu ne yapmalı?")
        self.assertContains(response, "Açıklama metni")
        self.assertContains(response, "@yazar")
        self.assertContains(response, "Seçenek A")

    def test_detail_unknown_id_is_404(self):
        self.assertEqual(self.client.get("/anket/yokboyleid1/").status_code, 404)

    def test_create_route_not_shadowed_by_detail(self):
        self.assertEqual(self.client.get(CREATE_URL).status_code, 302)

    def test_profile_lists_polls_and_stats(self):
        make_poll(self.author, "İkinci anket sorusu burada?", counts=(4, 0))
        response = self.client.get("/kullanici/yazar/")
        self.assertContains(response, "@yazar")
        self.assertContains(response, "2 anket · 7 oy aldı")
        self.assertContains(response, "Hafta sonu ne yapmalı?")

    def test_profile_is_case_insensitive_and_404_for_unknown(self):
        self.assertEqual(self.client.get("/kullanici/YAZAR/").status_code, 200)
        self.assertEqual(self.client.get("/kullanici/yok_kimse/").status_code, 404)

    def test_profile_only_shows_own_polls(self):
        other = User.objects.create_user("baska", "baska@example.com", PASSWORD)
        make_poll(other, "Başkasının anket sorusu?")
        self.assertNotContains(self.client.get("/kullanici/yazar/"), "Başkasının anket sorusu?")

    def test_profile_empty_state(self):
        User.objects.create_user("bos", "bos@example.com", PASSWORD)
        self.assertContains(self.client.get("/kullanici/bos/"), "Henüz anket yok.")

    def test_email_never_in_detail_or_profile_or_feed(self):
        for url in [self.poll.get_absolute_url(), "/kullanici/yazar/", "/"]:
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "gizli-yazar@example.com")
                self.assertNotContains(self.client.get(url), "gizli-yazar")
