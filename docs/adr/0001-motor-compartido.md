# ADR 0001: Un solo motor compartido, comportamiento por config

## Estado
Aceptado

## Fecha
2026-06 (refactor estructural), vigente al 2026-10-16

## Contexto
El bot nació para el oro y se copió para EUR/USD y para los modos swing y scalping. Con cuatro
copias, cada corrección había que hacerla cuatro veces, y las copias se iban separando sin que
nadie lo decidiera. Además, el panel y el backtest tienen que ver **exactamente** las mismas señales
que el bot en vivo; si no, el backtest mide otra cosa.

## Decisión
Toda la lógica vive una sola vez en `bot_engine/`. Cada bot es una carpeta que solo tiene
`config.py` y un `main.py` mínimo, que pone su carpeta primero en `sys.path`. El motor lee la
configuración con `from config import …`. Lo que tenga que ser distinto entre bots se resuelve con
una clave de config (`USE_*`, pesos, escalas), nunca con una bifurcación del código. El panel y el
backtest importan ese mismo motor.

## Alternativas consideradas
- **Copias por bot.** Ya era la situación de partida y causó divergencias. Se descartó.
- **Clases con herencia por instrumento.** Ocultan las diferencias en subclases y no resuelven que el
  backtest use el mismo código. Se descartó.

## Consecuencias
- Corregir algo una vez arregla los 4 bots, el panel y el backtest.
- Un proceso equivale a un config. Para operar varias clases a la vez, el panel arranca un proceso
  por perfil ([ADR 0003](0003-perfiles-por-clase.md)).
- Si una clave nueva se importa sin `getattr`, hay que agregarla a los 4 `config.py`, o esos bots
  fallan al importar.
