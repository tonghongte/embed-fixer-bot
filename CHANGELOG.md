# Changelog

## [Unreleased]

### 新增
- **Bilibili fallback**：Bilibili 影片連結預設使用 fxbilibili，若回應失敗（5xx 或連線錯誤）自動切換至 BiliFix（vxbilibili）
- **PTT pttweb.cc 支援**：pttweb.cc 連結在轉換時自動補上 `.html` 後綴，確保 fxptt 可正確解析

### 變更
- **連結顯示格式**：Ermiana 模式與 Webhook 模式的回覆連結改以 `[連結](url)` masked link 格式呈現，版面更簡潔
- **UI 簡化**：移除「切換模式」與「🗑️ 刪除」互動按鈕
- **原始連結按鈕預設關閉**：`show_original_link` 預設為 `False`，可透過 `/embed_fixer setting` 開啟
- **Twitter/X**：x.com 連結統一轉換至 `fxtwitter.com`（原為 `fixupx.com`）
- **Bilibili 預設服務**：由 BiliFix 改為 fxbilibili
- **Webhook fallback**：當頻道無法建立 Webhook（例如缺少 `Manage Webhooks` 權限）時，自動降級為 Ermiana 模式並記錄警告
- **Probe 方法**：fallback 探測請求由 HEAD 改為 GET（`allow_redirects=False`），回應門檻放寬至 < 500，避免 HEAD 不支援時誤觸 fallback
- **日誌路徑**：bot 日誌改存於 `logs/bot.log`（避免 Docker volume 掛載衝突）

### 修復
- **PChome 24h 中文顯示**：修正商品說明（slogan）及品牌欄位的 `\uXXXX` Unicode escape 未解碼問題，改用 `json.loads` 正確解析

### 移除
- **Twitch Clips**：移除平台支援（fxtwitch）
- **Iwara**：移除平台支援（fxiwara）
- **Weibo**：移除平台支援（WeiboEZ）
