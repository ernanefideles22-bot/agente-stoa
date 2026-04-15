"""
STOA Agent - Exemplos de Uso da API

Execute estes exemplos para testar diferentes funcionalidades do agente.
"""

import requests
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:8000"

def print_response(title: str, response: Dict[str, Any]):
    """Imprime resposta formatada"""
    print(f"\n{'='*60}")
    print(f"📝 {title}")
    print(f"{'='*60}")
    if isinstance(response, dict):
        print(json.dumps(response, indent=2, ensure_ascii=False))
    else:
        print(response)

# ==================== EXEMPLOS ====================

def test_health():
    """Testa se o servidor está online"""
    try:
        r = requests.get(f"{BASE_URL}/api/health")
        print_response("Health Check", r.json())
    except Exception as e:
        print(f"❌ Erro: {e}")

def test_weather():
    """Obtém informações de clima"""
    try:
        r = requests.get(f"{BASE_URL}/api/weather")
        print_response("Clima Atual", r.json())
    except Exception as e:
        print(f"❌ Erro: {e}")

def test_time():
    """Obtém hora atual"""
    try:
        r = requests.get(f"{BASE_URL}/api/time")
        print_response("Hora Atual", r.json())
    except Exception as e:
        print(f"❌ Erro: {e}")

def test_code_generation():
    """Testa geração de código"""
    print("\n🔧 Gerando código...")
    
    prompts = [
        {
            "prompt": "Crie um servidor Express em Node.js com GET /api/hello",
            "language": "javascript"
        },
        {
            "prompt": "Crie uma classe Python que valida emails",
            "language": "python"
        },
        {
            "prompt": "Crie um webhook FastAPI que recebe JSON e retorna processado",
            "language": "python"
        }
    ]
    
    for i, prompt_data in enumerate(prompts, 1):
        try:
            r = requests.post(
                f"{BASE_URL}/api/code-generate",
                json=prompt_data,
                timeout=30
            )
            print_response(f"Código {i}: {prompt_data['prompt'][:40]}...", r.json())
            time.sleep(1)  # Evita rate limiting
        except Exception as e:
            print(f"❌ Erro: {e}")

def test_website_generation():
    """Testa geração de websites"""
    print("\n🌐 Gerando website...")
    
    requirements = {
        "requirements": "Crie uma landing page moderna para uma agência de marketing digital com cores azul e branco, hero section, features, CTA e footer"
    }
    
    try:
        r = requests.post(
            f"{BASE_URL}/api/website-generate",
            json=requirements,
            timeout=30
        )
        
        data = r.json()
        print(f"\n{'='*60}")
        print("🌐 Website Gerado")
        print(f"{'='*60}")
        
        if 'html' in data:
            # Salva em arquivo
            with open("/tmp/stoa_website.html", "w", encoding="utf-8") as f:
                f.write(data['html'])
            print("✅ Website salvo em: /tmp/stoa_website.html")
            print(f"Tamanho: {len(data['html'])} caracteres")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    
    except Exception as e:
        print(f"❌ Erro: {e}")

def test_schedule_generation():
    """Testa geração de agenda"""
    print("\n📅 Gerando agenda...")
    
    requirements = {
        "requirements": "Planeje meu dia inteiro com: 2h STOA development, 2h trading bot, reuniões, pausas e análise de resultados"
    }
    
    try:
        r = requests.post(
            f"{BASE_URL}/api/schedule",
            json=requirements,
            timeout=30
        )
        print_response("Agenda do Dia", r.json())
    except Exception as e:
        print(f"❌ Erro: {e}")

def test_command_processing():
    """Testa processamento de comandos gerais"""
    print("\n🎯 Processando comandos...")
    
    commands = [
        "Explique como funcionam WebSockets em Python",
        "Qual é a melhor prática para estruturar um projeto FastAPI?",
        "Crie um plano de ação para melhorar meu bot de trading",
        "Como faz integração com GitHub Actions?",
    ]
    
    for cmd in commands:
        try:
            r = requests.post(
                f"{BASE_URL}/api/command",
                json={"text": cmd},
                timeout=30
            )
            
            data = r.json()
            print(f"\n{'─'*60}")
            print(f"💬 Comando: {cmd}")
            print(f"📌 Módulo: {data.get('module', 'N/A')}")
            print(f"✨ Resposta:\n{data.get('response', 'N/A')[:200]}...")
            
            time.sleep(1)
        except Exception as e:
            print(f"❌ Erro: {e}")

def test_websocket():
    """Testa WebSocket em tempo real"""
    print("\n⚡ Testando WebSocket...")
    
    import asyncio
    import websockets
    import json
    
    async def ws_test():
        uri = "ws://localhost:8000/ws"
        
        try:
            async with websockets.connect(uri) as websocket:
                print("✅ Conectado ao WebSocket")
                
                # Envia comando
                command = {"text": "Que horas são?"}
                await websocket.send(json.dumps(command))
                print(f"📤 Enviado: {command}")
                
                # Recebe resposta
                response = await websocket.recv()
                data = json.loads(response)
                print(f"📥 Recebido: {data}")
                
        except Exception as e:
            print(f"❌ Erro WebSocket: {e}")
    
    try:
        asyncio.run(ws_test())
    except Exception as e:
        print(f"⚠️ WebSocket não disponível (instale websockets): {e}")

def save_code_to_file(code: str, filename: str, language: str):
    """Salva código gerado em arquivo"""
    extensions = {
        "python": "py",
        "javascript": "js",
        "java": "java",
        "cpp": "cpp",
        "go": "go"
    }
    
    ext = extensions.get(language, "txt")
    filepath = f"/tmp/{filename}.{ext}"
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)
    
    print(f"💾 Código salvo em: {filepath}")

# ==================== MENU INTERATIVO ====================

def main():
    """Menu principal"""
    print("\n" + "="*60)
    print("🤖 STOA Agent - Exemplos de Uso da API")
    print("="*60)
    print("\nEscolha um teste:")
    print("1. Health Check")
    print("2. Clima")
    print("3. Hora/Data")
    print("4. Gerar Código")
    print("5. Gerar Website")
    print("6. Gerar Agenda")
    print("7. Processar Comandos")
    print("8. WebSocket")
    print("9. Executar Todos os Testes")
    print("0. Sair")
    
    while True:
        try:
            choice = input("\n👉 Digite sua escolha (0-9): ").strip()
            
            if choice == "1":
                test_health()
            elif choice == "2":
                test_weather()
            elif choice == "3":
                test_time()
            elif choice == "4":
                test_code_generation()
            elif choice == "5":
                test_website_generation()
            elif choice == "6":
                test_schedule_generation()
            elif choice == "7":
                test_command_processing()
            elif choice == "8":
                test_websocket()
            elif choice == "9":
                test_health()
                test_weather()
                test_time()
                test_code_generation()
                test_website_generation()
                test_schedule_generation()
                test_command_processing()
                test_websocket()
            elif choice == "0":
                print("\n👋 Até logo!")
                break
            else:
                print("❌ Opção inválida")
        
        except KeyboardInterrupt:
            print("\n\n👋 Até logo!")
            break
        except Exception as e:
            print(f"\n❌ Erro: {e}")

if __name__ == "__main__":
    # Verifica se servidor está rodando
    try:
        requests.get(f"{BASE_URL}/api/health", timeout=2)
    except:
        print("❌ ERRO: Servidor não está rodando!")
        print("\nInicie com: bash run.sh")
        exit(1)
    
    main()
