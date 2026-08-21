# OCI Always Free War Bot — Singapore (ap-singapore-1)

Bot retry otomatis 24/7 (GitHub Actions) untuk mengklaim instance **Oracle Cloud Always Free**
di region Singapura — region yang terkenal selalu "Out of host capacity".

> Diadaptasi dan di-fine-tune dari [WendyChen330/oci-arm-retry](https://github.com/WendyChen330/oci-arm-retry).
> Hampir semua bagian jaringan, interval, dan penanganan error sudah diubah dari versi asli (lihat bagian "Perubahan dari repo asli").

---

## Konteks: perubahan Always Free 18 Agustus 2026

Oracle memangkas jatah Always Free Ampere A1 menjadi **setengahnya** dan mulai menegakkannya
**18 Agustus 2026**:

| Resource | Sebelum | Sekarang |
|---|---|---|
| Ampere A1 (ARM) | 4 OCPU / 24 GB | **2 OCPU / 12 GB** (1.500 OCPU-jam + 9.000 GB-jam per bulan) |
| Micro E2.1.Micro | 2 instance | 2 instance (tidak berubah) |
| Block volume | 200 GB / region | 200 GB / region |

Instance free-tier yang melebihi limit lama **diterminasi otomatis** mulai 18 Agustus →
banyak kapasitas kosong baru muncul di region ramai. Bot ini menargetkan jatah yang baru:

- `oci_retry.py` → **VM.Standard.A1.Flex** 2 OCPU / 12 GB RAM / 100 GB boot
- `oci_retry_micro.py` → **VM.Standard.E2.1.Micro** 1 OCPU / 1 GB RAM / 50 GB boot

Total storage bila semua menang: 100 + 50 + 50 = **200 GB** (tepat di kuota — jangan tambah volume lain).

---

## Isi repo

| File | Fungsi |
|---|---|
| `oci_retry.py` | **Front utama** — war ARM A1 (`legacy-arm`), retry tiap 90–120 detik |
| `oci_retry_micro.py` | **Front sekunder** — war Micro kedua (`legacy-deploy-micro`), retry tiap 300–360 detik |
| `.github/workflows/oci_retry_micro.yml` | Workflow 24/7 untuk Micro |
| `.github/workflows/oci_retry.yml` | Workflow 24/7 untuk ARM |
| `inspect_tenancy.py` | Diagnostik read-only: AD, VCN, instance, pemakaian disk |
| `inspect_vcn.py` | Diagnostik read-only: security list & route table |
| `dry_run_check.py` | Diagnostik read-only: ketersediaan shape & image |

---

## Strategi

1. **ARM didahulukan (front utama), Micro kedua.** Satu Micro sudah dimiliki (`helia-micro`,
   berfungsi sebagai cadangan), jadi Micro kedua hanya bonus. ARM adalah hadiah utama
   (untuk deploy "super legacy") → ditembak paling agresif.
2. **Tuning rate-limit.** OCI men-throttle `LaunchInstance` per user (jendela ~60 detik —
   dua call berdekatan, yang kedua kena `429`). Kedua front diatur supaya total laju
   request ≈ **1 call / 80 detik**: ARM 90s + jitter 0–30s, Micro 300s + jitter 0–60s.
3. **Backoff 429 progresif**: 120 → 240 → 480 detik (maks 900 detik), reset setelah
   respons normal. Tidak tergantung interval dasar (bug versi awal: backoff ARM bisa
   membengkak 600 detik hanya karena satu 429).
4. **Preflight kuota.** Sebelum mulai, script cek apakah jatah sudah terpakai
   (2 OCPU A1 / 2 Micro). Sudah penuh → langsung exit sukses.
5. **Deteksi menang dari front lain.** Bila `LaunchInstance` ditolak karena kuota penuh
   (mis. front lokal menang duluan), script berhenti dengan status sukses — workflow
   otomatis menonaktifkan dirinya.
6. **Reuse infrastruktur jaringan existing (opsional).** Free tier dibatasi **maksimal
   2 VCN**. Set `EXISTING_SUBNET_NAME` ke nama display subnet publik yang sudah ada untuk
   memakainya tanpa membuat VCN baru; bila kosong, script membuat VCN bersama
   `retry-vcn-shared` (10.2.0.0/16) — aman selama jumlah VCN masih di bawah limit.
7. **Jitter acak** pada setiap interval agar tidak sinkron dengan bot lain.
8. **Buka port additif.** Script memastikan ingress 22/80/443/8501 terbuka di security
   list subnet — hanya menambah rule yang kurang, tidak pernah menghapus rule lama.

---

## Perubahan dari repo asli (WendyChen330/oci-arm-retry)

| Aspek | Repo asli | Repo ini |
|---|---|---|
| VCN | Bikin `retry-vcn` + `retry-vcn-micro` sendiri (CIDR 10.0/10.1) | Reuse subnet existing; fallback satu VCN bersama |
| Interval | 90 detik keduanya | ARM 90s (front utama), Micro 300s (sekunder) — tuning rate-limit |
| 429 | Diperlakukan seperti error biasa | Backoff progresif 120→240→480s (cap 900s) |
| Preflight | Tidak ada | Cek kuota dulu; stop elegan bila jatah sudah penuh |
| Deteksi menang paralel | Tidak ada | `LimitExceeded` + kuota penuh → exit sukses |
| Auth error | Retry terus | Fatal → exit 2 (hemat menit Actions) |
| Port | Replace seluruh ingress rule | Additif (hanya tambah yang kurang) |
| Spesifikasi | 2 OCPU / 12 GB | Sama (sudah sesuai limit pasca-Agustus 2026) |

---

## Konfigurasi

> ⚠️ **Jangan pernah commit data tenancy asli (OCID, IP, private key) ke repo public.**
> Repo ini sengaja generik: tenancy OCID dibaca dari `~/.oci/config` pada runtime
> (di GitHub Actions, file itu dibuat dari repository secrets). Nilai pribadi hanya
> hidup di GitHub Secrets atau di mesin lokal — tidak pernah di git.

```python
COMPARTMENT_ID = ""               # kosong = pakai tenancy dari ~/.oci/config
SSH_PUBLIC_KEY = "ssh-ed25519 AAAA... your-key"   # isi .pub kamu (ini aman di-commit)
INSTANCE_NAME  = "legacy-arm"     # ARM; Micro = "legacy-deploy-micro"
ARM_OCPUS = 2
ARM_MEMORY_IN_GBS = 12
BOOT_VOLUME_SIZE_IN_GBS = 100     # ARM; Micro = 50
RETRY_INTERVAL = 300              # ARM; Micro = 90
EXISTING_SUBNET_NAME = ""         # opsional: nama display subnet yang mau di-reuse
```

Region ditentukan oleh `region` di `~/.oci/config` / secret `OCI_REGION`
(bot ini dipakai di `ap-singapore-1`, tapi script-nya region-agnostic).

---

## GitHub Actions — setup

Butuh **6 secrets** (Settings → Secrets and variables → Actions):

| Secret | Isi |
|---|---|
| `OCI_USER` | OCID user (`ocid1.user.oc1..`) |
| `OCI_FINGERPRINT` | Fingerprint API key |
| `OCI_TENANCY` | OCID tenancy |
| `OCI_REGION` | `ap-singapore-1` |
| `OCI_PRIVATE_KEY` | Isi lengkap file `.pem` API key |
| `GH_PAT` | PAT classic scope `workflow` (untuk relay & auto-disable) |

Cara kerja workflow (masing-masing ARM & Micro):

```
Job jalan (~330 menit, ~220 attempt)
  ├─ Menang      → workflow auto-disable, selesai
  └─ Timeout     → otomatis trigger Job berikutnya (estafet tanpa jeda)
```

Jalankan dari tab **Actions** (`Run workflow`) atau:

```bash
gh workflow run oci_retry.yml --ref main         # front utama (ARM) dulu
gh workflow run oci_retry_micro.yml --ref main   # lalu front sekunder (Micro)
```

> Repo harus **public** supaya menit GitHub Actions unlimited.

---

## 🔔 Notifikasi kemenangan

Saat sebuah front **menang**, workflow otomatis:
1. Menonaktifkan dirinya sendiri (supaya tidak menembak lagi)
2. **Mengirim pesan Telegram** ke chat pemilik (bot `@oci_war_notify_bot`)
3. **Membuka GitHub Issue** berjudul `🎉 WON: ...` dan meng-assign ke pemilik repo

Telegram = push instan; Issue = catatan permanen + notifikasi GitHub.
Secrets yang dipakai: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

**Pastikan notifikasi aktif:** GitHub → avatar → **Settings** → **Notifications**, aktifkan
email untuk *Issues*, dan/atau install aplikasi GitHub mobile supaya dapat push notification.

Cek kemenangan di:
- **Issues**: https://github.com/rihanaandin/jkashd6gaw/issues (ada issue `🎉 WON` = menang)
- **Actions**: https://github.com/rihanaandin/jkashd6gaw/actions (workflow pemenang statusnya
  `completed` dan TIDAK ada run lanjutan; workflow yang kalah terus estafet)
