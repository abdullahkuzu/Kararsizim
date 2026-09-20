import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.http import HttpRequest
from django.test import Client, RequestFactory, TestCase
from django.views.defaults import server_error

from .models import Option, Poll
from .tests import PASSWORD, make_poll

User = get_user_model()

CSS_DIR = Path(settings.BASE_DIR) / "static" / "css"
TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates"


class ErrorPageTests(TestCase):
    def test_404_uses_custom_page_with_header(self):
        response = self.client.get("/olmayan-bir-sayfa/")
        self.assertContains(response, "Bu sayfa yok", status_code=404)
        self.assertContains(response, "Anketlere dön", status_code=404)
        self.assertContains(response, "Giriş yap", status_code=404)

    def test_unknown_poll_and_profile_use_404_page(self):
        for url in ("/anket/yokboyleid1/", "/kullanici/kimse_yok/"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "Bu sayfa yok", status_code=404)

    def test_403_page_for_non_owner(self):
        author = User.objects.create_user("yazar", "yazar@example.com", PASSWORD)
        other = User.objects.create_user("baska", "baska@example.com", PASSWORD)
        poll = make_poll(author)
        self.client.force_login(other)
        response = self.client.post(f"/anket/{poll.public_id}/kapat/")
        self.assertContains(response, "Buna iznin yok", status_code=403)

    def test_csrf_failure_page_is_turkish(self):
        response = Client(enforce_csrf_checks=True).post("/giris/", {"username": "a", "password": "b"})
        self.assertContains(response, "Oturum doğrulanamadı", status_code=403)

    def test_500_page_is_standalone(self):
        request = RequestFactory().get("/")
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Bir şeyler ters gitti", response.content.decode())
        self.assertNotIn("csrf", response.content.decode().lower())


class PageStructureTests(TestCase):
    def test_index_has_single_h1_skip_link_and_main(self):
        html = self.client.get("/").content.decode()
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('href="#main"', html)
        self.assertIn('<main id="main"', html)
        self.assertIn("Sen sor, birlikte karar verelim.", html)

    def test_fonts_are_loaded_with_swap_and_preconnect(self):
        html = self.client.get("/").content.decode()
        self.assertIn('rel="preconnect" href="https://fonts.googleapis.com"', html)
        self.assertIn('href="https://fonts.gstatic.com" crossorigin', html)
        for family in ("Bricolage+Grotesque", "Inter", "JetBrains+Mono"):
            self.assertIn(family, html)
        self.assertIn("display=swap", html)

    def test_slogan_is_consistent_everywhere(self):
        old = "kalabalık karar versin"
        offenders = [str(path.relative_to(TEMPLATE_DIR)) for path in TEMPLATE_DIR.rglob("*.html") if old in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])
        html = self.client.get("/").content.decode()
        self.assertIn('<meta name="description" content="Sen sor, birlikte karar verelim.">', html)
        self.assertIn('<meta property="og:description" content="Sen sor, birlikte karar verelim.">', html)
        self.assertRegex(html, r'<h1 class="page-title">Sen sor, birlikte karar verelim\.</h1>')

    def test_brand_assets_exist(self):
        for path in ("img/logo.svg", "img/og.png", "css/tokens.css", "css/base.css", "css/components.css"):
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))

    def test_favicon_and_logo_in_page(self):
        html = self.client.get("/").content.decode()
        self.assertIn('rel="icon" type="image/svg+xml" href="/static/img/logo.svg"', html)


class ShareMetaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("yazar", "gizli@example.com", PASSWORD)
        cls.poll = make_poll(cls.author, "Akşam yemeği için ne seçmeli?", counts=(3, 7))

    def test_default_meta(self):
        html = self.client.get("/").content.decode()
        self.assertIn('property="og:title" content="Kararsızım"', html)
        self.assertIn('property="og:image" content="http://testserver/static/img/og.png"', html)
        self.assertIn('name="twitter:card" content="summary_large_image"', html)

    def test_detail_shares_question_and_options(self):
        html = self.client.get(self.poll.get_absolute_url()).content.decode()
        self.assertIn('property="og:title" content="Akşam yemeği için ne seçmeli?"', html)
        self.assertIn("Seçenekler: Seçenek A, Seçenek B. Sen de oy ver.", html)
        self.assertIn(f'property="og:url" content="http://testserver{self.poll.get_absolute_url()}"', html)

    def test_share_meta_never_leaks_results_or_email(self):
        html = self.client.get(self.poll.get_absolute_url()).content.decode()
        head = html[: html.index("</head>")]
        self.assertNotIn("%", head.replace("%2B", ""))
        self.assertNotIn("10 kişi", head)
        self.assertNotIn("gizli@example.com", html)

    def test_question_is_escaped_in_meta(self):
        poll = make_poll(self.author, 'Tırnak "test" <b>kalın</b> anket sorusu?')
        head = self.client.get(poll.get_absolute_url()).content.decode()
        head = head[: head.index("</head>")]
        self.assertNotIn("<b>kalın</b>", head)
        self.assertIn("&lt;b&gt;", head)


class DesignSystemRuleTests(TestCase):
    def css_files(self):
        return sorted(CSS_DIR.glob("*.css"))

    def test_no_raw_hex_outside_tokens(self):
        hex_color = re.compile(r"#[0-9a-fA-F]{3,8}\b")
        offenders = []
        for path in [*self.css_files(), *TEMPLATE_DIR.rglob("*.html")]:
            if path.name == "tokens.css":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if hex_color.search(line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [])

    def test_every_css_variable_used_is_defined_in_tokens(self):
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", (CSS_DIR / "tokens.css").read_text(encoding="utf-8")))
        defined.add("--c")  # bileşen içi yerel değişken (seçenek rengi)
        used = set()
        for path in self.css_files():
            used |= set(re.findall(r"var\((--[a-z0-9-]+)", path.read_text(encoding="utf-8")))
        self.assertEqual(sorted(used - defined), [])

    def test_option_colors_follow_the_palette_order(self):
        tokens = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
        for index, color in enumerate(["violet", "pink", "mint", "sun", "sky"]):
            self.assertRegex(tokens, rf"--opt-{index}:\s*var\(--{color}\)")

    def test_accessibility_rules_present(self):
        base = (CSS_DIR / "base.css").read_text(encoding="utf-8")
        self.assertIn("outline: 3px solid var(--sun)", base)
        self.assertIn("outline-offset: 2px", base)
        self.assertIn("prefers-reduced-motion: reduce", base)

    def test_touch_targets_are_at_least_44px(self):
        components = (CSS_DIR / "components.css").read_text(encoding="utf-8")
        for selector in (".btn {", ".tab {", ".option-row {", ".site-logo {"):
            with self.subTest(selector=selector):
                start = re.search(rf"^{re.escape(selector)}", components, re.MULTILINE).start()
                block = components[start:]
                block = block[: block.index("}")]
                self.assertIn("min-height: 44px", block)

    def test_sun_never_carries_white_text(self):
        for path in self.css_files():
            css = path.read_text(encoding="utf-8")
            for block in re.findall(r"[^{}]+\{[^{}]*\}", css):
                if "background: var(--sun)" in block:
                    self.assertNotRegex(block, r"(?<!-)color:\s*var\(--surface\)")


class PollCardStateTests(TestCase):
    def test_empty_state_copy_and_button(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Henüz anket yok. İlk kararsızlığını sen paylaş.", html)
        self.assertIn('href="/anket/olustur/"', html)

    def test_closed_tag_and_neutral_bar_render(self):
        author = User.objects.create_user("yazar", "y@example.com", PASSWORD)
        make_poll(author, "Açık ve oylanmış anket sorusu?", counts=(2, 1))
        html = self.client.get("/").content.decode()
        self.assertIn("decision-bar-neutral", html)
        self.assertIn('role="img"', html)
        self.assertIn("Sonuçlar henüz gösterilmiyor", html)
