Program Kullanım Kılavuzu — Webdedik Bilişim
Gereksinimler

Python 3.11+

ffmpeg (video thumbnail ve önizleme için, sistem PATH’inde olmalı)

Bağımlılıklar:

pip install -r requirements-documents.txt
pip install -r requirements-thumbnail.txt
Başlatma
python main.py

Program açıldığında Başlangıç Penceresi görüntülenir. İki ana seçenek bulunur.

Başlangıç Ekranı
1. Yeni imaj ile başla

“İmaj seç” → E01 dosyasını seçin (örn. disk.E01)

E02, E03 vb. segmentler aynı klasörde bulunmalıdır.

“Case klasörü seçin” → Mevcut bir case klasörü veya yeni klasör seçin.

Seçimden sonra:

Case oluşturulur

İmaj eklenir

Ana pencere açılır

2. Case aç

“Case aç” → Daha önce oluşturulmuş case klasörünü seçin

Geçerli bir case klasöründe case.json bulunmalıdır

Ana pencere açılır ve kanıt listesinden seçim yapılabilir

Ana Pencere
Üst Alan
Öğe	Açıklama
Kanıt açılır listesi	Birden fazla E01 varsa seçim yapılır
Geri / İleri / Yukarı	Gezinme kontrolleri
Yenile	Mevcut klasörü yeniden yükler
Yol	Geçerli klasör yolu (salt okunur)
Genel Raporlama	Tüm imaj için rapor oluşturur (arka planda)
Arama Çubuğu

Arama terimi girin (örn: *.jpg, document.pdf)

“Ara” ile tüm volume’da arama yapılır

Sonuçlar yeni bir sekmede listelenir

Sol Panel (Ağaç Yapısı)

Hiyerarşi:

E01 → Partition → Volume → Klasörler

Tek tıklama → Seçim yapar

Çift tıklama → Klasörü açar

Volume’e çift tıklama → Kök dizine gider

Merkez Alan (Dosya Listesi)
Kontrol	Açıklama
Tür	Filtre: Tüm türler / Klasör / .jpg / .pdf vb.
0 byte göster	0 bayt dosyaları gösterir veya gizler
Görünüm	Detay (tablo) veya Büyük simge
Simge boyutu	Büyük simge modunda 96–200 px arası
Tümünü seç / Seçimi temizle	Dışa aktarma için işaretleme
Bölüm raporu	Sadece bu klasör için HTML/PDF rapor
Dosyayı aktarma	Seçilen dosyaları diske kaydeder
Etiketle	Seçili öğeye etiket ve not ekler
Dosya Listesi Etkileşimleri

Çift tıklama (klasör) → Klasöre girer

Çift tıklama (dosya) → Tam ekran önizleme açılır

Önizleme (Preview)

Desteklenen türler:

Resimler

PDF

Office belgeleri

Metin dosyaları

Videolar

Kısayollar
Tuş	İşlev
← / →	Önceki / Sonraki dosya
Space	Video oynat/durdur veya resimde fit modu
+ / -	Yakınlaştır / Uzaklaştır
0	Fit modu
1	%100 boyut
R / L	Sağa / sola döndür
Esc	Önizlemeyi kapat
Etiket Sistemi

Dosya veya klasör seçin

“Etiketle” butonuna basın

Etiket seçin veya yeni etiket oluşturun

İsteğe bağlı not girin

Etiket Ayarları

Yeni etiket ekleme

Renk belirleme

Kısayol atama (F1, F2 vb.)

Raporlama
Bölüm Raporu

Mevcut klasörde “Bölüm raporu” seçin

HTML ve/veya PDF formatı seçilebilir

Opsiyonlar:

Dosyaları çıkar

Hash hesapla

Sadece etiketlileri dahil et

Genel Raporlama

“Genel Raporlama” ile tüm imaj işlenir

Arka planda çalışır

İlerleme çubuğu gösterilir

İstenirse tüm dosyalar çıkarılır ve hash’lerle rapor oluşturulur

Menü
Menü	Seçenek	Açıklama
Dosya	E01 Ekle	Yeni E01 imajını case’e ekler
Dosya	Build Snapshot	Tüm volume metadata’sını SQLite’a kaydeder
Dosya	Build İptal	Snapshot işlemini iptal eder
Dosya	Case'ten Aç	Başka kanıt seçer
Görünüm	Ağaç görünümü	Sol paneli gösterir / gizler
Görünüm	Meta veri paneli	Sağ paneli gösterir / gizler
Görünüm	Günlük paneli	Alt log panelini gösterir / gizler
Araçlar	Etiket ayarları	Etiket tanımlarını düzenler
Dışa Aktarma

Listeden dosyaların checkbox’larını işaretleyin

“Dosyayı aktarma” seçeneğini kullanın

Hedef klasörü seçin

Dosyalar diske kopyalanır.

Ek olarak:

Listeyi CSV olarak dışa aktarabilirsiniz

Meta Veri Paneli (Inspector)

Sağ tarafta yer alan Meta veri sekmesi seçilen dosyaya ait detayları gösterir:

Dosya adı

Inode

Tür

Boyut

Tarihler (mtime, atime, ctime)

Silinmiş bilgisi

Hash değerleri (MD5, SHA1)

Hash Hesaplama

“Hash hesapla” ile MD5 ve SHA1 oluşturulur

Medya Dosyaları İçin Ek Bilgiler

GPS konumu

Cihaz bilgisi

Çekim tarihi

EXIF verileri
