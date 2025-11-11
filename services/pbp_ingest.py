# services/pbp_ingest.py

import json
import os
from typing import Optional

import pandas as pd
from sqlalchemy import text
from nba_api.stats.endpoints import playbyplayv2

try:
    from nba_api.stats.endpoints import playbyplayv3

    HAS_PBP_V3 = True
except ImportError:  # pragma: no cover - older nba_api installations
    playbyplayv3 = None
    HAS_PBP_V3 = False

from .db import engine

DATA_DIR = "data/pbp"
os.makedirs(DATA_DIR, exist_ok=True)


def fetch_pbp_df(game_id: str) -> pd.DataFrame:
    """Fetch play-by-play rows, preferring the newer V3 endpoint."""

    last_error: Optional[Exception] = None

    if HAS_PBP_V3:
        try:
            pbp3 = playbyplayv3.PlayByPlayV3(game_id=game_id)
            if hasattr(pbp3, "play_by_play"):
                df3 = pbp3.play_by_play.get_data_frame()
            else:  # pragma: no cover - defensive fallback
                dfs3 = pbp3.get_data_frames()
                df3 = dfs3[0] if dfs3 else pd.DataFrame()
            if df3 is not None and not df3.empty:
                return df3
        except Exception as exc:  # noqa: BLE001 - surface upstream error in fallback
            last_error = exc

    try:
        pbp2 = playbyplayv2.PlayByPlayV2(game_id=game_id)
        if hasattr(pbp2, "play_by_play"):
            df2 = pbp2.play_by_play.get_data_frame()
        else:
            dfs2 = pbp2.get_data_frames()
            df2 = dfs2[0] if dfs2 else pd.DataFrame()
        if df2 is None or df2.empty:
            raise RuntimeError("No play-by-play rows returned")
        return df2
    except Exception as exc:  # noqa: BLE001 - propagate with context
        if last_error is not None:
            raise RuntimeError(
                f"PlayByPlayV3 failed for {game_id}: {last_error}; "
                f"PlayByPlayV2 failed: {exc}"
            ) from exc
        raise RuntimeError(f"PlayByPlayV2 failed for {game_id}: {exc}") from exc


def normalize_pbp(df: pd.DataFrame, game_id: str) -> pd.DataFrame:
    df = df.copy()
    df["game_id"] = game_id

    lower_map = {c.lower(): c for c in df.columns}

    def pick_series(*candidates: str) -> pd.Series:
        for name in candidates:
            col = lower_map.get(name.lower())
            if col is not None:
                return df[col]
        return pd.Series([None] * len(df), index=df.index, dtype="object")

    df["event_num"] = pd.to_numeric(
        pick_series("EVENTNUM", "EVENT_NUM", "ACTIONNUMBER", "EVENTNBR"),
        errors="coerce",
    ).astype("Int64")
    df["period"] = pd.to_numeric(pick_series("PERIOD"), errors="coerce").astype("Int64")

    clock_series = pick_series("PCTIMESTRING", "PCTIME", "CLOCK")
    df["pctimestring"] = clock_series
    df["clock"] = clock_series

    df["event_msg_type"] = pick_series(
        "EVENTMSGTYPE",
        "EVENTMSGTYP",
        "EVENT_MSG_TYPE",
        "EVENTMSGTYPEID",
        "EVENTMSGTYPEV3",
        "EVENTMSGTYPE",
        "eventMsgType",
    )
    df["event_type"] = pick_series("EVENTTYPE", "EVENTYPE", "EVENT", "ACTIONTYPE")

    df["player1_id"] = pick_series(
        "PLAYER1_ID",
        "PLAYER1ID",
        "PERSON1_ID",
        "PERSONID",
        "PLAYER_ID",
    )
    df["player2_id"] = pick_series(
        "PLAYER2_ID",
        "PLAYER2ID",
        "PLAYER_ID2",
        "ASSISTPERSONID",
        "PERSON2_ID",
    )
    df["player3_id"] = pick_series(
        "PLAYER3_ID",
        "PLAYER3ID",
        "PLAYER_ID3",
        "BLOCKPERSONID",
        "PERSON3_ID",
    )

    for col in ["player1_id", "player2_id", "player3_id"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    score_series = pick_series("SCORE")
    margin_series = pick_series("SCOREMARGIN")

    score_home = pd.to_numeric(pick_series("SCOREHOME", "HOME_SCORE"), errors="coerce")
    score_away = pd.to_numeric(pick_series("SCOREAWAY", "VISITOR_SCORE"), errors="coerce")

    if score_series.isna().all() and (not score_home.isna().all() or not score_away.isna().all()):
        formatted_score = []

        for home_val, away_val in zip(score_home, score_away):
            if pd.isna(home_val) and pd.isna(away_val):
                formatted_score.append(None)
                continue

            def fmt(val):
                if pd.isna(val):
                    return ""
                try:
                    return str(int(val))
                except Exception:  # noqa: BLE001 - fall back to string cast
                    return str(val)

            away_str = fmt(away_val)
            home_str = fmt(home_val)

            if away_str and home_str:
                formatted_score.append(f"{away_str}-{home_str}")
            elif away_str:
                formatted_score.append(away_str)
            elif home_str:
                formatted_score.append(home_str)
            else:
                formatted_score.append(None)

        score_series = pd.Series(formatted_score, index=df.index, dtype="object")

    if margin_series.isna().all() and (not score_home.isna().all() or not score_away.isna().all()):
        diff = score_home - score_away
        formatted_margin = []
        for value in diff:
            if pd.isna(value):
                formatted_margin.append(None)
            elif abs(value) < 0.5:
                formatted_margin.append("TIE")
            else:
                try:
                    formatted_margin.append(str(int(value)))
                except Exception:  # noqa: BLE001 - fall back to string cast
                    formatted_margin.append(str(value))
        margin_series = pd.Series(formatted_margin, index=df.index, dtype="object")

    df["score"] = score_series
    df["score_margin"] = margin_series

    if lower_map.get("description"):
        description = pick_series("description", "playDescription")
    else:
        home_desc = pick_series("HOMEDESCRIPTION")
        neutral_desc = pick_series("NEUTRALDESCRIPTION")
        visitor_desc = pick_series("VISITORDESCRIPTION")
        description = (home_desc.fillna("") + neutral_desc.fillna("") + visitor_desc.fillna(""))
        description = description.str.strip()
        description = description.replace("", None)

    df["description"] = description

    def _to_serializable(value):
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
        if isinstance(value, (dict, list)):
            return value
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass
        return value

    df["raw_json"] = df.apply(
        lambda row: {key: _to_serializable(val) for key, val in row.to_dict().items()},
        axis=1,
    )

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


def ingest_pbp(
    game_id: str,
    df_raw: Optional[pd.DataFrame] = None,
    save_csv: bool = True,
) -> int:
    if df_raw is None:
        df_raw = fetch_pbp_df(game_id)
    else:
        df_raw = df_raw.copy()

    df = normalize_pbp(df_raw, game_id)

    if save_csv:
        out = os.path.join(DATA_DIR, f"pbp_{game_id}.csv")
        df_raw.to_csv(out, index=False, encoding="utf-8")

    if df.empty:
        return 0

    with engine.begin() as conn:
        for _, r in df.iterrows():
            payload = r.where(pd.notna(r), None).to_dict()
            if payload.get("raw_json") is not None:
                payload["raw_json"] = json.dumps(payload["raw_json"], ensure_ascii=False)
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
                payload,
            )

    return len(df)
