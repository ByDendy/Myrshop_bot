import asyncio
import logging
from collections import OrderedDict
from aiogram import Bot
from aiohttp import web


CACHE_SIZE = 200
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_lock = asyncio.Lock()


async def get_photo_bytes(bot: Bot, file_id: str) -> bytes | None:
    async with _lock:
        if file_id in _cache:
            _cache.move_to_end(file_id)
            return _cache[file_id]

    try:
        file = await bot.get_file(file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as e:
        logging.warning(f"photo_proxy: не смог скачать {file_id}: {e}")
        return None

    async with _lock:
        _cache[file_id] = data
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return data


def register_photo_route(app: web.Application, bot: Bot):
    async def photo_handler(request: web.Request):
        file_id = request.match_info["file_id"]
        data = await get_photo_bytes(bot, file_id)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(
            body=data,
            content_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    app.router.add_get("/api/photo/{file_id}", photo_handler)