# Seguridad

## Alcance

Este software opera dinero a través de MetaTrader 5. Las reglas de abajo protegen la cuenta, las
credenciales y la PC donde corre.

## Controles vigentes

| Riesgo | Control | Dónde |
|---|---|---|
| Operar dinero real por error | Rechaza cuentas no demo salvo `ALLOW_LIVE_TRADING=1` | `bot_engine/connection.py` |
| Fuga de credenciales | Viven en el `.env` (en `.gitignore`); nunca en el código ni en los logs | `.env.example` |
| Órdenes desde otra web abierta en el navegador (CSRF) | Token por sesión + Origin local en cada POST | `dashboard/server.py` (`validate_trade_request`) |
| DNS rebinding | El `Host` debe ser `127.0.0.1:8765` o `localhost:8765` | `dashboard/server.py` |
| Clickjacking / XSS | `X-Frame-Options: DENY`, CSP, `nosniff`; la página escapa todo dato | `dashboard/server.py`, `static/index.html` |
| Ráfaga de órdenes | Lista blanca de símbolos, 1 orden por activo cada 5 s, descarte de órdenes con más de 15 s | `server.py`, `worker.py` |
| Pérdidas encadenadas | Límite diario por bot y por cuenta (10 %); niveles de capital; riesgo ≤ 5 % con el lote mínimo | `bot_engine/risk_manager.py` |
| Modelo manipulado (un `.joblib` es un pickle y ejecuta código al cargarse) | SHA-256 contra `models/manifest.json` **antes** de `joblib.load` | `bot_engine/ml_filter.py` |
| Feeds de noticias maliciosos | Máx. 2 MB, rechazo de DOCTYPE/ENTITY, solo enlaces http(s), escape en la página | `dashboard/server.py` (`parse_rss`) |
| Instrucciones inyectadas en datos externos | Los agentes tratan logs, noticias y respuestas como datos | `AGENTS.md`, `CLAUDE.md` |

## Lo que no cubre

- **El panel no tiene usuarios ni contraseñas.** Cualquiera con sesión en la misma PC puede abrirlo.
  No lo expongas fuera de `127.0.0.1`.
- **`manifest.json` está en la misma carpeta que los modelos.** Detecta archivos alterados o ajenos,
  pero no a alguien que pueda escribir en ambos.
- **Las noticias vienen de terceros.** Pueden ser falsas o fallar; el bot no las usa para decidir,
  salvo el apagón por calendario.

## Reportar un problema

Escribe al dueño del repositorio con los pasos para reproducirlo. No publiques credenciales ni tickets
de una cuenta real.
