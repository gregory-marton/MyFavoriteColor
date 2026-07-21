#!/bin/bash

set -e

# Ensure the manifest exists before proceeding
if [ ! -f "EngAI_MANIFEST.txt" ]; then
    echo "❌ Error: EngAI_MANIFEST.txt not found!"
    exit 1
fi

if [ "FLASH" = "$1" ]; then
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
