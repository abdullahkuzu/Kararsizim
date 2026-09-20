# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Bu projenin tam şartnamesi [docs/PROJECT.md](docs/PROJECT.md) dosyasındadır. Her görevden önce oku. Fazlar sırayla uygulanır, faz atlanmaz (hangi fazın bittiğini `git log`'daki `feat: faz N` commit'leri gösterir). Şartnameyle çelişen bir karar gerekiyorsa uygulamadan önce kullanıcıya söyle.

Kararsızım: kullanıcıların kararsız kaldıkları konuları küçük anketlere dönüştürdüğü Django web uygulaması. Arayüz metinleri Türkçe, kod içindeki isimler İngilizce.

## Commands

Windows / PowerShell; sanal ortam `.venv` (Python 3.14).

```bash
.venv/Scripts/python manage.py runserver
.venv/Scripts/python manage.py check
.venv/Scripts/python manage.py makemigrations
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py test                       # tüm testler
.venv/Scripts/python manage.py test polls.tests.SomeTest.test_name   # tek test
```

Test framework'ü Django'nun kendi runner'ı; pytest vb. eklenmez. Lint/format aracı yok. `manage.py test` bellek içi SQLite kullanır (settings `test` komutunu algılar; Supabase pooler ayrı test DB açamaz), bu yüzden gerçek eşzamanlılık davranışı testlerde ancak mock ile simüle edilir; yarış durumunu gerçek Postgres'te denemek için çalışan sunucuya paralel istek at.
Windows/Git Bash'te `curl -d "next=/anket/..."` gibi `/` ile başlayan değerleri yol sanıp bozar; `MSYS_NO_PATHCONV=1` veya `--data-urlencode` kullan.

## Architecture

