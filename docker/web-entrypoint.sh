#!/bin/sh

set -eu

public_hostname=${PUBLIC_HOSTNAME:-}

invalid_hostname() {
    echo "PUBLIC_HOSTNAME must be one exact DNS hostname or IPv4 address without a scheme, port, path, wildcard, or whitespace." >&2
    exit 1
}

if [ -n "$public_hostname" ]; then
    case "$public_hostname" in
        *[!A-Za-z0-9.-]* | .* | *. | *..*)
            invalid_hostname
            ;;
    esac

    if [ "${#public_hostname}" -gt 253 ]; then
        invalid_hostname
    fi

    remaining=$public_hostname
    while :; do
        label=${remaining%%.*}
        case "$label" in
            "" | -* | *-)
                invalid_hostname
                ;;
        esac
        if [ "${#label}" -gt 63 ]; then
            invalid_hostname
        fi
        case "$remaining" in
            *.*)
                remaining=${remaining#*.}
                ;;
            *)
                break
                ;;
        esac
    done
fi

export PUBLIC_HOSTNAME="$public_hostname"
mkdir -p /tmp/nginx-conf.d
envsubst '${PUBLIC_HOSTNAME}' \
    </etc/nginx/templates/execution-os.conf.template \
    >/tmp/nginx-conf.d/execution-os.conf

exec "$@"
