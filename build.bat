@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo  Compilando Gemini Quota Gadget com PyInstaller
echo ========================================================

:: Detecta dinamicamente o caminho da biblioteca CustomTkinter no ambiente Python
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set CTK_PATH=%%i

if "%CTK_PATH%"=="" (
    echo [ERRO] Nao foi possivel localizar o pacote CustomTkinter. Verifique a instalacao do Python.
    if "%~1"=="" (
    pause
)
    exit /b 1
)

echo [OK] CustomTkinter localizado em: !CTK_PATH!

:: Compilacao: Arquivo unico (--onefile), sem janela de console (--noconsole)
python -m PyInstaller ^
    --noconsole ^
    --onefile ^
    --clean ^
    --name "GeminiQuotaGadget" ^
    --add-data "!CTK_PATH!;customtkinter/" ^
    --collect-all "webview" ^
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    --hidden-import "gemini_web_client" ^
    --hidden-import "gemini_login_window" ^
    --hidden-import "clr_loader" ^
    --hidden-import "pythonnet" ^
    main.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  Build concluido com sucesso!
    echo  Executavel gerado em: dist\GeminiQuotaGadget.exe
    echo ========================================================
) else (
    echo.
    echo [ERRO] Ocorreu uma falha durante o processo de build do PyInstaller.
)

if "%~1"=="" (
    pause
)
