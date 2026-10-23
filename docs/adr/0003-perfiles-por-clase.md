# ADR 0003: Perfiles independientes por clase de activo, calibrados con walk-forward

## Estado
Aceptado

## Fecha
2026-10-16

## Contexto
El panel analizaba divisas, metales, acciones y ETF cripto con **un solo config**, heredado del oro.
La auditoría v2 lo marcó como el hallazgo principal: un umbral y un SL/TP pensados para el oro no
tienen por qué servir a un par de divisas ni a una acción. El usuario pidió separar el análisis de
cada tipo de activo "para que haya independencia y no todo se base en el mismo modelo".

## Decisión
- **Seis perfiles.** Se crean en `dashboard/profiles/<clase>_<modo>/config.py`: forex, metals y
  stocks, cada uno en scalping y swing. Todos se arman con `_base.profile()`, que parte del config
  del bot más parecido y quita las claves en unidades absolutas.
- **Calibración.** `backtesting/calibrate.py` busca, por clase, el umbral, la regla de "ventas solo
  con macro bajista", el SL/TP y la temporalidad. Lo hace con walk-forward trimestral y purga,
  sumando todos los activos de la clase. Solo escribe en el config si el resultado fuera de muestra
  mejora a la configuración actual.
- **Un solo número mágico.** Todo el panel usa `MAGIC_NUMBER=20260630`, así el nivel de capital
  cuenta todas sus operaciones.

## Alternativas consideradas
- **Calibrar cada símbolo por separado.** Con 3 años, muchos símbolos tienen pocas operaciones y el
  riesgo de sobreajuste es alto. Queda en la hoja de ruta (PRD) como siguiente paso.
- **Un modelo global con el tipo de activo como variable.** Es más difícil de auditar, y un fallo en
  una clase contamina a las demás.

## Consecuencias
- El panel arranca 6 procesos worker.
- Un perfil cuyo resultado fuera de muestra no da PF > 1 se muestra como **"Sin ventaja probada"**.
  No se oculta, para no dar falsa confianza.
- Calibrar con 3 años de mercado mayormente alcista puede sobreajustar. El walk-forward lo mitiga,
  pero no lo elimina.
