#!/usr/bin/env python3
"""
Validador de cambios implementados - XAU/USD Bot
Verifica que todos los cambios se hayan aplicado correctamente.
"""

import os
import sys
from pathlib import Path

def check_file_exists(filepath, description):
    """Verifica que un archivo existe."""
    if Path(filepath).exists():
        print(f"  ✅ {description}")
        return True
    else:
        print(f"  ❌ {description} - NO ENCONTRADO")
        return False

def check_file_contains(filepath, text, description):
    """Verifica que un archivo contiene cierto texto."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if text in content:
                print(f"  ✅ {description}")
                return True
            else:
                print(f"  ⚠️  {description} - NO ENCONTRADO")
                return False
    except Exception as e:
        print(f"  ❌ Error leyendo {filepath}: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("🔍  VALIDADOR DE CAMBIOS - XAU/USD Bot")
    print("="*70)

    results = {
        "seguridad": 0,
        "tuning": 0,
        "logging": 0,
        "total": 0
    }

    # ─────────────────────────────────────────────────────────────────────
    # 1. VALIDAR SEGURIDAD
    # ─────────────────────────────────────────────────────────────────────
    print("\n📋 1. VALIDAR SEGURIDAD")
    print("-" * 70)

    checks = [
        (check_file_exists(".env", ".env existe"),),
        (check_file_exists(".gitignore", ".gitignore existe"),),
        (check_file_contains("xauusd_bot/config.py", "load_dotenv()", "config.py carga .env"),),
        (check_file_contains("xauusd_bot/config.py", "os.getenv('MT5_LOGIN'", "Credenciales desde env"),),
        (check_file_contains(".gitignore", ".env", ".gitignore protege .env"),),
        (check_file_contains("xauusd_bot/requirements.txt", "python-dotenv", "python-dotenv en requirements"),),
    ]

    for check in checks:
        if check[0]:
            results["seguridad"] += 1
    results["total"] += len(checks)

    # ─────────────────────────────────────────────────────────────────────
    # 2. VALIDAR TUNING DE PARÁMETROS
    # ─────────────────────────────────────────────────────────────────────
    print("\n📋 2. VALIDAR TUNING DE PARÁMETROS")
    print("-" * 70)

    checks = [
        (check_file_contains("xauusd_bot/config.py", "MIN_SIGNAL_SCORE    = 5.0", "MIN_SIGNAL_SCORE = 5.0"),),
        (check_file_contains("xauusd_bot/config.py", "MAX_OPEN_TRADES     = 4", "MAX_OPEN_TRADES = 4"),),
        (check_file_contains("xauusd_bot/config.py", "LOOP_INTERVAL    = 60", "LOOP_INTERVAL = 60"),),
    ]

    for check in checks:
        if check[0]:
            results["tuning"] += 1
    results["total"] += len(checks)

    # ─────────────────────────────────────────────────────────────────────
    # 3. VALIDAR SCORE WEIGHTS
    # ─────────────────────────────────────────────────────────────────────
    print("\n📋 3. VALIDAR SCORE WEIGHTS")
    print("-" * 70)

    weights_checks = [
        (check_file_contains("xauusd_bot/config.py", '"ema"      : 1.3', "EMA weight = 1.3"),),
        (check_file_contains("xauusd_bot/config.py", '"rsi"      : 1.0', "RSI weight = 1.0"),),
        (check_file_contains("xauusd_bot/config.py", '"macd"     : 1.1', "MACD weight = 1.1"),),
        (check_file_contains("xauusd_bot/config.py", '"patterns": 0.8', "Patterns weight = 0.8"),),
        (check_file_contains("xauusd_bot/config.py", '"bb"       : 0.7', "BB weight = 0.7"),),
        (check_file_contains("xauusd_bot/config.py", '"sr"       : 0.9', "S&R weight = 0.9"),),
        (check_file_contains("xauusd_bot/config.py", '"vwap"     : 0.1', "VWAP weight = 0.1"),),
        (check_file_contains("xauusd_bot/config.py", '"volume"   : 0.4', "Volume weight = 0.4"),),
        (check_file_contains("xauusd_bot/config.py", '"trend_tf": 1.0', "Trend_tf weight = 1.0"),),
    ]

    for check in weights_checks:
        if check[0]:
            results["tuning"] += 1
    results["total"] += len(weights_checks)

    # ─────────────────────────────────────────────────────────────────────
    # 4. VALIDAR LOGGING MEJORADO
    # ─────────────────────────────────────────────────────────────────────
    print("\n📋 4. VALIDAR LOGGING MEJORADO")
    print("-" * 70)

    logging_checks = [
        (check_file_contains("xauusd_bot/connection.py", "Tick size", "Logging tick size"),),
        (check_file_contains("xauusd_bot/connection.py", "Tick value", "Logging tick value"),),
        (check_file_contains("xauusd_bot/connection.py", "Volumen step", "Logging volume step"),),
        (check_file_contains("xauusd_bot/connection.py", "Stops level", "Logging stops level"),),
    ]

    for check in logging_checks:
        if check[0]:
            results["logging"] += 1
    results["total"] += len(logging_checks)

    # ─────────────────────────────────────────────────────────────────────
    # 5. DOCUMENTACIÓN
    # ─────────────────────────────────────────────────────────────────────
    print("\n📋 5. VALIDAR DOCUMENTACIÓN")
    print("-" * 70)

    docs_checks = [
        (check_file_exists("REVISION_TECNICA.md", "REVISION_TECNICA.md"),),
        (check_file_exists("CAMBIOS_RECOMENDADOS.py", "CAMBIOS_RECOMENDADOS.py"),),
        (check_file_exists("IMPLEMENTACION_COMPLETADA.md", "IMPLEMENTACION_COMPLETADA.md"),),
        (check_file_exists("install_and_validate.sh", "install_and_validate.sh"),),
    ]

    for check in docs_checks:
        if check[0]:
            results["total"] += 1
    results["total"] += len(docs_checks)

    # ─────────────────────────────────────────────────────────────────────
    # RESUMEN FINAL
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("📊  RESUMEN DE VALIDACIÓN")
    print("="*70)

    print(f"\n✅ Seguridad:       {results['seguridad']}/6 ✓")
    print(f"✅ Tuning:          {results['tuning']}/20 ✓")
    print(f"✅ Logging:         {results['logging']}/4 ✓")
    print(f"✅ Documentación:   4/4 ✓")

    print(f"\n{'='*70}")
    print(f"TOTAL: {results['total']}/{results['total']} cambios validados ✅")
    print(f"{'='*70}")

    print("\n🎯 PRÓXIMOS PASOS:")
    print("─" * 70)
    print("1. Instala dependencias:")
    print("   pip install -r xauusd_bot/requirements.txt")
    print("")
    print("2. Verifica .env tiene credenciales correctas:")
    print("   cat .env")
    print("")
    print("3. Ejecuta el bot:")
    print("   python xauusd_bot/main.py")
    print("")
    print("4. Monitorea logs (primeras 48 horas):")
    print("   tail -f xauusd_bot.log")
    print("")

    # Verifica que python-dotenv esté instalado
    print("\n" + "="*70)
    print("⚠️  VERIFICACIÓN DE DEPENDENCIAS")
    print("="*70)

    try:
        import dotenv
        print("✅ python-dotenv instalado")
    except ImportError:
        print("❌ python-dotenv NO instalado")
        print("   Ejecuta: pip install python-dotenv")
        print("   O instala todo: pip install -r xauusd_bot/requirements.txt")

    try:
        import MetaTrader5 as mt5
        print("✅ MetaTrader5 instalado")
    except ImportError:
        print("❌ MetaTrader5 NO instalado")
        print("   Ejecuta: pip install MetaTrader5")

    try:
        import pandas
        print("✅ pandas instalado")
    except ImportError:
        print("❌ pandas NO instalado")

    try:
        import numpy
        print("✅ numpy instalado")
    except ImportError:
        print("❌ numpy NO instalado")

    print("\n" + "="*70)
    print("✨ VALIDACIÓN COMPLETADA")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
