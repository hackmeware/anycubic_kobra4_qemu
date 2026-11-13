#!/bin/sh
# Diagnostic guest-only DHCP hook; never changes host networking.
set -eu
[ "${interface:-}" = eth0 ] || { echo K4_NET_ERROR_INTERFACE; exit 1; }
work=/tmp/k4-usb-net
mode=$(cat "$work/mode")
case "$mode" in isolated|internet) ;; *) echo K4_NET_ERROR_MODE; exit 1;; esac
valid_ip() {
    case "$1" in ''|*[!0-9.]*|.*|*.) return 1;; esac
    oldifs=$IFS; IFS=.; set -- $1; IFS=$oldifs
    [ "$#" -eq 4 ] || return 1
    for part do
        [ "${#part}" -le 3 ] && [ "$part" -le 255 ] 2>/dev/null || return 1
    done
}
case "${1:-}" in
 deconfig)
    ifconfig eth0 0.0.0.0
    ;;
 bound|renew)
    valid_ip "${ip:-}" && valid_ip "${subnet:-}" || { echo K4_NET_ERROR_ADDRESS; exit 1; }
    ifconfig eth0 "$ip" netmask "$subnet" up
    # Restrict to this interface; a missing old route is normal on first lease.
    route del default dev eth0 2>/dev/null || :
    gateway=
    for address in ${router:-}; do
        valid_ip "$address" || { echo K4_NET_ERROR_ROUTER; exit 1; }
        [ -n "$gateway" ] || gateway=$address
    done
    if [ -n "$gateway" ]; then
        route add default gw "$gateway" dev eth0
        echo K4_NET_ROUTE_CONFIGURED
    elif [ "$mode" = internet ]; then
        echo K4_NET_ERROR_NO_ROUTER; exit 1
    else
        echo K4_NET_ROUTE_UNAVAILABLE_LOCAL_ONLY
    fi
    : > "$work/resolv.conf"
    count=0
    for address in ${dns:-}; do
        valid_ip "$address" || { echo K4_NET_ERROR_DNS; exit 1; }
        count=$((count+1)); [ "$count" -le 3 ] || continue
        printf 'nameserver %s\n' "$address" >> "$work/resolv.conf"
    done
    if [ "$count" -eq 0 ]; then
        if [ "$mode" = internet ]; then echo K4_NET_ERROR_NO_DNS; exit 1; fi
        echo K4_NET_RESOLVER_UNAVAILABLE_LOCAL_ONLY
    else
    # R9 vendor /etc/resolv.conf is a dangling symlink to ../tmp/resolv.conf.
    # Preserve it and write only its verified RAM-backed target.
    if [ -L /etc/resolv.conf ]; then
        [ "$(readlink /etc/resolv.conf)" = ../tmp/resolv.conf ] || { echo K4_NET_ERROR_RESOLVER_SYMLINK; exit 1; }
        [ ! -L /tmp/resolv.conf ] || { echo K4_NET_ERROR_RESOLVER_TMP_SYMLINK; exit 1; }
        cat "$work/resolv.conf" > /tmp/resolv.conf
    else
        [ -f /etc/resolv.conf ] || { echo K4_NET_ERROR_RESOLVER_TARGET; exit 1; }
        if [ ! -f "$work/resolver-bound" ]; then
            mount -o bind "$work/resolv.conf" /etc/resolv.conf
            : > "$work/resolver-bound"
        fi
    fi
    cmp "$work/resolv.conf" /etc/resolv.conf || { echo K4_NET_ERROR_RESOLVER_READBACK; exit 1; }
    echo K4_NET_RESOLVER_CONFIGURED
    fi
    if [ "$mode" = isolated ]; then echo K4_NET_LOCAL_ONLY_READY; else echo K4_NET_INTERNET_CONFIGURATION_READY_UNTESTED; fi
    printf 'K4_NET_LEASE_READY ip=%s gateway=%s\n' "$ip" "$gateway"
    : > "$work/lease-ready"
    ;;
 *) echo K4_NET_ERROR_DHCP_EVENT; exit 1;;
esac
