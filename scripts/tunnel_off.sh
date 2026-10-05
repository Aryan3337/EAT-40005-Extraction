#!/usr/bin/env bash
# Turns live AI answers back OFF: stops Tailscale Funnel (the public
# address stops working) and stops the authenticating proxy. Ollama itself
# is left running locally -- it's harmless with Funnel off, since nothing
# public can reach it once the proxy that was in front of it is also gone.
#
# The hosted site keeps working after this -- the three cached demo
# answers and all retrieval/citations never depended on the tunnel. Only a
# brand-new, unscripted question goes back to the templated fallback.
set -euo pipefail

echo "1/2 Stopping Tailscale Funnel..."
"/c/Program Files/Tailscale/tailscale.exe" funnel --https=443 off || true

echo "2/2 Stopping the authenticating proxy..."
# pkill is unreliable against Windows-native processes from Git Bash (it
# silently finds nothing); PowerShell's process list, matched on the full
# command line, is what actually works on this machine.
powershell.exe -NoProfile -Command '
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*ollama_tunnel_proxy*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
' || true

echo
echo "Live AI is OFF. The hosted site still works normally."
