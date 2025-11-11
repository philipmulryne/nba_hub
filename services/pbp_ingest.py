# services/pbp_ingest.py

import os
import pandas as pd
from sqlalchemy import text
from nba_api.stats.endpoints import playbyplayv2

from .db import engine

DATA_DIR = "data/pbp"
os.makedirs(DATA_DIR, exist_ok=True)


def fetch_pbp_df(game_id: str) -> pd.DataFrame:
    pbp = playbyplayv2.PlayByPlayV2(game_id=game_id)
    if hasattr(pbp, "play_by_play"):
        df = pbp.play_by_play.get_data_frame()
    else:
        dfs = pbp.get_data_frames()
        df = dfs[0] if dfs else pd.DataFrame()

    if df is None or df.empty:
        raise RuntimeError(f"No play-by-play rows returned for {game_id}")
    return df


def normalize_pbp(df: pd.DataFrame, game_id: str) -> pd.DataFrame:
    df = df.copy()
    df["game_id"] = game_id

    # Map core columns
    df["event_num"] = df.get("EVENTNUM")
    df["period"] = df.get("PERIOD")
    df["pctimestring"] = df.get("PCTIMESTRING")
    df["event_msg_type"] = df.get("EVENTMSGTYPE") or df.get("EVENTMSGTYP")
    df["event_type"] = df.get("EVENTTYPE") or df.get("EVENTYPE")
    df["player1_id"] = df.get("PLAYER1_ID")
    df["player2_id"] = df.get("PLAYER2_ID")
    df["player3_id"] = df.get("PLAYER3_ID")
    df["score"] = df.get("SCORE")
    df["score_margin"] = df.get("SCOREMARGIN")

    # Build description from available fields
    for col in ["HOMEDESCRIPTION", "NEUTRALDESCRIPTION", "VISITORDESCRIPTION"]:
        if col not in df.columns:
            df[col] = None

    df["description"] = (
        df["HOMEDESCRIPTION"].fillna("")
        + df["NEUTRALDESCRIPTION"].fillna("")
        + df["VISITORDESCRIPTION"].fillna("")
    ).str.strip()
    df.loc[df["description"] == "", "description"] = None

    df["clock"] = df["pctimestring"]

    # Raw JSON snapshot
    df["raw_json"] = df.apply(lambda r: r.to_dict(), axis=1)

    keep = [
        "game_id",
        "event_num",
        "period",
        "clock",
        "pctimestring",
        "event_type",
        "event_msg_type",
        "player1_id",
        "player2_id",
        "player3_id",
        "description",
        "score",
        "score_margin",
        "raw_json",
    ]
    return df[keep]


def ingest_pbp(game_id: str, save_csv: bool = True) -> int:
    df_raw = fetch_pbp_df(game_id)
    df = normalize_pbp(df_raw, game_id)

    if save_csv:
        out = os.path.join(DATA_DIR, f"pbp_{game_id}.csv")
        df_raw.to_csv(out, index=False, encoding="utf-8")

    if df.empty:
        return 0

    with engine.begin() as conn:
        for _, r in df.iterrows():
            conn.execute(
                text("""
                    INSERT INTO nba.nba_pbp_events
                        (game_id, event_num, period, clock, pctimestring,
                         event_type, event_msg_type,
                         player1_id, player2_id, player3_id,
                         description, score, score_margin, raw_json)
                    VALUES
                        (:game_id, :event_num, :period, :clock, :pctimestring,
                         :event_type, :event_msg_type,
                         :player1_id, :player2_id, :player3_id,
                         :description, :score, :score_margin, :raw_json)
                    ON CONFLICT (game_id, event_num) DO NOTHING;
                """),
                dict(r),
            )

    return len(df)
