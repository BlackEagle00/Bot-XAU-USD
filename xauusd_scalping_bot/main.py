"""
Lanzador del bot — punto de entrada de ESTA variante.

No contiene lógica: pone en sys.path la carpeta de este bot (para que
`import config` resuelva a SU config.py) y la raíz del repo (para `import
bot_engine`), y arranca el motor compartido.

Uso:
    python main.py
    # o desde la raíz:  python run.py <oro|oro_scalping|eurusd|eurusd_scalping>
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent     # carpeta de ESTE bot (su config.py)
ROOT = HERE.parent                          # raíz del repo (contiene bot_engine/)

sys.path.insert(0, str(ROOT))               # para 'import bot_engine'
sys.path.insert(0, str(HERE))               # queda en sys.path[0] → 'import config' = el de ESTE bot

from bot_engine.core import run

if __name__ == "__main__":
    run()
