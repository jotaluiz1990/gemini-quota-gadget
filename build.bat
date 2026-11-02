@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo  Compilando Gemini Quota Gadget com PyInstaller
echo ========================================================

:: Detecta dinamicamente o caminho da biblioteca CustomTkinter no ambiente Python
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set CTK_PATH=%%i

if "%CTK_PATH%"=="" (
    echo [ERRO] Nao foi possivel localizar o pacote CustomTkinter. Verifique a instalacao do Python.
    pause
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
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    --hidden-import "keyboard" ^
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

pause
