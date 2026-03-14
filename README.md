# 🔧 Embed Fixer Bot

自動偵測 Discord 訊息中的社交媒體連結，並回覆修復後的嵌入預覽。

靈感來源：[ermiana](https://github.com/canaria3406/ermiana) 與 [embed-fixer](https://github.com/seriaati/embed-fixer)

---

## ✨ 功能

- **自動偵測**：監聽訊息中的社交媒體連結（支援 Spoiler `||url||`）
- **兩種模式可切換**：
  - **Ermiana 模式**（預設）：回覆修復連結，並隱藏原始訊息的嵌入預覽
  - **Webhook 模式**：刪除原訊息，以原作者身份透過 Webhook 重發修復後的訊息
- **互動按鈕**：回覆訊息附有「原始連結」按鈕（預設隱藏，可透過 `/embed_fixer setting` 開啟）
- **右鍵指令**：對任意訊息右鍵 → 「🔧 修復嵌入」手動觸發
- **NSFW 過濾**：Twitter/X 和 Pixiv 的 NSFW 貼文/作品在非 NSFW 頻道不會被修復（可透過 `/embed_fixer setting` 關閉）
- **媒體擷取**：指定頻道中的 Twitter/Pixiv 連結自動下載並發送完整圖集
- **翻譯**：Twitter/X 貼文可自動翻譯（使用 FxEmbed，`/translang` 設定目標語言；預設繁體中文）
- **使用者選擇退出**：`/ignore-me` 讓使用者自行退出自動修復
- **頻道黑名單 / 白名單**：管理員可針對特定頻道停用或限定修復（白名單優先）
- **身份組白名單**：只修復擁有特定身份組的使用者連結
- **Webhook 回覆標記**：回覆 Webhook 訊息時自動 tag 原作者（以 `$` 開頭可停用）
- **單連結跳過**：在連結前加 `$` 或以 `<url>` 包覆，可讓單個連結跳過修復
- **每伺服器獨立設定**：各伺服器可分別設定啟停、模式、平台、修復服務
- **設定持久化**：設定儲存於 `configs/guild_settings.json`

---

## 📺 支援平台

| 平台 | 修復服務 | 說明 |
|------|---------|------|
| 🐦 Twitter / X | FxEmbed、BetterTwitFix | 預設 FxEmbed（fxtwitter.com） |
| 🎨 Pixiv | Phixiv | |
| 🎵 TikTok | fxTikTok | |
| 🤖 Reddit | FixReddit、vxReddit | 預設 FixReddit |
| 📸 Instagram | InstaFix、KKInstagram | 預設 InstaFix |
| 🦋 Bluesky | VixBluesky、FxEmbed | 預設 VixBluesky |
| 📺 Bilibili | fxbilibili、BiliFix | 預設 fxbilibili；失敗自動 fallback 至 BiliFix |
| 🧵 Threads | FixThreads（自架）、vxThreads | 預設 FixThreads；使用自架實例（`drhong.ddns.net:9813`） |
| 📋 PTT | fxptt | 支援 ptt.cc 及 pttweb.cc |
| 🐾 FurAffinity | xfuraffinity、fxraffinity | 預設 xfuraffinity |
| 👥 Facebook | facebed（自架）、facebed.com | 使用 [facebed](https://github.com/tonghongte/facebed)；預設自架實例；支援含外部連結卡片的貼文圖片擷取 |
| 📝 Tumblr | fxtumblr | |
| 🖼️ DeviantArt | fxdeviantart | |
| 🐉 巴哈姆特電玩資訊站 | 內建爬蟲 | 場外休憩區；設定 `BAHA_UID`/`BAHA_PASSWD` 可讀取需登入的貼文 |
| 📖 E-Hentai / ExHentai | E-Hentai API | 顯示畫廊標題、分類、評分、標籤 |
| 🌿 Misskey | Misskey API | 僅 `misskey.io` |
| 🛒 PChome 24h | PChome API | 顯示商品名稱、價格、圖片 |
| 💬 Plurk | 內建爬蟲 | |
| 📺 Bilibili 動態 | Bilibili API | `/opus/` 動態貼文 |

---

## 🚀 快速開始

### 1. 建立機器人

前往 [Discord Developer Portal](https://discord.com/developers/applications)：

1. 建立新 Application → Bot
2. 開啟以下 Intents：
   - **Message Content Intent**（必要）
   - **Server Members Intent**
   - **Presence Intent**
3. 邀請機器人時需要以下 OAuth2 Scopes 與 Permissions：
   - Scopes：`bot`、`applications.commands`
   - Bot Permissions：`Send Messages`、`Read Message History`、`Manage Messages`（用於隱藏原始嵌入）、`Manage Webhooks`（Webhook 模式必要）、`Use Application Commands`

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env，填入 DISCORD_TOKEN
```

### 3. 安裝依賴

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 4. 啟動

```bash
python main.py
```

---

## 🐳 Docker 部署

```bash
cp .env.example .env
# 編輯 .env

docker compose up -d
```

### Portainer + GHCR 部署

如需透過 GitHub Container Registry 自動建置並以 Portainer Stack 部署，請參閱：

📖 [GHCR + Portainer Stack 部署教學](docs/portainer-ghcr-deploy.md)

---

## ⚙️ 指令說明

所有設定指令需要「管理伺服器」權限。

| 指令 | 說明 |
|------|------|
| `/embed_fixer info` | 顯示目前設定（啟停、模式、所有平台狀態、頻道黑名單） |
| `/embed_fixer toggle` | 開啟或關閉整個嵌入修復器 |
| `/embed_fixer mode` | 切換 Ermiana / Webhook 模式 |
| `/embed_fixer domain` | 啟用或停用特定平台 |
| `/embed_fixer method` | 選擇特定平台使用的修復服務 |
| `/embed_fixer channel` | 將頻道加入或移出**黑名單** |
| `/embed_fixer whitelist` | 將頻道加入或移出**白名單**（白名單非空時優先於黑名單） |
| `/embed_fixer role` | 將身份組加入或移出白名單 |
| `/embed_fixer setting` | 切換各種開關（Bot 可見性、NSFW 過濾、**原始連結按鈕**（預設關閉）、Webhook 回覆標記） |
| `/embed_fixer extract` | 設定媒體擷取頻道（Twitter/Pixiv 圖集自動下載發送） |
| `/translang` | 設定 Twitter/X 翻譯目標語言（僅 FxEmbed；預設繁體中文；需管理伺服器權限） |
| `/ignore-me` | 選擇退出／重新加入自動嵌入修復（任何人皆可使用） |
| 右鍵 → `🔧 修復嵌入` | 對任意訊息手動觸發修復（忽略退出與黑名單設定） |

### 模式差異

| | Ermiana 模式 | Webhook 模式 |
|-|-------------|-------------|
| 呈現方式 | 回覆修復連結 | 刪除原訊息並以原作者身份重發 |
| 隱藏原始嵌入 | ✅（需 Manage Messages） | ✅（原訊息已刪除） |
| 保留作者資訊 | ✅ | ✅（Webhook 使用原作者名稱與頭像） |
| 所需額外權限 | Manage Messages | Manage Webhooks |
| 適合情境 | 保持頻道整潔 | 最無縫的使用體驗 |

---

## 📁 專案結構

```
embed-fixer-bot/
├── src/
│   ├── bot.py              # Bot 主類別
│   └── cogs/
│       └── embed_fixer.py  # 核心 Cog（URL 偵測、修復、指令）
├── configs/                # 伺服器設定（自動建立）
│   └── guild_settings.json
├── main.py                 # 進入點
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## 🔒 所需 Bot 權限

| 權限 | 用途 |
|------|------|
| Read Messages / View Channels | 讀取訊息 |
| Send Messages | 回覆修復連結 |
| Read Message History | 取得訊息內容 |
| Manage Messages | 隱藏原始嵌入（Ermiana 模式） |
| Manage Webhooks | 以原作者身份重發訊息（Webhook 模式） |
| Use Application Commands | 斜線指令與右鍵指令 |

> **Manage Messages** 僅在 Ermiana 模式下使用。**Manage Webhooks** 僅在 Webhook 模式下使用。若無對應權限，Bot 會靜默跳過該訊息。

---

## 🛠️ 開發說明

- **語言**：Python 3.11+
- **框架**：[disnake](https://github.com/DisnakeDev/disnake) 2.9.1
- **設定儲存**：JSON 檔案（`configs/guild_settings.json`）
- **無需資料庫**：輕量部署

### 新增平台

在 [src/cogs/embed_fixer.py](src/cogs/embed_fixer.py) 的 `DOMAINS` 列表中加入：

```python
{
    "id": "platform_id",       # 唯一識別碼
    "name": "Platform Name",   # 顯示名稱
    "emoji": "🌐",             # 顯示 Emoji
    "patterns": [              # URL 匹配正則
        r"https?://example\.com/post/\w+",
    ],
    "fix_methods": {           # 修復服務（可多個）
        "ServiceName": [
            {"old": "example.com", "new": "fxexample.com"},
        ],
    },
    "default_method": "ServiceName",
},
```
