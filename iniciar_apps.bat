@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Inicia e para os apps Streamlit dos projetos. Sem argumento abre um menu; com argumento roda direto:
rem   iniciar_apps.bat 1 3      inicia os projetos 1 e 3 (aceita de 1 a 5)
rem   iniciar_apps.bat parar    para todos
rem Defina SEM_NAVEGADOR=1 para nao abrir o navegador. Cada app roda na sua janela e continua rodando
rem depois que este menu for fechado; feche a janela do app ou use a opcao P para parar.

set "STREAMLIT=%USERPROFILE%\.venvs\projetos-ia\Scripts\streamlit.exe"
if not exist "%STREAMLIT%" (
  echo Nao achei o ambiente virtual em: %STREAMLIT%
  echo Crie-o como descrito no README, secao "Preparando o ambiente".
  pause
  exit /b 1
)

set "NOME_1=Projeto 1 - Chatbot RAG"
set "ARQ_1=projeto_01_chatbot_rag\app.py"
set "PORTA_1=8501"
set "NOME_2=Projeto 2 - Analisador de acoes"
set "ARQ_2=projeto_02_analisador_acoes\app_mercado.py"
set "PORTA_2=8502"
set "NOME_3=Projeto 3 - YouTube e Reels"
set "ARQ_3=projeto_03_resumidor_youtube\app_youtube.py"
set "PORTA_3=8503"
set "NOME_4=Projeto 4 - Triador de curriculos"
set "ARQ_4=projeto_04_triador_curriculos\app_triador.py"
set "PORTA_4=8504"
set "NOME_5=Projeto 5 - Gerador de SQL"
set "ARQ_5=projeto_05_gerador_sql\app_sql.py"
set "PORTA_5=8505"

if "%~1"=="" goto :menu

:argumentos
if "%~1"=="" goto :fim
if /i "%~1"=="parar" (call :parar_todos) else (call :iniciar %~1)
shift
goto :argumentos

:menu
cls
echo ================================================
echo   Projetos de IA - iniciar e parar os apps
echo ================================================
echo.
for %%i in (1 2 3 4 5) do call :linha %%i
echo.
echo   [1-5] iniciar esse projeto      [P] parar todos
echo   [A] atualizar a tela            [S] sair
echo.
choice /c 12345PAS /n /m "Escolha: "
set "OP=%errorlevel%"
if %OP% equ 0 goto :fim
if %OP% gtr 8 goto :fim
if %OP% equ 8 goto :fim
if %OP% equ 6 call :parar_todos
if %OP% leq 5 call :iniciar %OP%
goto :menu

:carregar
set "NOME="
set "ARQ="
set "PORTA="
call set "NOME=%%NOME_%~1%%"
call set "ARQ=%%ARQ_%~1%%"
call set "PORTA=%%PORTA_%~1%%"
exit /b 0

:porta_em_uso
set "EM_USO="
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul && set "EM_USO=1"
exit /b 0

:linha
call :carregar %~1
call :porta_em_uso %PORTA%
if defined EM_USO (echo   [%~1] %NOME%  -  RODANDO em http://localhost:%PORTA%) else (echo   [%~1] %NOME%  -  parado)
exit /b 0

:iniciar
call :carregar %~1
if not defined ARQ (
  echo Projeto invalido: %~1. Use um numero de 1 a 5.
  exit /b 1
)
call :porta_em_uso %PORTA%
if defined EM_USO (
  echo %NOME% ja esta rodando em http://localhost:%PORTA%
) else (
  echo Iniciando %NOME% ...
  start "%NOME%" "%STREAMLIT%" run "%ARQ%" --server.port %PORTA% --server.headless true --browser.gatherUsageStats false
  call :esperar_porta %PORTA%
)
if not defined SEM_NAVEGADOR start "" "http://localhost:%PORTA%"
exit /b 0

:esperar_porta
set /a TENTATIVAS=0
:espera_loop
call :porta_em_uso %~1
if defined EM_USO exit /b 0
set /a TENTATIVAS+=1
if %TENTATIVAS% geq 60 (
  echo Demorou para subir: veja a janela do app.
  exit /b 0
)
ping -n 2 127.0.0.1 >nul
goto :espera_loop

:parar_todos
for %%i in (1 2 3 4 5) do call :parar %%i
exit /b 0

:parar
call :carregar %~1
set "PARADO="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%PORTA% .*LISTENING"') do (
  taskkill /PID %%p /T /F >nul 2>&1
  set "PARADO=1"
)
if defined PARADO (echo %NOME% parado.) else (echo %NOME% nao estava rodando.)
exit /b 0

:fim
endlocal
exit /b 0
