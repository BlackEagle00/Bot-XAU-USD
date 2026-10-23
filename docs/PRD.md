# PRD: Bots de trading MT5 y panel Aurum

| | |
|---|---|
| Estado | Vigente, v3 (2026-10-16) |
| Dueño | Usuario del repositorio |
| Fuente de requisitos | Pedidos del usuario en las sesiones de auditoría v1, v2 y v3 |

## 1. Resumen ejecutivo

**Problema.** El bot original operaba solo oro con un config pensado para cuentas grandes. En la
auditoría de 3 años, todas las temporalidades acertaban alrededor del 50 %. Con 100 USD casi no operaba
(el lote mínimo arriesgaba más del 1 %), y el panel analizaba todos los activos con los parámetros del oro.

**Solución.** Un motor compartido con perfiles independientes por clase de activo, calibrados con
walk-forward, más:
- un filtro predictivo que solo se activa donde demuestra ventaja fuera de muestra;
- una gestión de riesgo que se adapta al capital;
- un panel local para operar con un clic, con noticias y horarios en la hora del sistema.

**Criterios de éxito (medibles):**
1. Al menos una combinación de activo y temporalidad con **≥ 75 % de acierto fuera de muestra y
   PF > 1**. Los modelos que no cumplan no se guardan.
2. Una cuenta de **100 USD puede operar** al menos divisas, plata y acciones, con riesgo ≤ 5 % por
   operación avisado en pantalla.
3. **Cero órdenes en cuenta real** sin `ALLOW_LIVE_TRADING=1`, y cero órdenes del panel sin token
   válido (probado en tests).
4. Cada perfil muestra en el panel su PF fuera de muestra, y los que no tienen ventaja se marcan.
5. Todo lo que cambia el motor deja `python tests/test_engine.py` en verde.

## 2. Experiencia de usuario y funcionalidad

**Personas**
- **Trader individual con cuenta pequeña** (100–1 000 USD, en demo). Quiere ver qué activos van al
  alza o a la baja y abrir con un clic sin calcular lotes.
- **Operador técnico** (el mismo usuario con otro rol). Ajusta configs, corre backtests y audita resultados.

**Historias y criterios de aceptación**

| # | Historia | Criterios de aceptación |
|---|---|---|
| H1 | Como trader, quiero ver tarjetas por activo con la dirección actual para decidir rápido. | Pestañas Divisas / Metales / Acciones / Cripto (ETF) y Swing / Scalping; el botón destella fuerte con señal completa y suave con sesgo; se actualiza cada ~4 s. |
| H2 | Como trader, quiero abrir la operación con un clic. | Un modal muestra lote, SL, TP y riesgo en USD y en %; al confirmar aparece "Se ha realizado la apertura de una operación BUY/SELL…" con el ticket; las compuertas son las mismas que en el bot. |
| H3 | Como trader con 100 USD, quiero operar aunque el riesgo suba. | Si el lote mínimo arriesga entre 1 % y 5 %, se opera con aviso "riesgo elevado" y el capital necesario para volver al 1 %; por encima del 5 %, no se opera y se explica por qué. |
| H4 | Como trader, quiero saber qué pasa en el mundo financiero. | Sección Noticias con 3 fuentes y calendario; si una fuente falla, las demás siguen y se avisa "no disponible". |
| H5 | Como trader, quiero saber qué mercados están abiertos ahora. | El Inicio muestra 6 sesiones con barra de 24 h y "abre / cierra en…", todo en la hora del sistema (zona IANA del equipo). |
| H6 | Como operador, quiero saber si la configuración actual gana dinero. | `engine_backtest.py` y `calibrate.py` reportan solo resultados fuera de muestra; el panel muestra "Sin ventaja probada" cuando el PF ≤ 1. |
| H7 | Como operador, quiero que cada clase de activo tenga su propio modelo. | Hay 6 perfiles `<clase>_<modo>` independientes; calibrar uno no cambia los otros. |
| H8 | Como usuario nuevo, quiero entender el bot. | Secciones Acerca del bot, Velas japonesas, Conceptos clave y Soporte, sin emojis y en español. |

