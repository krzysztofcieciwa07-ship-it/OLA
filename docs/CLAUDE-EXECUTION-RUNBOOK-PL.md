# Polecenie dla Claude: wykonanie OLA DI-OS na Windows/ZBook

Pracuj w tym repozytorium i odpowiadaj po polsku. Cel pełnego ekosystemu jest ustalony w `CLAUDE.md`. Masz kontynuować implementację i rzeczywiste uruchomienie, a nie zakończyć na planie lub nowej makiecie. Poniższe kroki są kolejnością wykonania; konkretna awaria zatrzymuje zależny krok, ale nie inne niezależne prace.

## 1. Ustal rzeczywisty komputer i źródło

Wybierz lokalny folder `OLA-projekt` w Claude Code na ZBooku. W PowerShell uruchom ten blok z głównego katalogu repozytorium. Nie używaj PowerShell na Linux jako dowodu uruchomienia Windows.

```powershell
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Wymagany rzeczywisty Windows/ZBook.'
}
Get-Content .\CLAUDE.md, .\docs\CLAUDE-WINDOWS-NEXT.md
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Nie mozna odczytac checkout.' }
$OlaSha = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Nie mozna odczytac HEAD.' }
$OlaTree = (& git rev-parse 'HEAD^{tree}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Nie mozna odczytac tree.' }
$OlaBranch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or !$OlaBranch) { throw 'Wymagana jawna galaz.' }
$OlaLockPath = Join-Path (Split-Path -Parent (Get-Location).Path) 'SOURCE-LOCK.json'
if (Test-Path -LiteralPath $OlaLockPath) {
    $OlaLock = Get-Content -LiteralPath $OlaLockPath -Raw | ConvertFrom-Json
    if ($OlaLock.head_sha -cne $OlaSha -or $OlaLock.tree -cne $OlaTree) {
        throw 'Checkout rozni sie od paczki. Porownaj zmiany; nie nadpisuj ich.'
    }
}
$OlaReport = Join-Path $env:LOCALAPPDATA ('OLA-Control\reports\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $OlaReport | Out-Null
[pscustomobject]@{
    computer = [Environment]::MachineName
    os = [Environment]::OSVersion.VersionString
    checkout = (Get-Location).Path
    head = $OlaSha; tree = $OlaTree; branch = $OlaBranch
} | ConvertTo-Json | Set-Content (Join-Path $OlaReport 'source.json') -Encoding UTF8
& .\workstation\OLA-Preflight.ps1 -RepoRoot (Get-Location).Path -ExpectedSha $OlaSha -OutputFile (Join-Path $OlaReport 'preflight.json') -ProbeLoopback
if ($LASTEXITCODE -ne 0) { throw 'Preflight nie zebral poprawnie danych.' }
& .\workstation\OLA-Preview-Auth.ps1
```

Preflight zbiera stan; `COLLECTED` nie oznacza gotowego produktu. Ostatnie polecenie tylko odczytuje istniejący preview. Jeżeli zgłosi błąd, zapisz kod i ustal przyczynę. Zachowaj istniejące dane, kontenery, modele i lokalne zmiany. Nie używaj reset/clean, historycznego `OLA-Workstation.ps1` ani szerokiej zmiany uprawnień całego dysku.

Jeśli brak dostępu do folderu, najpierw sprawdź rzeczywistą ścieżkę, właściciela/ACL i czy ZIP został wypakowany do lokalnego katalogu użytkownika. Pracuj na osobnej kopii/worktree. Nie deklaruj połączenia z komputerem wyłącznie na podstawie instrukcji w czacie.

## 2. Uruchom regresje przed produktem

Sprawdź dostępność Node oraz Python 3.10+. Środowisko testowe i raporty mają być poza checkout, ponieważ bootstrap wymaga czystego źródła. Nie twórz `.venv` w repozytorium. Poniższy blok instaluje wyłącznie zależności testowanego projektu do nowego lokalnego venv; nie instaluje OLA jako usługi ani nie pobiera modelu.

