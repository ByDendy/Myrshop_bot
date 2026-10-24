import asyncio
import logging
import io
from collections import OrderedDict
from aiogram import Bot
from aiohttp import web
from PIL import Image


CACHE_SIZE = 500
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_lock = asyncio.Lock()


async def get_photo_bytes(bot: Bot, file_id: str, width: int = None) -> bytes | None:
    cache_key = f"{file_id}_{width}" if width else file_id
    
    async with _lock:
        if cache_key in _cache:
            _cache.move_to_end(cache_key)
            return _cache[cache_key]

    try:
        file = await bot.get_file(file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
        
        # Сжатие через Pillow
        if width:
            try:
                img = Image.open(io.BytesIO(data))
                ratio = width / float(img.size[0])
                height = int((float(img.size[1]) * float(ratio)))
                img = img.resize((width, height), Image.Resampling.LANCZOS)
                out_io = io.BytesIO()
                img.save(out_io, format="JPEG", quality=85)
                data = out_io.getvalue()
            except Exception as e:
                logging.warning(f"Pillow resize error: {e}")

    except Exception as e:
        logging.warning(f"photo_proxy: не смог скачать {file_id}: {e}")
        return None

    async with _lock:
        _cache[cache_key] = data
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return data


def register_photo_route(app: web.Application, bot: Bot):
    async def photo_handler(request: web.Request):
        file_id = request.match_info["file_id"]
        w_param = request.query.get("w")
        width = int(w_param) if w_param and w_param.isdigit() else None
        
        data = await get_photo_bytes(bot, file_id, width)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(
            body=data,
            content_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    app.router.add_get("/api/photo/{file_id}", photo_handler)
