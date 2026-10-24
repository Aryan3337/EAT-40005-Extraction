\# Mandi/Garo Chatbot — Local Setup Notes



Everything needed to run the full local stack: rag.py + Ollama + Flutter app + Neo4j.



Repo: https://github.com/Aryan3337/EAT-40005-Extraction

Branch: marcus-extraction-gates



\---



\## Quick start — 3 PowerShell windows



\### Window 1 — Backend (rag.py)



&#x20;   cd C:\\Users\\aryan\\OneDrive\\Desktop\\Extraction\\EAT-40005-Extraction

&#x20;   .\\.venv\\Scripts\\Activate.ps1

&#x20;   $env:PORT = "8000"

&#x20;   python -u rag.py --serve --neo4j --host 0.0.0.0



Wait for: RAG API listening on http://0.0.0.0:8000



\### Window 2 — Flutter app



&#x20;   $env:Path = \[Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + \[Environment]::GetEnvironmentVariable("Path", "User")

&#x20;   cd C:\\Users\\aryan\\OneDrive\\Desktop\\Extraction\\EAT-40005-Extraction\\flutter\_application

&#x20;   flutter run -d windows



Wait for the app window to open. Don't close this window — Ctrl+C here kills the app.



\### Window 3 — Testing / scratch



&#x20;   curl.exe -s -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{\\"query\\": \\"your question here\\"}'



\---



\## First-time setup per PowerShell session



If flutter isn't found in a fresh window, run:



&#x20;   $env:Path = \[Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + \[Environment]::GetEnvironmentVariable("Path", "User")



After one sign-out/sign-in cycle this won't be needed for flutter anymore.



\---



\## Ollama — check it is running



&#x20;   curl.exe -s http://localhost:11434/api/tags

&#x20;   ollama list

&#x20;   ollama ps



Ollama usually auto-starts on login. If it says connection refused, launch it from the Start menu or run `ollama serve` in its own window.



\---



\## Logins



Chatbot (Flutter app):

\- Username: mandichatbot

\- Password: mandichatbot123



Admin — do not use unless necessary, and NEVER upload anything (writes to shared graph):

\- Username: mandiadmin

\- Password: mandiadmin123



\---



\## Health checks



&#x20;   # Is rag.py alive?

&#x20;   curl.exe -s http://localhost:8000/

&#x20;   # Expected: {"error": "Not found"}



&#x20;   # Is Ollama alive?

&#x20;   curl.exe -s http://localhost:11434/api/tags



&#x20;   # What is in .env?

&#x20;   Get-Content .env

&#x20;   Get-Content .env | Select-String "NEO4J"

&#x20;   Get-Content .env | Select-String "OLLAMA\_MODEL"



&#x20;   # Where am I?

&#x20;   Get-Location

&#x20;   Get-ChildItem

&#x20;   Get-ChildItem -Force       # include hidden files like .env



\---



\## Git — pulling Marcus's changes



&#x20;   cd C:\\Users\\aryan\\OneDrive\\Desktop\\Extraction\\EAT-40005-Extraction

&#x20;   git status

&#x20;   git fetch origin

&#x20;   git log --oneline HEAD..origin/marcus-extraction-gates

&#x20;   git diff --name-only HEAD origin/marcus-extraction-gates

&#x20;   git checkout -- flutter\_application/     # discard Flutter auto-generated files

&#x20;   git pull origin marcus-extraction-gates



After pulling, check which dependency files changed:



&#x20;   git log --name-only -1 HEAD



\- requirements-serve.txt changed:

&#x20;     .\\.venv\\Scripts\\Activate.ps1

&#x20;     python -m pip install -r requirements-serve.txt

\- pubspec.yaml changed:

&#x20;     cd flutter\_application

&#x20;     flutter pub get



Then restart rag.py (Ctrl+C, relaunch). If any Flutter files changed, restart the app too.



Record the current commit:



&#x20;   git rev-parse --short HEAD



\---



\## Switching models



Edit .env:



&#x20;   notepad .env



Change `OLLAMA\_MODEL=mistral:7b` to `OLLAMA\_MODEL=deepseek-r1:7b`.



Restart rag.py — the env is read once at startup. First call after switching is slow (cold model load).



\---



\## Relevance gate (added 2026-10-08)



Controlled by env var SYNTHESIS\_RELEVANCE\_GATE. Defaults to on.



\- on (default): LLM judges whether retrieved evidence answers the question. Honest refusal when it doesn't.

\- off: pre-2026-10-08 behavior (speculative answers). Set SYNTHESIS\_RELEVANCE\_GATE=0 in .env to restore.



Affects latency: gate adds extra output tokens per response.



\---



\## Cold-call benchmark protocol



&#x20;   # 1. Check which questions are cached (avoid these)

&#x20;   Get-Content .\\data\\demo\_answer\_cache.json | Select-String "question"



