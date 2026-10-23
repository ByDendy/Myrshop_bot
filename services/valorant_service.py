import aiohttp
import logging
from datetime import datetime

async def get_recent_matches(riot_id: str, region: str = "eu", limit: int = 5):
    if not riot_id or "#" not in riot_id:
        return []
        
    name, tag = riot_id.split("#", 1)
    url = f"https://api.henrikdev.xyz/valorant/v3/matches/{region}/{name}/{tag}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                
        matches = data.get("data", [])[:limit]
        result = []
        
        for m in matches:
            metadata = m.get("metadata", {})
            players = m.get("players", {}).get("all_players", [])
            teams = m.get("teams", {})
            
            player = players[0] if players else {}
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
        logging.error(f"Valorant API error: {e}")
        return []