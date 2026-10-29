# NBA Bets 🏀

App que analiza los partidos de la NBA del día y te dice **a qué apostar**: ganador (moneyline),
hándicap (spread), over/under de puntos y **player props** (puntos, rebotes, asistencias, triples y PRA).

Solo recomienda una apuesta cuando la probabilidad estimada da **valor esperado positivo** (EV) frente
a la cuota de la casa, y te sugiere cuánto apostar con el criterio de Kelly fraccional.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # y pon tu ODDS_API_KEY (opcional pero recomendado)
```

## Uso

```bash
python -m nba_bets serve                 # panel web en http://localhost:8000
python -m nba_bets picks                 # recomendaciones de hoy en la terminal
python -m nba_bets picks --props         # incluye player props (más lento)
python -m nba_bets picks --date 2026-11-02 --no-tips
```

El panel tiene cuatro pestañas: **Mejores apuestas**, **Partidos** (proyección, mercados, lesiones,
pronósticos de tipsters), **Player props** y **Fuentes** (qué fuentes respondieron).

## Fuentes de datos

| Fuente | Qué aporta | Clave |
|---|---|---|
| ESPN (API pública) | Calendario, resultados, cuotas de referencia, lesiones | No |
| stats.nba.com (`nba_api`) | Rating ofensivo/defensivo, ritmo, game logs de jugadores | No |
| [The Odds API](https://the-odds-api.com) | Cuotas de muchas casas (elige la mejor) y **líneas de player props** | Sí (plan gratis: 500 peticiones/mes) |
| sportsgambler.com / scores24.live | Pronósticos de tipsters como "segunda opinión" | No (scraping) |

Sin `ODDS_API_KEY` la app funciona con las cuotas de ESPN, y los props se muestran como
**proyecciones** (puntos, rebotes… esperados) para que las compares con la línea de tu casa.

## Cómo decide

1. **Proyección del partido**: posesiones × rating ofensivo × (rating defensivo rival / media liga),
   mezclando temporada (65%) y últimos 10 partidos (35%). A principio de temporada pesa más la
   temporada anterior. Ajustes por ventaja de campo (+2.3), back-to-back (−1.5) y bajas ("Out").
2. **Probabilidades**: margen ~ Normal(σ=12.5) y total ~ Normal(σ=18) → P(gana), P(cubre hándicap), P(over).
3. **Mezcla con el mercado**: `prob = MODEL_WEIGHT·modelo + (1−MODEL_WEIGHT)·mercado sin margen`.
   El mercado es muy eficiente; mezclar evita que el modelo vea "valor" donde no lo hay.
4. **Tipsters**: cada web que coincide suma +1.5 puntos de probabilidad (máx. ±3).
5. **Recomendación** si `EV = prob × cuota − 1 ≥ MIN_EDGE` (3% por defecto). Stake = Kelly × 0.25, máx. 3% del bankroll.
6. **Props**: media ponderada (últimos 5, temporada actual, temporada anterior) ajustada por defensa y
   ritmo del rival; Normal para puntos/rebotes/asistencias y Poisson para triples. Se muestra cuántas
   de las últimas 10 veces superó la línea.

Todo se ajusta en `.env` (ver `.env.example`).

## Avisos

- stats.nba.com a veces bloquea IPs de servidores en la nube; en tu ordenador suele funcionar.
- El scraping de sportsgambler/scores24 es "best effort": respeta `robots.txt`, cachea 30 min y puede
  dejar de funcionar si cambian su web. Revisa sus términos de uso.
- Las apuestas de un mismo partido (p. ej. ganador y hándicap del mismo equipo) están correlacionadas;
  no las sumes como si fueran independientes.
- Es una herramienta informativa: **ningún modelo garantiza beneficios**. Apuesta con responsabilidad. +18.

## Tests

```bash
python -m pytest
```