&#x20;   # 2. Fire one cold call. Watch rag.py window for timing breakdown.

&#x20;   curl.exe -s -w "`ntime\_total: %{time\_total}s`n" -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{\\"query\\": \\"How do Garo marriage customs differ between Bangladesh and India?\\"}'



Rules:

\- One cold call per question — the second is prompt-cached and meaningless

\- Avoid questions in demo\_answer\_cache.json (returns in \~2s regardless)

\- Record time\_total, model, and whether the response was natural prose or the mechanical fallback

\- A call over 130s that returns stiff/mechanical text = template fallback = failure



Test question set:

1\. How do Garo marriage customs differ between Bangladesh and India?

2\. What role does music play in Garo cultural ceremonies?

3\. What is the significance of the Wangala festival?

4\. How is land ownership handled in traditional Garo society?

5\. What changes have occurred in Garo religious practices in recent decades?



\---



\## Flutter commands



Run from flutter\_application\\:



| Command | What it does |

|---|---|

| flutter pub get | Download dependencies (after pubspec.yaml changes) |

| flutter run -d windows | Build and launch the Windows desktop app |

| flutter clean | Wipe build artifacts (fixes stale CMake/build errors) |

| flutter doctor | Check toolchain |

| flutter devices | List available targets |

| flutter --version | Confirm Flutter works |



If a build fails with CMake errors:



&#x20;   flutter clean

&#x20;   flutter pub get

&#x20;   flutter run -d windows



\---



\## Debugging — common failures



| Symptom | Likely cause | First check |

|---|---|---|

| flutter: command not found | PATH not refreshed | Run the $env:Path line |

| rag.py says ServiceUnavailable on Neo4j | Aura creds wrong or paused | Get-Content .env \\| Select-String NEO4J |

| Connection refused on 11434 | Ollama not running | Start Ollama |

| Query returns template/mechanical text | 130s timeout -> fallback | Check rag.py timing lines |

| Query returns refusal message | Relevance gate judged evidence irrelevant | Expected — retrieval didn't find the fact |

| Flutter app shows network error | Backend not reachable | Is rag.py running on 8000? |

| ModuleNotFoundError in rag.py | Missing Python dep | python -m pip install <module> |

| nuget.exe not found during Flutter build | NuGet missing | winget install Microsoft.NuGet |



\---



\## Folder layout



&#x20;   EAT-40005-Extraction\\

&#x20;   |- rag.py                    <- server, run from here

&#x20;   |- .env                      <- secrets (do NOT commit)

&#x20;   |- requirements-serve.txt    <- server deps

&#x20;   |- data\\demo\_answer\_cache.json

&#x20;   |- .venv\\                    <- Python virtualenv

&#x20;   |- flutter\_application\\

&#x20;      |- pubspec.yaml

&#x20;      |- lib\\

&#x20;         |- main.dart

&#x20;         |- services\\

&#x20;            |- api\_config.dart

&#x20;            |- chat\_service.dart

&#x20;            |- admin\_service.dart



Rule of thumb:

\- rag.py, .env, requirements-serve.txt -> commands run in repo root

\- lib\\..., pubspec.yaml -> commands run in flutter\_application



\---



\## Window layout



&#x20;   +----------------------------+----------------------------+----------------------------+

&#x20;   | WINDOW 1: rag.py           | WINDOW 2: Flutter          | WINDOW 3: scratch          |

&#x20;   |                            |                            |                            |

&#x20;   | cd .../EAT-40005-Extraction| cd .../flutter\_application | curl tests, git, file      |

&#x20;   | .\\.venv\\Scripts\\Activate.ps1 flutter run -d windows     | checks                     |

&#x20;   | $env:PORT = "8000"         |                            |                            |

&#x20;   | python -u rag.py ...       |                            |                            |

&#x20;   |                            |                            |                            |

&#x20;   | <- watch log lines here    | <- user interacts here     | <- ad-hoc commands         |

&#x20;   +----------------------------+----------------------------+----------------------------+



\---



\## Stopping everything



\- rag.py: focus its window -> Ctrl+C

\- Flutter app: focus its window -> Ctrl+C

\- Ollama: leave running, or Task Manager -> "ollama" -> End task

\- No tunnel / Tailscale to shut down — fully local



Ctrl+C once = graceful. Twice = force. Don't close the window with the X button while a server is running.



\---



\## Useful one-off commands



&#x20;   # Find stray Python processes

&#x20;   Get-Process python | Select-Object Id, ProcessName, StartTime



&#x20;   # Kill by PID

&#x20;   Stop-Process -Id <PID>



&#x20;   # What is listening on port 8000?

&#x20;   Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue



&#x20;   # Open repo in Explorer

&#x20;   explorer .



&#x20;   # Open .env in Notepad

&#x20;   notepad .env



Always use curl.exe (not curl) in PowerShell — bare curl is aliased to Invoke-WebRequest and behaves differently.



\---



