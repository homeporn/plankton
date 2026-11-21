#!/usr/bin/env bash
set -euo pipefail
umask 077
root=$(cd "$(dirname "$0")/../.." && pwd -P)
file=${PLANKTON_ENV:-"$root/.env"}
[[ -r "$file" ]] || { echo "Скопируйте .env.example в .env и задайте каталоги." >&2; exit 2; }
# Доверенный файл оператора в формате shell с настройками стенда.
set -a
source "$file"
set +a
: "${STATE_DIR:?}" "${CONFIG_DIR:?}" "${DEMO_HOST:?}" "${DEMO_PORT:?}"
[[ $STATE_DIR == /* && $CONFIG_DIR == /* && $STATE_DIR != "$CONFIG_DIR" ]]
[[ $DEMO_HOST =~ ^[a-z0-9]+([.-][a-z0-9]+)*$ && $DEMO_PORT =~ ^[1-9][0-9]{3,4}$ ]]
(( DEMO_PORT >= 1024 && DEMO_PORT <= 65535 ))
[[ $DEMO_UID =~ ^[1-9][0-9]*$ && $DEMO_GID =~ ^[1-9][0-9]*$ ]] || { echo "Нужны ненулевые UID и GID." >&2; exit 2; }
compose() { docker compose --env-file "$file" -f "$root/docker-compose.yml" "$@"; }
check_https() {
    curl --fail --silent --show-error --retry 4 --retry-all-errors --retry-delay 1 --max-time 10 --noproxy '*' \
        --resolve "$DEMO_HOST:$DEMO_PORT:127.0.0.1" --cacert "$CONFIG_DIR/ca.crt" \
        --netrc-file "$CONFIG_DIR/client.netrc" "https://$DEMO_HOST:$DEMO_PORT/healthz"
}
case "${1:-}" in
    init)
        [[ $(id -u) == "$DEMO_UID" && $(id -g) == "$DEMO_GID" ]] || {
            echo "Укажите UID/GID владельца каталогов в .env." >&2; exit 2;
        }
        if [[ -e "$CONFIG_DIR" ]]; then
            echo "Каталог доступа уже существует. Сохраните действующие ключи." >&2; exit 2
        fi
        mkdir -p "$STATE_DIR" "$(dirname "$CONFIG_DIR")"
        stage=$(mktemp -d "$(dirname "$CONFIG_DIR")/.plankton-access-XXXXXXXX")
        temp=$(mktemp -d)
        trap 'rm -rf -- "$temp" "$stage"' EXIT
        mkdir -m 700 "$stage/proxy" "$stage/socket"
        openssl rand -hex 32 > "$stage/session.key"
        openssl rand -base64 32 > "$temp/password"
        { printf 'demo:'; openssl passwd -6 -stdin < "$temp/password"; } > "$stage/proxy/htpasswd"
        printf 'machine %s login demo password %s\n' "$DEMO_HOST" "$(<"$temp/password")" > "$stage/client.netrc"
        openssl req -x509 -newkey rsa:3072 -nodes -days 365 -subj '/CN=Plankton private demo CA' \
            -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign' \
            -keyout "$temp/ca.key" -out "$stage/ca.crt" 2>"$temp/openssl.log"
        openssl req -new -newkey rsa:2048 -nodes -subj "/CN=$DEMO_HOST" \
            -keyout "$stage/proxy/server.key" -out "$temp/server.csr" 2>>"$temp/openssl.log"
        san="DNS:$DEMO_HOST"
        if [[ $DEMO_HOST == 127.0.0.1 ]]; then san="IP:$DEMO_HOST"; fi
        printf 'basicConstraints=critical,CA:FALSE\nsubjectAltName=%s\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$san" > "$temp/extensions"
        openssl x509 -req -in "$temp/server.csr" -CA "$stage/ca.crt" -CAkey "$temp/ca.key" \
            -days 180 -set_serial "0x$(openssl rand -hex 16)" -extfile "$temp/extensions" \
            -out "$stage/proxy/server.crt" 2>>"$temp/openssl.log"
        mv -nT -- "$stage" "$CONFIG_DIR"
        [[ ! -e "$stage" ]] || { echo "Каталог доступа уже создан другим процессом." >&2; exit 2; }
        echo "Подготовлены сертификат, секрет сессии и пароль отдельного входа через прокси."
        ;;
    build)
        args=()
        if [[ -n ${BUILD_CA_FILE:-} ]]; then args+=(--secret "id=build_ca,src=$BUILD_CA_FILE"); fi
        docker build "${args[@]}" -t "$APP_IMAGE" "$root"
        docker image inspect "$PROXY_IMAGE" >/dev/null 2>&1 || docker pull "$PROXY_IMAGE"
        ;;
    start)
        major=$(docker version --format '{{.Server.Version}}' | cut -d . -f1)
        (( major >= 28 )) || { echo "Для привязки только к loopback нужен Docker Engine 28+." >&2; exit 2; }
        live=$(compose ps -q app)
        if [[ -n "$live" ]]; then
            current=$(docker inspect --format '{{.Image}}' "$live")
            selected=$(docker image inspect --format '{{.Id}}' "$APP_IMAGE")
            [[ $current == "$selected" ]] || { echo "Для замены работающего образа используйте update." >&2; exit 2; }
        fi
        compose up -d --no-build --pull never --wait --wait-timeout 180
        check_https
        ;;
    health) check_https ;;
    stop) compose stop proxy && compose stop app ;;
    backup) compose exec -T app python -m deploy.cloud backup ;;
    restore)
        [[ $# == 3 && -f "$2" && ! -e "$3" && ! -L "$3" && -d "$(dirname "$3")" ]] || {
            echo "restore <файл копии> <новый каталог в существующей директории>" >&2; exit 2
        }
        src=$(realpath "$2")
        parent=$(realpath "$(dirname "$3")")
        compose run --rm --no-deps -T -v "$(dirname "$src"):/restore-in:ro" -v "$parent:/restore-out" \
            app restore "/restore-in/$(basename "$src")" "/restore-out/$(basename "$3")"
        ;;
    update)
        # Новый тег уже собран/загружен. Работающий контейнер пока использует прежний образ.
        docker image inspect "$APP_IMAGE" >/dev/null
        compose stop proxy
        compose exec -T app python -m deploy.cloud backup
        compose stop app
        if ! compose up -d --no-build --pull never --force-recreate --wait --wait-timeout 180 || ! check_https; then
            compose stop proxy
            exit 1
        fi
        ;;
    *) echo "Команды: init, build, start, health, stop, backup, restore, update" >&2; exit 2 ;;
esac
