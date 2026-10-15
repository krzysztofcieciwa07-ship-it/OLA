# Pierwsze wykonanie Claude na Windows

Materiał do kontynuacji pracy, nie potwierdzenie produkcyjnej gotowości. Zmiany przygotowano na gałęzi PR #105, baza `d3737de160492716c67c153002a2b10dce841d34`. Baza PR to gałąź `ui/ola-command-center-live-20261014`, nie `main`. Aktualny SHA poprawionej paczki jest w zewnętrznym `SOURCE-LOCK.json`; nie nadawaj bazowemu SHA znaczenia zatwierdzonego wydania.

## Dlaczego potrzebne są te poprawki

1. Aurora w `busy().finally` bezwarunkowo odblokowywała przycisk. Po `APPROVED` znów można było go nacisnąć bez kandydata; reset sesji też nie utrzymywał blokady. Poprawka wyprowadza stan z aktualnego kandydata i tłumi błędy poprzedniej epoki.
2. `capture_source` porównywał nazwy Git z `str(relative_path)`. Na Windows separator `\` powodował fałszywe odrzucenie poprawnych plików jako niezarejestrowanych. Poprawka używa `as_posix()`; sprawdzanie dokładnych bajtów pozostaje.
3. Preview na PR #105 nie przechodził bramki historycznej nazwy gałęzi; czysty checkout dodatkowo nie miał ignorowanego `source-manifest.json` wymaganego przez Dockerfile. Bootstrap musi sprawdzić jawny branch i SHA, wygenerować inventory przed budowaniem i wykonać build przed utworzeniem sekretu. Szczegóły rzeczywistej zmiany odczytaj z diffu i `workstation/OLA-Preview-Auth.ps1`.

Importy Pythona tworzą też `__pycache__`; dodano wąskie ignorowanie tych plików, aby sam generator/test nie zmieniał stanu czystości checkout. Kontrola źródeł już pomijała cache, a dodatkowe rzeczywiste pliki w `app`/`policies` nadal blokują obserwację.

## Najpierw testy bez instalacji produktu

W PowerShell, w głównym katalogu prawdziwego checkout:

```powershell
node --test .\tests\aurora_approval_state.test.cjs
python -m unittest discover -s tests -p test_capture_source_portable.py -v
& .\tests\test_preview_bootstrap.ps1
```

Te testy nie wymagają FastAPI, kluczy, modelu ani bazy. Gdy Node lub Python nie istnieje, zapisz konkretny brak; nie deklaruj PASS. Samodzielny test PowerShell bootstrapu jest wskazany w `START-DLA-CLAUDE.md` paczki i plikach testowych.

Parsowanie skryptów na Windows PowerShell:

```powershell
foreach ($OlaFile in @('workstation/OLA-Preflight.ps1','workstation/OLA-Preview-Auth.ps1')) {
    $OlaTokens = $null
    $OlaErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path (Get-Location).Path $OlaFile), [ref]$OlaTokens, [ref]$OlaErrors
    ) | Out-Null
    if ($OlaErrors.Count -gt 0) { throw ('Bledna skladnia: ' + $OlaFile) }
}
& .\workstation\OLA-Preflight.ps1 -RepoRoot (Get-Location).Path -ProbeLoopback
```

Izolowane kontrole wykonane na Linux nie zastępują tego kroku ani testu Windows/ZBook. Nie uruchamiaj wszystkich skryptów `workstation` po kolei.

## Istniejący preview

Uruchom bez trybu zapisu:

```powershell
& .\workstation\OLA-Preview-Auth.ps1
```

`AUTH_NOT_CONFIGURED`, nieuruchomiony kontener, istniejący wolumen lub nieznane dane wymagają zbadania konkretnego stanu. Nie kasuj/odtwarzaj kontenera, nie przechodź na stary instalator i nie używaj `-CreatePreview` jako naprawy istniejącej instalacji. Backup i odtworzenie muszą być osobno przygotowane.

## Nowy preview i pierwszy realny przepływ

Przed zapisem sprawdź Docker Desktop, lokalny Ollama i istniejący model; czysty, zreviewowany checkout; dokładny SHA/branch; brak docelowego preview/wolumenu/sekretu oraz wolny port 18081. Nie uruchamiaj modelu chmurowego lub pobierania modelu automatycznie. Do źródeł na Windows wyłącz konwersję LF→CRLF podczas klonowania (`git -c core.autocrlf=false clone ...`): observer porównuje rzeczywiste bajty z Git i prawidłowo odmówi innego pliku. Nie rozluźniaj kontroli bajtów jako obejścia.

Użyj `-CreatePreview -ExpectedSha '<dokladny-SHA>' -ExpectedBranch '<faktyczna-galaz>' -Model '<dostepny-lokalny-model>'` tylko w przeznaczonym do tego, pustym środowisku lokalnym. Klucz tworzony jest oddzielnie przez `-IssueKey`; nie drukuj go w raporcie. Nie używaj przykładowych wartości jako prawdziwych.

Następnie w UI `http://127.0.0.1:18081`:

1. SETTINGS → zweryfikuj klucz przez rzeczywiste `/auth/session`.
2. CHAT → wyślij krótkie pytanie i potwierdź inferencję wybranego modelu. Brak modelu ma być kontrolowanym błędem/BLOCK.
3. Kontrolowane wykonanie → `17 * 23`; sprawdź rzeczywisty wynik `391`, identyfikator run, źródło/politykę/parametry oraz trwały raport. Nie myl tego zadania z arbitralnym wykonaniem PowerShell.
4. Control Plane → odczytaj run oraz replay; po odświeżeniu strony ponownie odczytaj zachowane dane. Nie dopisuj `VERIFIED` na podstawie samego HTTP 200.
5. Zmień/wyczyść klucz podczas żądania: stary wynik nie może pojawić się w nowej sesji. Brak/zły klucz oraz inny tenant muszą zostać odrzucone.
6. Osobny Local Executor i token: wykonaj tylko zarejestrowaną akcję odczytową `git-status`. Nie używaj klucza Core jako tokenu Windows.

Każdy etap ma dać zapis oczekiwane/obserwowane, błąd pierwszej granicy i powiązanie do SHA/run/artefaktu bez sekretów. Potem napraw tę granicę i kontynuuj katalog.

## Konkretne dalsze blokady

- Onboarding drugiego recenzenta w tym samym tenantcie nie jest udokumentowany jako rzeczywista procedura operatorska. `provision_local_operator.py` tworzy nowego tenanta z jednym kluczem. Dwa nowe tenanty nie spełniają tego kontraktu. Zaprojektuj kontrolowane utworzenie właściwej tożsamości/roli, bez ręcznej edycji produkcyjnej bazy i bez mocków w demonstracji.
- `workstation/verify.ps1` ufa polom historycznego `MANIFEST.json`. Nie potwierdza zawartości artefaktów ani obecnego runtime. Nie traktuj go jako odbioru tych zmian.
- Windows workflow sprawdza bridge i część kontraktów, a nie pełne `CreatePreview` + Docker + model + recenzenta. Wyniki każdego zakresu raportuj oddzielnie.
- Nie potwierdzono pełnego głosowego asystenta, wszystkich integracji, instalacji/aktualizacji/backupów ani całego OLA-01–OLA-17. To nadal wymagania końcowe, nie opcjonalne pominięcia.
- Wymagane podpisy, niezależny review/IGOR, egzekwowanie ochrony gałęzi i autoryzacja produkcyjna pozostają odrębne. Lokalna poprawka nie usuwa `PRODUCTION NO-GO`.
