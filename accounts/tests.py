from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

PASSWORD = "gizli-parola-2026"


def register_data(**overrides):
    data = {
        "username": "ali_veli",
        "email": "ali@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


class RegisterTests(TestCase):
    url = reverse("accounts:register")

    def test_register_logs_in_and_greets(self):
        response = self.client.post(self.url, register_data(), follow=True)
        self.assertRedirects(response, "/")
        self.assertContains(response, "Hoş geldin, @ali_veli")
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get().pk)

    def test_email_is_stored_lowercase(self):
        self.client.post(self.url, register_data(email="Ali@Example.COM"))
        self.assertEqual(User.objects.get().email, "ali@example.com")

    def test_duplicate_email_rejected(self):
        User.objects.create_user("baska", "ali@example.com", PASSWORD)
        response = self.client.post(self.url, register_data(email="ALI@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertContains(response, "Bu e-posta ile zaten bir hesap var.")
        self.assertEqual(User.objects.count(), 1)

    def test_username_case_insensitive_conflict(self):
        User.objects.create_user("KullaniciAdi", "bir@example.com", PASSWORD)
        response = self.client.post(self.url, register_data(username="kullaniciadi"))
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_username_characters_rejected(self):
        for bad in ["ali veli", "ali-veli", "ali.veli", "çağrı", "ali@veli"]:
            with self.subTest(username=bad):
                response = self.client.post(self.url, register_data(username=bad))
                self.assertIn("username", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_username_length_limits(self):
        for bad in ["ab", "a" * 21]:
            with self.subTest(username=bad):
                response = self.client.post(self.url, register_data(username=bad))
                self.assertIn("username", response.context["form"].errors)

    def test_reserved_username_rejected(self):
        for reserved in ["admin", "Root", "kayit", "hakkinda"]:
            with self.subTest(username=reserved):
                response = self.client.post(self.url, register_data(username=reserved))
                self.assertIn("username", response.context["form"].errors)

    def test_all_fields_required(self):
        response = self.client.post(self.url, {})
        self.assertEqual(
            set(response.context["form"].errors), {"username", "email", "password1", "password2"}
        )

    def test_password_validators_active(self):
        for weak in ["kisa1", "12345678", "password"]:
            with self.subTest(password=weak):
                response = self.client.post(self.url, register_data(password1=weak, password2=weak))
                self.assertIn("password2", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_password_mismatch_rejected(self):
        response = self.client.post(self.url, register_data(password2="baska-parola-2026"))
        self.assertIn("password2", response.context["form"].errors)

    def test_logged_in_user_is_redirected_away(self):
        self.client.post(self.url, register_data())
        self.assertRedirects(self.client.get(self.url), "/")


class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("KullaniciAdi", "kul@example.com", PASSWORD)

    def test_login_works(self):
        response = self.client.post(reverse("accounts:login"), {"username": "KullaniciAdi", "password": PASSWORD})
        self.assertRedirects(response, "/")

    def test_login_is_case_insensitive(self):
        response = self.client.post(reverse("accounts:login"), {"username": "kullaniciadi", "password": PASSWORD})
        self.assertRedirects(response, "/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_password_shows_error(self):
        response = self.client.post(reverse("accounts:login"), {"username": "KullaniciAdi", "password": "yanlis"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_is_respected(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=/anket/olustur/",
            {"username": "KullaniciAdi", "password": PASSWORD, "next": "/anket/olustur/"},
        )
        self.assertRedirects(response, "/anket/olustur/", fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "KullaniciAdi", "password": PASSWORD, "next": "https://evil.example/"},
        )
        self.assertRedirects(response, "/")

    def test_create_page_notice_shown_only_for_create_next(self):
        with_next = self.client.get(reverse("accounts:login") + "?next=/anket/olustur/")
        self.assertContains(with_next, "Anket oluşturmak için giriş yapman gerekiyor.")
        without = self.client.get(reverse("accounts:login"))
        self.assertNotContains(without, "Anket oluşturmak için giriş yapman gerekiyor.")

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), "/")
        self.assertNotIn("_auth_user_id", self.client.session)


class HeaderAndPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("gizli_kisi", "gizli@example.com", PASSWORD)

    def test_anonymous_header(self):
        response = self.client.get("/")
        self.assertContains(response, "Giriş yap")
        self.assertContains(response, "Kayıt ol")
        self.assertNotContains(response, "Anket oluştur")

    def test_authenticated_header(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertContains(response, "@gizli_kisi")
        self.assertContains(response, "Anket oluştur")
        self.assertContains(response, "Çıkış yap")
        self.assertNotContains(response, "Giriş yap")

    def test_email_never_rendered(self):
        self.client.force_login(self.user)
        for url in ["/", reverse("accounts:login")]:
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url, follow=True), "gizli@example.com")
