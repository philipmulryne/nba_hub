# hub.py

import os
from dash import Dash, html, dcc, Input, Output
import dash_bootstrap_components as dbc

from apps import nba_pbp_ingest  # import your first sub-app

# Ensure data directory exists
os.makedirs("data/pbp", exist_ok=True)

external_stylesheets = [dbc.themes.DARKLY]

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=external_stylesheets,
    title="Basketball Analytics Hub",
)

app.layout = dbc.Container(
    fluid=True,
    children=[
        dcc.Location(id="url", refresh=False),

        # Top bar
        dbc.Navbar(
            dbc.Container(
                [
                    dbc.NavbarBrand("Basketball Analytics Hub", className="ms-2"),
                    dbc.Nav(
                        [
                            dbc.NavLink("NBA PBP Ingest", href="/nba-pbp", active="exact"),
                            # Future apps:
                            # dbc.NavLink("Shot Charts", href="/shot-charts", active="exact"),
                            # dbc.NavLink("Lineups", href="/lineups", active="exact"),
                        ],
                        className="ms-auto",
                        navbar=True,
                    ),
                ],
                fluid=True,
            ),
            color="primary",
            dark=True,
            className="mb-3",
        ),

        # Page content
        html.Div(id="page-content", className="mt-2"),
    ],
)


@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def display_page(pathname):
    if pathname == "/nba-pbp":
        return nba_pbp_ingest.layout
    # future paths:
    # elif pathname == "/shot-charts": return shot_charts.layout
    # default
    return html.Div(
        [
            html.H3("Welcome to the Basketball Analytics Hub"),
            html.P(
                "Use the navigation above to access tools like NBA play-by-play ingestion. "
                "This hub is designed so you can plug in new analytics apps incrementally."
            ),
        ],
        className="text-light",
    )


if __name__ == "__main__":
    # Run the hub (gunicorn/uvicorn can import 'app' for production)
    app.run(debug=True, host="0.0.0.0", port=8030)
