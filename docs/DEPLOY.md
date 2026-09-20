# Kararsızım — Deployment (Vercel + Supabase)

Bu doküman `docs/PROJECT.md` Bölüm 10–11'in uygulamadaki karşılığıdır. Uygulama tek bir Django süreci olarak Vercel Function'da çalışır; veritabanı Supabase Postgres'tir. Vercel, `manage.py`'yi bulup `WSGI_APPLICATION` ayarından giriş noktasını çıkarır; `api/index.py` sarmalayıcısı veya `builds`/`routes` içeren `vercel.json` **yazılmaz**.

## Repodaki deploy dosyaları

| Dosya | Görevi |
|---|---|
| `vercel.json` | Yalnızca fonksiyon ayarı: `regions: ["fra1"]` (Supabase Frankfurt ile aynı bölge) ve `config/wsgi.py` için `maxDuration: 30`. |
| `.python-version` | Vercel Python sürümü (`3.13`). Django 6.1 en az 3.12 ister. Yerel geliştirme 3.14 ile yapılıyor. |
| `requirements.txt` | Sadece çalışma zamanı bağımlılıkları (Python'da ağaç budama yok, hepsi pakete girer). |
| `config/settings.py` | `WSGI_APPLICATION`, `STATIC_ROOT`; `DEBUG=False` iken `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, güvenli çerezler ve HSTS (3600 sn). |

**Statik dosyalar:** `STATIC_ROOT` tanımlı olduğu için Vercel `collectstatic`'i build sırasında kendisi çalıştırır ve dosyaları CDN'den sunar; build script'ine `collectstatic` yazılmaz. Depolama sınıfı bilerek **varsayılan** bırakıldı (Manifest kullanılmıyor): dosya adı özetlemesi (hash) için gereken manifest dosyası çalışma zamanında bulunamazsa her sayfa 500 verir, kazancı ise prototipte küçüktür. Vercel her deploy'da CDN önbelleğini yeniler.

## Ortam değişkenleri (Vercel → Project Settings → Environment Variables)

Hepsi **Production** (isterseniz Preview) için tanımlanır. Gizli olanlar `Sensitive` işaretlenmelidir ve repoya, sohbete, ekran görüntüsüne girmemelidir.

| Değişken | Değer | Gizli |
|---|---|---|
| `DJANGO_DEBUG` | `False` | hayır |
| `DJANGO_SECRET_KEY` | rastgele, en az 50 karakter (aşağıdaki komut) | **evet** |
| `VOTER_KEY_SALT` | rastgele; yerelden **farklı** olmalı | **evet** |
| `DJANGO_ALLOWED_HOSTS` | `.vercel.app` (özel alan adı eklenirse virgülle) | hayır |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://<proje>.vercel.app` (şema dahil, sonda `/` yok; özel alan adında ayrıca eklenir) | hayır |
| `DATABASE_URL` | Supabase **Transaction pooler**, port **6543** | **evet** |

`DATABASE_URL_DIRECT` (Session pooler, 5432) Vercel'e **konmaz**; yalnızca yerelde migration için kullanılır.

Gizli değer üretmek için (yerelde çalıştırılır, çıktı doğrudan Vercel paneline yapıştırılır):

```bash
.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(50))"
```

`DATABASE_URL` biçimi (`.env.example`'daki gibi; parolada `@`, `#` gibi karakterler URL-encode edilmelidir):

```
postgresql://postgres.<PROJE_REF>:<PAROLA>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

`CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True` ve `prepare_threshold=None` ayarları `settings.py`'de Postgres bağlantısı için otomatik uygulanır (transaction pooler prepared statement desteklemez).

## Migration'lar

Migration'lar Vercel build'inde **çalışmaz**; yerelden, Supabase Session pooler üzerinden çalıştırılır. `settings.py`, `migrate` komutunda `.env` içinde `DATABASE_URL_DIRECT` varsa onu otomatik kullanır:

```powershell
# PowerShell
.venv\Scripts\python manage.py migrate
```

```bash
# bash / Git Bash
.venv/Scripts/python manage.py migrate
```

Migration sonrası kontrol listesi:

1. `manage.py showmigrations` — hepsi `[X]`.
2. **Yeni tablo eklendiyse RLS'yi (politikasız) aç** ve güvenlik denetimini çalıştır. Supabase, `public` şemasını Data API ile dışarı açar; RLS kapalı tablo `anon` anahtarıyla okunabilir. Django `postgres` rolüyle bağlandığı için RLS'den etkilenmez.

   ```sql
   ALTER TABLE public.<tablo> ENABLE ROW LEVEL SECURITY;
   ```

3. Supabase Dashboard'da **Data API kapalı** olmalı (Project Settings → API). Bu proje Data API kullanmaz.

## İlk deploy (Git bağlantılı)

Ön koşullar (bir kez):

- Vercel hesabında **GitHub bağlantısı** (Settings → Authentication) ve **Vercel GitHub uygulamasının** ilgili depoya erişimi. Depo **özel** ise ikincisi şarttır, yoksa proje oluşturma `repo_not_found` verir. (https://github.com/apps/vercel/installations/new)
- Vercel'de proje **Framework: Django** olarak açılır; Root Directory repo kökü, Build/Install komutları boş kalır.

Adımlar:

1. Değişiklikleri `main`'e push'layın. Vercel her push'ta otomatik build alır.
2. Ortam değişkenlerini **ilk deploy'dan önce** ekleyin (yukarıdaki tablo). Değişken sonradan eklenir veya değiştirilirse mevcut deploy etkilenmez; **Redeploy** gerekir.
3. Deploy bitince gerçek üretim adresini projenin **Domains** sayfasından okuyun. `<proje>.vercel.app` adı başkasına aitse Vercel ek koyar (bu projede `kararsizim-nine.vercel.app`). `DJANGO_CSRF_TRUSTED_ORIGINS` bu adresle **birebir** eşleşmelidir. Aynı deploy'a başka adresler de bağlıysa (`<proje>-<takım>.vercel.app`) ve kullanıcılar onları da kullanacaksa hepsi virgülle eklenir; aksi halde o adreste girişte/oylamada CSRF hatası alınır.
4. **Vercel Authentication** yeni projelerde varsayılan olarak açıktır ve `*.vercel.app` adreslerini Vercel girişinin arkasına alır. Herkese açık bir ürün için **Settings → Deployment Protection** altında kapatılmalıdır (bu projede kapatıldı).

Bu projedeki canlı değerler: adres `https://kararsizim-nine.vercel.app`, Function bölgesi `fra1`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://kararsizim-nine.vercel.app,https://kararsizim-kuzuabdullah-4850.vercel.app`.

### Deploy sonrası duman testi

- [ ] `https://<proje>.vercel.app/` açılıyor (giriş duvarı yok); CSS, JS ve fontlar yükleniyor (tarayıcı konsolunda 404 yok).
- [ ] `http://` adresi `https://`'e yönleniyor.
- [ ] Kayıt ol → anket oluştur → oy ver uçtan uca çalışıyor.
- [ ] `/yok-boyle-bir-sayfa/` özel 404 sayfasını gösteriyor (Django hata ekranı değil).
- [ ] Çerezler `Secure` (tarayıcı geliştirici araçları → Application → Cookies).
- [ ] Bir süre kullanılmadıktan sonraki **ilk istek** 500 vermiyor (soğuk başlangıç).
- [ ] Sayfa kaynağında e-posta adresi yok.

## Sorun giderme

| Belirti | Olası neden | Çözüm |
|---|---|---|
| `Bad Request (400)` | `DJANGO_ALLOWED_HOSTS` adresi kapsamıyor | `.vercel.app` ekleyin, Redeploy |
| Girişte/oylamada `403 Oturum doğrulanamadı` | `DJANGO_CSRF_TRUSTED_ORIGINS` adresle uyuşmuyor (şema, alt alan adı ve projenin gerçek adı dahil) | Origin'i Domains sayfasındaki adresle birebir yazın, Redeploy |
| Adres Vercel giriş sayfasına yönlendiriyor | Vercel Authentication açık | Deployment Protection'ı kapatın |
| Proje oluşturma `repo_not_found` | Vercel GitHub uygulamasının özel depoya izni yok | Uygulamaya depo erişimi verin |
| Açılışta `500` | `DJANGO_SECRET_KEY` yok veya `DATABASE_URL` hatalı | Runtime loglarına bakın (`Deployments → Logs`) |
| `failed to resolve host` / bağlanamıyor | `db.<ref>.supabase.co` doğrudan adresi (yalnız IPv6) kullanılmış | Pooler adresini (`aws-0-...pooler.supabase.com`) kullanın |
| İlk istek yavaş veya hata | Bağlantı havuzu ayarları | `DATABASE_URL` 6543 portlu Transaction pooler olmalı |
| Statik dosyalar 404 | `STATIC_ROOT` tanımsız | `settings.py`'de tanımlı olduğunu doğrulayın |

Emin olmadığınız bir deploy hatasında `vercel.json` doldurarak tahmin etmeyin; önce Vercel'in güncel Django dokümanına bakın: <https://vercel.com/docs/frameworks/full-stack/django>.

## Yönetim paneli

`/admin/` yalnızca süper kullanıcıya açıktır ve şu an süper kullanıcı **yoktur**. Gerektiğinde yerelde, `DATABASE_URL_DIRECT` bağlantısıyla, güçlü bir parolayla oluşturun (parola etkileşimli sorulur, hiçbir yere yazılmaz):

```bash
.venv/Scripts/python manage.py createsuperuser
```

## Bilmeniz gerekenler

- **Yerel ve canlı aynı veritabanını kullanır.** `.env`'deki `DATABASE_URL` Supabase'i gösterdiği sürece yerelde açılan anketler ve hesaplar canlıda da görünür. Ayrı bir geliştirme veritabanı istenirse ikinci bir Supabase projesi gerekir.
- Demo veri (`seed_demo`) gerçek kullanıcı gelmeden önce silinebilir: `polls_poll` ve `accounts_user` içindeki `demo_*` kayıtları.
- `vercel dev` ile yerelde deploy ortamı denemek için Vercel CLI gerekir (`npm i -g vercel`, `vercel login`, `vercel link`, `vercel pull`); CLI kurulu değilse yukarıdaki yerel `DEBUG=False` denemesi (`collectstatic` + `X-Forwarded-Proto: https` başlığı) aynı davranışları doğrular.