```powershell
Get-Command node.exe -CommandType Application -ErrorAction Stop | Out-Null
Get-Command py.exe -CommandType Application -ErrorAction Stop | Out-Null
& py.exe -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Wymagany Python 3.10+.' }
$OlaVenv = Join-Path $env:LOCALAPPDATA ('OLA-Control\venvs\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Split-Path -Parent $OlaVenv) -Force | Out-Null
& py.exe -3 -m venv $OlaVenv
if ($LASTEXITCODE -ne 0) { throw 'Tworzenie venv nie powiodlo sie.' }
$OlaPython = Join-Path $OlaVenv 'Scripts\python.exe'
& $OlaPython -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Instalacja zaleznosci nie powiodla sie.' }
$OlaNodeTests = @(Get-ChildItem .\tests\*.test.cjs | ForEach-Object { $_.FullName })
& node.exe --test @OlaNodeTests
if ($LASTEXITCODE -ne 0) { throw 'Regresje UI nie przeszly.' }
& $OlaPython -m unittest discover -s tests -p test_capture_source_portable.py -v
if ($LASTEXITCODE -ne 0) { throw 'Regresje zrodel nie przeszly.' }
& .\tests\test_preview_bootstrap.ps1
if ($LASTEXITCODE -ne 0) { throw 'Regresje bootstrapu nie przeszly.' }
$OlaPytestXml = Join-Path $OlaReport 'pytest.xml'
& $OlaPython -m pytest -q --junitxml $OlaPytestXml
if ($LASTEXITCODE -ne 0) { throw 'Testy Pythona nie przeszly.' }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'Nie mozna sprawdzic stanu po testach.' }
```

Jeśli jest `python.exe`, a nie ma `py.exe`, użyj sprawdzonej ścieżki aplikacji Python do tych samych komend zamiast instalować drugi interpreter. Po każdej komendzie natywnej sprawdzaj jej kod, także na Windows PowerShell 5.1. Nie zapisuj wartości zmiennych środowiskowych ani sekretów do raportu. Testy z atrapą modelu pozostają testami z atrapą również na Windows.

## 3. Doprowadź do prawdziwego lokalnego preview

Sprawdź Docker Desktop i istniejący lokalny Ollama pod `http://127.0.0.1:11434`. Odczytaj `GET /api/tags` oraz `POST /api/show` dla wybranego, już obecnego modelu. Sprawdź metadane, a nie tylko nazwę: tag chmurowy lub `remote_host`/`remote_model` ma blokować uruchomienie. Brak wiarygodnych metadanych nie potwierdza lokalności. Nie pobieraj modelu ani nie uruchamiaj chmury automatycznie.

Istniejący preview naprawiaj z zachowaniem danych; `-CreatePreview` nie jest jego aktualizatorem. Wyłącznie gdy nie ma docelowego kontenera, wolumenu i sekretu, port 18081 jest wolny, a checkout jest czysty i przejrzany, przygotuj nowy preview. Użyj wartości odczytanych z tego checkout i rzeczywiście lokalnego modelu. Zmienna `$OlaModel` ma zawierać zweryfikowaną nazwę, nie przykład.

```powershell
if (!$OlaModel) { throw 'Najpierw ustal rzeczywisty lokalny model i jego metadane.' }
& .\workstation\OLA-Preview-Auth.ps1 -CreatePreview -ExpectedSha $OlaSha -ExpectedBranch $OlaBranch -Model $OlaModel
```

Oddzielny `-IssueKey` tworzy nowego tenanta i jednorazowo wypisuje jego klucz. Uruchom tę operację wyłącznie w prywatnym terminalu właściciela bez transkrypcji, a klucz wprowadź do lokalnego UI. Nie uruchamiaj jej przez narzędzie Claude zapisujące stdout w historii i nie proś o wklejenie klucza do czatu. Dla istniejącej instalacji użyj już skonfigurowanej tożsamości. Nie twórz kolejnego tenanta jako rzekomego drugiego recenzenta.

## 4. Wykonaj i udokumentuj pierwszy pełny przebieg

W UI pod `http://127.0.0.1:18081` wykonaj kolejno:

