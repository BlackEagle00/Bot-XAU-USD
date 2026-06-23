# 📱 GUÍA PASO A PASO: MIGRACIÓN A XM

**Cómo cambiar tu bot de MetaQuotes-Demo a XM (Colombia)**

---

## 📋 RESUMEN RÁPIDO

| Paso | Tiempo | Acción |
|---|---|---|
| 1 | 5 min | Crear cuenta demo en XM |
| 2 | 10 min | Descargar MetaTrader 5 de XM |
| 3 | 2 min | Loguear y probar conexión |
| 4 | 1-2 semanas | Probar bot en cuenta demo |
| 5 | 10 min | Abrir cuenta real en XM |
| 6 | $10-500 | Depositar dinero |
| 7 | 5 min | Actualizar credenciales en `.env` |
| 8 | Ongoing | Monitorear y operar |

---

## 🎯 PASO 1: CREAR CUENTA DEMO EN XM (5 min)

### 1.1 Ir al sitio de XM

1. Abre https://www.xm.com
2. Si te pregunta por país, selecciona **Colombia**
3. Busca el botón "Abrir Cuenta" o "Registrarse"

### 1.2 Llenar el formulario de registro

**Información que necesitas tener a mano:**
- ✅ Nombre completo (como aparece en tu cédula)
- ✅ Email (activo, XM te enviará credenciales)
- ✅ Teléfono (+57 xxxxx...)
- ✅ País: Colombia
- ✅ Ciudad/Región
- ✅ Número de cédula

### 1.3 Seleccionar "DEMO" en el tipo de cuenta

⚠️ **IMPORTANTE:** Cuando te pregunte el tipo de cuenta, selecciona:
- [ ] Cuenta Real
- [x] **Cuenta Demo** ← SELECCIONA ESTO

**Detalles de la cuenta demo:**
- Balance inicial: $10,000 USD (virtual)
- Apalancamiento: 1:200 (típico para forex)
- Spreads: Iguales a cuenta real
- Datos: En vivo (precios reales)

### 1.4 Verificar email

1. XM te enviará email de confirmación
2. Haz clic en el enlace de verificación
3. Tu cuenta demo estará **LISTA INMEDIATAMENTE**

**Credenciales que recibirás:**
```
Login (cuenta): 12345678 (ejemplo)
Password: XmPassword123 (ejemplo)
Servidor: XM-Demo
```

✅ **Guarda estas credenciales en un lugar seguro**

---

## 💻 PASO 2: DESCARGAR METATRADER 5 DE XM (10 min)

### 2.1 Descargar MT5

1. Vuelve al sitio de XM
2. Ve a "Plataformas de Trading" o "Descargas"
3. Descarga **"MetaTrader 5 para Windows"**
4. Ejecuta el instalador (`mt5installer.exe`)
5. Sigue los pasos por defecto

### 2.2 Seleccionar servidor XM

Cuando abra MT5 por primera vez, verás esta pantalla:

```
┌─────────────────────────────────┐
│ Seleccionar Servidor             │
├─────────────────────────────────┤
│ ☐ XM.com-Demo                    │
│ ☐ XM.com-Real                    │
│ ☐ Otros...                       │
└─────────────────────────────────┘
```

✅ Selecciona **"XM.com-Demo"** (para empezar en demo)

### 2.3 Loguear con credenciales de XM

1. Abre MT5
2. Menú: **File → Login to Trade Account**
3. Llena:
   - **Login:** El número que XM te envió (ej: 12345678)
   - **Password:** La contraseña de XM
   - **Server:** XM.com-Demo

4. Click "OK"

✅ **Deberías ver:**
- Verde: "Connected" en la esquina inferior derecha
- Tu balance: $10,000 USD (demo)

---

## 🧪 PASO 3: VERIFICAR CONEXIÓN (2 min)

### 3.1 Confirmar que XAUUSD existe

1. En MT5, abre **"Market Watch"** (lado izquierdo)
2. Busca **"XAUUSD"**
3. Si no aparece:
   - Click derecho en Market Watch
   - **"All Symbols"**
   - Busca **XAUUSD**
   - Click derecho → **"Show"**

### 3.2 Ver detalles del símbolo

1. Haz clic derecho en **XAUUSD**
2. **"Symbol Properties"**
3. Verifica:
   - ✅ Bid/Ask (precios actualizándose)
   - ✅ Spread (debe ser bajo, ~0.30 pips)
   - ✅ Dígitos: 2
   - ✅ Punto: 0.01

✅ **Si ves todo OK, tu conexión funciona**

---

## 🤖 PASO 4: PROBAR BOT EN DEMO (1-2 semanas)

### 4.1 Copiar bot a MT5 de XM

1. Localiza tu carpeta de bot:
   ```
   C:\Users\camil\OneDrive\Documentos\Inversion\Bot-XAU-USD
   ```

