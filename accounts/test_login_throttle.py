from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from polls import services
from polls.models import RateLimitHit
from polls.utils import client_ip_hash

User = get_user_model()

PASSWORD = "gizli-parola-2026"
LIMIT, WINDOW = services.RATE_LIMITS["login"]
BLOCKED = "Çok fazla başarısız giriş denemesi yaptın."


class LoginThrottleTests(TestCase):
    login_url = reverse("accounts:login")

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("kullanici", "kullanici@example.com", PASSWORD)
        cls.admin = User.objects.create_superuser("yonetici", "yonetici@example.com", PASSWORD)

    def attempt(self, password="yanlis-parola", username="kullanici", client=None, **extra):
        return (client or self.client).post(self.login_url, {"username": username, "password": password}, **extra)

    def fail(self, times, **kwargs):
        for _ in range(times):
            response = self.attempt(**kwargs)
            self.assertNotContains(response, BLOCKED)

    def test_failed_attempts_are_recorded(self):
        self.fail(3)
        self.assertEqual(RateLimitHit.objects.filter(scope="login").count(), 3)

    def test_unknown_usernames_count_too(self):
        self.attempt(username="kimse_yok")
        self.attempt(username="baska_yok")
        self.assertEqual(RateLimitHit.objects.filter(scope="login").count(), 2)

    def test_successful_login_is_not_counted(self):
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)
        self.assertEqual(RateLimitHit.objects.count(), 0)

    def test_login_still_works_just_below_the_limit(self):
        self.fail(LIMIT - 1)
        response = self.attempt(password=PASSWORD)
        self.assertRedirects(response, "/")

    def test_limit_blocks_even_the_correct_password(self):
        self.fail(LIMIT)
        response = self.attempt(password=PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, BLOCKED)
        self.assertContains(response, "15 dakika sonra tekrar dene.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_blocked_attempts_do_not_extend_the_block(self):
        self.fail(LIMIT)
        for _ in range(3):
            self.attempt(password=PASSWORD)
        self.assertEqual(RateLimitHit.objects.filter(scope="login").count(), LIMIT)

    def test_other_ips_are_unaffected(self):
        self.fail(LIMIT, REMOTE_ADDR="10.1.1.1")
        self.assertContains(self.attempt(password=PASSWORD, REMOTE_ADDR="10.1.1.1"), BLOCKED)
        self.assertRedirects(self.attempt(password=PASSWORD, REMOTE_ADDR="10.2.2.2", client=Client()), "/")

    def test_block_lifts_after_the_window(self):
        self.fail(LIMIT)
        RateLimitHit.objects.update(created_at=timezone.now() - timedelta(seconds=WINDOW + 5))
        self.assertRedirects(self.attempt(password=PASSWORD), "/")

    def test_remaining_time_is_shown_in_minutes(self):
        self.fail(LIMIT)
        RateLimitHit.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        self.assertContains(self.attempt(password=PASSWORD), "5 dakika sonra tekrar dene.")

    def test_block_does_not_leak_whether_username_exists(self):
        self.fail(LIMIT)
        known = self.attempt(username="kullanici", password=PASSWORD)
        unknown = self.attempt(username="kimse_yok", password="baska")
        self.assertContains(known, BLOCKED)
        self.assertContains(unknown, BLOCKED)

    def test_other_scopes_do_not_consume_login_budget(self):
        RateLimitHit.objects.bulk_create([RateLimitHit(scope="vote", ip_hash=client_ip_hash(_Req())) for _ in range(50)])
        self.assertRedirects(self.attempt(password=PASSWORD), "/")

    def test_authenticate_without_request_is_safe(self):
        self.assertIsNone(authenticate(username="kullanici", password="yanlis"))
        self.assertEqual(RateLimitHit.objects.count(), 0)

    def test_logged_in_user_is_redirected_before_throttle_matters(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.login_url), "/")


class AdminLoginThrottleTests(TestCase):
    admin_login = "/admin/login/"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("yonetici", "yonetici@example.com", PASSWORD)
        cls.member = User.objects.create_user("kullanici", "kullanici@example.com", PASSWORD)

    def attempt(self, password="yanlis-parola", username="yonetici", **extra):
        return self.client.post(self.admin_login, {"username": username, "password": password, "next": "/admin/"}, **extra)

    def test_admin_login_works_normally(self):
        self.assertRedirects(self.attempt(password=PASSWORD), "/admin/", fetch_redirect_response=False)

    def test_failed_admin_attempts_are_counted_and_block(self):
        for _ in range(LIMIT):
            self.assertNotContains(self.attempt(), BLOCKED)
        self.assertEqual(RateLimitHit.objects.filter(scope="login").count(), LIMIT)
        response = self.attempt(password=PASSWORD)
        self.assertContains(response, BLOCKED)
        self.assertEqual(self.client.get("/admin/").status_code, 302)  # oturum açılmadı

    def test_site_and_admin_logins_share_the_same_counter(self):
        for _ in range(LIMIT // 2):
            self.client.post(reverse("accounts:login"), {"username": "yonetici", "password": "yanlis"})
        for _ in range(LIMIT - LIMIT // 2):
            self.attempt()
        self.assertContains(self.attempt(password=PASSWORD), BLOCKED)
        self.assertContains(
            self.client.post(reverse("accounts:login"), {"username": "yonetici", "password": PASSWORD}), BLOCKED
        )

    def test_non_staff_password_is_still_rejected_by_admin(self):
        response = self.attempt(username="kullanici", password=PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, BLOCKED)


class _Req:
    META = {"REMOTE_ADDR": "127.0.0.1"}
