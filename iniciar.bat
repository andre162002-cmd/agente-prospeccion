@echo off
chcp 65001 >nul
title Agente de prospeccion - Finanzas a la carta
cd /d "%~dp0"

echo.
echo  ==============================================
echo   Agente de prospeccion - Finanzas a la carta
echo  ==============================================
echo.

set PY=
where py >nul 2>nul && set PY=py
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo  [ERROR] No encuentro Python en este computador.
  echo  Instalalo desde https://www.python.org/downloads/
  echo  y marca la casilla "Add python.exe to PATH" al instalar.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo  Preparando el programa por primera vez. Esto tarda unos minutos...
  %PY% -m venv .venv
)

echo  Revisando componentes...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo  [ERROR] No se pudieron instalar los componentes. Revisa tu conexion a internet.
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  Se creo el archivo de claves. Se abrira en el Bloc de notas:
  echo  pega tu clave de Google despues de GOOGLE_PLACES_API_KEY=
  echo  guarda con Ctrl+G o Ctrl+S, cierra el Bloc de notas y vuelve aqui.
  echo.
  notepad ".env"
)

echo.
echo  Listo. El agente se abrira en tu navegador en unos segundos.
echo  NO cierres esta ventana negra mientras uses el agente.
echo  Para apagarlo, cierra esta ventana.
echo.
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m prospector servidor
pause
