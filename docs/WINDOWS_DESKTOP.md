# Windows Desktop Setup

ShopAI-ыг Windows laptop-д dockerized service болгож ажиллуулах
зааварчилгаа. 20-30 минутын нэг удаагийн setup, дараа нь `start.bat`
double-click хийхэд автоматаар ажилдаг.

---

## Шаардах

- **Windows 10 build 19041+** эсвэл **Windows 11**
- **CPU:** 4 core минимум (8+ recommended)
- **RAM:** 8 GB min, 16 GB recommended (Ollama-д)
- **Storage:** 15 GB free (Docker image + Ollama models)
- **Internet:** Shopify / Meta Ads / LLM API-д хандах

---

## Нэг удаагийн setup

### 1. Docker Desktop суулгах

https://docs.docker.com/desktop/install/windows-install/

- Download → install → restart
- Docker Desktop нээгээд whale icon-ийн animation зогссон эсэхийг хvлээх
- Settings → General → "Start Docker Desktop when you log in" ✓

### 2. WSL2 backend (зөвлөмж)

Docker Desktop WSL2 backend-ээр ажиллуулах нь илvv хурдан:
- Settings → General → "Use the WSL 2 based engine" ✓
- PowerShell admin-аас: `wsl --install`

### 3. ShopAI татах

```powershell
# Git суулгаагvй бол: https://git-scm.com/download/win
git clone https://github.com/batkabatka362-cmyk/shopai.git
cd shopai
```

### 4. `.env` бvрдvvлэх

```powershell
copy .env.example .env
notepad .env
```

Заавал бөглөх 2 мөр:

```
SHOPAI_SHOPIFY_URL=your-store.myshopify.com
SHOPAI_SHOPIFY_KEY=shpat_xxxxxxxxxxxxx
```

Сонголттой:

```
GROQ_API_KEY=gsk_xxx           # LLM Model 1 (free, 30 req/min)
GEMINI_API_KEY=AIza...         # LLM Model 2 (free tier)
SHOPAI_API_TOKEN=32char_random # Bearer token (auto-generated if blank)
SHOPAI_ENABLE_LIVE_EXECUTION=0 # Keep 0 until ready-for-live READY
```

### 5. Эхний start

`start.bat`-ыг **double-click** хийнэ. Cmd window нээгдэж дараах алхмыг автоматаар хийнэ:

1. Docker Desktop ажиллаж буй эсэхийг шалгана
2. `.env` файл байгаа эсэхийг шалгана
3. 4 container бvтээж асаана (~2 GB татах эхний удаад):
   - `shopai-daemon` — autonomous cycle loop
   - `shopai-api` — HTTP API (port 8080)
   - `ollama` — local LLM (Mistral / Qwen / Llama3.2)
   - `cloudflared` — public webhook tunnel
4. Tunnel URL гарч ирэх хvртэл хvлээнэ (~30s)
5. Public URL-ийг хэвлэнэ:
   ```
   SHOPAI_WEBHOOK_CALLBACK_URL=https://xxx.trycloudflare.com/api/webhook/shopify
   ```
6. Browser-оос http://localhost:8080/health нээнэ

### 6. Webhook URL-ыг хадгалах

Хэвлэгдсэн URL-ыг `.env`-д нэмэж, daemon-г restart:

```powershell
notepad .env
REM SHOPAI_WEBHOOK_CALLBACK_URL мөрийг нэмээд хадгал
docker compose up -d --force-recreate shopai-daemon
```

### 7. Ready-for-live шалгах

```powershell
docker compose exec shopai-api python cli.py ready-for-live
```

`READY` гарвал → Т1-д бэлэн.

### 8. Live execution асаах

`.env`-д `SHOPAI_ENABLE_LIVE_EXECUTION=1` болгоно + daemon restart:

```powershell
docker compose up -d --force-recreate shopai-daemon
```

---

## Өдөр тутмын ашиглалт

```powershell
start.bat                           REM Асаах (double-click)

REM Logs харах
docker compose logs -f shopai-daemon
docker compose logs -f cloudflared

REM Зогсоох
docker compose down

REM Шинэ version татаж шинэчлэх
git pull
docker compose up -d --build
```

---

## Нийтлэг асуудал

### "Cannot connect to the Docker daemon"
Docker Desktop ажиллаж байгаа эсэхийг шалгана. Tray icon whale → click → wait.

### "Port 8080 already in use"
Өөр програм 8080 port-ыг ашиглаж байна. Тохиргоо:
- `docker-compose.yml`-ын `shopai-api` хэсэгт `"8080:8080"` → `"8081:8080"` болгох
- `http://localhost:8081/health`-ээр нэвтрэх

### Cloudflared tunnel URL шинэчлэгдсэн
Cloudflared-ын free tier нь restart бvрт шинэ URL өгнө. Stable URL-д:
- Cloudflare account + Zero Trust nameamed tunnel шаардах
- `docker-compose.yml`-ын cloudflared command-ыг `tunnel run <name>` болгох

### Shopify webhooks хvрэхгvй байна
1. Tunnel URL зөв эсэхийг шалгах: `https://xxx.trycloudflare.com/api/webhook/shopify`
2. `docker compose logs shopai-api` — HMAC signature rejection гараж байгаа эсэх
3. Store admin → Settings → Notifications → Webhooks — URL нь орсон эсэхийг шалгах

### Ollama GPU ашиглах (NVIDIA card-тай бол)
`docker compose --profile gpu up -d`. NVIDIA Container Toolkit суулгах шаардлагатай
(https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

### Диск дvvрсэн
Docker images + volumes-ийг цэвэрлэх:
```powershell
docker system prune -a --volumes
```
**Анхаар:** `--volumes` нь shopai_data + ollama_models-ийг ч устгана. Backup хий эхлээд.

---

## Phase 2 (ирээдvйд) — Tray icon app

PyInstaller-аар bundle хийсэн `shopai.exe` нь:
- Tray icon-той
- Right-click → Start / Stop / View logs
- System startup-д автоматаар нээгдэх сонголттой
- Docker Desktop суулгах шаардлагагvй (Python + embedded tunnel)

Т1 live 7 хоног ажиллаж evidence бvрдсэний дараа ship хийгдэнэ.
