import aiohttp
import logging
import os
from datetime import datetime

# Берём ключ из переменных окружения Railway
HENRIK_API_KEY = os.getenv("HENRIK_API_KEY")

async def get_recent_matches(riot_id: str, region: str = "eu", limit: int = 5):
    if not riot_id or "#" not in riot_id:
        return []

    if not HENRIK_API_KEY:
        logging.error("Valorant API: HENRIK_API_KEY не задан в Railway → Variables")
        return []

    name, tag = riot_id.split("#", 1)
    url = f"https://api.henrikdev.xyz/valorant/v3/matches/{region}/{name}/{tag}"
    
    # Заголовок с ключом авторизации
    headers = {"Authorization": HENRIK_API_KEY}
    
    try:
        async with aiohttp.ClientSession() as session:
            # Передаём headers в запрос
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    logging.error("Valorant API: неверный HENRIK_API_KEY (401)")
                    return []
                if resp.status == 403:
                    logging.error("Valorant API: доступ запрещён (403) — проверь ключ")
                    return []
                if resp.status != 200:
                    text = await resp.text()
                    logging.error(f"Valorant API error {resp.status}: {text[:200]}")
                    return []
                data = await resp.json()
                
        matches = data.get("data", [])[:limit]
        result = []
        
        for m in matches:
            metadata = m.get("metadata", {})
            players = m.get("players", {}).get("all_players", [])
            teams = m.get("teams", {})
            
            # Ищем именно нашего игрока по name и tag
            player = None
            for p in players:
                if p.get("name", "").lower() == name.lower() and p.get("tag", "").lower() == tag.lower():
                    player = p
                    break
            
            if not player:
                continue
                
            agent = player.get("character", "Unknown")
            map_name = metadata.get("map", "Unknown")
            
            red_score = teams.get("red", {}).get("rounds_won", 0)
            blue_score = teams.get("blue", {}).get("rounds_won", 0)
            
            our_team = player.get("team", "red")
            our_score = red_score if our_team == "red" else blue_score
            enemy_score = blue_score if our_team == "red" else red_score
            win = our_score > enemy_score
            
            kda = player.get("stats", {})
            start_time = metadata.get("game_start", 0)
            
            result.append({
                "agent_name": agent,
                "map_name": map_name,
                "score": f"{our_score} : {enemy_score}",
                "result": "win" if win else "loss",
                "kills": kda.get("kills", 0),
                "deaths": kda.get("deaths", 0),
                "assists": kda.get("assists", 0),
                "time_ago": datetime.fromtimestamp(start_time).strftime('%d.%m %H:%M') if start_time else "Недавно"
            })
        return result
    except Exception as e:
        logging.error(f"Valorant API exception: {e}")
        return []
