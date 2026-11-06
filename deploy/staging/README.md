# OLA — lokalne staging i odtworzenie Evidence

To jest rzeczywisty test kontenera Docker, ale **nie publiczne wdrożenie**. Listener jest ograniczony do `127.0.0.1:18080`. Test używa syntetycznego tenanta i tymczasowego wolumenu.

## Uruchomienie

Wymagane: Docker Engine + Compose v2, Python 3.12+, Git.

```bash
export OLA_RUNTIME_COMMIT="$(git rev-parse HEAD)"
export OLA_API_KEY_PEPPER="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python scripts/staging_rehearsal.py
unset OLA_API_KEY_PEPPER
```

Sekret pepper jest jednorazowy i nie trafia do artefaktu. Skrypt sprawdza czysty checkout, dokładny SHA, build-info w obrazie, /readyz, auth 401, syntetyczny audit, pełny hash-chain, blokadę mutacji, restart, backup SQLite do snapshotu, restore do osobnej bazy, integrity_check i stabilność health przez 12 sekund. Wynik PASS powstaje dopiero po poprawnym usunięciu testowego wolumenu.

## Granice

`READY` oznacza wyłącznie gotowość lokalnego CORE. `system_acceptance` pozostaje `NOT_VERIFIED`. Nie jest to dowód TLS/public DNS, hostingu produkcyjnego, zewnętrznego backupu, MFA, monitoringu SLO, rollbacku produkcji ani realnego obciążenia klientów.
