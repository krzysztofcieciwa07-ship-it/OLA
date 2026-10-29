# ADR-001 — AFE/Vantage jako komponent bezpieczeństwa ekosystemu OLA

- Status decyzji: **ACCEPTED** — decyzja właściciela z 2026-10-30
- Status wykonania: **NOT IMPLEMENTED END-TO-END / L0 REQUIRED**
- Kanoniczne źródło decyzji: `krzysztofcieciwa07-ship-it/OLA`
- Zakres: AFE/Vantage (Sentinel Gate), OLA DI-OS (`execution_safety_gate`, `agent_registry`), lokalny `bot_v8.py`
- Zasada: **decyzja właściciela nie zastępuje dowodu technicznego**

## Decyzja

1. AFE/Vantage pozostaje jedynym docelowym silnikiem oceny polityki agentów. Nie tworzymy drugiego, konkurencyjnego klasyfikatora.
2. Istniejący `ExecutionSafetyGate` w OLA pozostaje **punktem egzekwowania** decyzji przy rzeczywistym wykonaniu. Vantage ocenia, OLA egzekwuje. Oznacza to jeden spójny system kontroli, nie dwie równoległe bramki autoryzacji.
3. Wszystkie luki P0 są usuwane przed rozszerzeniem uprawnień. Do przejścia bramki obowiązuje L0.
4. Żadna część AFE/Vantage nie może inicjować transferu, płatności LIVE ani zmiany salda. Doświadczenia przed L3 mogą używać jedynie symulacji PAPER oraz webhooków bez ruchu kapitału.
5. Dopuszczenie do operacji finansowych wymaga niezależnego dowodu G1–G7 na jednym przypiętym SHA oraz jawnej decyzji właściciela. Brak dowodu oznacza odmowę.
6. Odwracalność: spadek bramki dowodowej lub wykrycie regresji obniża uprawnienia do L0; nie ma automatycznej promocji.

## Uzasadnienie

Jedna polityka, jedno miejsce egzekwowania i jeden audytowalny przepływ ograniczają rozbieżności. Naprawa istniejących komponentów ma pierwszeństwo nad budową alternatywy. Każda deklaracja z README wymaga odpowiadającego jej testu; deklaracje nieudowodnione są usuwane albo jawnie oznaczane jako SPEC/UNKNOWN.

## Docelowy kontrakt decyzyjny

`request -> authenticated identity + tenant + action + risk -> Vantage policy -> OLA enforcement -> evidence -> optional Human Gate -> outcome`

| Vantage | OLA / dowód | Skutek |
|---|---|---|
| `ALLOW` | `ALLOW` | Wyłącznie autoryzowana, jawnie dozwolona akcja w granicach poziomu |
| `BLOCK` | `DENY` | Brak efektu ubocznego; audyt odmowy |
| `HUMAN_APPROVAL` | `REVIEW` | Brak wykonania do czasu autentycznej, związanej z akcją zgody |

`HUMAN_APPROVAL` nie jest decyzją `ALLOW`. Pole bool przesłane przez klienta nie jest dowodem zgody. Bramka musi sprawdzać tożsamość, tenant, operację, SHA, hash dowodu, ważność i odporność na replay.

## P0 — katalog i kryteria zamknięcia

Wiersze PRIOR zachowują sens wcześniejszego ADR; poniższy status jest aktualizacją **dowodową**, nie deklaracją pełnego zamknięcia.

| ID | Obszar | Status 2026-10-30 | Warunek zamknięcia |
|---|---|---|---|
| P0-1 | AFE: osiągalność `HUMAN_APPROVAL` | PARTIAL / wcześniejsza wzmianka o `vantage_gate.py` wymaga mapowania na obecny `afe_vantage.py` | E2E na rzeczywistym wejściu z `ALLOW`, `BLOCK`, `HUMAN_APPROVAL`; nie tylko wywołanie `decide()` |
| P0-2 | OLA: bramka i rejestr na `/agent-run` | STATIC VERIFIED w `app/main.py`; testy HTTP są obecne, ale wykonania runtime na bieżącym SHA nie potwierdzono w tym przeglądzie | GitHub Actions z testem `HIGH` -> HTTP 403, brak `run_agent_task`, zapisane evidence |
| P0-3 | `bot_lock.py` i `execution_guard.py` z `bot_v8.py` | UNKNOWN: plików nie znaleziono w bieżącym drzewie kanonicznego OLA | Wskazać dokładny source SHA, dwuprocesowy test lock i test LIVE z brakującymi zmiennymi env |
| P0-4 | Rotacja starych kluczy z archiwum `.env` | UNKNOWN | Dowód rotacji u każdego dostawcy i test odrzucenia starych kluczy (401), bez ujawniania sekretów |
| P0-5 | Zakres Execution Layer | POLICY APPROVED, RUNTIME NOT VERIFIED | Wdrożony, negatywnie testowany zakaz ruchu kapitału w L0–L2; tylko webhook / PAPER |
| P0-6 | CI, Cosign, Docker CFR-18 | BLOCKED | Zielony CI **i niezależna weryfikacja** na jednym SHA, artefakty i potwierdzenie Docker live; podpis źródła |

