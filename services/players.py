# services/players.py

from datetime import datetime
from sqlalchemy import text
from nba_api.stats.endpoints import commonallplayers, commonplayerinfo

from .db import engine


def sync_players(active_only: bool = True):
    is_only_current = 1 if active_only else 0

    all_players = commonallplayers.CommonAllPlayers(
        is_only_current_season=is_only_current,
        league_id="00",
    ).get_data_frames()[0]

    with engine.begin() as conn:
        for _, row in all_players.iterrows():
            player_id = int(row["PERSON_ID"])
            full_name = row["DISPLAY_FIRST_LAST"]

            try:
                info = commonplayerinfo.CommonPlayerInfo(player_id=player_id).get_data_frames()[0]
            except Exception as e:
                print(f"Player {player_id} failed: {e}")
                continue

            pos = info.get("POSITION", [None])[0]
            ht = info.get("HEIGHT", [None])[0]
            wt = info.get("WEIGHT", [None])[0]
            country = info.get("COUNTRY", [None])[0]
            bdate = info.get("BIRTHDATE", [None])[0]

            # height in cm
            height_cm = None
            if isinstance(ht, str) and "-" in ht:
                try:
                    ft, inch = ht.split("-")
                    total_in = int(ft) * 12 + int(inch)
                    height_cm = round(total_in * 2.54, 1)
                except Exception:
                    pass

            # weight in kg
            weight_kg = None
            try:
                wt_lbs = float(wt)
                weight_kg = round(wt_lbs * 0.453592, 1)
            except Exception:
                pass

            conn.execute(
                text("""
                    INSERT INTO nba.nba_players
                        (player_id, full_name, first_name, last_name,
                         position, height_cm, weight_kg,
                         birthdate, nationality, last_updated)
                    VALUES
                        (:player_id, :full_name,
                         split_part(:full_name, ' ', 1),
                         split_part(:full_name, ' ', 2),
                         :position, :height_cm, :weight_kg,
                         :birthdate, :nationality, now())
                    ON CONFLICT (player_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        position = EXCLUDED.position,
                        height_cm = EXCLUDED.height_cm,
                        weight_kg = EXCLUDED.weight_kg,
                        birthdate = EXCLUDED.birthdate,
                        nationality = EXCLUDED.nationality,
                        last_updated = now();
                """),
                {
                    "player_id": player_id,
                    "full_name": full_name,
                    "position": pos,
                    "height_cm": height_cm,
                    "weight_kg": weight_kg,
                    "birthdate": bdate,
                    "nationality": country,
                },
            )
