from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from . import services
from .models import Option, Poll, Vote
from .tests import PASSWORD, make_poll, make_vote
from .utils import voter_key_for

User = get_user_model()

JSON_HEADERS = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}


def vote_url(poll):
    return f"/anket/{poll.public_id}/oy/"


def results_url(poll):
    return f"/anket/{poll.public_id}/sonuc/"


class VoteBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        cls.voter = User.objects.create_user("oyuncu", "oyuncu@example.com", PASSWORD)

    def setUp(self):
        self.poll = make_poll(self.author, "Bugün ne yemeli, karar veremedim?", counts=(0, 0, 0))
        self.options = list(self.poll.options.all())

    def cast(self, option, client=None, **extra):
        client = client or self.client
        return client.post(vote_url(self.poll), {"option_id": option.pk}, **extra)

    def cast_json(self, option, client=None):
        return self.cast(option, client, **JSON_HEADERS)

    def counters(self):
        self.poll.refresh_from_db()
        return self.poll.total_votes, [o.vote_count for o in self.poll.options.all()]


class VoteTests(VoteBaseTests):
    def test_anonymous_vote_succeeds_and_counters_increment(self):
        response = self.cast_json(self.options[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.counters(), (1, [0, 1, 0]))
        vote = Vote.objects.get()
        self.assertIsNone(vote.user)
        self.assertEqual(vote.option, self.options[1])
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["voted_option_id"], self.options[1].pk)
        self.assertEqual(data["total"], 1)

    def test_voter_key_is_salted_hash_of_session_key(self):
        self.cast_json(self.options[0])
        session_key = self.client.session.session_key
        key = Vote.objects.get().voter_key
        self.assertEqual(key, voter_key_for(session_key))
        self.assertEqual(len(key), 64)
        self.assertNotIn(session_key, key)

    def test_session_remembers_voted_poll(self):
        self.cast_json(self.options[0])
        self.assertEqual(self.client.session["voted_polls"], [self.poll.pk])

    def test_second_vote_same_session_is_409_and_counters_unchanged(self):
        self.cast_json(self.options[0])
        for option in (self.options[0], self.options[2]):
            response = self.cast_json(option)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"], "Bu ankete zaten oy verdin.")
            self.assertEqual(response.json()["voted_option_id"], self.options[0].pk)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))
        self.assertEqual(Vote.objects.count(), 1)

    def test_different_anonymous_visitors_can_each_vote(self):
        self.cast_json(self.options[0])
        self.cast_json(self.options[0], client=Client())
        self.assertEqual(self.counters(), (2, [2, 0, 0]))

    def test_second_vote_by_same_user_is_409(self):
        self.client.force_login(self.voter)
        self.assertEqual(self.cast_json(self.options[0]).status_code, 200)
        self.assertEqual(self.cast_json(self.options[1]).status_code, 409)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))
        self.assertEqual(Vote.objects.get().user, self.voter)

    def test_same_user_from_second_browser_is_409(self):
        first, second = Client(), Client()
        first.force_login(self.voter)
        second.force_login(self.voter)
        self.assertEqual(self.cast_json(self.options[0], first).status_code, 200)
        self.assertEqual(self.cast_json(self.options[1], second).status_code, 409)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))

    def test_anonymous_vote_then_login_cannot_vote_again(self):
        self.cast_json(self.options[0])
        self.client.force_login(self.voter)
        self.assertEqual(self.cast_json(self.options[1]).status_code, 409)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))

    def test_simultaneous_double_submit_hits_database_constraint(self):
        # Yarış: iki istek de "henüz oy vermemiş" kontrolünü geçer, ikincisi DB kısıtına takılır.
        self.client.force_login(self.voter)
        self.cast_json(self.options[0])
        other = Client()
        other.force_login(self.voter)
        with mock.patch.object(services, "_already_voted", return_value=False):
            response = self.cast_json(self.options[1], other)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))

    def test_option_of_another_poll_is_400(self):
        other_poll = make_poll(self.author, "Başka bir anketin sorusu burada?", counts=(0, 0))
        foreign = other_poll.options.first()
        response = self.cast_json(foreign)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.counters(), (0, [0, 0, 0]))
        other_poll.refresh_from_db()
        self.assertEqual(other_poll.total_votes, 0)
        self.assertEqual(Vote.objects.count(), 0)

    def test_missing_or_garbage_option_is_400(self):
        for data in ({}, {"option_id": ""}, {"option_id": "abc"}, {"option_id": "999999"}):
            with self.subTest(data=data):
                response = self.client.post(vote_url(self.poll), data, **JSON_HEADERS)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Vote.objects.count(), 0)

    def test_closed_poll_is_403(self):
        self.poll.status = Poll.Status.CLOSED
        self.poll.save()
        response = self.cast_json(self.options[0])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["is_open"], False)
        self.assertEqual(Vote.objects.count(), 0)

    def test_expired_poll_is_403(self):
        self.poll.closes_at = timezone.now() - timedelta(minutes=1)
        self.poll.save()
        self.assertEqual(self.cast_json(self.options[0]).status_code, 403)
        self.assertEqual(Vote.objects.count(), 0)

    def test_author_can_vote_on_own_poll(self):
        self.client.force_login(self.author)
        self.assertEqual(self.cast_json(self.options[0]).status_code, 200)
        self.assertEqual(self.counters(), (1, [1, 0, 0]))

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(vote_url(self.poll)).status_code, 405)

    def test_unknown_poll_is_404(self):
        response = self.client.post("/anket/yokboyleid1/oy/", {"option_id": 1}, **JSON_HEADERS)
        self.assertEqual(response.status_code, 404)

    def test_csrf_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        response = strict.post(vote_url(self.poll), {"option_id": self.options[0].pk}, **JSON_HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Vote.objects.count(), 0)

    def test_percents_in_payload_always_sum_to_100(self):
        for option in self.options:
            data = self.cast_json(option, Client()).json()
        self.assertEqual(sum(o["percent"] for o in data["options"]), 100)
        self.assertEqual(sorted(o["percent"] for o in data["options"]), [33, 33, 34])

    def test_counters_match_vote_rows_after_many_votes(self):
        for i in range(7):
            self.cast_json(self.options[i % 3], Client())
        total, counts = self.counters()
        self.assertEqual(total, Vote.objects.count())
        self.assertEqual(counts, [3, 2, 2])


