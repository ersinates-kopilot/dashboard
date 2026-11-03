# Instagram Takip

Ekran yüzlerinizin, çalıştığınız influencerların ve rakip hesapların Instagram performansını her gün otomatik toplayan ve bir dashboard'da gösteren web uygulaması.

## Neler var

- **Genel bakış:** Üç grubun özeti (hesap sayısı, toplam takipçi, medyan etkileşim, haftalık paylaşım), tüm hesapların tablosu (takipçi, 7/30 günlük değişim, etkileşim, paylaşım sıklığı) ve son 7 günün öne çıkan içerikleri.
- **Hesap detayı:** Takipçi grafiği, gönderi başına etkileşim grafiği ve gönderi listesi. Bağlı hesaplarda erişim, kaydetme, paylaşım ve izlenme de görünür. "Performans" sütunu, gönderinin beğenisini hesabın medyan beğenisiyle karşılaştırır (2× ve üstü yeşil gösterilir).
- **İçerikler:** Tüm hesapların gönderileri tek listede. Grup, dönem, tür (Reels/gönderi) ile filtrelenip etkileşim, beğeni, yorum ya da izlenmeye göre sıralanabilir.
- **Karşılaştır:** En fazla 8 hesabın takipçi büyümesi aynı grafikte, yüzde olarak. Böylece büyük ve küçük hesaplar adil karşılaştırılır.
- **Hesaplar:** Toplu hesap ekleme (kullanıcı adı veya profil linki), grup/not düzenleme, pasife alma, silme, elle toplama ve toplama kayıtları.
- **Bağlantı linki:** Her ekran yüzü/influencer için kişiye özel bir link. Kişi linke tıklayıp Instagram'da izin verince tam istatistikleri toplanır.

**Etkileşim oranı** her yerde aynı formülle hesaplanır: `(beğeni + yorum) / takipçi × 100`. Kaydetme ve paylaşım yalnızca bağlı hesaplarda bilindiği için formüle girmez. Böylece bağlı hesaplar ile rakipler aynı ölçüyle karşılaştırılır.

## Veri kaynakları

| Grup | Kaynak | Gerekenler |
|---|---|---|
| Ekran yüzleri, bağlanan influencerlar | Instagram Login (OAuth) | `IG_APP_ID`, `IG_APP_SECRET`; hesap İşletme/İçerik Üreticisi olmalı |
| Rakipler, bağlanmayan influencerlar | Meta Business Discovery | `META_IG_BUSINESS_ID`, `META_SYSTEM_TOKEN`; hedef hesap İşletme/İçerik Üreticisi olmalı |
| Kişisel hesaplar | Apify (isteğe bağlı) | `APIFY_TOKEN` |

Uygulama her hesap için kaynağı kendisi seçer: önce bağlı hesap, sonra Business Discovery. Hesap kişisel çıkarsa ve Apify açıksa Apify'a geçer. Apify kapalıysa hesap "Kişisel hesap (API dışı)" olarak işaretlenir.

> Apify, Instagram'ın herkese açık sayfalarını tarar ve Instagram kullanım şartları açısından gri alandadır. Kullanmak tamamen isteğe bağlıdır.

## Bilgisayarda çalıştırma (demo)

```bash
pip install -r requirements.txt
cp .env.example .env          # ADMIN_PASSWORD ve SECRET_KEY'i doldurun
python -m scripts.seed_demo   # 9 kurgusal hesap + 75 günlük geçmiş
uvicorn app.main:app --reload
```

Ardından http://localhost:8000 adresine gidip `ADMIN_PASSWORD` ile giriş yapın. Demo hesapların adı `demo_` ile başlar. Gerçek toplamaya dahil edilmezler; işiniz bitince Hesaplar sayfasından silebilirsiniz.

Testler: `python -m pytest -q`. Testler gerçek Meta API'ye istek atmaz, yanıtları taklit eder.

## Yayına alma (Railway örneği)

1. Kodu bir GitHub deposuna yükleyin.
2. railway.app'te **New Project → Deploy from GitHub repo** deyin. Dockerfile otomatik algılanır.
3. Aynı projeye **Add → Database → PostgreSQL** ekleyin. `DATABASE_URL` değişkenini uygulama servisine bağlayın (Variables → Add Reference).
4. Variables'a `.env.example` içindeki değerleri girin. `BASE_URL` olarak Railway'in verdiği adresi yazın (Settings → Networking → Generate Domain).
5. Uygulama açılınca giriş yapın ve Hesaplar sayfasından hesapları ekleyin.

