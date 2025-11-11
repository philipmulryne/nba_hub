import os
from datetime import datetime
import pandas as pd
from dash import (
    html,
    dcc,
    dash_table,
    Input,
    Output,
    State,
    callback,
    no_update,
)
import dash_bootstrap_components as dbc
from nba_api.stats.endpoints import scoreboardv2, playbyplayv2

# ✅ Import DB ingestion logic
from services.pbp_ingest import ingest_pbp

# Try to import PlayByPlayV3 if available (newer seasons)
try:
    from nba_api.stats.endpoints import playbyplayv3
    HAS_PBP_V3 = True
except ImportError:
    playbyplayv3 = None
    HAS_PBP_V3 = False

# -------------------------
# Config
# -------------------------

DATA_DIR = "data/pbp"
os.makedirs(DATA_DIR, exist_ok=True)

TEAM_ID_TO_NAME = {
    1610612737: "Atlanta Hawks",
    1610612738: "Boston Celtics",
    1610612739: "Cleveland Cavaliers",
    1610612740: "New Orleans Pelicans",
    1610612741: "Chicago Bulls",
    1610612742: "Dallas Mavericks",
    1610612743: "Denver Nuggets",
    1610612744: "Golden State Warriors",
    1610612745: "Houston Rockets",
    1610612746: "LA Clippers",
    1610612747: "Los Angeles Lakers",
    1610612748: "Miami Heat",
    1610612749: "Milwaukee Bucks",
    1610612750: "Minnesota Timberwolves",
    1610612751: "Brooklyn Nets",
    1610612752: "New York Knicks",
    1610612753: "Orlando Magic",
    1610612754: "Indiana Pacers",
    1610612755: "Philadelphia 76ers",
    1610612756: "Phoenix Suns",
    1610612757: "Portland Trail Blazers",
    1610612758: "Sacramento Kings",
    1610612759: "San Antonio Spurs",
    1610612760: "Oklahoma City Thunder",
    1610612761: "Toronto Raptors",
    1610612762: "Utah Jazz",
    1610612763: "Memphis Grizzlies",
    1610612764: "Washington Wizards",
    1610612765: "Detroit Pistons",
    1610612766: "Charlotte Hornets",
}

# -------------------------
# Layout
# -------------------------

layout = dbc.Container(
    fluid=True,
    children=[
        html.H3("NBA Play-by-Play Ingest", className="text-light mb-3"),

        # Date + load games
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Date (YYYY-MM-DD)", className="text-light"),
                        dcc.Input(
                            id="pbp-date",
                            type="text",
                            placeholder="2024-10-24",
                            value="2024-10-24",
                            className="form-control mb-2",
                        ),
                        html.Small(
                            "Lists games from ScoreboardV2 (stats.nba.com) for this date.",
                            className="text-muted",
                        ),
                    ],
                    md=3,
                ),
                dbc.Col(
                    html.Button(
                        "Load Games for Date",
                        id="pbp-load-games",
                        n_clicks=0,
                        className="btn btn-outline-info mt-4",
                    ),
                    md=2,
                ),
            ],
            className="mb-3",
        ),

        # Game select + manual ID + fetch PBP
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Select Game", className="text-light"),
                        dcc.Dropdown(
                            id="pbp-game-dropdown",
                            placeholder="Load games first, then select.",
                            options=[],
                            className="mb-2 dropdown-dark",
                        ),
                        html.Small(
                            "Game IDs from ScoreboardV2. You can override manually.",
                            className="text-muted",
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        html.Label("Or enter Game ID manually", className="text-light"),
                        dcc.Input(
                            id="pbp-game-id-manual",
                            type="text",
                            placeholder="e.g. 0022300001",
                            className="form-control mb-2",
                        ),
                        html.Small(
                            "If set, overrides dropdown. Use a valid NBA Stats gameId.",
                            className="text-muted",
                        ),
                    ],
                    md=3,
                ),
                dbc.Col(
                    html.Button(
                        "Fetch Play-by-Play",
                        id="pbp-fetch",
                        n_clicks=0,
                        className="btn btn-success mt-4",
                    ),
                    md=3,
                ),
            ],
            className="mb-3",
        ),

        dcc.Store(id="pbp-data-store"),

        # Status + table
        dbc.Row(
            dbc.Col(
                [
                    html.Div(id="pbp-status", className="text-info mb-2"),
                    dash_table.DataTable(
                        id="pbp-table",
                        columns=[],
                        data=[],
                        page_size=25,
                        style_table={"overflowX": "auto", "maxHeight": "600px"},
                        style_header={
                            "backgroundColor": "#222",
                            "color": "white",
                            "fontWeight": "bold",
                        },
                        style_cell={
                            "backgroundColor": "#111",
                            "color": "white",
                            "fontSize": 11,
                            "padding": "4px",
                            "whiteSpace": "normal",
                            "height": "auto",
                        },
                        filter_action="native",
                        sort_action="native",
                        sort_mode="multi",
                    ),
                ]
            ),
            className="mb-3",
        ),

        # Download CSV
        dbc.Row(
            dbc.Col(
                [
                    html.Button(
                        "Download CSV",
                        id="pbp-download-btn",
                        n_clicks=0,
                        className="btn btn-outline-warning",
                    ),
                    dcc.Download(id="pbp-download"),
                    html.Div(id="pbp-csv-path", className="text-muted mt-2"),
                ],
                width=4,
            ),
            className="mb-5",
        ),
    ],
)

# -------------------------
# Helpers
# -------------------------


