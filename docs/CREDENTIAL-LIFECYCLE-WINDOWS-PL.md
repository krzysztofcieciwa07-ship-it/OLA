# Operator, recenzent i unieważnianie poświadczeń na Windows/ZBooku

Ten dokument opisuje lokalną administrację bieżącego kandydata integracyjnego. Nie potwierdza wykonania tych kroków na fizycznym ZBooku. Przed zmianą istniejącego runtime zachowaj zewnętrzny backup i sprawdź odtworzenie na kopii. Nie kasuj kontenera ani wolumenu w celu aktualizacji.

## Zakresy i migracja

| Poświadczenie | Dozwolone operacje |
| --- | --- |
| `OLA_CORE` | Obecne funkcje Core, odczyt własnej sesji i stanu przeglądu; bez zatwierdzania wyniku |
| `REVIEW_RESULT` | Odczyt własnej sesji, stanu przeglądu oraz zatwierdzenie/odwołanie własnego przeglądu wyniku; bez uruchamiania Core |

Start API wykonuje addytywną migrację `api_keys`: `access_scope` oraz nullable `revoked_at`. Dotychczasowe klucze pozostają `OLA_CORE`; identyfikatory, hashe oraz Evidence nie są przepisywane. Stary dodatkowy pełny klucz nie staje się recenzentem. Kandydat i zatwierdzenie muszą zawierać nowe pola zakresów; dawny wynik bez tych pól wymaga nowego przebiegu.

Nowe moduły muszą być obecne w faktycznie uruchomionym obrazie. Samo skopiowanie plików na hosta nie aktualizuje kontenera. `-CreatePreview` nie jest aktualizatorem istniejącej instalacji. Nową wersję i migrację sprawdź na zachowanej kopii danych przed zmianą właściwego runtime.

Dwa poświadczenia o różnych zakresach nadal nie dowodzą tożsamości dwóch osób. `assurance=UNKNOWN`, `production_eligible=false`. Lokalny dostęp do środowiska/bazy jest granicą administracji; `expected-requester-id` jest niesekretnym pinem istniejącego klucza Core, a nie logowaniem administratora.

## Przygotowanie i odczyt inventory

W SETTINGS zweryfikuj klucz Core. Z „Identyfikatorów sesji” odczytaj rzeczywiste `$OlaTenantId` oraz `$OlaRequesterId`. Nie przekazuj sekretów do czatu, raportów, screenshotów ani HAR. Ustal nazwę istniejącego kontenera; poniżej użyto standardowego `ola-cc-preview`.

Poniższy odczyt wypisuje wyłącznie identyfikatory, zakresy i stan odwołania. Nie tworzy bazy ani nie odczytuje hashów:

```powershell
if (!$OlaTenantId -or !$OlaRequesterId) { throw 'Najpierw odczytaj identyfikatory sesji Core.' }
$OlaInventoryCode = @'
import json, sqlite3, sys
from pathlib import Path
from app.database import DB_PATH
uri = Path(DB_PATH).resolve().as_uri() + '?mode=ro'
with sqlite3.connect(uri, uri=True) as db:
    rows = db.execute('SELECT id,access_scope,revoked_at FROM api_keys WHERE tenant_id=? ORDER BY id', (sys.argv[1],)).fetchall()
print(json.dumps([dict(credential_id=r[0], access_scope=r[1], revoked_at=r[2]) for r in rows]))
'@
$OlaInventoryJson = & docker.exe exec ola-cc-preview python -c $OlaInventoryCode $OlaTenantId
if ($LASTEXITCODE -ne 0) { throw 'Inventory nie jest dostepne; sprawdz obraz, baze i migracje.' }
$OlaInventory = @($OlaInventoryJson | ConvertFrom-Json)
$OlaInventory | Format-Table credential_id, access_scope, revoked_at
$OlaExpectedActiveCount = @($OlaInventory | Where-Object { $null -eq $_.revoked_at }).Count
```

Oceń inventory przed zapisem. Liczba aktywnych kluczy jest pinem bieżącego stanu, nie trwałym tokenem idempotencji: po odwołaniu może wrócić do poprzedniej wartości. Po błędzie, utracie wyjścia lub zmianie inventory ponownie sprawdź stan. Nie zwiększaj pinu automatycznie ani nie ponawiaj wydania w pętli.

## Wydanie klucza recenzenta

Domyślny odczyt nie wydaje sekretu:

```powershell
$OlaReviewArgs = @(
    'exec', 'ola-cc-preview', 'python', '-m', 'scripts.provision_reviewer_credential',
    '--tenant-id', $OlaTenantId,
    '--expected-requester-id', $OlaRequesterId,
    '--expected-active-key-count', [string]$OlaExpectedActiveCount
)
& docker.exe @OlaReviewArgs
if ($LASTEXITCODE -ne 0) { throw 'Warunki wydania klucza recenzenta nie sa spelnione.' }
```

Zapis wykonuje właściciel WYŁĄCZNIE w prywatnym terminalu bez nagrywania/transkrypcji/stdout w historii AI. Nie uruchamiaj go przez narzędzie Claude lub Codex. `-it` i `isatty()` nie dowodzą prywatności terminala.