**No objetivos**
- Operar en cuenta real de forma automática. Exige una decisión explícita del usuario.
- Acceso remoto o multiusuario al panel.
- Garantizar rentabilidad. El sistema mide y declara; no promete.
- Una app móvil. Telegram cubre los avisos.

## 3. Requisitos del sistema predictivo

- **Herramientas:** scikit-learn (`HistGradientBoostingClassifier`), histórico de MT5 (3 años) y
  multiprocessing para generar las señales.
- **Evaluación:**
  - Walk-forward trimestral anclado con purga; τ se elige en validación (`VAL_WIN=0.80`).
  - Se reportan acierto, PF, expectativa en R, drawdown y Monte Carlo (percentil 95 del drawdown)
    con 100, 1 000 y 10 000 USD.
  - Un modelo solo se guarda si el resultado fuera de muestra da acierto ≥ 75 % y PF > 1.
- **Integridad:** SHA-256 en `models/manifest.json`.

## 4. Especificaciones técnicas

- **Arquitectura:** [ARCHITECTURE.md](ARCHITECTURE.md).
- **Integraciones:**
  - MetaTrader 5 (paquete Python, terminal local).
  - RSS de Google Noticias, CNBC e Investing.com.
  - JSON semanal de ForexFactory.
  - Telegram Bot API (opcional).
- **Seguridad y privacidad:** [../SECURITY.md](../SECURITY.md). Las credenciales viven solo en el
  `.env`; el panel solo escucha en `127.0.0.1`.

## 5. Riesgos y hoja de ruta

**Riesgos**

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Sobreajuste: 3 años de mercado mayormente alcista | Resultados en vivo peores que en el backtest | Walk-forward con purga, mínimo de operaciones por ventana, seguimiento en vivo (v3.4) |
| Riesgo elevado de 5 % por operación | 10 pérdidas seguidas ≈ −40 % | Aviso visible, nivel Micro con 1 operación, corte diario de cuenta del 10 % |
| Feeds de terceros | Noticias faltantes o cambios de formato | Fuentes independientes, fallo aislado, parser estricto |
| Histórico M5 limitado (~17 meses) | Scalping M5 poco validado | M5 queda fuera de la calibración; paso documentado para ampliar las barras |
| Perfiles sin ventaja (divisas y acciones en swing, PF fuera de muestra < 1) | Pérdidas si se opera por señal | Marca "Sin ventaja probada"; hoja de ruta abajo |

**Hoja de ruta: opciones de mejora de efectividad**

| Fase | Mejora | Por qué |
|---|---|---|
| v3 (hecho) | Perfiles por clase y calibración walk-forward | Cada clase deja de usar los parámetros del oro. |
| v3.1 | **Parámetros y modelos por símbolo** dentro de cada clase, con un mínimo de operaciones | USDJPY y EURUSD, o NVDA y MSFT, se comportan distinto aunque sean de la misma clase. |
| v3.1 | **Filtro de sesión** (operar solo Londres–Nueva York en divisas y solo la sesión regular en acciones) | La mayor parte del volumen y de los movimientos limpios ocurre en esas horas; fuera de ellas sube el spread relativo. |
| v3.2 | **Detector de régimen** (tendencia, rango o volatilidad alta) que cambia de parámetros | El motor sigue tendencias y pierde en rangos; el ADX solo es una primera aproximación. |
| v3.2 | **Tamaño por volatilidad objetivo** en lugar de riesgo fijo | Iguala el riesgo entre activos tranquilos y explosivos. |
| v3.2 | **Límite de exposición correlacionada** (oro, plata, EURUSD contra el dólar) | Varias operaciones en la misma dirección del dólar equivalen a una sola apuesta grande. |
| v3.3 | **Reentrenamiento periódico automático** con walk-forward (mensual) | Los modelos envejecen; hoy se reentrenan a mano. |
| v3.3 | **Ensamble** (gradient boosting + regresión logística + reglas) con votación | Reduce la varianza del filtro y la dependencia de un solo modelo. |
| v3.4 | **Métricas en vivo contra backtest** (acierto y PF móviles por perfil, con alerta de degradación) | Detecta pronto cuando la realidad se aparta de lo esperado. |
| v3.4 | Separar el JS del panel en `static/app.js` y agregar pruebas de interfaz | El archivo único crece con cada sección. |