- **Tek Django süreci**: HTML'i template'lerle üretir, küçük JSON uçları (`vote`, `results`) aynı view katmanından verilir. Ayrı API katmanı, DRF, Celery, Redis, Docker, frontend framework'ü **yok**; yeni bağımlılık gerekirse önce sor.
- **Katmanlar** (`polls/`): view'lar ince; DB yazma mantığı `services.py`, okuma sorguları `selectors.py`. Template içinde iş mantığı veya sorgu tetikleyen kod yazma. Anket listelerinde `select_related("author")` + `prefetch_related("options")` ile N+1'den kaçın.
- **Kimlik**: `accounts.User` (AbstractUser) ile özel kullanıcı modeli. `AUTH_USER_MODEL` ilk migration'dan **önce** ayarlanmalı; Faz 0'da bilerek `migrate` çalıştırılmadı. Supabase Auth/RLS kullanılmaz, Supabase sadece Postgres.
- **Oylama** (`polls/services.py::cast_vote`): sıra kapalı → 403, seçenek bu ankete ait değil → 400, zaten oy verilmiş → 409. Anonim oy `voter_key = sha256(session_key + VOTER_KEY_SALT)` ile takip edilir; `Vote` üzerinde iki koşullu `UniqueConstraint` yarış durumunu son kertede yakalar (`IntegrityError` → 409). `Option.vote_count` ve `Poll.total_votes` denormalize sayaçlardır, `transaction.atomic()` içinde `F()` ile artırılır. Oy sonrası `session["voted_polls"]` güncellenir; bu liste hem arayüz ipucu hem de "anonim oy verip sonra giriş yapan aynı oturum tekrar oy veremez" koruması olarak `cast_vote(voted_hint=...)`'e girer.
- **JSON / redirect ayrımı**: `vote` view'ı `X-Requested-With` veya `Accept: application/json` varsa JSON, yoksa başarıda redirect, hatada durum kodlu (403/409) detay sayfası döner. 400 düz metindir.
- **Sonuç gösterimi tek noktada**: `services.build_poll_view` (`PollView`, `OptionRow`) sonuçlar gizliyken `count`/`percent`'i hiç taşımaz; kart, detay ve `/sonuc/` JSON'u aynı yoldan geçer (`results_payload`). Yeni bir yerde sayı göstermek gerekirse bu yolu kullan, şablonda `poll.total_votes`/`option.vote_count` yazdırma.
- **Hız sınırı ve moderasyon** (Faz 7): `services.check_rate_limit`/`record_hit` (`RateLimitHit`, IP'nin tuzlanmış özeti; ham IP yok) anonim oyu ve anonim bildirimi sınırlar, `cast_vote(ip_hash=...)` içinde oy kaydıyla aynı transaction'da sayılır. IP `utils.client_ip_hash` ile alınır ve `X-Forwarded-For` yalnız `settings.CLIENT_IP_HEADER` tanımlıysa (`DEBUG=False`, Vercel) okunur. Bildirimler `Report` modelinde, kişi/oturum başına anket başına bir kez; `close_if_expired` süresi dolan anketi detay/oy/sonuç isteğinde kalıcı kapatır (cron yok). Kayıt formunda honeypot (`website` alanı) var.
- **Arama**: `selectors.feed_queryset(tab, query)` `question__iregex` ile çalışır; `search_pattern` girdiyi kaçışlar ve i/İ/ı/I'yi tek sınıfta birleştirir (Türkçe büyük/küçük harf). Sorguyu SQL'e ham verme.
- **Gizlilik**: e-posta hiçbir template, JSON veya logda görünmez; ham IP saklanmaz; anket URL'leri sıralı id yerine `public_id` kullanır.
- **Progressive enhancement**: JS kapalıyken anket oluşturma ve oy verme (form POST + redirect) çalışmalı; JS sadece iyileştirme (`static/js/`).
- **Frontend**: vanilla JS + el yazımı CSS. Şablonlarda, CSS'te ve `result-card.js`'te ham renk yok (canvas kartı renkleri ve fontları CSS token'larından okur), sadece [static/css/tokens.css](static/css/tokens.css) değişkenleri (renk, `--font-*`, `--fs-*`, `--sp-*`); `polls/test_ui.py` bunu ve tanımsız `var(--x)` kullanımını denetler. Yazı tipleri Google Fonts'tan (`base.html`), sistem fontuna düşer. `static/img/og.png` üretilmiş bir dosyadır (`tools/make_og.ps1`); SVG'lerde hex serbest.
- **Hata sayfaları**: `templates/{403,403_csrf,404,500}.html`. `500.html` bilerek `base.html`'i kullanmaz (bağımsız, bağlamsız render edilir).

## Configuration gotchas

- Ayarlar `.env`'den okunur (`.env.example`'a bak; `.env` git'e girmez). `DJANGO_DEBUG` varsayılanı `False`; `DJANGO_SECRET_KEY` boşsa yalnızca `DEBUG=True` iken geliştirme anahtarına düşülür.
- `DATABASE_URL` boşsa yerelde SQLite. Supabase için `DATABASE_URL` **transaction pooler (6543)**, `DATABASE_URL_DIRECT` **session pooler (5432)**; `migrate` komutu çalışırken [settings.py](config/settings.py) otomatik olarak `DATABASE_URL_DIRECT`'i kullanır. Doğrudan `db.<ref>.supabase.co` adresi (yalnız IPv6) kullanılmaz. Migration'lar Vercel build'inde değil, yerelden çalıştırılır.
- Postgres bağlantısında `CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`, `prepare_threshold=None` (transaction pooler prepared statement desteklemez); settings bunları yalnızca Postgres engine'inde uygular.
- Vercel Django'yu sıfır konfigürasyonla çalıştırır: `WSGI_APPLICATION` ve `STATIC_ROOT` yeterli. `api/index.py` sarmalayıcısı veya `builds`/`routes` içeren `vercel.json` yazma; build'de `collectstatic` çağırma. Sorun olursa tahmin etmek yerine güncel Vercel Django dokümanına bak.
- Statik dosya storage'ı bilerek varsayılan (Manifest yok): çalışma zamanında manifest bulunamazsa her sayfa 500 verir. Canlı adres https://kararsizim-nine.vercel.app (Vercel, `fra1`); `main`'e push otomatik deploy eder. **Model/tablo değişikliğinde önce migration'ı Supabase'e uygula, sonra push'la** (ayrıntı: `docs/DEPLOY.md`). Canlı ve yerel aynı Supabase veritabanını kullanır: denemelerde açtığın hesap/anketi sil, ama `Session.objects.all().delete()` gibi toplu silme yapma (gerçek kullanıcıların oturumunu düşürür).
- Supabase Data API tabloları dışarı açar: migration ile oluşan her yeni tabloda RLS'yi (politikasız) aç, yoksa `anon` anahtarıyla okunabilir; Django `postgres` rolüyle bağlandığı için etkilenmez. Migration sonrası `get_advisors(security)` ile kontrol et.
- Session backend veritabanıdır (serverless'ta bellek cache'i instance'lar arası paylaşılmaz); diske yazma yok.

## Workflow rules

- Her fazın sonunda değişiklikleri özetle, kabul kriterlerini tek tek işaretle ve `git commit` öner (`feat: faz N — ...`); kullanıcı onaylamadan sonraki faza geçme, commit'i kendin atma.
- Migration dosyalarını elle düzenleme; modeli değiştirip `makemigrations` çalıştır.
- Bir şeyi çözemiyorsan tahmin ederek üst üste deneme yapma; ne denediğini ve nerede takıldığını yaz.
