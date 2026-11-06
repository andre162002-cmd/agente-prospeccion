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
where py >nul 2>nul
if errorlevel 1 goto nopython

rem Se usa Python 3.13: las versiones mas nuevas aun no son compatibles con todos los componentes
py -V:3.13 --version >nul 2>nul && set "PY=py -V:3.13"
if not defined PY py -3.13 --version >nul 2>nul && set "PY=py -3.13"
if not defined PY (
  echo  Instalando Python 3.13, la version compatible con el agente. Espera unos minutos...
  py install 3.13
  py -V:3.13 --version >nul 2>nul && set "PY=py -V:3.13"
)
if not defined PY goto nopython

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo  Borrando una preparacion anterior incompatible...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo  Preparando el programa por primera vez. Esto tarda unos minutos...
  %PY% -m venv .venv
)

echo  Revisando componentes...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo  [ERROR] No se pudieron instalar los componentes.
  echo  Toma una foto de esta ventana y enviasela a Claude.
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
exit /b 0

:nopython
echo  [ERROR] No encuentro Python 3.13 en este computador.
echo  Descargalo desde https://www.python.org/downloads/release/python-3139/
echo  elige "Windows installer 64-bit" y marca "Add python.exe to PATH" al instalar.
echo.
pause
exit /b 1