2. Copia la carpeta **`xauusd_bot`** a:
   ```
   C:\Users\[tuUsuario]\AppData\Roaming\MetaTrader 5\MQL5\Experts
   ```

   (En Windows, presiona **Win+R** y escribe `%appdata%`)

### 4.2 Actualizar credenciales en `.env`

Tu archivo `.env` probablemente tiene:
```
MT5_LOGIN=10011299165
MT5_PASSWORD=1wZwC!Vw
MT5_SERVER=MetaQuotes-Demo
```

⚠️ **CAMBIA A CREDENCIALES DE XM DEMO:**
```
MT5_LOGIN=12345678              # Tu login de XM demo
MT5_PASSWORD=tu_password_xm     # Tu password de XM
MT5_SERVER=XM.com-Demo          # Servidor XM demo
```

### 4.3 Ejecutar bot en demo

```bash
cd C:\Users\camil\OneDrive\Documentos\Inversion\Bot-XAU-USD
python xauusd_bot/main.py
```

**Verifica en los logs:**
```
✅ Conectado. Cuenta: #12345678 @ XM.com-Demo
✅ Información del símbolo XAUUSD:
   • Tick size: 0.01
   • Tick value: 1.0
   • Spread: 0.30 pips
```

### 4.4 Monitorear durante 1-2 semanas

**Qué observar:**
- ✅ Número de trades (deben ser 8-20 por semana)
- ✅ Win rate (debe ser 55%+)
- ✅ P&L (seguimiento de ganancias/pérdidas)
- ✅ Spreads (verificar que sean consistentes)

**Si algo no funciona:**
1. Revisa los logs en `xauusd_bot.log`
2. Verifica que XAUUSD sea visible en MT5
3. Confirma que el servidor sea `XM.com-Demo`

---

## 💳 PASO 5: ABRIR CUENTA REAL EN XM (10 min)

**SOLO después de probar 1-2 semanas en demo exitosamente**

### 5.1 Ir a "Mis Cuentas"

1. Login a tu cuenta XM
2. Ve a **"Mis Cuentas"** o **"Account Management"**
3. Click en **"Abrir Cuenta Real"**

### 5.2 Llenar solicitud de cuenta real

Necesitarás:
- ✅ Experiencia de trading (elige tu nivel)
- ✅ Dinero a invertir (mín: $10 USD)
- ✅ Objetivos de trading
- ✅ Situación financiera
- ✅ Fuente de fondos

### 5.3 Cargar documentos de verificación

XM pedirá:
1. **Documento de identidad** — Foto ambos lados de tu cédula
2. **Comprobante de domicilio** — Factura de servicios (agua/luz/internet) reciente
3. **Selfie** — Tu foto sosteniendo tu cédula

**Tiempo de aprobación:** 1-24 horas

### 5.4 Recibir credenciales de cuenta real

XM te enviará por email:
```
Login (cuenta real): 87654321 (ejemplo, diferente a demo)
Password: RealPassword123
Servidor: XM.com-Real
Tipo: Real
```

✅ **GUARDA estas credenciales en lugar seguro**

---

## 💰 PASO 6: DEPOSITAR DINERO (Varía según método)

### 6.1 Métodos de depósito disponibles para Colombia

| Método | Tiempo | Mínimo | Comisión |
|---|---|---|---|
| 💳 Tarjeta débito/crédito | Inmediato | $10 | 0% |
| 🏦 Transferencia bancaria | 1-3 días | $50 | 0% |
| 📱 PerfectMoney | Inmediato | $10 | 0-2% |
| 💰 Skrill | Inmediato | $10 | 1-2% |

### 6.2 Depositar via tarjeta (más fácil)

1. En tu cuenta XM, ve a **"Fondos"** → **"Depositar"**
2. Selecciona **"Tarjeta de crédito/débito"**
3. Ingresa:
   - Número de tarjeta
   - Fecha de vencimiento
   - CVV
   - Monto (ej: $100 USD)
4. Click **"Depositar"**

**Confirmación:** Inmediata, tu balance actualiza en segundos

### 6.3 Depositar via transferencia bancaria

1. Ve a **"Fondos"** → **"Depositar"** → **"Transferencia Bancaria"**
2. XM te mostrará datos bancarios
3. En tu banco, haz transferencia internacional a XM
4. Referencia: Tu número de cuenta XM

**Confirmación:** 1-3 días hábiles

---

## 🔐 PASO 7: ACTUALIZAR BOT CON CREDENCIALES REALES (5 min)

⚠️ **IMPORTANTE: Solo después de depositar dinero exitosamente**

### 7.1 Editar `.env`

