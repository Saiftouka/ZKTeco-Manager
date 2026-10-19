@echo off
setlocal

title Backup ZKTeco Manager

set "PROJECT=C:\Users\tjfr31\Documents\ZKTeco_Manager"
set "BACKUPS=C:\Users\tjfr31\Documents\ZKTeco_Manager_Backups"

echo.
echo ============================================
echo          BACKUP ZKTECO MANAGER
echo ============================================
echo.

if not exist "%PROJECT%" (
    echo ERREUR : Projet introuvable.
    echo %PROJECT%
    echo.
    pause
    exit /b 1
)

if not exist "%BACKUPS%" (
    mkdir "%BACKUPS%"
)

echo Projet :
echo %PROJECT%
echo.
echo Destination :
echo %BACKUPS%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$date=Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'; $destination=Join-Path '%BACKUPS%' ('ZKTeco_Manager_'+$date+'.zip'); Compress-Archive -Path '%PROJECT%\*' -DestinationPath $destination -CompressionLevel Optimal -Force; Write-Output $destination"

if errorlevel 1 (
    echo.
    echo ============================================
    echo          ERREUR PENDANT LE BACKUP
    echo ============================================
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo       BACKUP TERMINE AVEC SUCCES
echo ============================================
echo.
echo Destination :
echo %BACKUPS%
echo.

pause

endlocal
``