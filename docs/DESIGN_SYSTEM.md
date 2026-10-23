# Sistema de diseño: panel Aurum

Fuente única: `dashboard/static/index.html` (CSS en `<style>`, iconos en el sprite `<svg>`). Nace de la
recomendación de la skill `ui-ux-pro-max` para un "fintech trading dashboard": estilo oscuro tipo OLED,
verde y rojo semánticos, Fira Sans + Fira Code, iconos SVG. Aplica en CSS propio los principios de
`ui-styling` (tokens, accesibilidad, composición), sin React ni Tailwind
([ADR 0005](adr/0005-panel-stdlib.md)).

## Principios

1. **Los datos primero.** Las cifras van en Fira Code con números tabulares; el color solo dice
   dirección o estado, nunca es decoración.
2. **El color con significado.** Verde = alcista, compra o abierto; rojo = bajista o venta; ámbar =
   advertencia; dorado = marca y foco; celeste = información.
3. **Sin emojis.** Todo icono sale del sprite SVG (`<svg class="i"><use href="#i-…"/></svg>`). El texto
   que llega del motor pasa por `noEmoji()`.
4. **El movimiento informa.** El destello del botón indica la fuerza de la señal. Todo se apaga con
   `prefers-reduced-motion`.

## Tokens (`:root`)

| Grupo | Token | Valor | Uso |
|---|---|---|---|
| Fondo | `--bg` / `--bg-2` | `#060a16` / `#0b1122` | Página / pozos (barras, medidores) |
| Superficie | `--surface` / `--surface-2` | `#0f172a` / `#141d33` | Tarjetas / elementos elevados, seleccionados |
| Línea | `--line` / `--line-2` | `#1f2a44` / `#2b3958` | Bordes / bordes en hover |
| Texto | `--ink` / `--ink-2` / `--muted` | `#e8edf7` / `#b4bfd6` / `#7c89a8` | Principal / secundario / etiquetas |
| Marca | `--gold` / `--gold-2` / `--gold-ink` | `#e9b949` / `#f6d78a` / `#1a1302` | Foco, pestaña activa, numeración |
| Alcista | `--up` / `--up-2` / `--up-soft` | `#22c55e` / `#16a34a` / 12 % | Compra, abierto |
| Bajista | `--down` / `--down-2` / `--down-soft` | `#f43f5e` / `#e11d48` / 12 % | Venta, error |
| Estado | `--warn` / `--info` (+ `-soft`) | `#f59e0b` / `#38bdf8` | Riesgo elevado / avisos |
| Radio | `--r-sm` / `--r` / `--r-lg` | 8 / 12 / 16 px | Chips y controles / botones / tarjetas |
| Movimiento | `--ease` | `cubic-bezier(.2,.8,.2,1)` | Entradas y hover (150–300 ms) |
| Tipografía | `--f-sans` / `--f-mono` | Fira Sans / Fira Code + respaldo del sistema | Texto / cifras |

**Escala tipográfica:** 11 · 12 · 13 · 14 · 15 (base) · 16 · 18 · 19 · 22 · 26 px, con títulos
`clamp(24px, 3.2vw, 34px)`. Pesos 400 / 500 / 600 / 700.

## Componentes

### Botón de acción (`.act`)

| Variante | Clase | Cuándo |
|---|---|---|
| Compra fuerte | `.act.bull.strong` | Señal completa alcista: destello verde de 1.2 s |
| Compra suave | `.act.bull.weak` | Solo sesgo alcista: "respiración" de 2.8 s |
| Venta fuerte / suave | `.act.bear.strong` / `.weak` | Lo mismo en rojo |
| Deshabilitado | `:disabled` | Mercado cerrado o sin dirección |

**Estados:**
- **Hover:** `brightness(1.1)`.
- **Activo:** `scale(.98)`.
- **Foco:** contorno dorado de 2 px.
- **Cargando:** el texto pasa a "Enviando…" y el botón queda deshabilitado.

**Accesibilidad:** es un `<button>` nativo, se activa con Enter o Espacio y el texto dice la acción.

### Tarjeta de activo (`.card`)

- **Estructura:** símbolo + nombre; chip Abierto / Cerrado; precio (verde o rojo según el último
  tick); estadísticas; medidor del score con marcas en ±umbral; botón; plan (lote, riesgo, SL, TP);
  probabilidad del modelo; patrones; filtros activos.
- **Variantes:** `.bull` y `.bear` agregan un borde superior de color.
- **Estados especiales:** "No disponible en tu broker" y el mensaje de error.
- **Hover:** sube 2 px.

### Chip (`.chip`)

- **Variantes:** `.up`, `.down`, `.warn`, `.gold` y neutro.
- **Opcional:** un `.dot` delante.
- **Uso:** solo para estado o categoría, nunca como botón.

### Control segmentado (`.seg`)

Grupo de botones con `aria-pressed`. Se usa para el modo (Swing / Scalping) y la clase de activo.

### Avisos

| Componente | Clase | Uso |
|---|---|---|
| Nota | `.note.warn` / `.note.info` | Dentro del modal y sobre las tarjetas (p. ej. "Sin ventaja probada") |
| Toast | `.toast.ok` / `.toast.err` | Resultado de una orden; `aria-live="polite"`; se cierra a los 9 s |
| Banner | `.banner` | Error global (MT5 caído, servidor sin respuesta); `role="alert"` |
| Modal | `.modal` > `.dialog` | Confirmación de la orden; `role="dialog"`, `aria-modal`; se cierra con Esc o clic fuera; el foco va al botón Confirmar |

### Sesión de mercado (`.srow`)

- **Estructura:** nombre y descripción; barra de 24 h en hora local (`.track` con `.band` en
  dorado); marca de la hora actual (`.now`); chip Abierta / Cerrada con "abre / cierra … · en N".
- **Fuente de los horarios:** se calculan con zonas IANA; la hora mostrada es siempre la del sistema.

### Esqueleto de carga (`.skel`)

Brillo animado mientras llega el primer análisis.

## Patrones

- **Navegación:** barra superior fija con `aria-current="page"` en la sección activa; el reloj del
  sistema a la derecha.
- **Datos externos:** se escapan siempre con `esc()`; los enlaces de noticias abren en otra pestaña con
  `rel="noopener noreferrer"`.
- **Responsive:** la rejilla usa `auto-fill` y `minmax(min(300px, 100%), 1fr)`; por debajo de 760 px
  las columnas se apilan, se oculta la regla de horas y los márgenes laterales quedan en 16 px.
  Verificado a 1440 y 375 px.

## Auditoría (2026-10-16)

| Categoría | Definidos | Valores fijos encontrados fuera de tokens |
|---|---|---|
| Colores | 28 tokens | 5 hex de texto sobre fondos de color (`#04150a`, `#fff`, `#fde3b0`, `#cdeefe`, `#ffd3db`), 25 `rgba()` de sombras y halos, 2 hex en el JS de las velas |
| Tipografía | 2 familias | 10 tamaños en px sin token |
| Espaciado | — | Valores en px directos (sin escala) |

**Acciones prioritarias:**
1. Pasar los 5 colores de texto sobre color a tokens `--on-up`, `--on-down`, `--on-warn`, `--on-info`
   y `--on-danger`.
2. Definir una escala `--s-1…--s-6` (4 / 8 / 12 / 16 / 20 / 24 px) y usarla en paddings y gaps.
3. Pasar los tamaños de texto a `--t-xs…--t-xl`.
