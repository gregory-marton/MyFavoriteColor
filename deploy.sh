#!/bin/bash

set -e

if [ "$PORT" = "emu" ]; then
    PYTHON_BIN="${PYTHON:-.venv/bin/python}"
    if [ ! -f "$PYTHON_BIN" ]; then
        PYTHON_BIN="python3"
    fi
    esptool.py() {
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
fi

# Ensure the manifest exists before proceeding
if [ ! -f "EngAI_MANIFEST.txt" ]; then
    echo "❌ Error: EngAI_MANIFEST.txt not found!"
    exit 1
fi

if [ "FLASH" = "$1" ] || [ "1" = "$FLASH" ]; then
    esptool.py --chip esp32c3 --port /dev/cu.usbmodem2101 erase-flash
    esptool.py --chip esp32c3 --port /dev/cu.usbmodem2101 --baud 460800 write-flash -z 0x0 ESP32_GENERIC_C3-20250415-v1.25.0.bin
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
