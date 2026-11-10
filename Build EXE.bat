@echo off
REM Builds "dist\MD Reader\MD Reader.exe". Run that exe to Install (just for you / all users) or use it Portable.
REM Works offline when PySide6 and PyInstaller are already installed (the other packages come from "wheels").
REM Takes a few minutes. Warnings about QML plugins are normal and can be ignored.
setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
set "CHECK=PySide6.QtWebEngineWidgets, PyInstaller"
call :findpython || goto :fail
echo Using Python: %PY%
"%PY%" -c "import PySide6.QtWebEngineWidgets" >nul 2>nul
if errorlevel 1 (
    call :online_install "PySide6 (the window toolkit)" PySide6 || goto :fail
)
"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    call :online_install "PyInstaller (the EXE builder)" pyinstaller || goto :fail
)
call :offline_packages || goto :fail
if not exist app_icon.ico "%PY%" md_reader.py --make-icon app_icon.ico
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name "MD Reader" --icon app_icon.ico ^
  --exclude-module PIL --exclude-module numpy --exclude-module pygame --exclude-module tkinter ^
  --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module yaml ^
  md_reader.py
echo.
if not exist "dist\MD Reader\MD Reader.exe" goto :fail
REM Release zip: the exe only runs next to its _internal folder, so share the whole folder.
for /f "tokens=3" %%V in ('findstr /b /c:"APP_VERSION =" md_reader.py') do set "VER=%%~V"
set "ZIP=dist\MD-Reader-v%VER%-win64.zip"
if exist "dist\MD Reader\settings.json" del "dist\MD Reader\settings.json"
echo Making the release zip...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\MD Reader' -DestinationPath '%ZIP%' -Force"
echo.
echo Done.
echo   App:         dist\MD Reader\MD Reader.exe  - open it and choose Install or Portable.
echo   Release zip: %ZIP%
echo                Upload this zip to GitHub Releases. The exe alone does not run without its _internal folder.
pause
exit /b 0

:fail
echo.
echo Build failed - copy the last lines above and send them to Claude.
pause
exit /b 1

REM ===========================================================================
REM Helpers. Nothing below needs the internet unless something is missing AND
REM a quick check shows the internet is actually reachable.
REM ===========================================================================

REM Finds Python. Prefers a copy that already has everything in CHECK installed.
REM Looks at the py launcher, PATH and the usual install folders, and skips the
REM Microsoft Store "python" shortcut.
:findpython
set "PY="
set "PYANY="
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do call :trypy "%%P"
if defined PY exit /b 0
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do call :trypy "%%P"
if defined PY exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%LOCALAPPDATA%\Python\pythoncore-3*" "%ProgramFiles%\Python3*") do (
    if not defined PY call :trypy "%%~D\python.exe"
)
if defined PY exit /b 0
if defined PYANY (
    set "PY=%PYANY%"
    exit /b 0
)
echo.
echo Python 3 was not found on this PC.
call :online
if errorlevel 1 (
    echo There is no internet connection, so it can't be downloaded now.
    echo Install Python 3 from python.org on this PC, then run this file again.
    exit /b 1
)
where winget >nul 2>nul
if errorlevel 1 goto :py_manual
choice /c YN /m "Install Python 3 now (free, from Microsoft's winget)"
if errorlevel 2 goto :py_manual
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :trypy "%%~D\python.exe"
if not defined PYANY goto :py_manual
set "PY=%PYANY%"
exit /b 0
:py_manual
echo Opening python.org. Install Python 3 and tick "Add python.exe to PATH", then run this file again.
start "" "https://www.python.org/downloads/windows/"
exit /b 1

:trypy
if not exist "%~1" exit /b 0
if not defined PYANY set "PYANY=%~1"
"%~1" -c "import %CHECK%" >nul 2>nul && set "PY=%~1"
exit /b 0

REM Installs markdown, pygments and pymdown-extensions from the "wheels" folder
REM next to this file. Works with no internet.
:offline_packages
"%PY%" -c "import markdown, pygments, pymdownx" >nul 2>nul && exit /b 0
echo Installing markdown, pygments and pymdown-extensions from the wheels folder (no internet needed)...
"%PY%" -m pip install --disable-pip-version-check --no-index --no-deps --find-links "%HERE%wheels" markdown pygments pymdown-extensions
"%PY%" -c "import markdown, pygments, pymdownx" >nul 2>nul && exit /b 0
exit /b 1

REM Quick internet check (about 4 seconds at most). errorlevel 0 = online.
:online
where curl.exe >nul 2>nul
if errorlevel 1 (
    ping -n 1 -w 2500 www.google.com | find "TTL=" >nul && exit /b 0
    exit /b 1
)
curl.exe -s -m 4 -o nul https://www.bing.com && exit /b 0
curl.exe -s -m 4 -o nul https://www.google.com && exit /b 0
exit /b 1

REM Installs packages from the internet, but only if it is reachable.
REM Usage: call :online_install "what it is for" package [package...]
:online_install
set "WHAT=%~1"
shift
call :online
if not errorlevel 1 goto :oi_start
echo.
echo %WHAT% is not installed in:
echo     %PY%
echo and this PC has no internet right now, so it can't be downloaded.
echo Turn the internet on once (for example with Internet Toggle) and run this file again.
exit /b 1
:oi_start
set "PKGS="
:oi_loop
if "%~1"=="" goto :oi_go
set "PKGS=%PKGS% %~1"
shift
goto :oi_loop
:oi_go
echo Downloading%PKGS% ...
"%PY%" -m pip install --disable-pip-version-check%PKGS%
exit /b %errorlevel%