```
MT5_LOGIN=87654321              # Tu login de XM REAL
MT5_PASSWORD=tu_password_real   # Tu password de XM REAL
MT5_SERVER=XM.com-Real          # Servidor XM REAL
```

### 7.2 Ejecutar bot con cuenta real

```bash
python xauusd_bot/main.py
```

**Verifica en los logs:**
```
✅ Conectado. Cuenta: #87654321 @ XM.com-Real
💰 Balance: 100.00 USD
🔄 Loop iniciado (cada 60s)
```

✅ **Bot está vivo en cuenta real**

---

## 📊 PASO 8: MONITOREO Y OPERACIÓN (Ongoing)

### 8.1 Primeros días (crítico)

**Monitorea cada 2-4 horas:**
- [ ] ¿Bot sigue conectado? (verificar logs)
- [ ] ¿Cantidad de trades razonable?
- [ ] ¿Spreads OK?
- [ ] ¿Dinero disponible?

### 8.2 Primera semana

**Monitorea diariamente:**
- [ ] Número de trades/día
- [ ] Win rate
- [ ] P&L total
- [ ] Máximo drawdown

### 8.3 Luego (operación normal)

**Verifica:**
- [ ] Revisión semanal de P&L
- [ ] Estado del balance (¿hay suficiente margen?)
- [ ] Cambios en condiciones del mercado

---

## ⚠️ CHECKLIST DE SEGURIDAD

Antes de depositar dinero real:

- [ ] Probé bot 1-2 semanas en demo
- [ ] Validé que funciona con spreads reales de XM
- [ ] Archivos `.env` y credenciales están seguros
- [ ] NUNCA compartiré mi `.env` con nadie
- [ ] Entiendo que operar conlleva riesgo de pérdida
- [ ] Dinero depositado es lo que puedo permitirme perder
- [ ] Leeré los términos y condiciones de XM
- [ ] Declararé ganancias en impuestos (DIAN)

---

## 🆘 PROBLEMAS COMUNES Y SOLUCIONES

### Problema: "Server not found - XM.com-Demo"

**Solución:**
1. Cierra MT5
2. Ve a: **Herramientas** → **Opciones** → **Servidores**
3. Busca "XM.com-Demo"
4. Si no aparece, descarga nuevamente MT5 desde XM.com

### Problema: "Login failed - Invalid account"

**Solución:**
1. Verifica usuario/password en email de XM
2. Copia exactamente (mayúsculas/minúsculas importan)
3. Verifica que el servidor sea correcto (XM.com-Demo o XM.com-Real)

### Problema: "XAUUSD not available"

**Solución:**
1. Click derecho en Market Watch
2. **"All Symbols"**
3. Busca XAUUSD
4. Click derecho → **"Show in Market Watch"**
5. Si aún no aparece, contacta XM support

### Problema: Bot no abre trades

**Solución:**
1. Verifica que balance > $50 (para un lote)
2. Revisa spreads (si son muy altos, puede bloquear)
3. Verifica que ATR > 2.0 (mercado muy plano bloquea)
4. Revisa score de señales en logs

### Problema: "Insufficient margin"

**Solución:**
1. Tu balance es muy bajo para el lote calculado
2. Deposita más dinero O
3. Reduce `RISK_PER_TRADE` en config.py (de 1% a 0.5%)

---

## 📞 CONTACTOS DE SOPORTE

### XM Support (24/5)

- **Chat en vivo:** https://www.xm.com/es/support
- **Email:** support@xm.com
- **Teléfono:** Disponible en sitio (con código de Colombia +57)
- **Horario:** Lunes-viernes sin parar, sábado-domingo no disponible

### Para problemas del bot

- Revisa `xauusd_bot.log`
- Verifica credenciales en `.env`
- Confirma conexión a MT5 (verde en esquina inferior derecha)

---

## ✅ RESUMEN FINAL

| Paso | Estado | Tiempo total |
|---|---|---|
| 1. Crear demo | ✅ | ~5 min |
| 2. Descargar MT5 | ✅ | ~10 min |
| 3. Conectar | ✅ | ~2 min |
| 4. Probar bot (demo) | ✅ | ~1-2 semanas |
| 5. Cuenta real | ✅ | ~10 min |
| 6. Depositar | ✅ | ~5 min - 3 días |
| 7. Actualizar bot | ✅ | ~5 min |
| 8. Operar | ✅ | Ongoing |

**Total: ~1.5-2 semanas hasta operar con dinero real**

---

## 🚀 ¡LISTO!

Ahora tienes:
- ✅ Bot mejorado con parámetros optimizados
- ✅ Broker regulado y confiable (XM)
- ✅ Credenciales seguras en `.env`
- ✅ Conocimiento sobre regulación en Colombia

**¡Adelante con tu trading!** 🎯

---

**¿Necesitas ayuda en algún paso?** Déjame saber.