1. SETTINGS: rzeczywiste `GET /auth/session` z kluczem Core w nagłówku `X-API-Key`. Nie zapisuj sekretu w screenshotach, HAR ani raporcie.
2. CHAT: rzeczywiste pytanie do wybranego lokalnego modelu. Zapisz nazwę modelu i obserwowalny dowód inferencji. Sam `/health` nie wystarcza.
3. Kontrolowane wykonanie: `POST /nina-run`, JSON `{"task":"17 * 23","requested_tools":["safe_expression","local_mcp_tool_registry.sha256"]}`. Sprawdź wynik `391`, status aplikacyjny, `run_id`, powiązanie źródła/polityki i trwałe evidence. HTTP 200 może zawierać `BLOCK`.
4. Odczyt/replay: rzeczywiste `GET /control/runs/{run_id}`, potem odświeżenie strony i ponowny odczyt. Nie wymyślaj osobnego endpointu `/replay`; użyj istniejącego kontraktu Control Plane.
5. Sprawdź brak/zły klucz, innego tenanta, błąd modelu, pustą/wadliwą odpowiedź modelu, `Calculate 1 / 0`, przepełnienie pośrednie oraz zmianę klucza w trakcie żądania. Nie wyłączaj modelu współdzielonego z inną pracą; awarie badaj w izolowanym teście. Każdy test opisz jako rzeczywisty albo symulowany.
6. Local Executor: najpierw `& .\workstation\OLA-Local-Executor.ps1 -SelfTest`. Zwykłe uruchomienie bez parametrów działa w osobnym terminalu i wypisuje własny token; zastosuj tę samą ochronę stdout. Nie obsługuje parametrów `-Token`, `-Port` ani `-RepoRoot`. Połączenie z UI używa osobnego Bearer tokenu i Origin `http://127.0.0.1:18081`. Zweryfikuj `GET /v1/actions` oraz `POST /v1/run` z `{"action":"git-status"}`. Nie używaj klucza Core jako tokenu Executor.

Dla każdej granicy zapisz oczekiwane/obserwowane, SHA, run i artefakt. Napraw pierwszą potwierdzoną awarię, dodaj właściwą regresję, uruchom ją i kontynuuj. Nie nadawaj statusu pełnego E2E na podstawie atrap HTTP lub DOM.

## 5. Kontynuuj pełny ekosystem i pozostałe zadania

Prowadź macierz funkcja → kod → rzeczywisty test → artefakt → stan dla katalogu OLA-01–OLA-17. Domykaj asystenta tekstowego i głosowego, modele, zadania i dokumenty, narzędzia Windows, Evidence/IGOR/Replay, kokpit, instalację/aktualizację/backup i integracje. Nie zastępuj braków kolejnymi wskaźnikami „online”. Jeśli katalogu nie ma w repo, odszukaj go w dostarczonych materiałach i odnotuj dostępne źródło.

Drugiego recenzenta w tym samym tenantcie trzeba wdrożyć jako prawdziwą odrębną tożsamość z właściwą rolą. `-IssueKey` nie rozwiązuje tego zadania. Nie obchodź Human Gate, nie edytuj ręcznie produkcyjnej bazy. Brak tej tożsamości blokuje zależne zatwierdzenie, ale nie niezależne naprawy.

Audiobook jest odrębnym rezultatem: w folderze nadrzędnym sprawdź `audiobook/edycja-lektorska-v2/`. Zachowaj pełny tekst 20 części/48 rozdziałów, notę proweniencji między 47 i 48, epilog i zakończenie. Najpierw odsłuchaj próbki A/B oraz słownik nazw systemów, porównaj z tekstem i popraw błędne nazwy. Rozdziel tekst wydawniczy od fonetycznego. Docelowo dostarcz osobny odtwarzalny MP3 oraz indeks części, bez zastępowania książki krótką próbką. Nie deklaruj zaakceptowanej naturalności bez odsłuchu ani dostępu do nieudostępnionych czatów. Użyj oryginalnego polskiego lektora z wyraźną dykcją i dynamicznym prowadzeniem, bez podszywania się pod znaną osobę.

Promocję organiczną kontynuuj zgodnie z `CLAUDE.md` tylko na wskazanym profilu i przez rzeczywiście podłączony kanał, po sprawdzeniu duplikatów. Płatny budżet nie został ustalony.

Na końcu podaj krótko: wykonane zmiany, rzeczywiście uruchomione kontrole z systemem i SHA, działający przebieg, pliki oraz konkretne blokady. Oddziel `PASS`, `BLOCKED`, `NOT RUN`. Nie wykonuj push/merge do `main`, produkcyjnego wdrożenia ani zakupów w ramach tych instrukcji.
