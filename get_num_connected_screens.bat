@echo off
wmic desktopmonitor get Description | grep -v Description | grep -P "\w" | wc -l
