# OLA — rdzeń OLA di-OS

> **Status:** repozytorium zawiera kod backendu, testy i procesy CI. **Nie jest dowodem gotowości produkcyjnej całego OLA di-OS.** Funkcje komunikatora NOVA, wizualizacja 4K i lokalne poprawki Codex mogą znajdować się poza tym repozytorium.

## Mapa publicznych projektów

Punktem odniesienia jest [katalog wszystkich 9 publicznych repozytoriów](docs/REPOSITORY_CATALOG.md) oraz jego [wersja JSON](docs/REPOSITORY_CATALOG.json). Katalog rozróżnia własny kod, forki, specyfikacje i projekty eksperymentalne; **nie utożsamia forków z gotowymi modułami OLA**.

## Co znajduje się w tym repozytorium

- `app/` — API FastAPI, kontrola wykonywania, funkcje agentów, workflow, modele i zapis dowodów.
- `tests/` — testy kontraktów, bezpieczeństwa, integralności i zachowania.
- `.github/workflows/` — automatyczne testy i przepływy weryfikacyjne; każdy wynik dotyczy konkretnego commita.
- `docs/` — dokumentacja i katalog portfolio.

## Lokalne uruchomienie — tylko środowisko deweloperskie

Wymagany Python oraz zależności projektu. Nie używaj danych produkcyjnych ani publicznych poświadczeń.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export OLA_EG_DB_PATH=./ola-local.db
export OLA_LLM_MODE=deterministic
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Następnie w innym terminalu:

```bash
curl --fail --silent http://127.0.0.1:8000/health
python -m pytest -q
```

`GET /health` weryfikuje tylko odpowiedź serwera. Chronione operacje wymagają poprawnego tenant ID, konta/klucza i bezpiecznie skonfigurowanego `OLA_API_KEY_PEPPER`; sama instalacja nie tworzy produkcyjnej tożsamości. Nie wystawiaj tego deweloperskiego serwera bezpośrednio do Internetu.

## Weryfikowalny wynik zamiast deklaracji

1. Wskaż dokładny commit, wersję zależności i środowisko.
2. Uruchom odpowiednie testy, w tym negatywne przypadki uprawnień.
3. Zapisz artefakty i ich SHA-256; niezależnie sprawdź dowody.
4. Oddziel wyniki CI od rzeczywistego stanu produkcyjnego.
5. Przy brakującym dowodzie zgłoś `UNKNOWN` / `BLOCKED`, nie `VERIFIED`.

Stan aktualny: kompletne wdrożenie systemowe **nie zostało potwierdzone przez samą zawartość tego repozytorium**.

Bezpieczeństwo i zgłaszanie podatności: [SECURITY.md](SECURITY.md). Zmiany należy proponować przez pull requesty, bez publikowania sekretów.
