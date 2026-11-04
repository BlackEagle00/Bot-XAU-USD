# Bot Scalping XAUUSD en un VPS Windows (24/7)

Mismo código y config que en el PC. El símbolo se resuelve solo (`bot_engine/symbols.py`: XAUUSD / GOLD con cualquier sufijo).

## 1. Servidor (lo hace el titular de la cuenta)
- AWS: activar MFA en la cuenta raíz y crear un presupuesto con alarma a 5 USD.
- EC2 → Windows Server 2022 Base, t3.small (2 GB; t3.medium si la RAM libre baja de 500 MB), disco gp3 de 40 GB.
- Security Group: RDP (3389) **solo desde tu IP**. No abras ningún otro puerto.

## 2. Instalación (por RDP)
1. Instala MT5 de VT Markets, inicia sesión en la cuenta, activa **Algo Trading** y marca "guardar contraseña".
2. Instala Python 3.13 desde python.org, con "Add to PATH" marcado.
3. Copia el repo en un zip, **sin** `venv/`, `logs/`, `__pycache__/`.
4. Crea `.env` **a mano dentro del VPS**. No lo envíes por chat ni por correo.
5. En la carpeta del repo: `pip install -r requirements.txt` y luego `python tests/test_engine.py` (debe salir todo OK).

## 3. Ensayo de 24 h (sin órdenes)
`powershell -ExecutionPolicy Bypass -File deploy\start_vps.ps1`

Este comando lanza `observe.py` y la sombra. Revisa `logs\watchdog.log` y comprueba que el log del bot escribe 📊 cada 15 s.

## 4. Paso a REAL (con 0 posiciones del bot abiertas)
1. **Primero detén el bot del PC** (mata `run.py oro_scalping` y su `main.py`). Dos bots en la misma cuenta abren posiciones duplicadas.
2. Detén el ensayo y arranca: `powershell -ExecutionPolicy Bypass -File deploy\start_vps.ps1 -Mode live -Terminal "C:\Program Files\VT Markets MetaTrader 5\terminal64.exe"`. Ajusta la ruta a la de tu instalación.
3. Para comprobar sin lanzar nada, añade `-DryRun`: el script dice qué PIDs ve y sale.

## 5. Que arranque solo
- Activa el inicio de sesión automático del usuario. En Windows Server: Sysinternals Autologon.
- En el Programador de tareas crea "Al iniciar sesión" → `powershell -ExecutionPolicy Bypass -File <repo>\deploy\start_vps.ps1 -Mode live -Terminal <ruta>`.
- En Energía, pon "nunca suspender". En Windows Update, fija horas activas y deja los reinicios para el sábado (mercado cerrado).

## Dashboard
`python run.py dashboard` → http://127.0.0.1:8765, accesible solo desde el navegador dentro del RDP. Desde ese panel se pueden enviar órdenes, así que **no** lo expongas a internet. Para usarlo desde el móvil, instala Tailscale en el VPS y en el móvil, sin abrir puertos.