```powershell
$OlaReviewWriteArgs = @(
    'exec', '-it', 'ola-cc-preview', 'python', '-m', 'scripts.provision_reviewer_credential',
    '--tenant-id', $OlaTenantId,
    '--expected-requester-id', $OlaRequesterId,
    '--expected-active-key-count', [string]$OlaExpectedActiveCount,
    '--apply', '--acknowledge-review-result-access'
)
& docker.exe @OlaReviewWriteArgs
if ($LASTEXITCODE -ne 0) { throw 'Sprawdz inventory przed ponowieniem; commit mogl juz nastapic.' }
```

Sekret pojawia się raz, po commit; zapisz go prywatnie dla recenzenta. Zachowaj niesekretny `CREDENTIAL_ID`. Sekretu nie można odzyskać. Jeśli go utracono, odwołaj dokładny rekord po odczycie inventory, zanim świadomie wydasz nowy klucz.

## Przegląd wyniku w kokpicie

1. Wydaj klucz recenzenta przed uruchomieniem nowego zadania. W SETTINGS pozostaw Core inicjatora.
2. Uruchom `17 * 23`, odczytaj raport oraz Evidence/Replay. Nie dodawaj nowych dowodów między tym wynikiem a zatwierdzeniem.
3. Recenzent przegląda wynik i wprowadza swój `REVIEW_RESULT` w pole zatwierdzania. UI odczytuje obie sesje; backend ponownie wymaga właściwego zakresu, tego samego tenanta i odrębnego ID.
4. Zatwierdzenie wiąże aktualny tip, raport, źródło, politykę i parametry oraz wygasa po 15 minutach. Odczyty stanu nie przedłużają ważności.
5. Kokpit sprawdza bieżące `GET /nina-run/{run_id}/approval`; uwzględnij `STALE`, `REVOKED`, `BLOCKED` oraz odwołany klucz. `APPROVED` dotyczy wyłącznie przeglądu wyniku.

Usunięcie kluczy z pól karty nie unieważnia ich na serwerze. UI czyści pole recenzenta po zakończonym żądaniu, ale nie jest to operacja odwołania poświadczenia.

## Unieważnienie dokładnego poświadczenia

Ponownie odczytaj inventory. Ustaw `$OlaTargetCredentialId` oraz `$OlaTargetScope` na sprawdzony rekord. Zachowaj inny, aktywny klucz Core jako `$OlaRequesterId`. Moduł blokuje samoodwołanie, ostatni Core, obcego tenanta, inny zakres, nieaktualną liczbę i ponowne odwołanie.

```powershell
if (!$OlaTargetCredentialId -or $OlaTargetScope -notin @('OLA_CORE','REVIEW_RESULT')) {
    throw 'Najpierw ustal dokladny cel i zakres z inventory.'
}
$OlaRevokeArgs = @(
    'exec', 'ola-cc-preview', 'python', '-m', 'scripts.revoke_tenant_credential',
    '--tenant-id', $OlaTenantId,
    '--credential-id', $OlaTargetCredentialId,
    '--expected-requester-id', $OlaRequesterId,
    '--expected-target-scope', $OlaTargetScope,
    '--expected-active-key-count', [string]$OlaExpectedActiveCount
)
& docker.exe @OlaRevokeArgs
if ($LASTEXITCODE -ne 0) { throw 'Warunki uniewaznienia nie sa spelnione.' }
```

Po ocenie dry-run wykonaj w prywatnym terminalu tę samą operację z `docker exec -it` oraz końcowymi flagami `--apply --acknowledge-revocation`. Wynik nie zawiera sekretu. Rekord klucza pozostaje w bazie; `revoked_at` i zdarzenie `credential.revoked` commitują się atomowo. Błąd Evidence cofa operację.

Odwołany klucz otrzymuje ogólne HTTP 401. Bieżący stan jego zatwierdzenia jest `BLOCKED` z `reviewer_credential_status=REVOKED`, bez usuwania historycznego zatwierdzenia. Zapis zatwierdzenia i odwołania przeglądu ponownie sprawdza uprawnienia po uzyskaniu blokady transakcji. Odwołanie nie cofa zewnętrznej czynności Core rozpoczętej przed jego wykonaniem.

## Rotacja i granice odbioru

Historyczny `scripts/reissue_api_keys_v2.py` pozostaje narzędziem offline z zapisem ograniczonym do POSIX/0600; nie uruchamiaj go jako natywnego instalatora/rotacji Windows. Teraz pomija odwołane klucze, zachowuje zakres aktywnych i sprawdza także zmiany scope/revoked_at po backupie. Nie uruchamiaj rotacji na żywej bazie.

Odbiór na Windows wymaga migracji kopii starej bazy, nowego rzeczywistego przebiegu UI/API/model, przeglądu wyniku i unieważnienia testowego poświadczenia. Automatyczne testy Linux i runner Windows CI nie potwierdzają dostępu do fizycznego ZBooka, tożsamości osoby ani gotowości produkcyjnej.
