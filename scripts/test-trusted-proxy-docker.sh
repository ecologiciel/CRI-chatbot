#!/usr/bin/env bash
# Rehearse an authenticated client-IP boundary with a private Docker network.
set -Eeuo pipefail
umask 077
: "${TEST_BACKEND_IMAGE:?Backend image required}"
script_dir=$(cd "$(dirname "$0")" && pwd)
root=$(mktemp -d /tmp/hostinger-proxy-test.XXXXXXXX)
suffix=${root##*.}; suffix=${suffix,,}
project="test_proxy${suffix}"
c=(docker compose --project-name "$project" -f "$root/compose.yml")
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ "$root" =~ ^/tmp/hostinger-proxy-test\.[a-zA-Z0-9]{8}$ && "$project" =~ ^test_proxy[a-z0-9]{8}$ ]]; then
    if (( rc != 0 )); then
      "${c[@]}" logs --tail=30 proxy backend >&2 || true
    fi
    "${c[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$root"
  else
    echo 'Invalid fixture path; refusing cleanup' >&2; rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
mkdir "$root/app"
cp "$script_dir/../backend/app/core/trusted_proxy.py" "$root/app/trusted_proxy.py"
cat > "$root/app/probe.py" <<'PY'
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from trusted_proxy import TrustedProxyIPMiddleware
async def http(request):
    return JSONResponse({"client": request.client.host, "proof_present": "x-internal-client-ip-proof" in request.headers})
async def ws(socket):
    await socket.accept()
    await socket.send_json({"client": socket.client.host, "proof_present": "x-internal-client-ip-proof" in socket.headers})
    await socket.close()
app = Starlette(routes=[Route("/", http), WebSocketRoute("/ws", ws)])
app.add_middleware(TrustedProxyIPMiddleware, secret="a" * 64)
PY
chmod 755 "$root" "$root/app"
chmod 644 "$root/app/"*.py
cat > "$root/compose.yml" <<YAML
services:
  proxy:
    image: traefik:v3.7.20
    command:
      - --providers.docker=true
      - --log.level=DEBUG
      - --providers.docker.exposedbydefault=false
      - --providers.docker.constraints=Label(\`fixture.proxy.test\`,\`$project\`)
      - --providers.docker.network=${project}_default
      - --entrypoints.web.address=:8080
    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]
  backend:
    image: $TEST_BACKEND_IMAGE
    working_dir: /fixture
    volumes: ["$root/app:/fixture:ro"]
    entrypoint: ["uvicorn", "probe:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
    healthcheck: { disable: true }
    labels:
      - fixture.proxy.test=$project
      - traefik.enable=true
      - traefik.http.routers.fixture.rule=PathPrefix(\`/\`)
      - traefik.http.routers.fixture.entrypoints=web
      - traefik.http.routers.fixture.middlewares=fixture-proof
      - traefik.http.middlewares.fixture-proof.headers.customrequestheaders.X-Internal-Client-IP-Proof=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      - traefik.http.services.fixture.loadbalancer.server.port=8000
  client:
    image: $TEST_BACKEND_IMAGE
    entrypoint: ["sleep", "600"]
YAML
"${c[@]}" up -d proxy backend client >/dev/null
client=$("${c[@]}" ps -q client)
client_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$client")
[[ "$client_ip" =~ ^[0-9.]+$ ]] || { echo 'Invalid fixture address' >&2; exit 1; }
ready=0
for attempt in $(seq 1 30); do
  if docker exec "$client" python -c 'import urllib.request; urllib.request.urlopen("http://proxy:8080/",timeout=2)' >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo 'Fixture proxy did not become ready' >&2; exit 1; }
docker exec -e EXPECTED_IP="$client_ip" "$client" python -c '
import asyncio,http.client,json,os,urllib.request
import websockets
expected=os.environ["EXPECTED_IP"]
def http(url, headers):
 req=urllib.request.Request(url,headers=headers)
 return json.load(urllib.request.urlopen(req,timeout=5))
for url in ("http://proxy:8080/", "http://backend:8000/"):
 result=http(url,{"X-Forwarded-For":"203.0.113.99", "X-Internal-Client-IP-Proof":"attacker"})
 assert result == {"client":expected,"proof_present":False}, result
conn=http.client.HTTPConnection("proxy",8080,timeout=5)
conn.putrequest("GET","/")
conn.putheader("X-Forwarded-For","203.0.113.99")
conn.putheader("X-Forwarded-For","203.0.113.98")
conn.putheader("X-Internal-Client-IP-Proof","attacker1")
conn.putheader("X-Internal-Client-IP-Proof","attacker2")
conn.endheaders()
response=conn.getresponse()
assert response.status==200
assert json.load(response)=={"client":expected,"proof_present":False}
conn.close()
async def ws():
 async with websockets.connect("ws://proxy:8080/ws", additional_headers={"X-Forwarded-For":"203.0.113.99", "X-Internal-Client-IP-Proof":"attacker"}) as conn:
  result=json.loads(await conn.recv())
  assert result == {"client":expected,"proof_present":False}, result
asyncio.run(ws())
print("TRAEFIK_HTTP_WEBSOCKET_FORGERY_REJECTED")'