**Dodatkowa luka wdrożeniowa L0:** bieżący kod OLA `/agent-run` dopuszcza zarejestrowane zadania `LOW`. Dlatego samo opublikowanie tego ADR **nie wymusza L0**. Brak fail-closed runtime guard dla poziomu uprawnień pozostaje blokadą przed wdrożeniem ADR.

## Poziomy uprawnień

| Poziom | Uprawnienie | Awans |
|---|---|---|
| L0 | Obserwacja, zapis decyzji, brak efektów wykonawczych AFE | Stan początkowy i powrót po regresji |
| L1 | PAPER bez kapitału; symulowane zadania | P0-1..P0-3, G1–G4 |
| L2 | PAPER z prawdziwym `HUMAN_APPROVAL`; nadal **zero ruchu pieniędzy** | G1–G6 na dokładnym SHA |
| L3 | LIVE tylko z limitami, circuit breaker, dwoma odrębnymi jawnie włączonymi warunkami env oraz zatwierdzeniem właściciela | G1–G7 i zapis decyzji właściciela w repo |

L2 nie upoważnia do prawdziwej transakcji nawet po zgodzie człowieka. Ewentualna kontrola lub wykonanie finansowe zaczyna się dopiero na L3 po spełnieniu odrębnych warunków bezpieczeństwa.

## Bramka dowodowa G1–G7

- **G1:** czysty *Git checkout* na przypiętym SHA w GitHub Actions; nie chodzi o Stripe Checkout.
- **G2:** logi, testy, SHA-256 plików, identyfikator runu, commit SHA i niezmienny artefakt.
- **G3:** test przez prawdziwy endpoint/punkt egzekwowania, nie wyłącznie import modułu.
- **G4:** osiągalność wszystkich trzech wyników z rzeczywistym wejściem.
- **G5:** bypassy, parafrazy, rozstrzelone litery, brak tokenu, błędny tenant, nieznana akcja i brak konfiguracji są odrzucane; brak efektów ubocznych.
- **G6:** weryfikator poza kodem aplikacji przelicza hashe i sprawdza podpis, SHA, źródłowy run oraz tożsamość workflow; nie importuje aplikacji.
- **G7 (L3):** niezależny przegląd i ponowne wykonanie G1–G6 przez osobę spoza sesji autorów, z podpisanym wynikiem.

Nie wystarcza zielony test izolowanego komponentu, osobny SHA w każdej bramce ani nieweryfikowalny raport tekstowy.

## Zasady wykonania i źródło prawdy

- Kanoniczne repo: `krzysztofcieciwa07-ship-it/OLA`. Repo `vantage` pozostaje źródłem komponentu do czasu kontrolowanej migracji i przypięcia wersji, a nie drugim produkcyjnym centrum decyzji.
- Katalog roboczy i wersja kodu muszą być jednoznacznie wskazane w evidence manifest. Dawne kopie i archiwa nie stają się automatycznie produkcją.
- Do czasu zatwierdzonego merge/deploy status zmian z PR pozostaje **CANDIDATE**.
- Żadne sekrety, bankowe identyfikatory osobowe ani pełne dane płatności nie mogą być publikowane w evidence.
- Żadnych zgód domniemanych, hidden gates ani automatycznej promocji do LIVE.

## Migawka źródeł i zastrzeżenia audytu — 2026-10-30

- OLA `main`: `f9dce999ec4447d80b23ce5ac6aa5a840f7e6144`, commit podpisany, gałąź niechroniona.
- `app/main.py` importuje i wywołuje `ExecutionSafetyGate` oraz `build_agent_registry`; `tests/test_agent_run_safety_gate.py` zawiera testy negatywne. To jest dowód kodu, nie niezależny E2E na tym SHA.
- Vantage `main`: `1dc161887903b2151ff5c815a322c056ce8b35e8`, unsigned, gałąź niechroniona.
- Vantage Draft PR #8: `ffed66c8361abc5a56edff0dd1a417bf93a25940`. `Vantage Verify` run 40968975127 = SUCCESS, artefakt 12939461955; niezależny run 40969041489 = FAILURE (tożsamość certyfikatu PR vs main). CFR-18: osobne błędy; nie uznawać P0-6 za zamknięte.
- Określenie „nieważny token GitHub” z wcześniejszych notatek nie zostało potwierdzone — odczyt przez połączenie GitHub zadziałał.
- Źródła: https://github.com/krzysztofcieciwa07-ship-it/OLA ; https://github.com/krzysztofcieciwa07-ship-it/vantage ; https://github.com/krzysztofcieciwa07-ship-it/vantage/pull/8

## Konsekwencje

Wstrzymanie ekspansji uprawnień i nowych funkcji zależnych od AFE do czasu zamknięcia P0-1..P0-3. Produkcja finansowa pozostaje zabroniona bez pełnej niezależnej bramki i zatwierdzenia właściciela. Każde twierdzenie o stanie systemu ma wskazywać konkretny SHA, run, artefakt i wynik.

## Pewność

- Wysoka: polityka „integracja i dowód przed finansami”.
- Wysoka (statycznie): obecne importy i blokada HIGH w OLA.
- Średnia: skuteczność kontroli end-to-end, ponieważ nie wszystkie testy wykonano na aktualnym `main`.
- Niska: termin finalizacji i stan źródeł `bot_v8.py` oraz rotacji dawnych sekretów.
