# DiskAdvisor

6000 RHEL sunucudan gelen disk ekleme/extend taleplerini otomatik değerlendiren, 0-100 skorlu ve eşik bazlı karar üreten (APPROVE / APPROVE_REDUCED / MANUAL_REVIEW / REJECT) bir Advisor sistemi.

Bu repo, onaylanmış plana göre kurulmuş **ilk faz iskeletidir**: uçtan uca çalışan, test edilebilir bir backend + frontend. RPM paketleme, gerçek Dynatrace/AAP Controller credential'larıyla prod bağlantısı, SSO/auth ve HA bu fazın kapsamı dışındadır.

## Mimari (özet)

- `diskadvisor-api` (FastAPI, systemd servisi): ITSM'den senkron `POST /api/v1/advisor/evaluate` çağrısını karşılar; PostgreSQL'deki metrikleri okur, gerekirse Ansible Automation Platform (AAP) Controller'da tek seferlik bir audit job'u tetikler (`limit=<hostname>` ile tek host'a daraltılmış), scoring engine ile karar üretir.
- `diskadvisor-collector` (systemd timer + oneshot service): periyodik olarak (1) Dynatrace Entities API v2'den RHEL host envanterini çeker ve `hosts` tablosuna senkronize eder, (2) Metrics API v2'den bu host'lara ait disk kullanım verisini çekip `disk_metrics` tablosuna yazar.
- React (Vite+TS) UI: Dashboard, Talep listesi, Talep detayı (skor/gerekçe + manuel override), Host metrik trendi.

Detaylı mimari ve veri modeli için onaylı plan: bkz. proje geçmişi / `backend/app/db/models.py`.

## Fleet-wide izleme (sadece talepler değil, mevcut ortamın standardı)

`disk_metrics` tablosu (Dynatrace'den saatlik toplanan geçmiş veri) üzerinden, tek bir talebe bağlı olmayan iki fleet görünümü (`app/services/fleet_analytics.py`):

- `GET /api/v1/hosts/top-growth?days=7&limit=10` — son N günde **doluluk yüzdesi (percentage-point) en çok artan** 10 file system, host+mount başına hem % artış hem GB artış birlikte döner. Sıralama GB değil % puan bazlı yapılır, çünkü disk boyutları çok değişken (100GB vs 2TB) — GB bazlı sıralama her zaman en büyük diskleri öne çıkarırdı.
- `GET /api/v1/hosts/high-usage?threshold_pct=90` — doluluğu şu an %90 ve üzeri olan tüm file system'ler.

Dashboard'da bu iki liste her zaman hem **%** hem **GB** birlikte gösterilir. Geçmişe dönük karşılaştırma için `disk_metrics` verisi silinmeden PostgreSQL'de birikir (şu an bir retention/purge politikası yok — tablo büyüklüğü zamanla izlenmeli).

## Analiz sayfası (kök sebep korelasyonu)

`GET /api/v1/hosts/{hostname}/correlation?days=7` — seçilen tek bir host için CPU/bellek/network/disk I/O metriklerini **canlı olarak Dynatrace'den** çeker (DB'ye yazılmaz, sürekli fleet-wide toplama değildir — sadece top-growth/high-usage listesine düşen ya da talep anındaki "şüpheli" host'lar için, kullanıcı Analiz sayfasını açtığında tetiklenir). Frontend'de bu, disk kullanım trendiyle yan yana gösterilir (`frontend/src/pages/Analysis.tsx`) — bir kaynak sıçramasının (CPU/network/disk I/O) disk büyümesiyle zamanda çakışıp çakışmadığını görsel olarak incelemek için.

Metrik listesi `app/core/config.py`'de `DISKADVISOR_DYNATRACE_CORRELATION_METRICS` ile ayarlanabilir (varsayılan: `builtin:host.cpu.usage`, `builtin:host.mem.usage`, `builtin:host.disk.read.bytes`, `builtin:host.disk.write.bytes`, `builtin:host.net.nic.bytesRx`, `builtin:host.net.nic.bytesTx`) — **bu metrik adları canlı bir Dynatrace tenant'ına karşı doğrulanmadı**, kod jenerik çalışır (yanıtta olmayan bir metrik boş seri olarak döner, hata vermez), ama gerçek tenant'a bağlanmadan önce Dynatrace'in Metrics API "browse" endpoint'i (`GET /api/v2/metrics`) ile bu key'lerin gerçekten var olduğu doğrulanmalı.

**Kapsam dışı bırakılan** (kullanıcı onayıyla): hangi *proses*in disk büyümesine sebep olduğunu bulmak. Dynatrace'in Metrics API'si bunu güvenilir şekilde vermiyor (process-level disk I/O attribution, tenant'a/OneAgent sürümüne göre değişir ve doğrulanamadı). Bunun yerine mevcut AAP/Ansible audit mekanizması (`backend/deploy/ansible/audit_disk.yml`) zaten en büyük dizinleri ve eski/rotate edilmemiş log dosyalarını buluyor; proses tespiti istenirse bu playbook'a `lsof`/`fuser` adımı eklenerek genişletilebilir (sonraki faz).

## Backend'i çalıştırma

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # gerekirse DB/Dynatrace/SSH ayarlarını düzenleyin

# Migration (varsayılan .env ile SQLite kullanılabilir, prod'da Postgres):
alembic -c app/db/alembic.ini upgrade head

# API'yi başlat:
uvicorn app.main:app --reload --port 8000
```

Örnek manuel test:

```bash
curl -X POST http://localhost:8000/api/v1/advisor/evaluate \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TCK-1","hostname":"app01","mount_point":"/var/log","requested_gb":20,"requester":"kullanici"}'
```

### Testler

```bash
cd backend
pytest
```

`tests/` klasörü şunları kapsar:
- `test_scoring.py`: scoring engine (saf fonksiyon) için kapsamlı unit testler, özellikle "SSH audit'e erişilemezse karar her zaman MANUAL_REVIEW olmalı" invariant'ı.
- `test_api.py`: `/advisor/evaluate`, `/requests`, `/requests/{id}/override`, `/hosts` endpoint'leri; SQLite in-memory DB fixture'ı ile.
- `test_dynatrace_client.py`: Dynatrace Metrics API v2 client'ı, mock HTTP transport ile.
- `test_ssh_audit.py`: AAP Controller audit TTL cache mantığı ve `job_templates/{id}/launch/` + `jobs/{id}/` çağrıları, mock HTTP transport ile (`limit`/`extra_vars` payload'ının doğru gönderildiği dahil).

## Frontend'i çalıştırma

```bash
cd frontend
npm install
cp .env.example .env             # VITE_API_BASE_URL backend adresini gösterir
npm run dev                      # http://localhost:5173
```

Backend'e ulaşılamazsa (örn. sadece UI'ı demo etmek için) sayfalar otomatik olarak `src/api/mockData.ts` içindeki örnek veriyle render olur.

Build doğrulaması:

```bash
npm run build
```

## Ansible entegrasyonu (AAP Controller, önemli)

DiskAdvisor sunucularda ajan çalıştırmaz, SSH açmaz ve Ansible'ı kendi üzerinde çalıştırmaz — sadece bir **AAP Controller API istemcisidir**:

1. `POST {AAP_BASE_URL}/api/controller/v2/job_templates/{DISKADVISOR_ANSIBLE_CONTROLLER_JOB_TEMPLATE_ID}/launch/`
   body: `{"limit": "<hostname>", "extra_vars": {"target_mount_point": "<mount>"}}`
   → job template'in inventory'si 6000 host'un tamamını içerir, `limit` isteği sadece talebin geldiği tek host'a daraltır.
2. `GET {AAP_BASE_URL}/api/controller/v2/jobs/{job_id}/` periyodik olarak (`ansible_controller_poll_interval_seconds`) sorgulanır, `status` terminal bir duruma (`successful`/`failed`/`error`/`canceled`) gelene kadar.
3. Playbook (`backend/deploy/ansible/audit_disk.yml`) sonuçları `ansible.builtin.set_stats` ile yayınlar; Controller bunları job'ın `artifacts` alanında döner — DiskAdvisor bu `artifacts`'i doğrudan okur (paylaşımlı dosya sistemi gerekmez).
4. Job `successful` değilse veya `ssh_audit_timeout_seconds` içinde terminal duruma gelmezse `run_audit` `None` döner → scoring engine skor hesaplamaz, karar otomatik `MANUAL_REVIEW`.

Sonuçlar, aynı host/mount için `ssh_audit_cache_ttl_hours` (varsayılan 24s) boyunca `directory_audits` tablosunda cache'lenir — TTL içinde tekrar Controller'a job atılmaz.

İlgili dosyalar: `app/services/ssh_audit.py` (`_launch_controller_job`, `run_audit`), `backend/deploy/ansible/audit_disk.yml`.

## Systemd (dokümantasyon amaçlı, bu fazda deploy edilmedi)

- `backend/deploy/systemd/diskadvisor-api.service`
- `backend/deploy/systemd/diskadvisor-collector.service` + `.timer`

## Stub / mock olan kısımlar (önemli)

- **Dynatrace bağlantısı**: `app/services/dynatrace_client.py` gerçek bir Entities API v2 + Metrics API v2 istemcisidir (RHEL host keşfi + disk kullanım metrikleri) ama bu oturumda **canlı bir Dynatrace tenant'ına karşı çalıştırılmadı**; testlerde mock HTTP transport kullanılır. `list_rhel_hosts` host'ları `osType(LINUX)` ile sunucu tarafında, `osVersion` içinde "Red Hat" geçenleri istemci tarafında filtreler (Dynatrace'in distro bazlı bir entitySelector'ü yok).
- **AAP Controller audit**: `app/services/ssh_audit.py` gerçek bir Controller REST istemcisidir (launch + poll + artifacts) ama gerçek bir AAP Controller/RHEL host olmadan uçtan uca test edilemez; unit testlerde `launch_fn` ve mock HTTP transport kullanılır. `backend/deploy/ansible/audit_disk.yml` gerçek fleet'e karşı bu oturumda çalıştırılmadı — job template olarak Controller'a elle yüklenmesi gerekir.
- **Frontend**: gerçek backend'e bağlanacak şekilde yazıldı; backend çalışmıyorsa sayfalar otomatik olarak mock veriyle render olur.

## Doğrulama durumu

`pytest`, `alembic upgrade head` (SQLite ile) ve `npm run build` bu ortamda **çalıştırılıp doğrulandı** (22/22 backend testi geçti, 6 tablo migration'ı hatasız uygulandı, frontend hatasız derlendi). AAP Controller entegrasyonu değişikliğinden sonra testler tekrar çalıştırılmalı:

```bash
cd backend && pip install -r requirements.txt && pytest
cd backend && alembic -c app/db/alembic.ini upgrade head   # prod: gerçek PostgreSQL ile
cd frontend && npm install && npm run build
```
