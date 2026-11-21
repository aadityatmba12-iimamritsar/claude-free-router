@echo off
REM Live Clipper launcher. First run installs yt-dlp; needs Python and ffmpeg (winget install Gyan.FFmpeg).
python -m pip install -U yt-dlp >nul
set PORT=8080
if "%CLIPPER_PASSCODE%"=="" set /p CLIPPER_PASSCODE=Set a passcode (blank = none): 
start "" http://localhost:%PORT%
python app.py
