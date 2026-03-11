import asyncio
import logging
import os

from colorlog import ColoredFormatter
from disnake import Intents
from disnake.ext.commands import CommandSyncFlags
from dotenv import load_dotenv

from src.bot import Bot


def setup_logging():
    formatter = ColoredFormatter(
        "%(asctime)s %(log_color)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "white",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        },
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    os.makedirs("logs", exist_ok=True)
    file_handler = logging.FileHandler(
        filename="logs/bot.log", encoding="utf-8", mode="w"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        handlers=[stream_handler, file_handler],
        level=logging.INFO,
    )


def main():
    load_dotenv(".env")
    setup_logging()

    logger = logging.getLogger("main")

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("未找到 DISCORD_TOKEN，請在 .env 中設定")
        return

    loop = asyncio.new_event_loop()

    bot = Bot(
        logger=logger,
        command_prefix=os.getenv("PREFIX", "+"),
        intents=Intents.all(),
        loop=loop,
        command_sync_flags=CommandSyncFlags.default(),
        owner_id=int(os.getenv("OWNER_ID", "0")),
    )

    bot.load_extension("src.cogs.embed_fixer")
    logger.info("已載入 EmbedFixer cog")

    bot.run(token)


if __name__ == "__main__":
    main()
