@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

rem Uma rodada do monitor para todos os clientes, com log. E isto que o Agendador de Tarefas chama.
rem
rem Para agendar toda segunda as 7h (rode uma vez, no seu terminal):
rem
rem   schtasks /create /tn "Radar - monitor semanal" /tr "\"%~f0\"" /sc weekly /d MON /st 07:00
rem
rem Conferir:  schtasks /query /tn "Radar - monitor semanal"
rem Rodar ja:  schtasks /run   /tn "Radar - monitor semanal"
rem Remover:   schtasks /delete /tn "Radar - monitor semanal" /f
rem
rem O monitor so COLETA. O Radar continua sendo gerado, revisado e enviado por voce:
rem   streamlit run projeto_02_analisador_acoes/app_radar.py

set "PYTHON=%USERPROFILE%\.venvs\projetos-ia\Scripts\python.exe"
set "PASTA_LOG=%~dp0logs"
if not exist "%PASTA_LOG%" mkdir "%PASTA_LOG%"
set "LOG=%PASTA_LOG%\monitor_%DATE:~6,4%-%DATE:~3,2%-%DATE:~0,2%.log"

if not exist "%PYTHON%" (
  echo [%DATE% %TIME%] ERRO: ambiente virtual nao encontrado em %PYTHON% >> "%LOG%"
  exit /b 1
)

echo. >> "%LOG%"
echo ======== [%DATE% %TIME%] iniciando >> "%LOG%"
"%PYTHON%" "%~dp0rodar_monitor.py" >> "%LOG%" 2>&1
set "CODIGO=%ERRORLEVEL%"
echo ======== [%DATE% %TIME%] terminou com codigo %CODIGO% >> "%LOG%"

rem Um erro aqui e silencioso: ninguem esta olhando quando a tarefa roda. O codigo de saida fica
rem visivel na coluna "Ultimo resultado" do Agendador, e o motivo fica no log acima.
exit /b %CODIGO%