Render, Fly.io ya da kendi sunucunuzda da aynı Dockerfile ile çalışır. Uygulamayı **tek worker** ile çalıştırın. Zamanlayıcı uygulamanın içinde olduğu için birden fazla kopya, toplamayı birden fazla kez tetikler.

## Meta kurulumu

### 1. Business Discovery (rakipler)

1. Kendi Instagram hesabınızı İşletme hesabına çevirip bir Facebook sayfasına bağlayın.
2. developers.facebook.com'da **Business** türünde bir uygulama oluşturup Business Portfolio'nuza bağlayın.
3. Business Suite → Ayarlar → Sistem kullanıcıları bölümünde Admin rolünde bir sistem kullanıcısı oluşturun. Bu kullanıcıya sayfayı, Instagram hesabını ve uygulamayı atayın.
4. "Generate new token" ile süresi **Never** olan bir token üretin. İzinler: `instagram_basic`, `pages_show_list`, `pages_read_engagement`, `business_management`. Bu token `META_SYSTEM_TOKEN` olur.
5. Graph API Explorer'da `me/accounts?fields=name,instagram_business_account` sorgusunu çalıştırın. Dönen `instagram_business_account.id` değeri (17841… ile başlar) `META_IG_BUSINESS_ID` olur.

### 2. Instagram Login (ekran yüzleri ve influencerlar)

1. Aynı uygulamaya **Instagram → API setup with Instagram login** ürününü ekleyin.
2. Bu ekranda görünen **Instagram app ID** ve **Instagram app secret** değerleri `IG_APP_ID` ve `IG_APP_SECRET` olur. Bunlar Facebook App ID ile aynı değildir.
3. "Business login settings" bölümüne OAuth yönlendirme adresi olarak `{BASE_URL}/oauth/instagram/callback` yazın.
4. **Geliştirme modu:** Uygulama incelemeden geçmeden yalnızca uygulamaya *Instagram Tester* olarak eklenen hesaplar bağlanabilir (App roles → Roles → Instagram Testers). Ekran yüzleriniz bu şekilde hemen başlayabilir; davet edilen kişi davetini Instagram'da Ayarlar → Web sitesi izinleri bölümünden kabul etmeli.
5. **Dış influencerlar** için uygulamanın Meta App Review'dan `instagram_business_basic` ve `instagram_business_manage_insights` izinleriyle geçmesi ve işletme doğrulamasının (Business Verification) yapılması gerekir. Bu süreç genelde birkaç gün ile birkaç hafta sürer. İnceleme için bir gizlilik politikası sayfası ve kısa bir ekran kaydı istenir.

Bağlanan hesapların token'ları 60 gün geçerlidir. Uygulama günlük toplama sırasında süresi dolmadan yeniler. Token'lar veritabanında `SECRET_KEY` ile şifreli saklanır.

## Sınırlar

- Business Discovery, kişisel hesapların ve gizli hesapların verisini vermez.
- Sahibi beğenileri gizlediyse beğeni sayısı gelmez; o gönderinin etkileşim oranı hesaplanmaz ("gizli" yazar).
- Hikayeler yalnızca bağlı hesaplarda ve yayında oldukları 24 saat içinde görülebilir.
- Profil fotoğrafı linkleri Instagram tarafında süreli olduğu için bazen baş harf gösterilir; bir sonraki toplamada yenilenir.
- Meta API sürümü (`META_GRAPH_VERSION`) yaklaşık iki yılda bir emekliye ayrılır. Meta yeni sürüm duyurduğunda bu değeri güncelleyin.

## Proje yapısı

```
app/
  main.py            Web uygulaması, sayfalar, OAuth akışı, zamanlayıcı
  collector.py       Toplama orkestrasyonu (kaynak seçimi, kaydetme)
  collectors/        Meta (Business Discovery + Instagram Login) ve Apify istemcileri
  metrics.py         Büyüme, etkileşim, paylaşım sıklığı hesapları
  db.py              Veritabanı modelleri
  templates/ static/ Arayüz
scripts/seed_demo.py Demo verisi
tests/               Otomatik testler
```

## Sonraki adımlar için fikirler

- Haftalık e-posta raporu ve yapay zekâ ile içerik yorumu (hangi konu/format işe yarıyor)
- Takipçi demografisi (bağlı hesaplar için yaş, cinsiyet, şehir)
- Kampanya etiketleme: influencer iş birliği gönderilerini işaretleyip kampanya bazında rapor
- Çoklu kullanıcı ve rol (izleyici/düzenleyici)
- Ani düşüş/viral gönderi uyarıları
