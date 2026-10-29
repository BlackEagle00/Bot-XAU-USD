"""
Lanzador — elige qué bot ejecutar.

Uso:
    python run.py                  # menú interactivo
    python run.py oro              # ejecuta directo el bot de Oro (swing H4/D1/W1)
    python run.py oro_scalping     # ejecuta directo el bot de Oro (scalping M15/H1/H4)
    python run.py dashboard        # panel web local (http://127.0.0.1:8765)
    python run.py sim_parallel     # sombra Balance × Bróker del scalping (sin órdenes reales)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BOTS = {
    "oro":              ("Oro (XAUUSD / GOLD) — swing H4/D1/W1",      ROOT / "xauusd_bot"),
    "oro_scalping":     ("Oro (XAUUSD / GOLD) — scalping M15/H1/H4", ROOT / "xauusd_scalping_bot"),
}


def run_bot(folder: Path):
    try:
        subprocess.run([sys.executable, "main.py"], cwd=str(folder))
    except KeyboardInterrupt:
        # El bot hijo ya maneja Ctrl+C y se cierra limpio (signal.signal en main.py).
        # Solo evitamos que el traceback se propague aquí en el proceso padre.
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "dashboard":
        try:   # panel web: http://127.0.0.1:8765
            subprocess.run([sys.executable, str(ROOT / "dashboard" / "server.py")], cwd=str(ROOT))
        except KeyboardInterrupt:
            pass
        return
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "sim_parallel":
        try:   # proceso aparte; las órdenes de MT5 quedan anuladas dentro del script
            subprocess.run([sys.executable, str(ROOT / "sim_parallel" / "sim_parallel.py"), *sys.argv[2:]], cwd=str(ROOT))
        except KeyboardInterrupt:
            pass
        return
    if len(sys.argv) > 1:
        key = sys.argv[1].strip().lower()
        if key not in BOTS:
            print(f"Opción '{key}' inválida. Usa: {', '.join(BOTS)}")
            sys.exit(1)
        label, folder = BOTS[key]
        print(f"Iniciando {label}...")
        run_bot(folder)
        return

    print("¿Qué bot quieres ejecutar?")
    keys = list(BOTS)
    for i, key in enumerate(keys, start=1):
        label, _ = BOTS[key]
        print(f"  {i}. {label}")

    choice = input("Opción: ").strip()
    try:
        key = keys[int(choice) - 1]
    except (ValueError, IndexError):
        print("Opción inválida.")
        sys.exit(1)

    label, folder = BOTS[key]
    print(f"Iniciando {label}...")
    run_bot(folder)


if __name__ == "__main__":
    main()
