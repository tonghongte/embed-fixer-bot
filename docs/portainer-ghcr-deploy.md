# 使用 Portainer Stack 部署教學

透過 GHCR 預建映像，在 Portainer 以 Stack 方式快速部署，無需自行建置。

---

## 前置需求

- 已安裝並執行 Portainer（v2.x 以上）的伺服器
- 伺服器上已安裝 Docker
- Discord Bot Token（[建立方式](#建立-discord-bot)）

---

## 步驟一：建立 Discord Bot

前往 [Discord Developer Portal](https://discord.com/developers/applications)：

1. **New Application** → 輸入名稱 → 左側選 **Bot**
2. **Reset Token** 取得 Token（妥善保管）
3. 開啟以下 Privileged Gateway Intents：
   - **Message Content Intent**
   - **Server Members Intent**
   - **Presence Intent**
4. 左側選 **OAuth2** → **URL Generator**，Scopes 勾選 `bot`、`applications.commands`
5. Bot Permissions 勾選：`Send Messages`、`Read Message History`、`Manage Messages`、`Use Application Commands`
6. 複製產生的連結，用瀏覽器開啟，將機器人邀請至伺服器

---

## 步驟二：在 Portainer 建立 Stack

1. 登入 Portainer → 選擇 Environment → **Stacks** → **Add stack**
2. **Name**：填入 `embed-fixer-bot`（或任意名稱）
3. **Build method** 選 **Web editor**，貼入以下內容：

```yaml
services:
  embed-fixer-bot:
    image: ghcr.io/tonghongte/embed-fixer-bot:latest
    container_name: embed-fixer-bot
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=your_discord_token_here
      # 選填
      # - OWNER_ID=123456789012345678
      # - PREFIX=+
      # 巴哈姆特（選填，用於顯示需要登入才能瀏覽的場外貼文）
      # - BAHA_UID=your_bahamut_uid
      # - BAHA_PASSWD=your_bahamut_password
    volumes:
      - embed_fixer_configs:/app/configs
      - embed_fixer_data:/app/data
      - embed_fixer_log:/app/logs

volumes:
  embed_fixer_configs:
  embed_fixer_data:
  embed_fixer_log:
```

4. 將 `DISCORD_TOKEN` 的值替換為你的 Bot Token
5. 點選 **Deploy the stack**

---

## 資料持久化說明

| Volume | 容器路徑 | 說明 |
|--------|----------|------|
| `embed_fixer_configs` | `/app/configs` | 伺服器設定（`guild_settings.json`） |
| `embed_fixer_data` | `/app/data` | 其他資料 |
| `embed_fixer_log` | `/app/logs` | 日誌檔案（`bot.log`） |

---

## 更新至最新版本

Portainer → **Stacks** → 選擇 stack → **Pull and redeploy**

---

## 常見問題

**Q：Container 啟動後立刻停止**
→ Portainer → Container → **Logs** 查看原因。最常見為 `DISCORD_TOKEN` 未填或錯誤。

**Q：重啟後設定消失**
→ 確認 Stack compose 中的 volumes 區塊完整保留。

**Q：機器人無法隱藏原始嵌入**
→ 確認機器人在該頻道有 **Manage Messages** 權限，或改用簡單模式（`/embed_fixer mode`）。

**Q：巴哈姆特場外貼文無法顯示**
→ 需要填入 `BAHA_UID` 與 `BAHA_PASSWD` 環境變數。未填時，需要登入才能瀏覽的貼文將無法產生嵌入。
