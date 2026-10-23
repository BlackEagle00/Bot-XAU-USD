# ADR 0005: Panel web local solo con librería estándar

## Estado
Aceptado

## Fecha
2026-10

## Contexto
El usuario pidió un panel con tarjetas por activo, un botón que destella con la dirección y que
abra órdenes al hacer clic, además de noticias y horarios de mercado. El panel puede abrir órdenes,
así que cualquier dependencia o script remoto es superficie de ataque. Corre en la misma PC que MT5.

## Decisión
- **Servidor.** `http.server` (ThreadingHTTPServer), escuchando solo en `127.0.0.1:8765`.
- **Página.** Una sola `static/index.html` con CSS y JS propios, sin frameworks ni CDN de scripts.
  Las únicas fuentes externas permitidas por la CSP son las de Google Fonts.
- **Noticias.** `urllib` + `xml.etree`, con límites de tamaño y rechazo de DOCTYPE/ENTITY.
- **Órdenes.** Exigen un token por sesión, inyectado en la página, más Host y Origin locales, lista
  blanca de símbolos y una orden por activo cada 5 s.
- **Diseño.** Se aplican las guías de las skills `ui-ux-pro-max` y `ui-styling` (tokens, foco
  visible, reduced-motion, iconos SVG sin emojis) en CSS propio. Ver
  [`../DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md).

## Alternativas consideradas
- **React + Tailwind + shadcn/ui** (lo que asume `ui-styling`). Necesita Node, un build y
  dependencias de npm para una sola página local. Se descartó.
- **Flask o FastAPI.** Suman dependencias sin aportar nada a este tamaño.

## Consecuencias
- Cero dependencias nuevas y nada que compilar.
- Toda la página está en un archivo grande. Si crece mucho, conviene separar el JS en `static/app.js`.
- Si Google Fonts no carga, la página usa las fuentes del sistema.
