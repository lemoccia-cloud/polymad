"""
polyMad — Polymarket Weather Analysis CLI

Fetches active weather temperature markets from Polymarket,
compares them against Open-Meteo ensemble forecasts, and ranks
opportunities by expected value using fractional Kelly sizing.

Usage:
    python -m src.main --bankroll 1000
    python -m src.main --bankroll 500 --cities Warsaw Berlin --show-all
    python -m src.main --model gfs025 --edge-threshold 0.08 --rank-by edge
"""
import argparse
import logging
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from config import settings
from src.data.polymarket_client import PolymarketClient, parse_weather_market, PolymarketAPIError
from src.data.weather_client import WeatherClient, CityNotFoundError, WeatherAPIError
from src.analysis import edge_calculator
from src.analysis.kelly import compute_position_size, kelly_summary
from src.models.market import OpportunityResult

console = Console()
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="polyMad — Polymarket weather market edge finder",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--bankroll", type=float, default=1000.0,
        help="Total bankroll in USD for Kelly sizing"
    )
    parser.add_argument(
        "--edge-threshold", type=float, default=settings.EDGE_ALERT_THRESHOLD,
        help="Minimum edge (0–1) to trigger an alert"
    )
    parser.add_argument(
        "--max-markets", type=int, default=50,
        help="Maximum number of markets to analyze"
    )
    parser.add_argument(
        "--rank-by", choices=["expected_value", "edge", "kelly_fraction"],
        default="expected_value",
        help="Metric to sort results by"
    )
    parser.add_argument(
        "--model", choices=["ecmwf_ifs025", "gfs025"],
        default=settings.ENSEMBLE_MODEL,
        help="Ensemble weather model to use"
    )
    parser.add_argument(
        "--show-all", action="store_true",
        help="Show all markets including those below the edge threshold"
    )
    parser.add_argument(
        "--cities", nargs="+", metavar="CITY",
        help="Filter to specific cities only"
    )
    parser.add_argument(
        "--min-liquidity", type=float, default=settings.MIN_LIQUIDITY_USD,
        help="Minimum market liquidity in USD"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    model_label = "ECMWF IFS 0.25°" if args.model == "ecmwf_ifs025" else "GFS 0.25°"

    console.print(
        f"\n[bold cyan]polyMad[/bold cyan] — Polymarket Weather Analysis"
        f"  [dim]{now_str}[/dim]"
    )
    console.print(
        f"[dim]Bankroll: [/dim][bold]${args.bankroll:,.0f}[/bold]"
        f"  [dim]Edge threshold: [/dim][bold]{args.edge_threshold*100:.1f}%[/bold]"
        f"  [dim]Model: [/dim][bold]{model_label}[/bold]\n"
    )

    # Step 1: Fetch weather events from Polymarket (events pagination approach)
    with console.status("[cyan]Fetching Polymarket temperature events...[/cyan]"):
        poly_client = PolymarketClient()
        try:
            raw_market_tuples = poly_client.fetch_weather_markets(
                min_liquidity=args.min_liquidity,
            )
        except PolymarketAPIError as exc:
            console.print(f"[red]Failed to fetch markets: {exc}[/red]")
            sys.exit(1)

    if not raw_market_tuples:
        console.print("[yellow]No temperature markets found.[/yellow]")
        return

    console.print(f"[dim]Found {len(raw_market_tuples)} candidate sub-markets.[/dim]")

    # Step 2: Parse sub-markets
    weather_markets = []
    for tup in raw_market_tuples[:args.max_markets]:
        raw_mkt, event_title, event_end_date = tup[0], tup[1], tup[2]
        event_slug = tup[3] if len(tup) > 3 else ""
        market = parse_weather_market(
            raw_mkt, event_title=event_title, end_date_str=event_end_date, event_slug=event_slug
        )
        if market is None:
            continue
        if args.cities and market.city not in args.cities:
            continue
        weather_markets.append(market)

    if not weather_markets:
        console.print("[yellow]No parseable weather temperature markets found.[/yellow]")
        return

    console.print(f"[dim]Parsed {len(weather_markets)} temperature markets.[/dim]")

    # Step 3: Deduplicate ensemble API calls by (city, date)
    # Build a cache key: (city, date_str) -> WeatherForecast
    forecast_cache: dict = {}
    weather_client = WeatherClient()
    results: list = []

    total = len(weather_markets)
    for i, market in enumerate(weather_markets, 1):
        cache_key = (market.city, market.resolution_date.strftime("%Y-%m-%d"), market.threshold_celsius, market.bucket_type)

        if cache_key not in forecast_cache:
            with console.status(
                f"[cyan]Fetching ensemble forecast for {market.city} "
                f"{market.resolution_date.strftime('%b %d')} "
                f"({i}/{total})...[/cyan]"
            ):
                try:
                    forecast = weather_client.get_ensemble_forecast(
                        city=market.city,
                        resolution_date=market.resolution_date,
                        threshold_celsius=market.threshold_celsius,
                        direction=market.bucket_type,
                        model=args.model,
                    )
                    forecast_cache[cache_key] = forecast
                except CityNotFoundError as exc:
                    console.print(f"[yellow]  Skipping {market.city}: {exc}[/yellow]")
                    continue
                except WeatherAPIError as exc:
                    console.print(f"[yellow]  Weather API error for {market.city}: {exc}[/yellow]")
                    continue

        forecast = forecast_cache[cache_key]

        # Step 4: Compute edge and opportunity
        result = edge_calculator.analyze_market(market, forecast)
        results.append(result)

    if not results:
        console.print("[yellow]No results after analysis.[/yellow]")
        return

    # Step 5: Rank opportunities
    ranked = edge_calculator.rank_opportunities(results, by=args.rank_by)

    # Add results below threshold if --show-all
    if args.show_all:
        ranked_ids = {id(r) for r in ranked}
        below = sorted(
            [r for r in results if id(r) not in ranked_ids],
            key=lambda r: r.expected_value,
            reverse=True,
        )
        all_results = ranked + below
    else:
        all_results = ranked

    # Step 6: Render output
    render_table(all_results, args.bankroll, args.edge_threshold)
    if ranked:
        render_alerts(ranked, args.bankroll)

    # Summary
    alert_count = sum(1 for r in results if r.alert)
    console.print(
        f"\n[dim]{len(results)} markets analyzed | "
        f"{len(ranked)} with positive EV | "
        f"{alert_count} alert(s)[/dim]\n"
    )


def render_table(results: list, bankroll: float, edge_threshold: float) -> None:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_footer=False,
        header_style="bold dim",
        row_styles=["", "dim"],
    )

    table.add_column("City", style="bold", min_width=12)
    table.add_column("Date", min_width=6)
    table.add_column("Threshold", justify="right", min_width=9)
    table.add_column("Dir", justify="center", min_width=5)
    table.add_column("Mkt Prob", justify="right", min_width=8)
    table.add_column("Model Prob", justify="right", min_width=10)
    table.add_column("Edge", justify="right", min_width=7)
    table.add_column("EV/$1", justify="right", min_width=7)
    table.add_column("Kelly%", justify="right", min_width=7)
    table.add_column("Bet $", justify="right", min_width=7)
    table.add_column("Members", justify="right", min_width=7)
    table.add_column("", min_width=4)  # Alert column

    for result in results:
        m = result.market
        f = result.forecast

        edge_pct = result.edge * 100
        mkt_pct = m.market_implied_prob * 100
        model_pct = f.model_probability * 100
        ev = result.expected_value
        kelly_pct = result.suggested_bet_fraction * 100
        bet_usd = compute_position_size(bankroll, result.kelly_fraction)

        # Edge color
        if result.edge > edge_threshold:
            edge_str = Text(f"+{edge_pct:.1f}%", style="bold green")
        elif result.edge > 0.01:
            edge_str = Text(f"+{edge_pct:.1f}%", style="yellow")
        elif result.edge >= 0:
            edge_str = Text(f"+{edge_pct:.1f}%", style="dim")
        else:
            edge_str = Text(f"{edge_pct:.1f}%", style="red dim")

        # EV color
        if ev > 0.1:
            ev_str = Text(f"+${ev:.3f}", style="bold green")
        elif ev > 0:
            ev_str = Text(f"+${ev:.3f}", style="green")
        else:
            ev_str = Text(f"${ev:.3f}", style="red dim")

        # Kelly / bet
        if kelly_pct >= 1.0:
            kelly_str = Text(f"{kelly_pct:.1f}%", style="cyan")
            bet_str = Text(f"${bet_usd:.0f}", style="bold cyan")
        else:
            kelly_str = Text("—", style="dim")
            bet_str = Text("—", style="dim")

        # Alert
        alert_str = Text("[!]", style="bold yellow") if result.alert else Text("")

        # Direction icon
        dir_icon = "↑" if m.direction == "above" else "↓"

        table.add_row(
            m.city,
            m.resolution_date.strftime("%b %d"),
            f"{m.threshold_celsius:+.0f}°C",
            dir_icon,
            f"{mkt_pct:.0f}%",
            f"{model_pct:.0f}%",
            edge_str,
            ev_str,
            kelly_str,
            bet_str,
            str(f.ensemble_member_count) if f.ensemble_member_count > 1 else "det.",
            alert_str,
        )

    console.print(table)


