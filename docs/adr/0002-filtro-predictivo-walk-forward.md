# ADR 0002: Filtro predictivo con meta-labeling y validación walk-forward

## Estado
Aceptado

## Fecha
2026-10

## Contexto
La auditoría v1 mostró aciertos cercanos al 50 % en todas las temporalidades. El usuario pidió
subir el acierto por encima del 75 % en algunas de ellas **ganando dinero**. Un modelo evaluado con
los mismos datos con que se entrenó promete aciertos que después no se cumplen en vivo.

## Decisión
- **Qué decide el modelo.** No reemplaza la señal: decide si se toma (meta-labeling).
  `ml_filter.features()` es la misma función en el backtest y en vivo. Un
  `HistGradientBoostingClassifier` estima la probabilidad de que el precio toque el TP antes que el SL.
- **Validación.** Walk-forward trimestral anclado, con **purga**: no se entrena con operaciones que
  terminan dentro del periodo de prueba. El umbral τ se elige en una ventana de validación
  (`VAL_WIN=0.80`).
- **Cuándo se guarda un modelo.** Solo si **fuera de muestra** logra ≥ 75 % de acierto con PF > 1.
  Si no lo logra, se borra el archivo viejo.
- **Integridad.** Cada modelo se registra con su SHA-256 en `models/manifest.json`, y `load` rechaza
  cualquier archivo que no figure ahí, porque un `.joblib` es un pickle.

## Alternativas consideradas
- **Validación cruzada aleatoria (k-fold).** Filtra el futuro hacia el pasado en series de tiempo. Se descartó.
- **Red neuronal o LSTM.** Necesita más datos que 3 años de velas H1/H4 y no se puede explicar. Se descartó.
- **Subir solo el umbral del score.** Sube un poco el acierto, pero corta casi todas las operaciones.

## Consecuencias
- El 75 % solo se logra en algunos activos y temporalidades. En los demás no hay modelo, y el bot
  opera con las reglas solas.
- Hay que reentrenar cuando cambien el motor o el config, porque cambia el hash y la caché.
- scikit-learn se importa de forma diferida: los bots funcionan sin él si no hay modelos.
