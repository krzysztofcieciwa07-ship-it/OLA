# OLA — próba wdrożenia lokalnego (nie produkcja)

Ten katalog uruchamia **prawdziwy kontener OLA**, ale tylko na `127.0.0.1:18080`.
Trwałość SQLite jest sprawdzana **przed i po restarcie** kontenera. Po próbie
wolumen testowy jest usuwany; nie wykorzystywać tej konfiguracji do danych klientów.

## Uruchomienie

Wymagane: Docker Engine, `docker compose` v2, Python 3.12+, Git i repozytorium.
Nie wpisuj sekretów do terminala współdzielonego, historii shella ani plików w repo.

```bash
export OLA_RUNTIME_COMMIT="$(git rev-parse HEAD)"
# Przygotuj unikalny sekret bez zapisywania wartości do pliku:
export OLA_API_KEY_PEPPER="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python scripts/staging_rehearsal.py
unset OLA_API_KEY_PEPPER
```

Wynik: `staging-proof.json` (bez kluczy API i peppera). Zawiera commit, listę
zaliczonych kontroli oraz korzeń łańcucha dowodów SHA-256.

### Co kontroluje test

- `docker compose config --quiet`, kontrola dokładnego commita, kontener HTTP.
- Uwierzytelnianie: brak klucza i błędny klucz → HTTP 401.
- Syntetyczny `POST /audit` → HTTP 200, pięć dowodów.
- Niezależne przeliczenie V2, w tym przywiązania rekordu do typu i producenta.
- Próba nieautoryzowanej modyfikacji SQLite → odmowa przez trigger append-only.
- Restart kontenera, niezmieniony korzeń łańcucha dowodów, stabilne health przez 12 s.
- Zniszczenie **wyłącznie lokalnego** wolumenu testowego przy wyjściu.

### Co nadal jest zablokowane

- Publiczny listener, TLS, zewnętrzny DNS i certyfikaty nie są skonfigurowane.
- Backup/restore poza jednym lokalnym wolumenem, HA, migracje, podpisywanie
  przez zewnętrzny trust anchor i niezależny system monitorowania nie są objęte próbą.
- NOVA, Codex, Vantage i inne agenty nie są tutaj połączone produkcyjnie.
- `PASS` tego testu **nie oznacza wdrożenia produkcyjnego ani wyniku OLA di-OS 10/10**.
