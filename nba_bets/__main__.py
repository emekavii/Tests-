"""Uso:
    python -m nba_bets serve [--port 8000]       # panel web en http://localhost:8000
    python -m nba_bets picks [--date AAAA-MM-DD] [--props] [--no-tips]
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import engine

MARKET_ES = {"moneyline": "Ganador", "spread": "Hándicap", "total": "Over/Under", "prop": "Player prop"}


def print_picks(data: dict) -> None:
    print(f"\nNBA · {data['date']} · temporada {data['season']}")
    print("Fuentes:", ", ".join(f"{k}={v}" for k, v in data["sources"].items()))
    for g in data["games"]:
        p = g["projection"]
        print(f"\n{g['away_name']} @ {g['home_name']}  [{g['status']}]")
        print(f"  Proyección: {g['away']} {p['away_pts']} - {g['home']} {p['home_pts']}  "
              f"(total {p['total']}, prob. local {p['p_home_win']:.0%})")
        outs = [f"{i['player']} ({i['status']})" for i in g["injuries"]]
        if outs:
            print("  Lesiones:", ", ".join(outs))
        for t in g["tips"]:
            print(f"  Tip {t['source']}: {t['market']} {t['selection']} {t['point'] or ''}")
        for m in g["markets"]:
            flag = "★" if m["recommended"] else " "
            print(f"  {flag} {m['label']:<45} cuota {m['odds']:<6} prob {m['prob']:.1%}  EV {m['ev']:+.1%}")
        for pr in g["props"]:
            if pr.get("line") is None:
                print(f"    {pr['player']}: " + ", ".join(f"{k} {v}" for k, v in pr["projections"].items()))
            else:
                flag = "★" if pr["recommended"] else " "
                print(f"  {flag} {pr['label']:<45} cuota {pr['odds']:<6} proy {pr['projection']}  EV {pr['ev']:+.1%}")

    print("\n=== MEJORES APUESTAS ===")
    if not data["top_picks"]:
        print("Ninguna apuesta supera el umbral de valor hoy. No apostar también es una decisión.")
    for i, m in enumerate(data["top_picks"][:10], 1):
        print(f"{i:>2}. [{MARKET_ES.get(m['market'], m['market'])}] {m['label']} @ {m['odds']} "
              f"({m.get('book', '')}) · EV {m['ev']:+.1%} · stake {m['stake']} · confianza {m.get('confidence', '-')}")
    print("\nApuesta con responsabilidad. Ningún modelo garantiza beneficios.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="nba_bets")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="Arranca el panel web")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    picks = sub.add_parser("picks", help="Muestra las recomendaciones en la terminal")
    picks.add_argument("--date", help="AAAA-MM-DD (por defecto hoy, hora de Nueva York)")
    picks.add_argument("--props", action="store_true", help="Incluir player props (más lento)")
    picks.add_argument("--no-tips", action="store_true", help="No consultar webs de tipsters")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("nba_bets.api:app", host=args.host, port=args.port)
    else:
        day = date.fromisoformat(args.date) if args.date else datetime.now(ZoneInfo("America/New_York")).date()
        print_picks(engine.analyze_day(day, with_props=args.props, with_tips=False if args.no_tips else None))


if __name__ == "__main__":
    main()
