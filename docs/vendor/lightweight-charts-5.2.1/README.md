# Lightweight Charts 5.2.1

The unmodified production standalone browser bundle is self-hosted at `src/trading-panel/lightweight-charts-5.2.1.js`. It includes its dependencies and exports `window.LightweightCharts`; no CDN or remote chart frame is used by the exchange chart renderer.

Source: [official v5.2.1 release](https://github.com/tradingview/lightweight-charts/releases/tag/v5.2.1), published `lightweight-charts@5.2.1` npm archive. The archive's SHA-512 npm integrity was verified before copying its bundle and license. `lightweight-charts-provenance.json` records the fixed source URL, integrity and bundle SHA-256. The matching release tag supplied NOTICE, which the npm archive does not include.

Preserve `lightweight-charts-LICENSE.txt` and `lightweight-charts-NOTICE.txt` when redistributing these files. The renderer displays the NOTICE attribution and a link to TradingView on each chart, following the [official attribution requirement](https://tradingview.github.io/lightweight-charts/docs#attribution).

Load `/lightweight-charts-5.2.1.js`, then `/exchange-chart.js`, then the grid controller. The engine only renders the existing normalized public exchange data; it does not fetch market data or send orders. The wrapper calculates optional EMA20/50 and rolling turnover/base-volume VWAP60.
