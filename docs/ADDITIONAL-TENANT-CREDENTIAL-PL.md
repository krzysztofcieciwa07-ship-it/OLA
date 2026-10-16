# Drugie poświadczenie istniejącego tenanta

Ta procedura uzupełnia lokalny onboarding OLA Core. Obecny `-IssueKey` tworzy nowego tenanta; nie służy do dodania klucza istniejącej organizacji. Nowy moduł `scripts.provision_additional_tenant_key` wydaje dodatkowy klucz w sprawdzonym tenantcie, z osobnym `credential_id`.

Każdy taki klucz otrzymuje obecny pełny zakres `OLA_CORE`. System nie ma jeszcze przypisania kluczy do osób ani roli ograniczonej do recenzji. Dwa różne klucze nie dowodzą dwóch różnych ludzi. Operator lokalny musi przekazać poświadczenie uprawnionej drugiej osobie poza czatem i zachować rozdział pracy. `assurance` pozostaje `UNKNOWN`, a `production_eligible` — `false`.

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

Jeśli terminal zamknie się po commit, ale przed skopiowaniem sekretu, jego odzyskanie nie jest możliwe. Nie podnoś automatycznie oczekiwanej liczby i nie wydawaj kolejnych kluczy w pętli. Wymagana będzie kontrolowana decyzja operatorska; model danych nie ma jeszcze gotowej procedury odwołania klucza.

## Przegląd wyniku przez drugi klucz

1. Potwierdź przez odczytowe `/auth/session`, że oba klucze mają ten sam `tenant_id` i różne `credential_id`. Odczyt drugiego klucza wykonaj przed nowym zadaniem, w osobnej prywatnej karcie, lub bez zmiany głównej sesji inicjatora.
2. W głównej karcie pozostaw klucz inicjatora w SETTINGS. Uruchom nowe `17 * 23` i odczytaj raport. Zmiana globalnego klucza kasuje bieżącego kandydata w interfejsie.
3. Druga osoba zapoznaje się z raportem i wprowadza swój klucz wyłącznie w pole drugiego operatora przy tym kandydacie. Weryfikacja obejmuje bieżący `tip_hash`, `report_sha256`, źródło, politykę i okno 15 minut.
4. Między wykonaniem a przeglądem nie dodawaj innych dowodów, np. przez `/chat` lub nowe zadanie. Odczyty `/auth/session` i `/control/runs/{run_id}` nie przesuwają tipa. Nowy dowód może unieważnić kandydata albo istniejące zatwierdzenie.
5. Potwierdź stan `GET /nina-run/{run_id}/approval` z właściwym Bearer. Uwzględnij `STALE`, `BLOCKED` i wygaśnięcie. Sukces ma zakres `review-result`; nie uprawnia do produkcji ani dowolnego polecenia Windows.

## Co pozostaje do odbioru

Testy automatyczne sprawdzają poświadczenia, izolację tenantów i trwały przegląd wyniku w testowej SQLite. Nie potwierdzają tożsamości drugiej osoby, jej odrębnego urządzenia, rzeczywistego modelu, Windows ani niezależnego wydania. Integracja z użytkownikami/rolami, kontrolowane odwoływanie kluczy i rzeczywisty odbiór przez drugiego operatora nadal wymagają osobnej implementacji i weryfikacji.
