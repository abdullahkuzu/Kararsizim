# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Bu projenin tam şartnamesi [docs/PROJECT.md](docs/PROJECT.md) dosyasındadır. Her görevden önce oku. Fazlar sırayla uygulanır, faz atlanmaz (şu an Faz 0 tamam; bir sonraki Faz 1). Şartnameyle çelişen bir karar gerekiyorsa uygulamadan önce kullanıcıya söyle.

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

Test framework'ü Django'nun kendi runner'ı; pytest vb. eklenmez. Lint/format aracı yok.

## Architecture

- **Tek Django süreci**: HTML'i template'lerle üretir, küçük JSON uçları (`vote`, `results`) aynı view katmanından verilir. Ayrı API katmanı, DRF, Celery, Redis, Docker, frontend framework'ü **yok**; yeni bağımlılık gerekirse önce sor.
- **Katmanlar** (`polls/`): view'lar ince; DB yazma mantığı `services.py`, okuma sorguları `selectors.py`. Template içinde iş mantığı veya sorgu tetikleyen kod yazma. Anket listelerinde `select_related("author")` + `prefetch_related("options")` ile N+1'den kaçın.
- **Kimlik**: `accounts.User` (AbstractUser) ile özel kullanıcı modeli. `AUTH_USER_MODEL` ilk migration'dan **önce** ayarlanmalı; Faz 0'da bilerek `migrate` çalıştırılmadı. Supabase Auth/RLS kullanılmaz, Supabase sadece Postgres.
- **Oylama**: anonim oy `voter_key = sha256(session_key + VOTER_KEY_SALT)` ile takip edilir; `Vote` üzerinde iki koşullu `UniqueConstraint` var (user'lı / anonim). `Option.vote_count` ve `Poll.total_votes` denormalize sayaçlardır, `transaction.atomic()` içinde `F()` ile artırılır.
- **Sonuç gizliliği (sunucu tarafında)**: oy vermemiş ziyaretçiye (anket sahibi ve kapalı anketler hariç) yüzde/sayılar HTML'e ve `/sonuc/` JSON'una hiç gönderilmez, sadece toplam oy döner. Bkz. PROJECT.md Bölüm 6.
- **Gizlilik**: e-posta hiçbir template, JSON veya logda görünmez; ham IP saklanmaz; anket URL'leri sıralı id yerine `public_id` kullanır.
- **Progressive enhancement**: JS kapalıyken anket oluşturma ve oy verme (form POST + redirect) çalışmalı; JS sadece iyileştirme (`static/js/`).
- **Frontend**: vanilla JS + el yazımı CSS. Şablonlarda ve CSS'te ham hex kodu yok, sadece [static/css/tokens.css](static/css/tokens.css) değişkenleri.

## Configuration gotchas

- Ayarlar `.env`'den okunur (`.env.example`'a bak; `.env` git'e girmez). `DJANGO_DEBUG` varsayılanı `False`; `DJANGO_SECRET_KEY` boşsa yalnızca `DEBUG=True` iken geliştirme anahtarına düşülür.
- `DATABASE_URL` boşsa yerelde SQLite. Supabase için `DATABASE_URL` **transaction pooler (6543)**, `DATABASE_URL_DIRECT` **session pooler (5432)**; `migrate` komutu çalışırken [settings.py](config/settings.py) otomatik olarak `DATABASE_URL_DIRECT`'i kullanır. Doğrudan `db.<ref>.supabase.co` adresi (yalnız IPv6) kullanılmaz. Migration'lar Vercel build'inde değil, yerelden çalıştırılır.
- Postgres bağlantısında `CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`, `prepare_threshold=None` (transaction pooler prepared statement desteklemez); settings bunları yalnızca Postgres engine'inde uygular.
- Vercel Django'yu sıfır konfigürasyonla çalıştırır: `WSGI_APPLICATION` ve `STATIC_ROOT` yeterli. `api/index.py` sarmalayıcısı veya `builds`/`routes` içeren `vercel.json` yazma; build'de `collectstatic` çağırma. Sorun olursa tahmin etmek yerine güncel Vercel Django dokümanına bak.
- Statik dosya storage'ı şimdilik varsayılan; Manifest storage, `DEBUG=False` testlerde `{% static %}` etiketini bozabilir, Faz 6'da karar verilecek.
- Session backend veritabanıdır (serverless'ta bellek cache'i instance'lar arası paylaşılmaz); diske yazma yok.

## Workflow rules

- Her fazın sonunda değişiklikleri özetle, kabul kriterlerini tek tek işaretle ve `git commit` öner (`feat: faz N — ...`); kullanıcı onaylamadan sonraki faza geçme, commit'i kendin atma.
- Migration dosyalarını elle düzenleme; modeli değiştirip `makemigrations` çalıştır.
- Bir şeyi çözemiyorsan tahmin ederek üst üste deneme yapma; ne denediğini ve nerede takıldığını yaz.
