#!/bin/bash

set -e

if [ "$PORT" = "emu" ]; then
    PYTHON_BIN="${PYTHON:-.venv/bin/python}"
    if [ ! -f "$PYTHON_BIN" ]; then
        PYTHON_BIN="python3"
    fi
    esptool() {
        "$PYTHON_BIN" -m smotoremu.cli flash --vfs-dir "${SMOTOR_DIR:-$HOME/.smotor/default}"
    }
    mpremote() {
        if [ "$1" = "exec" ]; then
            "$PYTHON_BIN" -m smotoremu.cli flash --vfs-dir "${SMOTOR_DIR:-$HOME/.smotor/default}" >/dev/null
        elif [ "$1" = "cp" ]; then
            src="$2"
            dst_file="${3#:}"
            if [ -z "$dst_file" ] || [ "$dst_file" = ":" ]; then dst_file="$src"; fi
            vfs_dir="${SMOTOR_DIR:-$HOME/.smotor/default}"
            mkdir -p "$vfs_dir/$(dirname "$dst_file")"
            cp "$src" "$vfs_dir/$dst_file"
        elif [ "$1" = "reset" ]; then
            echo "🚀 Emulated device reset complete."
        fi
    }
elif [ -n "$PORT" ]; then
    # Real hardware, explicit port -- needed once more than one SmartMotor
    # might be connected at once (healthcheck_host.py's --deploy option
    # targets one port at a time out of a whole class set; mpremote's bare
    # auto-detect would pick an arbitrary one).
    mpremote() {
        command mpremote connect "$PORT" "$@"
    }
fi

# Ensure the manifest exists before proceeding
if [ ! -f "EngAI_MANIFEST.txt" ]; then
    echo "❌ Error: EngAI_MANIFEST.txt not found!"
    exit 1
fi

if [ "FLASH" = "$1" ] || [ "1" = "$FLASH" ]; then
    FLASH_PORT="$PORT"
    if [ -z "$FLASH_PORT" ]; then
        # Discovered, not assumed -- a board's actual port number (e.g.
        # /dev/cu.usbmodem101) depends on enumeration order/OS and isn't
        # fixed; the earlier hardcoded /dev/cu.usbmodem1101 default was
        # already wrong for the board on the bench today. Same candidate
        # pattern as healthcheck_host.py's filter_candidate_ports().
        FLASH_PORT=$(command mpremote connect list 2>/dev/null \
            | awk '{print $1}' | grep -E 'usbmodem|usbserial|wchusbserial|ttyACM|ttyUSB' | head -1)
    fi
    if [ -z "$FLASH_PORT" ]; then
        echo "❌ Error: no SmartMotor-looking serial port found. Set PORT=/dev/cu.usbmodemXXXX explicitly." >&2
        exit 1
    fi
    echo "⚡ Flashing $FLASH_PORT"
    esptool --chip esp32c3 --port "$FLASH_PORT" erase-flash
    esptool --chip esp32c3 --port "$FLASH_PORT" --baud 460800 write-flash -z 0x0 ESP32_GENERIC_C3-20250415-v1.25.0.bin
fi

if [ "$PORT" != "emu" ]; then
    if [ -n "$PORT" ]; then
        ./bin/smotor reset --port "$PORT" || true
    else
        ./bin/smotor reset || true
    fi
fi

echo "🔌 Wiping existing files on the device..."
mpremote exec "import os; [os.remove(f) for f in os.listdir()]"
echo "🚀 Uploading fresh files..."

# Read line-by-line, ignoring leading/trailing whitespace and empty lines
while IFS= read -r file; do
    # Skip empty lines
    if [ -z "$file" ]; then continue; fi
    
    if [ -f "$file" ]; then
        echo "   -> Copying $file"
        mpremote cp "$file" :
    else
        echo "   ⚠️ Warning: $file not found locally, skipping."
    fi
done < EngAI_MANIFEST.txt

mpremote reset
echo "✅ Deployment complete!"

# Optional: skip the hand-timed three-finger salute entirely. Writes the
# same healthcheck_state.txt marker healthcheck_host.py uses to remote-start
# a unit (see main.py's healthcheck_pending() check) -- boots straight into
# healthcheck.py on the next reset instead of requiring UP+DOWN+SELECT held
# through a script-driven power cycle, which is awkward to time by hand.
# Usage: ./deploy.sh healthcheck        (deploy, then start healthcheck)
#        FLASH=1 ./deploy.sh healthcheck (full erase+reflash first, if a
#                                         plain deploy isn't landing cleanly)
if [ "healthcheck" = "$1" ] || [ "1" = "$HEALTHCHECK" ]; then
    marker_tmp="$(mktemp)"
    printf '0|None|None' > "$marker_tmp"
    echo "🩺 Writing healthcheck_state.txt -- device will boot into healthcheck.py"
    mpremote cp "$marker_tmp" :healthcheck_state.txt
    rm -f "$marker_tmp"
    mpremote reset
    echo "✅ Healthcheck started!"
fi
