# OLA DI-OS — instrukcja pracy dla Claude

Komunikacja z właścicielem po polsku. Docelowy runtime i odbiór produktu: Windows/ZBook. Cel jest ustalony: kompletny ekosystem OLA, asystent tekstowy/głosowy, modele, zadania, dokumenty, agenty, kontrolowane narzędzia, Evidence/IGOR/Replay, Aurora i obsługa Windows. Nie pytaj ponownie, co system robi, ani nie ograniczaj zadania do makiety.

## Zacznij od wykonania

1. Odczytaj `docs/CLAUDE-WINDOWS-NEXT.md` oraz konkretne komendy w `docs/CLAUDE-EXECUTION-RUNBOOK-PL.md`. Jeśli otrzymałeś paczkę audytu, odczytaj jej `START-DLA-CLAUDE.md`, aktualny status i katalog OLA-01–OLA-18.
2. Sprawdź istniejące zmiany i instrukcje lokalne. Nie wykonuj reset/clean ani nie nadpisuj pracy właściciela. Nie zmieniaj gałęzi w używanym checkout bez sprawdzenia; użyj osobnego worktree, gdy potrzebujesz izolacji.
3. Na Windows uruchom diagnostykę, która niczego nie instaluje:

```powershell
& .\workstation\OLA-Preflight.ps1 -RepoRoot (Get-Location).Path -OutputFile (Join-Path $env:TEMP 'ola-preflight.json') -ProbeLoopback
```

4. Zapisz faktyczny HEAD, tree, branch, lokalne zmiany i wersje narzędzi. JSON `COLLECTED` nie oznacza gotowego produktu. Ustal, czy preview i jego dane już istnieją; zachowaj je.
5. Wykonaj na Windows izolowane testy poprawek opisane w `docs/CLAUDE-WINDOWS-NEXT.md`, a następnie pierwszy rzeczywisty przepływ. Napraw pierwszą niedziałającą granicę i powtórz tylko właściwy test. Nie kończ na kolejnej inwentaryzacji.

## Źródło, preview i autoryzacja

- SHA paczki/brancha identyfikuje konkretny kod; nie jest zatwierdzeniem przez właściciela. Zmiana plików oznacza nowy stan do przetestowania. Nie odtwarzaj historycznego `b3d5fa99...` jako rzekomo obowiązującego HEAD.
- `OLA-Preview-Auth.ps1` domyślnie tylko sprawdza istniejący preview. `-CreatePreview` i `-IssueKey` są oddzielnymi operacjami zapisu. Nowy preview dotyczy wyłącznie nieistniejącego kontenera/wolumenu, dokładnego SHA i jawnego `ExpectedBranch` zgodnego z checkout. Dokument opisuje warunki wykonania; nie jest dowodem, że wykonano je na komputerze właściciela.
- Nie uruchamiaj historycznego `workstation/OLA-Workstation.ps1` jako aktualnego instalatora. Kasuje swój katalog źródłowy/kontener i używa starego SHA, deterministycznego trybu oraz stałego klucza.
- Core API key i token Local Executor to osobne domeny uprawnień. Nie umieszczaj sekretów w czacie, kodzie, logach ani paczkach. Nie twórz wspólnego klucza domyślnego.
- Zachowaj porównanie bajtów źródeł, brak fallbacku po błędzie Git, zakresy tenantów, niezależnego recenzenta i Human Gate. Nie wyłączaj testów ani bramek, aby uzyskać zielony wynik.
- Poprawny `/health`, lokalny hash, `APPROVED` przeglądu wyniku i zielony CI nie stanowią autoryzacji wykonania produkcyjnego. `main` i produkcja wymagają osobnego polecenia właściciela.

## Pierwszy rezultat i pełny zakres

Pierwszy krok integracji: UI → rzeczywiste uwierzytelnione API → lokalny model → ograniczone narzędzie → trwały raport/evidence → odczyt i replay → poprawny status UI. Osobno sprawdź brak klucza, zły klucz, błąd modelu oraz reset sesji podczas odpowiedzi. Przegląd wyniku wymaga odrębnego poświadczenia `REVIEW_RESULT` w tym samym tenantcie; nie zastępuj go nowym tenantem ani pełnym kluczem Core. Procedurę migracji, wydawania i unieważniania opisuje `docs/CREDENTIAL-LIFECYCLE-WINDOWS-PL.md`. Dotychczasowy dodatkowy klucz pozostaje Core i nie może zatwierdzać wyników. Rozdział uprawnień poświadczeń nie potwierdza tożsamości odrębnych osób.

To pierwszy etap pełnego zakresu, a nie jego redukcja. Prowadź macierz funkcja → kod → rzeczywisty test → artefakt → stan i kontynuuj OLA-01–OLA-17. Rozdziel testy izolowane, Windows CI i lokalny ZBook. Ujawnij każdy SKIPPED/NOT RUN i zakres symulacji.

## Zadania towarzyszące

W paczce audytu jest już pełny roboczy audiobook „FANTAZJA AI”, 43:13,5, oraz brief narracji. Zachowaj 20 części/48 rozdziałów i notę proweniencji między 47 i 48. Odbiór wymowy i głosu pozostaje otwarty. Najpierw odsłuchaj krótkie próby docelowego lektora o mocnej polskiej dykcji i komentatorskiej dynamice; nie regeneruj całej książki wyłącznie dla zmiany parametru tempa.

Promocja organiczna na wskazanym profilu OLA LinkedIn jest już zlecona. Historyczną blokadą był brak połączonej sieci Metricool. Jeśli masz ten kanał, sprawdź właściwy profil i duplikaty przed kontynuacją; nie pytaj ponownie o tę samą zgodę. Budżetu reklam płatnych nie ustalono. Nie wysyłaj innych wiadomości ani nie rozszerzaj promocji poza uzgodniony profil.

Nie zakładaj dostępu do wszystkich czatów GPT/Claude. Korzystaj z rzeczywiście dostępnych eksportów i plików; nie dopisuj historii. Raportuj krótko: co zmieniłeś, co uruchomiłeś, gdzie, na jakim SHA i co konkretnie nadal blokuje dalszy krok.