def fetch_games_for_date(date_str: str):
    """
    Use ScoreboardV2 to list games for a given date with readable labels.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        return [], f"Invalid date '{date_str}': {e}"

    api_date = dt.strftime("%m/%d/%Y")

    try:
        sb = scoreboardv2.ScoreboardV2(game_date=api_date, day_offset=0)
    except Exception as e:
        return [], f"Error calling scoreboardv2: {e}"

    gh = sb.game_header.get_data_frame()
    ls = sb.line_score.get_data_frame()

    if gh.empty:
        return [], f"No games returned by ScoreboardV2 for {date_str}."

    team_map = {}
    if not ls.empty:
        for _, row in ls.iterrows():
            tid = row.get("TEAM_ID")
            if pd.isna(tid):
                continue
            try:
                tid = int(tid)
            except Exception:
                continue
            city = (row.get("TEAM_CITY_NAME") or "").strip()
            nick = (row.get("TEAM_NICKNAME") or "").strip()
            abbr = (row.get("TEAM_ABBREVIATION") or "").strip()
            name = f"{city} {nick}".strip() if city or nick else abbr or f"Team {tid}"
            team_map[tid] = name

    options = []
    for _, row in gh.iterrows():
        game_id = row["GAME_ID"]

        def norm(x):
            try:
                return int(x)
            except Exception:
                return None

        home_id = norm(row.get("HOME_TEAM_ID"))
        away_id = norm(row.get("VISITOR_TEAM_ID"))

        home_name = team_map.get(home_id) or TEAM_ID_TO_NAME.get(home_id) or "Home"
        away_name = team_map.get(away_id) or TEAM_ID_TO_NAME.get(away_id) or "Away"

        status = (row.get("GAME_STATUS_TEXT") or "").strip()
        tip = (row.get("LIVE_PERIOD_TIME_BCAST") or "").strip()

        label = f"{away_name} @ {home_name}"
        if status:
            label += f" – {status}"
        elif tip:
            label += f" ({tip})"

        options.append({"label": label, "value": game_id})

    msg = f"Loaded {len(options)} game(s) for {date_str}."
    return options, msg


def _fetch_pbp(game_id: str) -> pd.DataFrame:
    """Try PlayByPlayV3 first, fallback to V2."""
    if HAS_PBP_V3:
        try:
            pbp3 = playbyplayv3.PlayByPlayV3(game_id=game_id)
            if hasattr(pbp3, "play_by_play"):
                df3 = pbp3.play_by_play.get_data_frame()
                if df3 is not None and not df3.empty:
                    return df3
        except Exception as e:
            print(f"PlayByPlayV3 failed for {game_id}: {e}")

    try:
        pbp2 = playbyplayv2.PlayByPlayV2(game_id=game_id)
        if hasattr(pbp2, "play_by_play"):
            df2 = pbp2.play_by_play.get_data_frame()
        else:
            dfs = pbp2.get_data_frames()
            df2 = dfs[0] if dfs else pd.DataFrame()

        if df2 is not None and not df2.empty:
            return df2
        raise RuntimeError("Empty play-by-play rows for this game.")
    except Exception as e:
        raise RuntimeError(f"PBP fetch failed for {game_id}: {e}")

# -------------------------
# Callbacks
# -------------------------


@callback(
    Output("pbp-game-dropdown", "options"),
    Output("pbp-status", "children"),
    Input("pbp-load-games", "n_clicks"),
    State("pbp-date", "value"),
    prevent_initial_call=True,
)
def load_games(n_clicks, date_str):
    if not date_str:
        return [], "Please enter a date."
    options, msg = fetch_games_for_date(date_str)
    return options, msg


@callback(
    Output("pbp-data-store", "data"),
    Output("pbp-table", "columns"),
    Output("pbp-table", "data"),
    Output("pbp-status", "children", allow_duplicate=True),
    Input("pbp-fetch", "n_clicks"),
    State("pbp-game-dropdown", "value"),
    State("pbp-game-id-manual", "value"),
    prevent_initial_call=True,
)
def fetch_pbp_and_display(n_clicks, selected_game_id, manual_game_id):
    manual_game_id = (manual_game_id or "").strip()
    game_id = manual_game_id or selected_game_id

    if not game_id:
        return no_update, [], [], "Please select a game or enter a Game ID."

    try:
        df = _fetch_pbp(game_id)
    except Exception as e:
        return {}, [], [], f"Error fetching PBP for {game_id}: {e}"

    if df.empty:
        msg = f"No play-by-play data found for {game_id}."
        return {}, [], [], msg

    if "EVENTNUM" in df.columns:
        df = df.sort_values("EVENTNUM")

    columns = [{"name": c, "id": c} for c in df.columns]
    data = df.to_dict("records")

    # ✅ Store in PostgreSQL
    try:
        rows = ingest_pbp(game_id, save_csv=True)
        status_msg = f"Loaded {len(df)} events for {game_id}. Stored {rows} rows in DB."
    except Exception as e:
        status_msg = f"Loaded {len(df)} events for {game_id}, but DB insert failed: {e}"

    return data, columns, data, status_msg


@callback(
    Output("pbp-download", "data"),
    Output("pbp-csv-path", "children"),
    Input("pbp-download-btn", "n_clicks"),
    State("pbp-data-store", "data"),
    State("pbp-game-dropdown", "value"),
    State("pbp-game-id-manual", "value"),
    prevent_initial_call=True,
)
def download_pbp_csv(n_clicks, pbp_data, selected_game_id, manual_game_id):
    if not pbp_data:
        return no_update, "No data to download. Fetch play-by-play first."

    manual_game_id = (manual_game_id or "").strip()
    game_id = manual_game_id or selected_game_id or "unknown"

    df = pd.DataFrame(pbp_data)
    filename = f"pbp_{game_id}.csv"
    path = os.path.join(DATA_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8")

    return dcc.send_data_frame(df.to_csv, filename, index=False), f"CSV saved at: {path}"
