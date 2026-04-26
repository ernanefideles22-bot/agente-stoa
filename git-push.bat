@echo off
cd /d "C:\Users\ernan\OneDrive\Projetos\agente-stoa"
git add -A
git commit -m "feat: migracao para Anthropic Claude, routing expandido, model_json robusto, system prompts aprimorados"
git push origin main
pause