class VoteWithoutJavascriptTests(VoteBaseTests):
    def test_success_redirects_to_detail_and_shows_results(self):
        response = self.cast(self.options[0])
        self.assertRedirects(response, self.poll.get_absolute_url())
        page = self.client.get(self.poll.get_absolute_url())
        self.assertContains(page, "%100")
        self.assertContains(page, "option-row-voted")

    def test_success_shows_toast(self):
        response = self.client.post(vote_url(self.poll), {"option_id": self.options[0].pk}, follow=True)
        self.assertContains(response, "Oyun kaydedildi.")

    def test_second_vote_renders_page_with_409_and_message(self):
        self.cast(self.options[0])
        response = self.cast(self.options[1])
        self.assertContains(response, "Bu ankete zaten oy verdin.", status_code=409)
        self.assertContains(response, "%100", status_code=409)

    def test_closed_poll_renders_403_with_message(self):
        self.poll.status = Poll.Status.CLOSED
        self.poll.save()
        response = self.cast(self.options[0])
        self.assertContains(response, "Bu anket kapandı.", status_code=403)

    def test_invalid_option_is_400_without_stray_message(self):
        response = self.client.post(vote_url(self.poll), {"option_id": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(self.client.get("/"), "Geçersiz seçenek.")


class DetailVoteUITests(VoteBaseTests):
    def test_open_unvoted_poll_has_enabled_buttons_and_script(self):
        response = self.client.get(self.poll.get_absolute_url())
        self.assertContains(response, "data-vote-form")
        self.assertContains(response, "js/vote.js")
        self.assertNotContains(response, "disabled")
        self.assertContains(response, 'name="option_id"', count=3)

    def test_closed_poll_buttons_are_disabled(self):
        self.poll.status = Poll.Status.CLOSED
        self.poll.save()
        response = self.client.get(self.poll.get_absolute_url())
        self.assertContains(response, "disabled", count=3)
        self.assertNotContains(response, "data-vote-form")
        self.assertNotContains(response, "js/vote.js")

    def test_voted_poll_buttons_are_disabled(self):
        self.cast(self.options[0])
        response = self.client.get(self.poll.get_absolute_url())
        self.assertContains(response, "disabled", count=3)
        self.assertNotContains(response, "js/vote.js")

    def test_own_choice_is_marked(self):
        self.cast(self.options[1])
        response = self.client.get(self.poll.get_absolute_url())
        self.assertContains(response, "option-row-voted", count=1)
        self.assertContains(response, "Senin oyun")

    def test_hidden_state_has_no_numbers_but_empty_fills(self):
        make_vote(self.poll, 0, voter_key="x")
        Poll.objects.filter(pk=self.poll.pk).update(total_votes=1)
        Option.objects.filter(pk=self.options[0].pk).update(vote_count=1)
        response = self.client.get(self.poll.get_absolute_url())
        self.assertNotContains(response, "%100")
        self.assertContains(response, "width: 0%", count=3)


class ResultsEndpointTests(VoteBaseTests):
    def test_non_voter_gets_total_only(self):
        Poll.objects.filter(pk=self.poll.pk).update(total_votes=10)
        Option.objects.filter(pk=self.options[0].pk).update(vote_count=3)
        Option.objects.filter(pk=self.options[1].pk).update(vote_count=7)
        response = self.client.get(results_url(self.poll))
        data = response.json()
        self.assertEqual(data["total"], 10)
        self.assertIsNone(data["voted_option_id"])
        self.assertTrue(data["is_open"])
        for option in data["options"]:
            self.assertEqual(set(option), {"id", "text"})
        body = response.content.decode()
        self.assertNotIn('"count"', body)
        self.assertNotIn('"percent"', body)

    def test_voter_gets_counts_and_percents(self):
        self.cast(self.options[2])
        data = self.client.get(results_url(self.poll)).json()
        self.assertEqual(data["voted_option_id"], self.options[2].pk)
        by_id = {o["id"]: o for o in data["options"]}
        self.assertEqual(by_id[self.options[2].pk]["count"], 1)
        self.assertEqual(by_id[self.options[2].pk]["percent"], 100)

    def test_owner_gets_results_without_voting(self):
        Poll.objects.filter(pk=self.poll.pk).update(total_votes=4)
        Option.objects.filter(pk=self.options[0].pk).update(vote_count=4)
        self.client.force_login(self.author)
        data = self.client.get(results_url(self.poll)).json()
        self.assertEqual(data["options"][0]["percent"], 100)
        self.assertIsNone(data["voted_option_id"])

    def test_closed_poll_gets_results_for_everyone(self):
        Poll.objects.filter(pk=self.poll.pk).update(total_votes=2, status=Poll.Status.CLOSED)
        Option.objects.filter(pk=self.options[0].pk).update(vote_count=2)
        data = self.client.get(results_url(self.poll)).json()
        self.assertFalse(data["is_open"])
        self.assertEqual(data["options"][0]["percent"], 100)

    def test_payload_shape_and_no_leaks(self):
        self.client.force_login(self.voter)
        self.cast(self.options[0])
        response = self.client.get(results_url(self.poll))
        data = response.json()
        self.assertEqual(set(data), {"total", "options", "voted_option_id", "is_open", "badge"})
        for option in data["options"]:
            self.assertEqual(set(option), {"id", "text", "count", "percent"})
        body = response.content.decode().lower()
        for secret in ("@example.com", "oyuncu", "yazar", "user", "email"):
            self.assertNotIn(secret, body)

    def test_response_is_not_cacheable(self):
        self.assertIn("no-store", self.client.get(results_url(self.poll))["Cache-Control"])

    def test_unknown_poll_is_404_and_post_not_allowed(self):
        self.assertEqual(self.client.get("/anket/yokboyleid1/sonuc/").status_code, 404)
        self.assertEqual(self.client.post(results_url(self.poll)).status_code, 405)


class OwnerActionTests(VoteBaseTests):
    def close_url(self):
        return f"/anket/{self.poll.public_id}/kapat/"

    def delete_url(self):
        return f"/anket/{self.poll.public_id}/sil/"

    def test_owner_can_close(self):
        self.client.force_login(self.author)
        response = self.client.post(self.close_url())
        self.assertRedirects(response, self.poll.get_absolute_url())
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, Poll.Status.CLOSED)
        self.assertEqual(self.client.post(self.close_url()).status_code, 302)

    def test_closed_by_owner_blocks_votes(self):
        self.client.force_login(self.author)
        self.client.post(self.close_url())
        self.assertEqual(self.cast_json(self.options[0], Client()).status_code, 403)

    def test_non_owner_cannot_close(self):
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.close_url()).status_code, 403)
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, Poll.Status.ACTIVE)

    def test_anonymous_cannot_close_or_delete(self):
        for url in (self.close_url(), self.delete_url()):
            response = self.client.post(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/giris/"))
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, Poll.Status.ACTIVE)

    def test_close_requires_post(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(self.close_url()).status_code, 405)

    def test_delete_get_shows_confirmation_and_keeps_poll(self):
        self.client.force_login(self.author)
        response = self.client.get(self.delete_url())
        self.assertContains(response, "Bu işlem geri alınamaz.")
        self.assertContains(response, self.poll.question)
        self.assertTrue(Poll.objects.filter(pk=self.poll.pk).exists())

    def test_owner_can_delete_with_cascade(self):
        make_vote(self.poll, 0, voter_key="a")
        self.client.force_login(self.author)
        response = self.client.post(self.delete_url(), follow=True)
        self.assertRedirects(response, "/")
        self.assertContains(response, "Anket silindi.")
        self.assertFalse(Poll.objects.filter(pk=self.poll.pk).exists())
        self.assertEqual(Option.objects.count(), 0)
        self.assertEqual(Vote.objects.count(), 0)

    def test_non_owner_cannot_delete(self):
        self.client.force_login(self.voter)
        self.assertEqual(self.client.get(self.delete_url()).status_code, 403)
        self.assertEqual(self.client.post(self.delete_url()).status_code, 403)
        self.assertTrue(Poll.objects.filter(pk=self.poll.pk).exists())

    def test_owner_controls_only_visible_to_owner(self):
        self.assertNotContains(self.client.get(self.poll.get_absolute_url()), "Anketi kapat")
        self.client.force_login(self.voter)
        self.assertNotContains(self.client.get(self.poll.get_absolute_url()), "Anketi sil")
        self.client.force_login(self.author)
        page = self.client.get(self.poll.get_absolute_url())
        self.assertContains(page, "Anketi kapat")
        self.assertContains(page, "Anketi sil")

    def test_close_button_hidden_once_closed(self):
        self.client.force_login(self.author)
        self.client.post(self.close_url())
        page = self.client.get(self.poll.get_absolute_url())
        self.assertNotContains(page, "Anketi kapat")
        self.assertContains(page, "Anketi sil")
