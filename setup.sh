#!/usr/bin/env bash
# setup.sh — configura o agente STOA no VPS (Ubuntu/Debian)
# Uso: bash setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="stoaia.com.br"
NGINX_AVAILABLE="/etc/nginx/sites-available/stoaia"
NGINX_ENABLED="/etc/nginx/sites-enabled/stoaia"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERRO]${NC}  $*"; exit 1; }

# ── 1. Verificações iniciais ────────────────────────────────────────────────
info "Verificando pré-requisitos..."

[[ $EUID -eq 0 ]] || error "Execute como root: sudo bash setup.sh"

for cmd in docker nginx certbot; do
    if ! command -v "$cmd" &>/dev/null; then
        warn "$cmd não encontrado — instalando..."
        case "$cmd" in
            docker)
                apt-get update -qq
                apt-get install -y ca-certificates curl gnupg
                install -m 0755 -d /etc/apt/keyrings
                curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
                    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
                echo "deb [arch=$(dpkg --print-architecture) \
                    signed-by=/etc/apt/keyrings/docker.gpg] \
                    https://download.docker.com/linux/ubuntu \
                    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
                    > /etc/apt/sources.list.d/docker.list
                apt-get update -qq
                apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
                ;;
            nginx)
                apt-get update -qq && apt-get install -y nginx
                ;;
            certbot)
                apt-get update -qq && apt-get install -y certbot python3-certbot-nginx
                ;;
        esac
    fi
done
ok "Pré-requisitos prontos."

# ── 2. Arquivo .env.safe ────────────────────────────────────────────────────
ENV_FILE="$REPO_DIR/.env.safe"

if [[ ! -f "$ENV_FILE" ]]; then
    warn ".env.safe não encontrado. Criando a partir do exemplo..."
    cp "$REPO_DIR/.env.safe.example" "$ENV_FILE"
    echo ""
    echo -e "${YELLOW}Por favor, edite o arquivo .env.safe antes de continuar:${NC}"
    echo "  nano $ENV_FILE"
    echo ""
    echo "Campos obrigatórios:"
    echo "  STOA_ACCESS_TOKEN  — token secreto para autenticar a UI"
    echo "  ANTHROPIC_API_KEY  — chave da API da Anthropic"
    echo ""
    read -rp "Pressione ENTER após preencher o .env.safe para continuar..."
fi

# Converter CRLF → LF (sed não interpreta \r em regex; tr sim)
tr -d '\r' < "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"

# Validar campos obrigatórios
source "$ENV_FILE"
[[ -n "${STOA_ACCESS_TOKEN:-}" ]] || error "STOA_ACCESS_TOKEN não definido em .env.safe"
[[ -n "${ANTHROPIC_API_KEY:-}" ]]  || error "ANTHROPIC_API_KEY não definido em .env.safe"
ok ".env.safe validado."

# ── 3. Build e start Docker ─────────────────────────────────────────────────
info "Construindo e iniciando container Docker..."
cd "$REPO_DIR"
docker compose -f docker-compose.safe.yml down --remove-orphans 2>/dev/null || true
docker compose -f docker-compose.safe.yml up -d --build
ok "Container iniciado."

# Aguardar health check
info "Aguardando app responder em :18000..."
for i in {1..20}; do
    if curl -sf "http://127.0.0.1:${HOST_PORT:-18000}/api/health" > /dev/null 2>&1; then
        ok "App respondendo."
        break
    fi
    [[ $i -eq 20 ]] && error "App não respondeu após 60s. Verifique: docker compose logs"
    sleep 3
done

# ── 4. Nginx ────────────────────────────────────────────────────────────────
info "Configurando Nginx..."
cp "$REPO_DIR/nginx.stoaia.conf" "$NGINX_AVAILABLE"

# Remover configuração padrão se existir
[[ -f /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default

[[ -L "$NGINX_ENABLED" ]] || ln -s "$NGINX_AVAILABLE" "$NGINX_ENABLED"
nginx -t || error "Configuração do Nginx inválida."
systemctl reload nginx
ok "Nginx configurado."

# ── 5. Certbot SSL ──────────────────────────────────────────────────────────
CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"

if [[ -f "$CERT_PATH" ]]; then
    ok "Certificado SSL já existe. Pulando emissão."
else
    info "Emitindo certificado SSL para $DOMAIN..."
    read -rp "E-mail para o Certbot (notificações de renovação): " CERTBOT_EMAIL
    [[ -n "$CERTBOT_EMAIL" ]] || error "E-mail obrigatório para o Certbot."

    certbot --nginx \
        -d "$DOMAIN" -d "www.$DOMAIN" \
        --non-interactive --agree-tos \
        --email "$CERTBOT_EMAIL" \
        --redirect
    ok "Certificado SSL emitido."
fi

# Reload final após SSL
nginx -t && systemctl reload nginx
ok "Nginx recarregado com SSL."

# ── 6. Renovação automática ─────────────────────────────────────────────────
if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl reload nginx") | crontab -
    ok "Renovação automática SSL agendada (todo dia às 03:00)."
fi

# ── 7. Resumo ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  STOA Agent configurado com sucesso!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  URL:        https://$DOMAIN"
echo "  Container:  $(docker compose -f "$REPO_DIR/docker-compose.safe.yml" ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null | tail -1)"
echo ""
echo "Comandos úteis:"
echo "  Ver logs:    docker compose -f $REPO_DIR/docker-compose.safe.yml logs -f"
echo "  Reiniciar:   docker compose -f $REPO_DIR/docker-compose.safe.yml restart"
echo "  Parar:       docker compose -f $REPO_DIR/docker-compose.safe.yml down"
echo ""
