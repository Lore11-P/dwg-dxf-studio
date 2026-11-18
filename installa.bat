@echo off
setlocal
cd /d "%~dp0"
echo === DWG / DXF Studio - installazione ===
echo.

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python non trovato.
        echo Installa Python 3.10 o successivo da https://www.python.org/downloads/
        echo Durante l'installazione spunta "Add python.exe to PATH".
        pause
        exit /b 1
    )
    set "PY=py -3"
)

if exist ".venv\Scripts\python.exe" goto dipendenze
echo Creo l'ambiente Python in .venv ...
%PY% -m venv .venv
if errorlevel 1 goto errore

:dipendenze
echo Installo le dipendenze ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto errore

if /i "%~1"=="/noshortcut" goto avvio
set "SCORC=S"
set /p "SCORC=Creare la scorciatoia sul desktop? [S/n] "
if /i "%SCORC%"=="n" goto senza
if /i "%SCORC%"=="no" goto senza
echo Creo la scorciatoia sul desktop ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crea_scorciatoia.ps1"
goto avvio

:senza
echo Scorciatoia non creata. Puoi crearla quando vuoi con "Crea scorciatoia desktop.bat".

:avvio
echo.
echo Installazione completata. Avvio DWG / DXF Studio ...
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

:errore
echo.
echo Installazione non riuscita. Controlla il messaggio sopra.
pause
exit /b 1