- **OCI Console**: Compute → Instances (muncul instance baru)

---

## Setelah menang

1. Cek Console → Compute → Instances → public IP, lalu:
   ```bash
   ssh -i <private-key-kamu> ubuntu@<public-ip>
   ```
2. **PENTING — anti-reclaim:** Oracle mereklamasi instance Always Free yang idle
   (selama 7 hari: CPU p95 < 20%, network < 20%, memory < 20% untuk A1).
   Syaratnya AND — menjaga CPU saja sudah cukup.
3. Instance Micro yang menang bisa dipakai untuk menjalankan `oci_retry.py`
   sebagai front tambahan war ARM.

### Anti-idle: `helia-antiidle` (Micro, menang 20 Agu 2026)

Solusi custom di folder `instance/anti-idle/` (bukan repo pihak ketiga — hasil audit
menunjukkan repo populer hanya efektif sebagian dan sulit dilepas):

- `helia-antiidle.sh` — duty-cycle 40s sibuk (`sha256sum /dev/zero`) / 20s istirahat (~67%)
- `helia-antiidle.service` — systemd, auto-restart, **Nice=19** (prioritas terendah —
  project asli selalu menang rebutan CPU meski service lupa dimatikan)
- **Hapus 1 perintah**:
  ```bash
  sudo systemctl disable --now helia-antiidle && \
  sudo rm /etc/systemd/system/helia-antiidle.service /usr/local/bin/helia-antiidle.sh && \
  sudo systemctl daemon-reload
  ```
- Verifikasi empiris via metrik Oracle sendiri:
  ```bash
  .venv/bin/python instance/check_cpu_metric.py 6   # target: percentile(0.95) > 20%
  ```
- Catatan spesifikasi instance (RAM/disk/tipe) sengaja TIDAK ditulis di sini —
  cek OCI Console. Jangan menaruh IP publik atau OCID di repo public.

