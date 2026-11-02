# Drugie poświadczenie istniejącego tenanta

Ta procedura uzupełnia lokalny onboarding OLA Core. Obecny `-IssueKey` tworzy nowego tenanta; nie służy do dodania klucza istniejącej organizacji. Nowy moduł `scripts.provision_additional_tenant_key` wydaje dodatkowy klucz w sprawdzonym tenantcie, z osobnym `credential_id`.

Każdy taki klucz otrzymuje pełny zakres `OLA_CORE` i nie może zatwierdzać wyników. Do recenzji służy osobny zakres `REVIEW_RESULT` i procedura `docs/CREDENTIAL-LIFECYCLE-WINDOWS-PL.md`, która opisuje również migrację oraz unieważnianie. Dwa różne klucze nie dowodzą dwóch różnych ludzi. `assurance` pozostaje `UNKNOWN`, a `production_eligible` — `false`.

## Przed rozpoczęciem

1. Zweryfikuj źródło i rzeczywiście wdrożony obraz. Kontener musi zawierać nowy moduł; obecność pliku na hoście nie aktualizuje istniejącego obrazu. Nie odtwarzaj kontenera ani wolumenu jako automatycznego obejścia.
2. W istniejącym kokpicie wybierz SETTINGS, zweryfikuj klucz inicjatora i odczytaj z pola „Identyfikatory sesji” pełne `tenant_id` i `credential_id`. Są to identyfikatory, nie tajny klucz. Nie kopiuj zawartości pola hasła, HAR ani nagłówków żądań.
3. Ustal oczekiwaną liczbę obecnych kluczy. Dla tenanta utworzonego jednorazowo przez obecny `-IssueKey` jest to 1. Ta liczba jest warunkiem zapisu, a nie liczbą kluczy do utworzenia. Niezgodność zatrzymuje operację; nie zwiększaj jej automatycznie po ponowieniu.
4. Użyj prywatnego lokalnego terminalu właściciela, bez transkrypcji, udostępniania ekranu lub przechwytywania stdout. Nie wykonuj polecenia zapisu przez narzędzie Claude/Codex, które zapisuje odpowiedzi do historii.

## Sprawdzenie bez wydawania klucza

W PowerShell ustaw `$OlaTenantId` oraz `$OlaRequesterId` na rzeczywiste identyfikatory otrzymane z SETTINGS. Nie wpisuj w te zmienne sekretu. Przed pierwszym dodaniem klucza ustaw `$OlaExpectedKeyCount = 1`.

```powershell
if (!$OlaTenantId -or !$OlaRequesterId) { throw 'Najpierw odczytaj identyfikatory zweryfikowanej sesji.' }
if ($null -eq $OlaExpectedKeyCount) { throw 'Najpierw ustal oczekiwana liczbe obecnych kluczy.' }
$OlaCheckArgs = @(
    'exec', 'ola-cc-preview', 'python', '-m', 'scripts.provision_additional_tenant_key',
    '--tenant-id', $OlaTenantId,
    '--expected-requester-id', $OlaRequesterId,
    '--expected-key-count', [string]$OlaExpectedKeyCount
)
& docker.exe @OlaCheckArgs
if ($LASTEXITCODE -ne 0) { throw 'Warunki dodania poswiadczenia nie sa spelnione.' }
```

Domyślny tryb tylko sprawdza istniejącego tenanta, przypisanie wskazanego poświadczenia i liczbę kluczy. Nie tworzy bazy, schematu, tenanta ani klucza. Przy braku bazy lub właściwej konfiguracji napraw najpierw konkretną instalację, zachowując dane.

## Zapis wyłącznie w prywatnym terminalu

Poniższy blok jest oddzielną operacją wydania pełnego klucza Core. Uruchom go po ocenie powyższego wyniku i ustaleniu, komu zostanie powierzony nowy klucz. `-it` udostępnia terminal nowemu modułowi; nie zastępuje ochrony historii terminala i nagrywania ekranu.

```powershell
$OlaWriteArgs = @(
    'exec', '-it', 'ola-cc-preview', 'python', '-m', 'scripts.provision_additional_tenant_key',
    '--tenant-id', $OlaTenantId,
    '--expected-requester-id', $OlaRequesterId,
    '--expected-key-count', [string]$OlaExpectedKeyCount,
    '--apply', '--acknowledge-full-tenant-access'
)
& docker.exe @OlaWriteArgs
if ($LASTEXITCODE -ne 0) { throw 'Operacja nie potwierdzila zakonczenia. Sprawdz stan przed ponowieniem; commit mogl juz nastapic.' }
```

Zapis wymaga obu jawnych flag i interaktywnego stdin/stdout. Transakcja ponownie sprawdza tenanta, poświadczenie inicjatora i liczbę kluczy przed dodaniem nowego wpisu. Zapisuje wyłącznie hash istniejącym KDF; sekret pokazuje raz dopiero po udanym commit. Odczyt otwiera SQLite w trybie `ro`, a zapis w `rw`, aby brakujący plik nie został automatycznie utworzony także po wyścigu sprawdzenie/otwarcie. Nie zmienia starego klucza, historycznych dowodów ani schematu. Nie dodaje publicznego endpointu wydawania kluczy.

Jeśli terminal zamknie się po commit, ale przed skopiowaniem sekretu, jego odzyskanie nie jest możliwe. Nie podnoś automatycznie oczekiwanej liczby i nie wydawaj kolejnych kluczy w pętli. Sprawdź inventory i odwołaj dokładny nieużywany rekord zgodnie z `docs/CREDENTIAL-LIFECYCLE-WINDOWS-PL.md`. Ten moduł nadal liczy wszystkie historyczne rekordy; nowa procedura recenzenta liczy aktywne poświadczenia.

## Przegląd wymaga osobnego zakresu

Pełny drugi klucz Core otrzyma HTTP 403 na ścieżce zatwierdzenia. Wydaj jawnie klucz recenzenta i wykonaj nowy przebieg według `docs/CREDENTIAL-LIFECYCLE-WINDOWS-PL.md`. Nie zmieniaj zakresu starego klucza ręcznie w bazie ani nie przepisuj dawnych dowodów.

## Co pozostaje do odbioru

Testy automatyczne sprawdzają poświadczenia, zakresy, odwołanie, izolację tenantów i trwały przegląd wyniku w testowej SQLite. Nie potwierdzają tożsamości drugiej osoby, jej odrębnego urządzenia, rzeczywistego modelu, fizycznego Windows/ZBooka ani niezależnego wydania.