def render_alerts(results: list, bankroll: float) -> None:
    alerts = [r for r in results if r.alert]
    if not alerts:
        return

    console.print("[bold yellow]ALERTS — High Edge Opportunities[/bold yellow]")
    console.print("─" * 64)

    for result in alerts:
        m = result.market
        f = result.forecast
        bet_usd = compute_position_size(bankroll, result.kelly_fraction)
        ks = kelly_summary(result.kelly_fraction, bankroll)

        console.print(
            f"[bold yellow][!][/bold yellow] [bold]{m.city.upper()}[/bold] "
            f"{m.resolution_date.strftime('%b %d')}  |  {m.question}"
        )
        console.print(
            f"    Market: [dim]{m.market_implied_prob*100:.0f}%[/dim]  "
            f"Model ({f.ensemble_member_count} members): [bold green]{f.model_probability*100:.0f}%[/bold green]  "
            f"Edge: [bold green]+{result.edge*100:.1f}%[/bold green]  "
            f"EV: [bold green]+${result.expected_value:.3f}/$1[/bold green]"
        )
        if bet_usd > 0:
            console.print(
                f"    Suggested: [bold cyan]${bet_usd:.0f}[/bold cyan] "
                f"({ks['capped_kelly']*100:.1f}% of ${bankroll:,.0f} bankroll, "
                f"quarter-Kelly)"
            )
        console.print(
            f"    Liquidity: ${m.liquidity_usd:,.0f}  |  "
            f"Volume: ${m.volume_usd:,.0f}  |  "
            f"Expires: {m.end_date.strftime('%Y-%m-%dT%H:%MZ')}"
        )
        console.print()


if __name__ == "__main__":
    args = parse_args()
    run(args)
