@echo off
cd /d "C:\Users\ernan\OneDrive\Projetos\agente-stoa"
git add -A
git commit -m "migracao: openai -> anthropic claude (haiku + sonnet)"
git push origin main
pause
