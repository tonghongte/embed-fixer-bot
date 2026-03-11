"""
嵌入修復器 (Embed Fixer) Cog

自動偵測訊息中的社交媒體連結，並回覆修復後的嵌入預覽。

支援兩種呈現模式（可切換）：
  - Ermiana 模式（預設）：回覆修復連結 + 隱藏原始嵌入
  - Webhook 模式：刪除原訊息並以原作者身份透過 Webhook 重發

支援右鍵指令：對任意訊息執行「🔧 修復嵌入」。

支援平台：
  Twitter/X · Pixiv · TikTok · Reddit · Instagram · Bluesky
  Bilibili · Threads · PTT · FurAffinity · Twitch Clips
  Facebook · Tumblr · DeviantArt · Iwara
  Weibo · 巴哈姆特 · E-Hentai/ExHentai · Misskey
  PChome 24h · Plurk · Bilibili 動態
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import aiohttp
import disnake
from bs4 import BeautifulSoup
from disnake import ApplicationCommandInteraction, MessageCommandInteraction
from disnake.ext import commands
from disnake.ext.commands import Cog

from src.bot import Bot

# ══════════════════════════════════════════════
#  設定管理
# ══════════════════════════════════════════════

SETTINGS_FILE = Path("configs/guild_settings.json")


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _guild_settings(data: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in data:
        data[key] = {
            "enabled": True,
            "mode": "ermiana",        # "ermiana" | "webhook"
            "disabled_domains": [],   # 停用的 domain id 列表
            "fix_methods": {},        # {domain_id: method_name}
            "ignored_users": [],      # 選擇退出的使用者 ID 列表
            "blacklist_channels": [], # 停用修復的頻道 ID 列表（黑名單）
            "whitelist_channels": [], # 只允許修復的頻道 ID 列表（白名單，優先於黑名單）
            "whitelist_roles": [],    # 只修復擁有這些身份組的使用者（空＝全部）
            "fix_bots": False,        # 是否修復機器人發送的連結
            "nsfw_filter": True,      # 是否在非 NSFW 頻道過濾 NSFW 貼文
            "show_original_link": True,  # 是否顯示「原始連結」按鈕
            "webhook_reply": True,    # 回覆 Webhook 訊息時是否標記原始作者
            "extract_channels": [],   # 媒體擷取頻道列表（Twitter/Pixiv）
            "translate_lang": "zh-TW", # Twitter 翻譯語言（僅 FxEmbed）
        }
    return data[key]


# ══════════════════════════════════════════════
#  巴哈姆特 Token 管理
# ══════════════════════════════════════════════

class _BahaAuth:
    """巴哈姆特登入 Cookie 管理（BAHAENUR / BAHARUNE）。"""
    enur: Optional[str] = None
    rune: Optional[str] = None

    @classmethod
    async def refresh(cls, session: aiohttp.ClientSession) -> bool:
        uid = os.getenv("BAHA_UID", "")
        passwd = os.getenv("BAHA_PASSWD", "")
        if not uid or not passwd:
            return False
        try:
            async with session.post(
                "https://api.gamer.com.tw/mobile_app/user/v3/do_login.php",
                data=f"uid={uid}&passwd={passwd}&vcode=9487",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": "ckAPP_VCODE=9487",
                },
                timeout=aiohttp.ClientTimeout(total=5),
                allow_redirects=False,
            ) as resp:
                new_enur = resp.cookies.get("BAHAENUR")
                new_rune = resp.cookies.get("BAHARUNE")
                if new_enur and new_rune:
                    cls.enur = new_enur.value
                    cls.rune = new_rune.value
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def cookie_header(cls) -> dict:
        if cls.enur and cls.rune:
            return {"Cookie": f"BAHAENUR={cls.enur}; BAHARUNE={cls.rune};"}
        return {}


# ══════════════════════════════════════════════
#  Embed Handlers（API / 爬蟲建立 Discord Embed）
# ══════════════════════════════════════════════

async def _build_bahamut_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """爬取巴哈姆特場外論壇貼文 OG 資訊，建立 Embed。"""
    async def _fetch(headers: dict) -> Optional[disnake.Embed]:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("meta", property="og:title")
            title = title_tag.get("content") if title_tag else None
            if not title or title == "巴哈姆特電玩資訊站 - 系統訊息":
                return None
            desc_tag = soup.find("meta", property="og:description")
            img_tag = soup.find("meta", property="og:image")
            embed = disnake.Embed(
                title=title[:256],
                url=url,
                description=(desc_tag.get("content", "")[:4080] if desc_tag else ""),
                color=0x17cc8c,
            )
            if img_tag and img_tag.get("content"):
                embed.set_image(url=img_tag["content"])
            embed.set_footer(text="巴哈姆特電玩資訊站")
            return embed
        except Exception:
            return None

    result = await _fetch(_BahaAuth.cookie_header())
    if result is not None:
        return result
    # Token 可能過期，嘗試刷新後重試
    if os.getenv("BAHA_UID"):
        if await _BahaAuth.refresh(session):
            return await _fetch(_BahaAuth.cookie_header())
    return None


async def _build_ehentai_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """呼叫 E-Hentai API 取得畫廊資料，建立 Embed。"""
    m = re.search(r"e[x-]hentai\.org/g/(\d+)/([0-9a-z]+)", url)
    if not m:
        return None
    gid, token = int(m.group(1)), m.group(2)

    tag_tr = {
        "artist": "繪師", "character": "角色", "cosplayer": "Coser",
        "female": "女性", "group": "社團", "language": "語言",
        "male": "男性", "mixed": "混合", "other": "其他",
        "parody": "原作", "reclass": "重新分類", "temp": "臨時",
    }

    async def _call_api() -> Optional[dict]:
        try:
            async with session.post(
                "https://api.e-hentai.org/api.php",
                json={"method": "gdata", "gidlist": [[gid, token]], "namespace": 1},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json(content_type=None)
            meta = data.get("gmetadata", [])
            return meta[0] if meta else None
        except Exception:
            return None

    import asyncio as _asyncio
    metadata = await _call_api()
    if metadata is None:
        # E-Hentai API 有速率限制，等待下一個 5 秒視窗後重試
        await _asyncio.sleep(5)
        metadata = await _call_api()
    if metadata is None:
        return None

    tag_map: dict[str, list[str]] = {}
    for raw in metadata.get("tags", []):
        parts = raw.split(":", 1)
        if len(parts) == 2:
            tag_map.setdefault(parts[0], []).append(parts[1])

    tag_lines = [f"{tag_tr.get(t, t)}: {', '.join(vs)}" for t, vs in tag_map.items()]

    embed = disnake.Embed(
        title=metadata.get("title", "")[:256],
        url=f"https://e-hentai.org/g/{gid}/{token}",
        description=metadata.get("title_jpn", "")[:4080],
        color=0xe95959,
    )
    if metadata.get("thumb"):
        embed.set_image(url=metadata["thumb"])
    embed.add_field(name="類別", value=metadata.get("category", "N/A"), inline=True)
    embed.add_field(name="評分", value=str(metadata.get("rating", "N/A")), inline=True)
    embed.add_field(name="上傳者", value=metadata.get("uploader", "N/A"), inline=True)
    if tag_lines:
        embed.add_field(name="標籤", value="\n".join(tag_lines)[:1024], inline=False)
    embed.set_footer(text="E-Hentai")
    posted = metadata.get("posted")
    if posted:
        embed.timestamp = datetime.fromtimestamp(int(posted), tz=timezone.utc)
    return embed


async def _build_misskey_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """呼叫 Misskey API 取得 Note 資料，建立 Embed。"""
    m = re.search(r"misskey\.io/notes/([a-zA-Z0-9]+)", url)
    if not m:
        return None
    note_id = m.group(1)
    try:
        async with session.post(
            "https://misskey.io/api/notes/show",
            json={"noteId": note_id},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            note = await resp.json(content_type=None)

        images = [f for f in note.get("files", []) if f.get("type", "").startswith("image/")]
        total_reactions = sum(note.get("reactions", {}).values())
        stats = f"💬{note.get('repliesCount', 0)} 🔁{note.get('renoteCount', 0)} ❤️{total_reactions}"

        user = note.get("user", {})
        embed = disnake.Embed(
            title=(user.get("name") or user.get("username", ""))[:256],
            url=f"https://misskey.io/notes/{note_id}",
            description=(note.get("text") or "")[:4080],
            color=0x99c539,
        )
        embed.set_author(
            name=f"@{user.get('username', '')}",
            icon_url=user.get("avatarUrl") or "",
        )
        if images:
            embed.set_image(url=images[0]["url"])
        embed.set_footer(text=stats)
        if note.get("createdAt"):
            try:
                embed.timestamp = datetime.fromisoformat(note["createdAt"].replace("Z", "+00:00"))
            except ValueError:
                pass
        return embed
    except Exception:
        return None


async def _build_pchome_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """呼叫 PChome API 取得商品資料，建立 Embed。"""
    m = re.search(r"24h\.pchome\.com\.tw/prod/([A-Z0-9]+-[A-Z0-9]+)", url)
    if not m:
        return None
    product_id = m.group(1)
    try:
        async with session.get(
            f"https://ecapi-cdn.pchome.com.tw/ecshop/prodapi/v2/prod/{product_id}"
            f"&fields=Name,Nick,Price,Pic&_callback=jsonp_prod",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            text1 = await resp.text()

        nick_m = re.search(r'"Nick":"(.*?)",', text1)
        price_m = re.search(r'"P":(\d+)', text1)
        pic_m = re.search(r'"B":"(.*?)",', text1)
        if not nick_m or not price_m or not pic_m:
            return None

        nick = BeautifulSoup(nick_m.group(1), "html.parser").get_text()
        price = price_m.group(1)
        pic_url = "https://img.pchome.com.tw/cs" + pic_m.group(1).replace("\\\\", "").replace("\\", "")

        brand, slogan = "", ""
        try:
            async with session.get(
                f"https://ecapi-cdn.pchome.com.tw/cdn/ecshop/prodapi/v2/prod/{product_id}"
                f"/desc&fields=Meta,SloganInfo&_callback=jsonp_desc",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp2:
                text2 = await resp2.text()
            brand_m = re.search(r'BrandNames":\[(.*?)\]', text2)
            slogan_m = re.search(r'SloganInfo":\[(.*?)\]', text2)
            if brand_m:
                brand = brand_m.group(1).replace('","', "_").strip('"')
            if slogan_m:
                slogan = slogan_m.group(1).replace('","', "\n").strip('"')
        except Exception:
            pass

        embed = disnake.Embed(
            title=nick[:256],
            url=f"https://24h.pchome.com.tw/prod/{product_id}",
            description=slogan[:4080] if slogan else "",
            color=0xff6600,
        )
        embed.set_image(url=pic_url)
        embed.add_field(name="價格", value=f"NT$ {price}", inline=True)
        embed.add_field(name="品牌", value=brand or "無", inline=True)
        embed.set_footer(text="PChome 24h購物")
        return embed
    except Exception:
        return None


async def _build_plurk_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """爬取 Plurk 貼文內容，建立 Embed。"""
    m = re.search(r"plurk\.com/(?:m/)?p/([a-zA-Z0-9]+)", url)
    if not m:
        return None
    plurk_id = m.group(1)
    try:
        async with session.get(
            f"https://www.plurk.com/p/{plurk_id}",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        script_text = " ".join(s.string or "" for s in soup.find_all("script") if s.string)

        replurk_m = re.search(r'"replurkers_count": (\d+)', script_text)
        fav_m = re.search(r'"favorite_count": (\d+)', script_text)
        resp_m = re.search(r'"response_count": (\d+)', script_text)

        name_tag = soup.find(class_="name")
        name = name_tag.get_text(strip=True) if name_tag else "Plurk 使用者"

        text_tag = soup.find(class_="text_holder")
        if text_tag:
            for br in text_tag.find_all("br"):
                br.replace_with("\n")
            content = text_tag.get_text()
        else:
            content = ""

        raw_idx = script_text.find("content_raw")
        pics = re.findall(r"https://images\.plurk\.com/[^\\\"\s]+", script_text[raw_idx:]) if raw_idx >= 0 else []

        user_id_m = re.search(r'"page_user":\s*\{"id":\s*(\d+)', script_text)
        avatar_m = re.search(r'"avatar":\s*(\d+)', script_text)
        nick_m = re.search(r'"nick_name":\s*"([^"]+)"', script_text)

        user_id = user_id_m.group(1) if user_id_m else "17527487"
        avatar = avatar_m.group(1) if avatar_m else "79721750"
        nick = nick_m.group(1) if nick_m else "plurkuser"

        stats = (
            f"💬{resp_m.group(1) if resp_m else 0} "
            f"🔁{replurk_m.group(1) if replurk_m else 0} "
            f"❤️{fav_m.group(1) if fav_m else 0}"
        )

        embed = disnake.Embed(
            title=name[:256],
            url=f"https://www.plurk.com/p/{plurk_id}",
            description=content[:4080],
            color=0xefa54c,
        )
        embed.set_author(
            name=f"@{nick}",
            icon_url=f"https://avatars.plurk.com/{user_id}-medium{avatar}.gif",
        )
        if pics:
            embed.set_image(url=pics[0])
        embed.set_footer(text=stats)
        return embed
    except Exception:
        return None


async def _build_bilibili_opus_embed(url: str, session: aiohttp.ClientSession) -> Optional[disnake.Embed]:
    """呼叫 Bilibili API 取得動態貼文資料，建立 Embed。"""
    m = re.search(r"bilibili\.com/opus/(\d+)", url)
    if not m:
        return None
    opus_id = m.group(1)
    try:
        async with session.get(
            f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={opus_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0",
                "Accept-Language": "zh-TW,zh;q=0.8",
            },
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            data = await resp.json(content_type=None)

        if data.get("code") != 0 or not data.get("data"):
            return None

        item = data["data"]["item"]
        modules = item.get("modules", {})
        author = modules.get("module_author", {})
        dynamic = modules.get("module_dynamic", {})
        dynamic_type = item.get("type", "")

        embed = disnake.Embed(
            title=(author.get("name") or "Bilibili")[:256],
            url=f"https://www.bilibili.com/opus/{opus_id}",
            color=0x00aeec,
        )
        embed.set_author(
            name=f"UID {author.get('mid', '')}",
            icon_url=author.get("face") or "",
        )

        if dynamic_type == "DYNAMIC_TYPE_DRAW":
            desc = dynamic.get("desc", {}).get("text", "")
            pics = dynamic.get("major", {}).get("draw", {}).get("items", [])
            embed.description = desc[:4080]
            if pics:
                embed.set_image(url=pics[0]["src"])
        elif dynamic_type == "DYNAMIC_TYPE_ARTICLE":
            article = dynamic.get("major", {}).get("article", {})
            embed.description = (article.get("title") or "")[:4080]
            covers = article.get("covers", [])
            if covers:
                embed.set_image(url=covers[0])
        else:
            embed.description = (dynamic.get("desc", {}).get("text") or "")[:4080]

        embed.set_footer(text="Bilibili 動態")
        return embed
    except Exception:
        return None


# ══════════════════════════════════════════════
#  平台資訊擷取（NSFW 檢查 / 媒體擷取）
# ══════════════════════════════════════════════

_MAX_MEDIA_FILESIZE = 10 * 1024 * 1024  # 10 MB


async def _fetch_twitter_post(url: str, session: aiohttp.ClientSession) -> Optional[dict]:
    """呼叫 fxtwitter API 取得推文資訊（possibly_sensitive, media.all[]）。"""
    m = re.search(r"(?:twitter|x)\.com/([A-Za-z0-9_]+)/status/(\d+)", url)
    if not m:
        return None
    handle, tweet_id = m.group(1), m.group(2)
    try:
        async with session.get(
            f"https://api.fxtwitter.com/{handle}/status/{tweet_id}",
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
        return data.get("tweet")
    except Exception:
        return None


async def _fetch_pixiv_artwork(url: str, session: aiohttp.ClientSession) -> Optional[dict]:
    """呼叫 phixiv API 取得 Pixiv 作品資訊（tags, image_proxy_urls）。"""
    m = re.search(r"pixiv\.net(?:/[a-zA-Z]+)?/artworks/(\d+)", url)
    if not m:
        return None
    artwork_id = m.group(1)
    try:
        async with session.get(
            f"https://phixiv.net/api/info?id={artwork_id}",
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except Exception:
        return None


async def _download_as_files(
    urls: list[str],
    session: aiohttp.ClientSession,
    *,
    spoiler: bool = False,
) -> list[disnake.File]:
    """下載媒體 URL，回傳 discord.File 列表（自動跳過超出 10 MB 的檔案）。"""
    import io
    files: list[disnake.File] = []
    for url in urls[:10]:  # Discord 每則訊息最多 10 個附件
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.content_length and resp.content_length > _MAX_MEDIA_FILESIZE:
                    continue
                data = await resp.read()
                if len(data) > _MAX_MEDIA_FILESIZE:
                    continue
            parsed = urlparse(url)
            filename = parsed.path.split("/")[-1] or "media"
            if "." not in filename:
                filename += ".jpg"
            if spoiler:
                filename = f"SPOILER_{filename}"
            files.append(disnake.File(io.BytesIO(data), filename=filename))
        except Exception:
            continue
    return files


# ══════════════════════════════════════════════
#  域名與修復服務定義
# ══════════════════════════════════════════════

DOMAINS: list[dict] = [
    {
        "id": "twitter",
        "name": "Twitter / X",
        "emoji": "🐦",
        "patterns": [
            r"https?://(www\.)?twitter\.com/[A-Za-z0-9_]{1,15}/status/\d+",
            r"https?://(www\.)?x\.com/[A-Za-z0-9_]{1,15}/status/\d+",
        ],
        "fix_methods": {
            "FxEmbed": [
                {"old": "twitter.com", "new": "fxtwitter.com"},
                {"old": "x.com",       "new": "fixupx.com"},
            ],
            "BetterTwitFix": [
                {"old": "twitter.com", "new": "vxtwitter.com"},
                {"old": "x.com",       "new": "fixvx.com"},
            ],
        },
        "default_method": "FxEmbed",
    },
    {
        "id": "pixiv",
        "name": "Pixiv",
        "emoji": "🎨",
        "patterns": [
            r"https?://(www\.)?pixiv\.net(/[a-zA-Z]+)?/artworks/\d+",
        ],
        "fix_methods": {
            "Phixiv": [
                {"old": "pixiv.net", "new": "phixiv.net"},
            ],
        },
        "default_method": "Phixiv",
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "emoji": "🎵",
        "patterns": [
            r"https?://(www\.)?tiktok\.com/(t/\w+|@[\w.]+/video/\d+)",
            r"https?://vm\.tiktok\.com/\w+",
            r"https?://vt\.tiktok\.com/\w+",
        ],
        "fix_methods": {
            "fxTikTok": [
                {"old": "tiktok.com",    "new": "tnktok.com"},
                {"old": "vm.tiktok.com", "new": "vm.tnktok.com"},
                {"old": "vt.tiktok.com", "new": "vt.tnktok.com"},
            ],
        },
        "default_method": "fxTikTok",
    },
    {
        "id": "reddit",
        "name": "Reddit",
        "emoji": "🤖",
        "patterns": [
            r"https?://(www\.|old\.)?reddit\.com/r/\w+/comments/\w+/\w+",
            r"https?://(www\.|old\.)?reddit\.com/r/\w+/s/\w+",
        ],
        "fix_methods": {
            "FixReddit": [
                {"old": "reddit.com", "new": "fxreddit.seria.moe"},
            ],
            "vxReddit": [
                {"old": "reddit.com", "new": "vxreddit.com"},
            ],
        },
        "default_method": "FixReddit",
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "emoji": "📸",
        "patterns": [
            r"https?://(www\.)?instagram\.com/(p|reels?)/[\w-]+",
            r"https?://(www\.)?instagram\.com/[\w.]+/(p|reels?)/[\w-]+",
        ],
        "fix_methods": {
            "InstaFix": [
                {"old": "instagram.com", "new": "eeinstagram.com"},
            ],
            "KKInstagram": [
                {"old": "instagram.com", "new": "kkinstagram.com"},
            ],
        },
        "default_method": "InstaFix",
    },
    {
        "id": "bluesky",
        "name": "Bluesky",
        "emoji": "🦋",
        "patterns": [
            r"https?://(www\.)?bsky\.app/profile/[\w.-]+/post/\w+",
        ],
        "fix_methods": {
            "VixBluesky": [
                {"old": "bsky.app", "new": "bskx.app"},
            ],
            "FxEmbed": [
                {"old": "bsky.app", "new": "fxbsky.app"},
            ],
        },
        "default_method": "VixBluesky",
    },
    {
        "id": "bilibili",
        "name": "Bilibili",
        "emoji": "📺",
        "patterns": [
            r"https?://(www\.|m\.)?bilibili\.com/video/\w+",
            r"https?://(www\.)?b23\.tv/\w+",
        ],
        "fix_methods": {
            "fxbilibili": [
                {"old": "bilibili.com", "new": "fxbilibili.seria.moe"},
                {"old": "b23.tv",       "new": "fxbilibili.seria.moe/b23"},
            ],
            "BiliFix": [
                {"old": "bilibili.com", "new": "vxbilibili.com"},
                {"old": "b23.tv",       "new": "vxb23.tv"},
            ],
        },
        "default_method": "fxbilibili",
        "fallback_method": "BiliFix",
    },
    {
        "id": "threads",
        "name": "Threads",
        "emoji": "🧵",
        "patterns": [
            r"https?://(www\.)?threads\.(net|com)/@[\w.]+(/post/\w+)?",
        ],
        "fix_methods": {
            "FixThreads": [
                {"old": "threads.net", "new": "fixthreads.seria.moe"},
                {"old": "threads.com", "new": "fixthreads.seria.moe"},
            ],
            "vxThreads": [
                {"old": "threads.net", "new": "vxthreads.net"},
                {"old": "threads.com", "new": "vxthreads.net"},
            ],
        },
        "default_method": "FixThreads",
    },
    {
        "id": "ptt",
        "name": "PTT",
        "emoji": "📋",
        "patterns": [
            r"https?://(www\.)?ptt\.cc/bbs/[A-Za-z0-9_]+/M\.\d+\.A\.[A-Z0-9]+\.html",
        ],
        "fix_methods": {
            "fxptt": [
                {"old": "ptt.cc", "new": "fxptt.seria.moe"},
            ],
        },
        "default_method": "fxptt",
    },
    {
        "id": "furaffinity",
        "name": "FurAffinity",
        "emoji": "🐾",
        "patterns": [
            r"https?://(www\.)?furaffinity\.net/view/\d+",
        ],
        "fix_methods": {
            "xfuraffinity": [
                {"old": "furaffinity.net", "new": "xfuraffinity.net"},
            ],
            "fxraffinity": [
                {"old": "furaffinity.net", "new": "fxraffinity.net"},
            ],
        },
        "default_method": "xfuraffinity",
    },
    {
        "id": "twitch",
        "name": "Twitch Clips",
        "emoji": "🎮",
        "patterns": [
            r"https?://clips\.twitch\.tv/\w+",
            r"https?://m\.twitch\.tv/clip/\w+",
            r"https?://(www\.)?twitch\.tv/\w+/clip/\w+",
        ],
        "fix_methods": {
            "fxtwitch": [
                {"old": "clips.twitch.tv", "new": "fxtwitch.seria.moe/clip"},
                {"old": "m.twitch.tv",     "new": "fxtwitch.seria.moe"},
                {"old": "twitch.tv",       "new": "fxtwitch.seria.moe"},
            ],
        },
        "default_method": "fxtwitch",
    },
    {
        "id": "facebook",
        "name": "Facebook",
        "emoji": "👥",
        "patterns": [
            r"https?://(www\.)?facebook\.com/share/[rv]/\w+",
            r"https?://(www\.)?facebook\.com/reel/\d+",
        ],
        "fix_methods": {
            "facebed": [
                {"old": "facebook.com", "new": "facebed.com"},
            ],
        },
        "default_method": "facebed",
    },
    {
        "id": "tumblr",
        "name": "Tumblr",
        "emoji": "📝",
        "patterns": [
            r"https?://(www\.)?tumblr\.com/[a-zA-Z0-9_-]+/\d+",
        ],
        "fix_methods": {
            "fxtumblr": [
                {"old": "tumblr.com", "new": "tpmblr.com"},
            ],
        },
        "default_method": "fxtumblr",
    },
    {
        "id": "deviantart",
        "name": "DeviantArt",
        "emoji": "🖼️",
        "patterns": [
            r"https?://(www\.)?deviantart\.com/[\w.-]+/art/[\w.-]+-\d+",
        ],
        "fix_methods": {
            "fxdeviantart": [
                {"old": "deviantart.com", "new": "fixdeviantart.com"},
            ],
        },
        "default_method": "fxdeviantart",
    },
    {
        "id": "iwara",
        "name": "Iwara",
        "emoji": "🎬",
        "patterns": [
            r"https?://(www\.)?iwara\.tv/video/\w+/\w+",
        ],
        "fix_methods": {
            "fxiwara": [
                {"old": "iwara.tv", "new": "fxiwara.seria.moe"},
            ],
        },
        "default_method": "fxiwara",
    },
    # ── 以下為 API / 爬蟲類平台 ──────────────────
    {
        "id": "weibo",
        "name": "Weibo",
        "emoji": "📱",
        "patterns": [
            r"https?://m\.weibo\.cn/detail/\d+",
        ],
        "fix_methods": {
            "WeiboEZ": [
                {"old": "m.weibo.cn", "new": "weiboez.com"},
            ],
        },
        "default_method": "WeiboEZ",
    },
    {
        "id": "bahamut",
        "name": "巴哈姆特電玩資訊站",
        "emoji": "🐉",
        "patterns": [
            r"https?://(forum\.gamer\.com\.tw|m\.gamer\.com\.tw)/(?:forum/)?(?:C|Co)\.php\?bsn=60076&(?:snA|sn)=\d+",
        ],
        "preserve_query": True,
        "embed_handler": _build_bahamut_embed,
    },
    {
        "id": "ehentai",
        "name": "E-Hentai / ExHentai",
        "emoji": "📖",
        "patterns": [
            r"https?://e[x-]hentai\.org/g/\d+/[0-9a-z]+",
        ],
        "embed_handler": _build_ehentai_embed,
    },
    {
        "id": "misskey",
        "name": "Misskey",
        "emoji": "🌿",
        "patterns": [
            r"https?://misskey\.io/notes/[a-zA-Z0-9]+",
        ],
        "embed_handler": _build_misskey_embed,
    },
    {
        "id": "pchome",
        "name": "PChome 24h",
        "emoji": "🛒",
        "patterns": [
            r"https?://24h\.pchome\.com\.tw/prod/[A-Z0-9]+-[A-Z0-9]+",
        ],
        "embed_handler": _build_pchome_embed,
    },
    {
        "id": "plurk",
        "name": "Plurk",
        "emoji": "💬",
        "patterns": [
            r"https?://(www\.)?plurk\.com/(?:m/)?p/[a-zA-Z0-9]+",
        ],
        "embed_handler": _build_plurk_embed,
    },
    {
        "id": "bilibili_opus",
        "name": "Bilibili 動態",
        "emoji": "📺",
        "patterns": [
            r"https?://(www\.)?bilibili\.com/opus/\d+",
        ],
        "embed_handler": _build_bilibili_opus_embed,
    },
]

# 快速 id → config 查找
_DOMAIN_MAP: dict[str, dict] = {d["id"]: d for d in DOMAINS}

# 所有平台 choices（供 /embed_fixer domain 使用）
_DOMAIN_CHOICES: dict[str, str] = {
    f"{d['emoji']} {d['name']}": d["id"] for d in DOMAINS
}

# 僅有多個修復服務的平台（供 /embed_fixer method 使用）
_METHOD_DOMAIN_CHOICES: dict[str, str] = {
    f"{d['emoji']} {d['name']}": d["id"]
    for d in DOMAINS
    if len(d.get("fix_methods", {})) > 1
}


# ══════════════════════════════════════════════
#  URL 工具
# ══════════════════════════════════════════════

def extract_urls(text: str) -> list[tuple[str, bool]]:
    """
    從文字中擷取 URL，回傳 (url, is_spoilered) 清單。
    - 跳過以 <url> 包覆的連結（Discord 不自動嵌入）
    - 正確處理 ||spoiler|| 包覆的連結
    """
    spoiler_pat = r"\|\|(https?://[^\s|]+)\|\|"
    regular_pat = r"(?<!\$)(?<!<)(https?://[^\s>]+)(?!>)"

    spoiler_urls = [(m, True) for m in re.findall(spoiler_pat, text)]
    cleaned = re.sub(spoiler_pat, "", text)
    regular_urls = [(m, False) for m in re.findall(regular_pat, cleaned)]

    return spoiler_urls + regular_urls


def _strip_query(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, "", p.fragment))


def _replace_domain(url: str, old: str, new: str) -> str:
    p = urlparse(url)
    if p.netloc == old or p.netloc.endswith(f".{old}"):
        return urlunparse(p._replace(netloc=new))
    return url


def _apply_fix(url: str, rules: list[dict]) -> Optional[str]:
    """依序套用規則，回傳首個成功修復的 URL；無匹配則回傳 None。"""
    for rule in rules:
        fixed = _replace_domain(url, rule["old"], rule["new"])
        if fixed != url:
            return fixed
    return None


def _match_domain(url: str) -> Optional[tuple[dict, str]]:
    """比對 URL 並回傳 (domain_config, match_url)；無匹配則回傳 None。"""
    clean = _strip_query(url)
    for domain in DOMAINS:
        # preserve_query=True 的平台（如巴哈），保留查詢參數進行比對與回傳
        test_url = url if domain.get("preserve_query") else clean
        for pat in domain["patterns"]:
            if re.match(pat, test_url, re.IGNORECASE):
                return domain, test_url
    return None


# ══════════════════════════════════════════════
#  UI 元件
# ══════════════════════════════════════════════

class FixReplyView(disnake.ui.View):
    """修復回覆的互動元件：[原始連結]"""

    def __init__(
        self,
        author_id: int,
        original_url: str,
        cog: "EmbedFixerCog",
        guild_id: int,
        show_original_link: bool = True,
    ):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.cog = cog
        self.guild_id = guild_id
        self.message: Optional[disnake.Message] = None

        # 原始連結按鈕（Link 型不能放 callback）
        if show_original_link:
            self.add_item(disnake.ui.Button(
                label="原始連結",
                url=original_url,
                style=disnake.ButtonStyle.link,
                row=0,
            ))

    async def on_timeout(self):
        """超時後停用互動按鈕（保留連結按鈕）。"""
        for child in self.children:
            if isinstance(child, disnake.ui.Button) and not child.url:
                child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class MethodSelectView(disnake.ui.View):
    """修復服務選擇 View（下拉選單）。"""

    def __init__(self, cog: "EmbedFixerCog", gs: dict, domain: dict, current: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.gs = gs
        self.domain = domain

        options = [
            disnake.SelectOption(
                label=name,
                value=name,
                default=(name == current),
                description="✓ 目前使用" if name == current else None,
            )
            for name in domain["fix_methods"]
        ]
        select = disnake.ui.StringSelect(placeholder="選擇修復服務", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: disnake.MessageInteraction):
        method = interaction.data["values"][0]
        self.gs.setdefault("fix_methods", {})[self.domain["id"]] = method
        self.cog._save()
        d = self.domain
        await interaction.response.edit_message(
            embed=disnake.Embed(
                title=f"{d['emoji']} {d['name']} 修復服務",
                description=f"已切換至 **{method}**",
                color=0x57F287,
            ),
            view=None,
        )


# ══════════════════════════════════════════════
#  主 Cog
# ══════════════════════════════════════════════

class EmbedFixerCog(Cog):
    """嵌入修復器：自動修復社交媒體連結的嵌入預覽。"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.logger = logging.getLogger("embed_fixer")
        self._data = _load_settings()
        self._session: Optional[aiohttp.ClientSession] = None
        self._webhooks: dict[int, disnake.Webhook] = {}

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def cog_unload(self):
        if self._session and not self._session.closed:
            self.bot.loop.create_task(self._session.close())

    async def _get_or_create_webhook(
        self, channel: disnake.TextChannel
    ) -> Optional[disnake.Webhook]:
        """取得或建立頻道的 Webhook（快取於 self._webhooks）。"""
        cached = self._webhooks.get(channel.id)
        if cached:
            return cached
        try:
            for wh in await channel.webhooks():
                if wh.user and wh.user.id == self.bot.user.id:
                    self._webhooks[channel.id] = wh
                    return wh
            wh = await channel.create_webhook(name="Embed Fixer")
            self._webhooks[channel.id] = wh
            return wh
        except (disnake.Forbidden, disnake.HTTPException):
            return None

    # ── 媒體擷取輔助 ─────────────────────────────

    async def _do_media_extract(
        self,
        channel: disnake.abc.Messageable,
        domain_id: str,
        platform_info: Optional[dict],
        *,
        is_spoilered: bool,
        is_nsfw_ch: bool,
    ) -> None:
        """下載並發送 Twitter/Pixiv 媒體至頻道。"""
        if platform_info is None:
            return

        media_urls: list[str] = []
        if domain_id == "twitter":
            media_data = platform_info.get("media", {})
            if isinstance(media_data, dict):
                media_urls = [
                    m["url"] for m in media_data.get("all", [])
                    if isinstance(m, dict) and m.get("url")
                ]
        elif domain_id == "pixiv":
            media_urls = platform_info.get("image_proxy_urls", [])

        if not media_urls:
            return

        should_spoiler = is_spoilered or is_nsfw_ch
        for i in range(0, len(media_urls), 10):
            batch = media_urls[i:i + 10]
            files = await _download_as_files(batch, self._get_session(), spoiler=should_spoiler)
            if files:
                try:
                    await channel.send(files=files)
                except (disnake.Forbidden, disnake.HTTPException):
                    pass

    # ── 設定存取 ────────────────────────────────

    def _gs(self, guild_id: int) -> dict:
        return _guild_settings(self._data, guild_id)

    def _save(self):
        _save_settings(self._data)

    # ── 核心修復邏輯 ─────────────────────────────

    async def _fix_message(
        self,
        message: disnake.Message,
        *,
        force: bool = False,
    ) -> bool:
        """
        嘗試對訊息進行嵌入修復。
        force=True 時跳過 enabled 檢查（來自右鍵指令）。
        回傳 True 表示成功修復了至少一個 URL。
        """
        if not message.guild:
            return False

        gs = self._gs(message.guild.id)
        if not force and not gs.get("enabled", True):
            return False

        if not force and message.author.id in gs.get("ignored_users", []):
            return False

        # 頻道白名單（非空時只處理白名單內的頻道）
        whitelist_ch = gs.get("whitelist_channels", [])
        if not force and whitelist_ch and message.channel.id not in whitelist_ch:
            return False

        # 頻道黑名單（白名單不存在時才檢查）
        if not force and not whitelist_ch and message.channel.id in gs.get("blacklist_channels", []):
            return False

        # 身份組白名單
        whitelist_roles = gs.get("whitelist_roles", [])
        if not force and whitelist_roles and isinstance(message.author, disnake.Member):
            if not any(r.id in whitelist_roles for r in message.author.roles):
                return False

        mode = gs.get("mode", "ermiana")
        disabled = gs.get("disabled_domains", [])
        nsfw_filter = gs.get("nsfw_filter", True)
        show_original_link = gs.get("show_original_link", True)
        custom_methods = gs.get("fix_methods", {})
        extract_channels = gs.get("extract_channels", [])
        translate_lang = gs.get("translate_lang", "zh-TW")

        urls = extract_urls(message.content)
        if not urls:
            return False

        for url, is_spoilered in urls:
            result = _match_domain(url)
            if not result:
                continue

            domain, match_url = result
            if domain["id"] in disabled and not force:
                continue

            # ── 取得平台資訊（Twitter / Pixiv）──────────
            is_nsfw_ch = (
                isinstance(message.channel, disnake.TextChannel)
                and message.channel.is_nsfw()
            )
            platform_info: Optional[dict] = None
            if not force and domain["id"] in ("twitter", "pixiv"):
                needs_info = (
                    (nsfw_filter and not is_nsfw_ch)  # 非 NSFW 頻道需要 NSFW 過濾
                    or message.channel.id in extract_channels  # 媒體擷取
                )
                if needs_info:
                    if domain["id"] == "twitter":
                        platform_info = await _fetch_twitter_post(url, self._get_session())
                    else:
                        platform_info = await _fetch_pixiv_artwork(url, self._get_session())

            # ── NSFW 過濾 ──────────────────────────────
            if not force and nsfw_filter and not is_nsfw_ch and platform_info is not None:
                if domain["id"] == "twitter" and platform_info.get("possibly_sensitive"):
                    continue
                elif domain["id"] == "pixiv":
                    tags = platform_info.get("tags", [])
                    if "#R-18" in tags:
                        continue

            view = FixReplyView(
                author_id=message.author.id,
                original_url=url,
                cog=self,
                guild_id=message.guild.id,
                show_original_link=show_original_link,
            )

            # ── 準備修復內容 ─────────────────────────
            fixed_content: Optional[str] = None
            fixed_embed: Optional[disnake.Embed] = None
            fixed: Optional[str] = None  # fix_method 型暫存

            if "embed_handler" in domain:
                try:
                    fixed_embed = await domain["embed_handler"](match_url, self._get_session())
                except Exception:
                    fixed_embed = None
                if fixed_embed is None:
                    continue
            else:
                method_name = custom_methods.get(domain["id"], domain["default_method"])
                if method_name not in domain["fix_methods"]:
                    method_name = domain["default_method"]
                fixed = _apply_fix(url, domain["fix_methods"][method_name])
                if not fixed:
                    continue
                # fallback：probe 失敗時改用另一個方法
                # 若使用預設 → fallback_method；若使用自訂 → 另一個可用方法
                _all_methods = list(domain.get("fix_methods", {}).keys())
                fallback_method = None
                if domain.get("fallback_method"):
                    if method_name == domain["default_method"]:
                        fallback_method = domain["fallback_method"]
                    else:
                        # 自訂方法 → fallback 到其他方法（優先 default_method）
                        others = [m for m in _all_methods if m != method_name]
                        fallback_method = domain["default_method"] if domain["default_method"] in others else (others[0] if others else None)
                if fallback_method and fallback_method in domain["fix_methods"]:
                    probe_ok = False
                    try:
                        async with self._get_session().head(
                            fixed, allow_redirects=True,
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            probe_ok = resp.status < 400
                    except Exception:
                        pass
                    if not probe_ok:
                        fallback_fixed = _apply_fix(url, domain["fix_methods"][fallback_method])
                        if fallback_fixed:
                            fixed = fallback_fixed
                # 翻譯：Twitter + FxEmbed → 在 URL 後附加語言代碼
                if domain["id"] == "twitter" and method_name == "FxEmbed" and translate_lang:
                    fixed = fixed.rstrip("/") + f"/{translate_lang}"
                fixed_content = f"||{fixed}||" if is_spoilered else fixed

            # ── Webhook 模式：刪原訊息 + 以原作者身份重發 ──
            if mode == "webhook" and not force and isinstance(
                message.channel, (disnake.TextChannel, disnake.VoiceChannel)
            ):
                webhook = await self._get_or_create_webhook(message.channel)
                if webhook:
                    try:
                        if fixed_embed is not None:
                            # embed_handler 型：原訊息 URL 加 <> 防止自動嵌入
                            wh_content = message.content.replace(url, f"<{url}>")
                            await message.delete()
                            sent = await webhook.send(
                                content=wh_content,
                                embed=fixed_embed,
                                view=view,
                                username=message.author.display_name,
                                avatar_url=str(message.author.display_avatar.url),
                                wait=True,
                            )
                        else:
                            # fix_method 型：直接替換訊息中的 URL
                            if is_spoilered:
                                wh_content = message.content.replace(
                                    f"||{url}||", f"||{fixed}||"
                                )
                            else:
                                wh_content = message.content.replace(url, fixed)
                            await message.delete()
                            sent = await webhook.send(
                                content=wh_content,
                                view=view,
                                username=message.author.display_name,
                                avatar_url=str(message.author.display_avatar.url),
                                wait=True,
                            )
                        view.message = sent
                        if message.channel.id in extract_channels and domain["id"] in ("twitter", "pixiv"):
                            await self._do_media_extract(
                                message.channel, domain["id"], platform_info,
                                is_spoilered=is_spoilered, is_nsfw_ch=is_nsfw_ch,
                            )
                        return True
                    except (disnake.Forbidden, disnake.HTTPException) as e:
                        self.logger.warning(f"Webhook 發送失敗，降級為 Ermiana 模式: {e}")
                        # 刪除失敗時 webhook 快取可能已失效
                        self._webhooks.pop(message.channel.id, None)

            # ── Ermiana 模式（預設）：回覆 + 隱藏原始嵌入 ──
            try:
                if fixed_embed is not None:
                    reply = await message.reply(
                        embed=fixed_embed,
                        view=view,
                        allowed_mentions=disnake.AllowedMentions(replied_user=False),
                    )
                else:
                    reply = await message.reply(
                        content=fixed_content,
                        view=view,
                        allowed_mentions=disnake.AllowedMentions(replied_user=False),
                    )
                view.message = reply

                if mode == "ermiana":
                    try:
                        await message.edit(suppress=True)
                    except (disnake.Forbidden, disnake.HTTPException):
                        pass

                if message.channel.id in extract_channels and domain["id"] in ("twitter", "pixiv"):
                    await self._do_media_extract(
                        message.channel, domain["id"], platform_info,
                        is_spoilered=is_spoilered, is_nsfw_ch=is_nsfw_ch,
                    )

                return True

            except (disnake.Forbidden, disnake.HTTPException) as e:
                self.logger.warning(f"無法發送修復回覆: {e}")

        return False

    # ── 訊息監聽 ─────────────────────────────────

    async def _handle_webhook_reply(self, message: disnake.Message) -> bool:
        """
        當使用者回覆某個 Webhook 訊息時，自動標記原始作者。
        以訊息開頭 $ 可停用此功能。
        回傳 True 表示已處理。
        """
        if not message.reference or message.content.startswith("$"):
            return False

        ref = message.reference.resolved
        if not isinstance(ref, disnake.Message) or not ref.webhook_id:
            return False

        webhook_username = ref.author.name  # webhook 使用原作者 display_name
        # 在伺服器成員中尋找 display_name 相符者
        member = disnake.utils.find(
            lambda m: m.display_name == webhook_username,
            message.guild.members,
        )
        if not member or member.id == message.author.id:
            return False

        try:
            await message.reply(
                f"↩️ {member.mention}",
                allowed_mentions=disnake.AllowedMentions(users=True, replied_user=False),
            )
            return True
        except (disnake.Forbidden, disnake.HTTPException):
            return False

    @Cog.listener()
    async def on_message(self, message: disnake.Message):
        if not message.guild:
            return

        gs = self._gs(message.guild.id)
        if not gs.get("enabled", True):
            return

        # Bot 可見性：預設不處理 Bot 訊息，除非開啟 fix_bots
        if message.author.bot and not gs.get("fix_bots", False):
            # Webhook 回覆標記功能仍對非 Bot 的訊息生效
            return

        if not message.author.bot and gs.get("webhook_reply", True):
            await self._handle_webhook_reply(message)

        if "http" not in message.content:
            return

        me = message.guild.get_member(self.bot.user.id)
        if me and not message.channel.permissions_for(me).send_messages:
            return

        await self._fix_message(message)

    # ── /translang ───────────────────────────────

    @commands.slash_command(name="translang", description="設定 Twitter/X 貼文的翻譯語言（僅限 FxEmbed；需管理伺服器權限）")
    @commands.default_member_permissions(manage_guild=True)
    @commands.guild_only()
    async def translang(
        self,
        inter: ApplicationCommandInteraction,
        lang: str = commands.Param(
            description="目標語言",
            choices={
                "停用": "disable",
                "English": "en",
                "日本語": "ja",
                "繁體中文": "zh-TW",
                "简体中文": "zh-CN",
                "한국어": "ko",
                "Français": "fr",
                "Deutsch": "de",
                "Español": "es",
                "Português": "pt",
                "ภาษาไทย": "th",
                "Bahasa Indonesia": "id",
            },
        ),
    ):
        gs = self._gs(inter.guild_id)
        if lang == "disable":
            gs["translate_lang"] = None
            self._save()
            await inter.response.send_message("🔕 Twitter/X 翻譯已停用。", ephemeral=True)
        else:
            gs["translate_lang"] = lang
            self._save()
            await inter.response.send_message(
                f"🌐 Twitter/X 翻譯已設為 **{lang}**（僅 FxEmbed）。", ephemeral=True
            )

    # ── /ignore-me ───────────────────────────────

    @commands.slash_command(name="ignore-me", description="選擇退出／重新加入本伺服器的嵌入自動修復")
    @commands.guild_only()
    async def ignore_me(self, inter: ApplicationCommandInteraction):
        """使用者自助選擇退出或重新加入嵌入修復。"""
        gs = self._gs(inter.guild_id)
        ignored: list = gs.setdefault("ignored_users", [])
        uid = inter.author.id
        if uid in ignored:
            ignored.remove(uid)
            self._save()
            await inter.response.send_message(
                "✅ 已重新加入：你的連結將再次被自動修復。", ephemeral=True
            )
        else:
            ignored.append(uid)
            self._save()
            await inter.response.send_message(
                "🚫 已選擇退出：你的連結將不再被自動修復。\n"
                "若要重新加入，再次執行 `/ignore-me`。",
                ephemeral=True,
            )

    # ── 右鍵訊息指令 ─────────────────────────────

    @commands.message_command(name="🔧 修復嵌入")
    async def ctx_fix_embed(self, interaction: MessageCommandInteraction):
        """對任意訊息手動觸發嵌入修復。"""
        await interaction.response.defer(ephemeral=True)
        success = await self._fix_message(interaction.target, force=True)
        if success:
            await interaction.edit_original_response(content="✅ 嵌入修復完成！")
        else:
            await interaction.edit_original_response(
                content="❌ 此訊息中未找到可修復的社交媒體連結。"
            )

    # ── 斜線指令：/embed_fixer ───────────────────

    @commands.slash_command(name="embed_fixer", description="嵌入修復器設定")
    @commands.default_member_permissions(manage_guild=True)
    async def embed_fixer(self, inter: ApplicationCommandInteraction):
        pass

    # ── /embed_fixer info ────────────────────────

    @embed_fixer.sub_command(name="info", description="顯示目前的嵌入修復器設定")
    async def ef_info(self, inter: ApplicationCommandInteraction):
        gs = self._gs(inter.guild_id)
        enabled = gs.get("enabled", True)
        mode = gs.get("mode", "ermiana")
        disabled = gs.get("disabled_domains", [])
        methods = gs.get("fix_methods", {})
        blacklist = gs.get("blacklist_channels", [])
        whitelist_ch = gs.get("whitelist_channels", [])
        whitelist_roles = gs.get("whitelist_roles", [])
        ignored_users = gs.get("ignored_users", [])

        mode_label = "Ermiana（隱藏原始嵌入）" if mode == "ermiana" else "Webhook（刪除原訊息並重發）"
        status_label = "✅ 啟用" if enabled else "❌ 停用"
        self_ignored = inter.author.id in ignored_users

        lines = []
        for d in DOMAINS:
            off = d["id"] in disabled
            icon = "❌" if off else "✅"
            if "fix_methods" in d:
                m = methods.get(d["id"], d["default_method"])
                lines.append(f"{icon} {d['emoji']} **{d['name']}** → `{m}`")
            else:
                lines.append(f"{icon} {d['emoji']} **{d['name']}**")

        extract_chs = gs.get("extract_channels", [])
        translate_lang = gs.get("translate_lang", "zh-TW")
        toggles = (
            f"Bot 可見性: {'✅' if gs.get('fix_bots', False) else '❌'}  "
            f"NSFW 過濾: {'✅' if gs.get('nsfw_filter', True) else '❌'}  "
            f"原始連結按鈕: {'✅' if gs.get('show_original_link', True) else '❌'}  "
            f"Webhook 回覆: {'✅' if gs.get('webhook_reply', True) else '❌'}"
        )

        embed = disnake.Embed(title="🔧 嵌入修復器", color=0x5865F2)
        embed.add_field(name="狀態", value=status_label, inline=True)
        embed.add_field(name="模式", value=mode_label, inline=True)
        embed.add_field(name="我的狀態", value="🚫 已退出" if self_ignored else "✅ 參與中", inline=True)
        embed.add_field(name="開關設定", value=toggles, inline=False)
        embed.add_field(name="支援平台", value="\n".join(lines), inline=False)
        if whitelist_ch:
            embed.add_field(name="頻道白名單", value=" ".join(f"<#{c}>" for c in whitelist_ch), inline=False)
        elif blacklist:
            embed.add_field(name="頻道黑名單", value=" ".join(f"<#{c}>" for c in blacklist), inline=False)
        if whitelist_roles:
            embed.add_field(name="身份組白名單", value=" ".join(f"<@&{r}>" for r in whitelist_roles), inline=False)
        if extract_chs:
            embed.add_field(name="媒體擷取頻道", value=" ".join(f"<#{c}>" for c in extract_chs), inline=False)
        if translate_lang:
            embed.add_field(name="Twitter 翻譯", value=f"`{translate_lang}`（僅 FxEmbed）", inline=False)
        embed.set_footer(text="/embed_fixer mode/domain/method/channel/whitelist/role/setting/extract · /translang · /ignore-me")

        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── /embed_fixer toggle ──────────────────────

    @embed_fixer.sub_command(name="toggle", description="開啟或關閉嵌入修復器")
    async def ef_toggle(self, inter: ApplicationCommandInteraction):
        gs = self._gs(inter.guild_id)
        gs["enabled"] = not gs.get("enabled", True)
        self._save()
        label = "✅ 已開啟" if gs["enabled"] else "❌ 已停用"
        await inter.response.send_message(f"嵌入修復器 {label}", ephemeral=True)

    # ── /embed_fixer mode ────────────────────────

    @embed_fixer.sub_command(name="mode", description="切換呈現模式")
    async def ef_mode(
        self,
        inter: ApplicationCommandInteraction,
        mode: str = commands.Param(
            description="呈現模式",
            choices={
                "Ermiana（回覆修復連結並隱藏原始嵌入）": "ermiana",
                "Webhook（刪除原訊息並以原作者身份重發）": "webhook",
            },
        ),
    ):
        gs = self._gs(inter.guild_id)
        gs["mode"] = mode
        self._save()
        label = "Ermiana（隱藏原始嵌入）" if mode == "ermiana" else "Webhook（刪除原訊息並重發）"
        await inter.response.send_message(f"已切換至 **{label}** 模式", ephemeral=True)

    # ── /embed_fixer domain ──────────────────────

    @embed_fixer.sub_command(name="domain", description="啟用或停用特定平台")
    async def ef_domain(
        self,
        inter: ApplicationCommandInteraction,
        platform: str = commands.Param(
            description="選擇平台",
            choices=_DOMAIN_CHOICES,
        ),
    ):
        gs = self._gs(inter.guild_id)
        disabled: list = gs.setdefault("disabled_domains", [])
        d = _DOMAIN_MAP.get(platform)
        name = f"{d['emoji']} {d['name']}" if d else platform

        if platform in disabled:
            disabled.remove(platform)
            status = "✅ 已啟用"
        else:
            disabled.append(platform)
            status = "❌ 已停用"

        self._save()
        await inter.response.send_message(f"**{name}** {status}", ephemeral=True)

    # ── /embed_fixer method ──────────────────────

    @embed_fixer.sub_command(name="method", description="設定特定平台的修復服務")
    async def ef_method(
        self,
        inter: ApplicationCommandInteraction,
        platform: str = commands.Param(
            description="選擇平台",
            choices=_METHOD_DOMAIN_CHOICES,
        ),
    ):
        gs = self._gs(inter.guild_id)
        d = _DOMAIN_MAP.get(platform)
        if not d or "fix_methods" not in d:
            await inter.response.send_message("此平台不支援切換修復服務。", ephemeral=True)
            return

        current = gs.get("fix_methods", {}).get(platform, d["default_method"])
        view = MethodSelectView(cog=self, gs=gs, domain=d, current=current)
        embed = disnake.Embed(
            title=f"{d['emoji']} {d['name']} 修復服務",
            description=f"目前使用：**{current}**\n請從下方選單選擇。",
            color=0x5865F2,
        )
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── /embed_fixer channel ─────────────────────

    @embed_fixer.sub_command(name="channel", description="將頻道加入或移出黑名單（黑名單中的頻道不進行嵌入修復）")
    async def ef_channel(
        self,
        inter: ApplicationCommandInteraction,
        channel: disnake.TextChannel = commands.Param(description="目標頻道"),
    ):
        gs = self._gs(inter.guild_id)
        blacklist: list = gs.setdefault("blacklist_channels", [])
        if channel.id in blacklist:
            blacklist.remove(channel.id)
            self._save()
            await inter.response.send_message(
                f"✅ {channel.mention} 已從黑名單移除，嵌入修復已重新啟用。", ephemeral=True
            )
        else:
            blacklist.append(channel.id)
            self._save()
            await inter.response.send_message(
                f"🚫 {channel.mention} 已加入黑名單，嵌入修復已停用。", ephemeral=True
            )

    # ── /embed_fixer whitelist ───────────────────

    @embed_fixer.sub_command(name="whitelist", description="設定頻道白名單（只有白名單頻道才進行嵌入修復；非空時優先於黑名單）")
    async def ef_whitelist(
        self,
        inter: ApplicationCommandInteraction,
        channel: disnake.TextChannel = commands.Param(description="目標頻道"),
    ):
        gs = self._gs(inter.guild_id)
        whitelist: list = gs.setdefault("whitelist_channels", [])
        if channel.id in whitelist:
            whitelist.remove(channel.id)
            self._save()
            await inter.response.send_message(
                f"✅ {channel.mention} 已從白名單移除。", ephemeral=True
            )
        else:
            whitelist.append(channel.id)
            self._save()
            await inter.response.send_message(
                f"✅ {channel.mention} 已加入白名單。", ephemeral=True
            )

    # ── /embed_fixer role ────────────────────────

    @embed_fixer.sub_command(name="role", description="設定身份組白名單（只有擁有這些身份組的使用者才被修復；空＝全部）")
    async def ef_role(
        self,
        inter: ApplicationCommandInteraction,
        role: disnake.Role = commands.Param(description="目標身份組"),
    ):
        gs = self._gs(inter.guild_id)
        whitelist: list = gs.setdefault("whitelist_roles", [])
        if role.id in whitelist:
            whitelist.remove(role.id)
            self._save()
            await inter.response.send_message(
                f"✅ {role.mention} 已從白名單移除。", ephemeral=True,
                allowed_mentions=disnake.AllowedMentions.none(),
            )
        else:
            whitelist.append(role.id)
            self._save()
            await inter.response.send_message(
                f"✅ {role.mention} 已加入白名單。", ephemeral=True,
                allowed_mentions=disnake.AllowedMentions.none(),
            )

    # ── /embed_fixer setting ─────────────────────

    @embed_fixer.sub_command(name="setting", description="切換各種開關設定")
    async def ef_setting(
        self,
        inter: ApplicationCommandInteraction,
        key: str = commands.Param(
            description="設定項目",
            choices={
                "Bot 可見性（修復機器人發送的連結）": "fix_bots",
                "NSFW 過濾（非 NSFW 頻道跳過 NSFW 貼文）": "nsfw_filter",
                "顯示原始連結按鈕": "show_original_link",
                "Webhook 回覆標記原作者": "webhook_reply",
            },
        ),
    ):
        gs = self._gs(inter.guild_id)
        default = key != "fix_bots"  # fix_bots 預設 False，其餘預設 True
        current = gs.get(key, default)
        gs[key] = not current
        self._save()
        label_map = {
            "fix_bots": "Bot 可見性",
            "nsfw_filter": "NSFW 過濾",
            "show_original_link": "顯示原始連結按鈕",
            "webhook_reply": "Webhook 回覆標記原作者",
        }
        state = "✅ 開啟" if gs[key] else "❌ 關閉"
        await inter.response.send_message(
            f"**{label_map[key]}** 已設為 {state}", ephemeral=True
        )

    # ── /embed_fixer extract ─────────────────────

    @embed_fixer.sub_command(name="extract", description="設定媒體擷取頻道（Twitter/Pixiv 連結自動發送完整圖集）")
    async def ef_extract(
        self,
        inter: ApplicationCommandInteraction,
        channel: disnake.TextChannel = commands.Param(description="目標頻道"),
    ):
        gs = self._gs(inter.guild_id)
        extract: list = gs.setdefault("extract_channels", [])
        if channel.id in extract:
            extract.remove(channel.id)
            self._save()
            await inter.response.send_message(
                f"✅ {channel.mention} 已停用媒體擷取。", ephemeral=True
            )
        else:
            extract.append(channel.id)
            self._save()
            await inter.response.send_message(
                f"✅ {channel.mention} 已啟用媒體擷取（Twitter/Pixiv 圖集自動下載發送）。",
                ephemeral=True,
            )


def setup(bot: Bot):
    bot.add_cog(EmbedFixerCog(bot))
