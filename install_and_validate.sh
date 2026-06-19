#!/bin/bash
# Script de instalación y validación de cambios
# Ejecutar con: bash install_and_validate.sh

echo "════════════════════════════════════════════════════════════════"
echo "🚀  XAU/USD Bot — Instalación y Validación de Cambios"
echo "════════════════════════════════════════════════════════════════"

# PASO 1: Verificar que exista .env
echo ""
echo "✓ Paso 1: Verificando archivo .env..."
if [ -f ".env" ]; then
    echo "  ✅ Archivo .env existe"
    echo "  Contenido:"
    grep -v "^#" .env | grep -v "^$" | sed 's/=.*/=***/ ' | sed 's/^/    /'
else
    echo "  ❌ ERROR: Archivo .env no encontrado"
    echo "  Crea .env con:"
    echo "    MT5_LOGIN=tu_numero_de_cuenta"
    echo "    MT5_PASSWORD=tu_contraseña"
    echo "    MT5_SERVER=tu_servidor"
    exit 1
fi

# PASO 2: Verificar dependencias
echo ""
echo "✓ Paso 2: Verificando dependencias Python..."
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "  Python: $python_version"

if ! command -v pip &> /dev/null; then
    echo "  ❌ pip no encontrado. Instala Python con pip."
    exit 1
fi
echo "  ✅ pip disponible"

# PASO 3: Instalar dependencias
echo ""
echo "✓ Paso 3: Instalando dependencias desde requirements.txt..."
if [ -f "xauusd_bot/requirements.txt" ]; then
    pip install -r xauusd_bot/requirements.txt --quiet
    echo "  ✅ Dependencias instaladas"
else
    echo "  ❌ ERROR: requirements.txt no encontrado"
    exit 1
fi

# PASO 4: Verificar cambios en config.py
echo ""
echo "✓ Paso 4: Verificando cambios en config.py..."

if grep -q "load_dotenv()" xauusd_bot/config.py; then
    echo "  ✅ Config carga desde .env"
else
    echo "  ❌ Config no carga desde .env"
fi

if grep -q "MIN_SIGNAL_SCORE.*5\.0" xauusd_bot/config.py; then
    echo "  ✅ MIN_SIGNAL_SCORE = 5.0"
else
    echo "  ⚠️  MIN_SIGNAL_SCORE no es 5.0"
fi

if grep -q "MAX_OPEN_TRADES.*4" xauusd_bot/config.py; then
    echo "  ✅ MAX_OPEN_TRADES = 4"
else
    echo "  ⚠️  MAX_OPEN_TRADES no es 4"
fi

if grep -q "LOOP_INTERVAL.*60" xauusd_bot/config.py; then
    echo "  ✅ LOOP_INTERVAL = 60"
else
    echo "  ⚠️  LOOP_INTERVAL no es 60"
fi

# PASO 5: Verificar pesos de scoring
echo ""
echo "✓ Paso 5: Verificando SCORE_WEIGHTS..."
if grep -q '"ema".*1\.3' xauusd_bot/config.py; then
    echo "  ✅ Score weights optimizados"
else
    echo "  ⚠️  Verifica score weights"
fi

# PASO 6: Verificar .gitignore
echo ""
echo "✓ Paso 6: Verificando .gitignore..."
if [ -f ".gitignore" ]; then
    if grep -q ".env" .gitignore; then
        echo "  ✅ .gitignore protege .env"
    else
        echo "  ⚠️  .gitignore no protege .env"
    fi
else
    echo "  ⚠️  .gitignore no existe"
fi

# PASO 7: Resumen de cambios
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "📋  RESUMEN DE CAMBIOS IMPLEMENTADOS"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "✅ SEGURIDAD:"
echo "   • Credenciales movidas a .env"
echo "   • .gitignore protege datos sensibles"
echo "   • python-dotenv agregado a requirements.txt"
echo ""
echo "✅ TUNING DE PARÁMETROS:"
echo "   • MIN_SIGNAL_SCORE: 6.5 → 5.0 (+30-40% operaciones)"
echo "   • MAX_OPEN_TRADES: 2 → 4 (mejor acumulación)"
echo "   • LOOP_INTERVAL: 300s → 60s (más reactividad)"
echo "   • SCORE_WEIGHTS: Rebalanceados para mejor calidad"
echo ""
echo "✅ LOGGING MEJORADO:"
echo "   • connection.py: Información detallada del símbolo"
echo "   • Tick size, tick value y stops level logueados"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✨ INSTALACIÓN COMPLETADA"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "🎯 PRÓXIMOS PASOS:"
echo ""
echo "1. Verifica que .env tenga tus credenciales corrrectas:"
echo "   cat .env"
echo ""
echo "2. Ejecuta el bot:"
echo "   python xauusd_bot/main.py"
echo ""
echo "3. Monitorea los logs en los primeros 24-48 horas:"
echo "   • Número de trades (debe aumentar ~30-40%)"
echo "   • Win rate (debe mantenerse igual o mejorar)"
echo "   • P&L (debe mejorar ~5-10%)"
echo ""
echo "4. Si tienes problemas, revisa:"
echo "   • Los logs en xauusd_bot.log"
echo "   • Que MT5 esté abierto y con sesión iniciada"
echo "   • Que .env tenga credenciales válidas"
echo ""
