PowerShell -Command "Set-ExecutionPolicy RemoteSigned" -Scope CurrentUser >> "%TEMP%\ScreenAutodetectLog.txt" 2>&1
PowerShell -File %USERPROFILE%\WindowsScripts\screen-autodetect.ps1 >> "%TEMP%\ScreenAutodetectLog.txt" 2>&1 
