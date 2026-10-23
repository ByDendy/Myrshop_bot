import aiohttp
import logging
import os
from datetime import datetime

# Загружаем ключ из переменных окружения Railway
HENRIK_API_KEY = os.getenv("HENRIK_API_KEY")

async def get_recent_matches(riot_id: str, region: str = "eu", limit: int = 5):
    logging.info(f"Valorant API: вызов для riot_id={riot_id!r}, ключ={'ЕСТЬ' if HENRIK_API_KEY else 'НЕТ'}")

    if not riot_id or "#" not in riot_id:
        logging.warning("Valorant API: riot_id пустой или не содержит '#'")
        return []

    if not HENRIK_API_KEY:
        logging.error("Valorant API: HENRIK_API_KEY не задан в Railway → Variables")
        return []

    name, tag = riot_id.split("#", 1)
    url = f"https://api.henrikdev.xyz/valorant/v3/matches/{region}/{name}/{tag}"
    
    headers = {"Authorization": HENRIK_API_KEY}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    logging.error("Valorant API: неверный HENRIK_API_KEY (401)")
                    return []
                if resp.status == 403:
                    logging.error("Valorant API: доступ запрещён (403)")
                    return []
                if resp.status == 404:
                    logging.warning(f"Valorant API: игрок {riot_id} не найден (404)")
                    return []
                if resp.status == 429:
                    logging.error("Valorant API: превышен лимит (429)")
                    return []
                if resp.status != 200:
                    text = await resp.text()
                    logging.error(f"Valorant API error {resp.status}: {text[:200]}")
                    return []
                
                data = await resp.json()
                
        matches = data.get("data") or []
        matches = matches[:limit]
        logging.info(f"Valorant API: получено {len(matches)} матчей для {riot_id}")
        
        result = []
        for m in matches:
            metadata = m.get("metadata") or {}
            players = m.get("players", {}).get("all_players") or []
            teams = m.get("teams") or {}
            
            # Ищем именно нашего игрока
            player = None
            for p in players:
                if (p.get("name") or "").lower() == name.lower() and (p.get("tag") or "").lower() == tag.lower():
                    player = p
                    break
            
            if not player:
                continue
                
            agent = player.get("character") or "Unknown"
            map_name = metadata.get("map") or "Unknown"
            
            # Защита от None в счетах
            red_rounds = (teams.get("red") or {}).get("rounds_won") or 0
            blue_rounds = (teams.get("blue") or {}).get("rounds_won") or 0
            
            our_team = player.get("team") or "red"
            our_score = red_rounds if our_team == "red" else blue_rounds
            enemy_score = blue_rounds if our_team == "red" else red_rounds
            win = our_score > enemy_score
            
            kda = player.get("stats") or {}
            start_time = metadata.get("game_start") or 0
            
            result.append({
                "agent_name": agent,
                "map_name": map_name,
                "score": f"{our_score} : {enemy_score}",
                "result": "win" if win else "loss",
                "kills": kda.get("kills") or 0,
                "deaths": kda.get("deaths") or 0,
                "assists": kda.get("assists") or 0,
                "time_ago": datetime.fromtimestamp(start_time).strftime('%d.%m %H:%M') if start_time else "Недавно"
            })
        return result
    except Exception as e:
        logging.error(f"Valorant API exception: {e}")
        return []
