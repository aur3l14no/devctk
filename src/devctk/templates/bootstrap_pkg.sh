# Detect package manager
pm=none
command -v apt-get >/dev/null 2>&1 && pm=apt
if [ "$pm" = "none" ]; then
    command -v apk >/dev/null 2>&1 && pm=apk
fi

# Install sudo if missing
if ! command -v sudo >/dev/null 2>&1; then
    case "$pm" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq && apt-get install -y --no-install-recommends sudo
            ;;
        apk)
            apk add --no-cache sudo shadow
            ;;
        *)
            echo "sudo missing and no supported package manager" >&2
            exit 1
            ;;
    esac
fi

# Install bash if missing
if ! command -v bash >/dev/null 2>&1; then
    case "$pm" in
        apk) apk add --no-cache bash ;;
        *) : ;;
    esac
fi
