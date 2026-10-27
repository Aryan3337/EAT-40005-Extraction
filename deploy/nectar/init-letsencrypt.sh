#!/bin/sh
# Obtain the TLS certificate this deployment serves. Run once on a fresh
# instance; `certbot renew` in the compose file handles everything after.
#
#   ./init-letsencrypt.sh                 # staging (fake cert, no rate limit)
#   STAGING=0 ./init-letsencrypt.sh       # the real thing
#   STAGING=0 FORCE=1 ./init-letsencrypt.sh   # replace a valid certificate
#
# Why staging first: sslip.io is NOT on the Public Suffix List, so Let's
# Encrypt counts every *.sslip.io certificate issued anywhere on the
# internet against ONE shared registered-domain limit. A misconfiguration
# discovered against production can therefore lock out not just us. Prove
# the plumbing against staging, which has its own generous limits, then
# re-run with STAGING=0. A staging certificate is untrusted by browsers --
# that is expected, and is not the failure you are looking for.
#
# Chicken-and-egg this script exists to break: nginx refuses to start when
# ssl_certificate points at a file that does not exist, but the HTTP-01
# challenge needs nginx already serving port 80. So: write a throwaway
# self-signed cert at the real path, start nginx, swap it for the real one,
# reload.

set -eu

cd "$(dirname "$0")"

CERT_NAME=p85
LIVE_DIR="/mnt/data/letsencrypt/live/${CERT_NAME}"
STAGING="${STAGING:-1}"
FORCE="${FORCE:-0}"
EMAIL="${LETSENCRYPT_EMAIL:-}"

# The domain is derived from the instance's own address rather than passed
# in, because on Nectar's Classic Provider network the public IP is
# configured directly on the interface -- there is no NAT and no floating
# IP. That makes this script correct after a rebuild with a different IP
# without anyone having to remember to edit it. Override by passing the
# domain as the first argument.
if [ "${1:-}" != "" ]; then
    DOMAIN="$1"
else
    IP="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p')"
    if [ -z "$IP" ]; then
        echo "Could not determine this instance's IP. Pass the domain explicitly:" >&2
        echo "  $0 <ip>.sslip.io" >&2
        exit 1
    fi
    DOMAIN="${IP}.sslip.io"
fi

echo "Domain:      $DOMAIN"
echo "Cert name:   $CERT_NAME  (so the path never contains the IP)"
if [ "$STAGING" = "1" ]; then
    echo "Environment: STAGING -- the resulting certificate is NOT trusted."
    echo "             Re-run with STAGING=0 once this succeeds."
else
    echo "Environment: PRODUCTION"
fi
echo

# sslip.io resolving correctly is a precondition for HTTP-01, and when it
# is wrong the certbot error is about validation rather than about DNS.
RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)"
if [ -z "$RESOLVED" ]; then
    echo "FAILED: $DOMAIN does not resolve from this host." >&2
    exit 1
fi
echo "$DOMAIN resolves to $RESOLVED"

sudo mkdir -p /mnt/data/letsencrypt /mnt/data/certbot-www

if [ -f "${LIVE_DIR}/fullchain.pem" ] && [ "$FORCE" != "1" ]; then
    echo
    echo "A certificate already exists at ${LIVE_DIR}."
    sudo openssl x509 -in "${LIVE_DIR}/fullchain.pem" -noout -subject -issuer -enddate
    echo
    echo "Nothing to do. Re-run with FORCE=1 to replace it."
    exit 0
fi

# --- 1. Throwaway certificate, purely so nginx will start -----------------
echo
echo "Writing a temporary self-signed certificate so nginx can start..."
sudo mkdir -p "$LIVE_DIR"
# --entrypoint is required: this image's entrypoint is `certbot`, so without
# it the arguments below become `certbot openssl req ...`.
docker run --rm -v /mnt/data/letsencrypt:/etc/letsencrypt \
    --entrypoint openssl certbot/certbot \
    req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "/etc/letsencrypt/live/${CERT_NAME}/privkey.pem" \
    -out "/etc/letsencrypt/live/${CERT_NAME}/fullchain.pem" \
    -subj "/CN=localhost"

# --- 2. nginx up, serving port 80 for the challenge -----------------------
echo
echo "Starting the stack..."
docker compose up -d
echo "Waiting for nginx to answer on port 80..."
# Any HTTP status means nginx answered; 404 for a nonexistent challenge
# token is the expected one. Only "000" means nothing is listening.
i=0
while [ "$i" -lt 30 ]; do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' \
            http://localhost/.well-known/acme-challenge/probe)" != "000" ]; then
        break
    fi
    i=$((i + 1))
    sleep 2
done
if [ "$i" -ge 30 ]; then
    echo "FAILED: nginx is not answering on port 80 after 60s." >&2
    echo "Check: docker compose logs web" >&2
    exit 1
fi
echo "nginx is serving."

# --- 3. Drop the throwaway and ask Let's Encrypt for the real one ---------
echo
echo "Removing the temporary certificate and requesting a real one..."
sudo rm -rf "$LIVE_DIR" "/mnt/data/letsencrypt/archive/${CERT_NAME}" \
            "/mnt/data/letsencrypt/renewal/${CERT_NAME}.conf"

set -- certonly \
    --webroot -w /var/www/certbot \
    --cert-name "$CERT_NAME" \
    -d "$DOMAIN" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring

if [ "$STAGING" = "1" ]; then
    set -- "$@" --staging
fi

if [ -n "$EMAIL" ]; then
    set -- "$@" --email "$EMAIL"
else
    # No address means no warning mail if renewal silently breaks. Fine for
    # staging; set LETSENCRYPT_EMAIL before the production run.
    set -- "$@" --register-unsafely-without-email
fi

docker compose run --rm --entrypoint certbot certbot "$@"

# --- 4. Make nginx pick it up ---------------------------------------------
echo
echo "Reloading nginx..."
docker compose exec -T web nginx -s reload

echo
sudo openssl x509 -in "${LIVE_DIR}/fullchain.pem" -noout -subject -issuer -enddate
echo
if [ "$STAGING" = "1" ]; then
    echo "Staging certificate installed. The plumbing works."
    echo "Now run:  STAGING=0 FORCE=1 LETSENCRYPT_EMAIL=you@example.com $0"
else
    echo "Done. The site is at https://${DOMAIN}/"
    echo "Rebuild the Flutter bundle with"
    echo "  --dart-define=API_BASE_URL=https://${DOMAIN}"
    echo "or the browser will call the old origin and every request will fail."
fi
