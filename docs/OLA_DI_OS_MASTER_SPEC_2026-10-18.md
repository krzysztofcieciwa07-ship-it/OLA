# OLA di-OS — JEDYNA SPECYFIKACJA WYKONAWCZA FRONTENDU I INTEGRACJI

**Data:** 2026-10-18  
**Cel:** ukończyć już istniejący OLA di-OS — działającą witrynę publiczną, aplikację operacyjną, istniejące moduły, testy, dowody, przygotowanie do bezpiecznego wdrożenia.  
**Tryb:** bez przepisywania całego projektu; bez duplikatów; bez udawanych funkcji, wyników i statusów.

> **POLECENIE GŁÓWNE DLA AGENTA PROGRAMISTYCZNEGO**  
> Pracuj w `krzysztofcieciwa07-ship-it/OLA`. Najpierw odczytaj i zinwentaryzuj kod, gałęzie, PR #109 i #113, API, testy i mechanizmy autoryzacji. Dokończ **istniejący** frontend Command Center, dołącz do niego spójną, wielopodstronową witrynę OLA di-OS w nowej identyfikacji wizualnej opisanej poniżej. Nie twórz alternatywnego frontendu ani nowego backendu. Wszystkie funkcje muszą działać przez rzeczywiste API i rzeczywiste polityki, a funkcje bez backendu mają status UNAVAILABLE/UNVERIFIED, nie fikcyjne „healthy”. Wykonaj testy, udokumentuj dowody z dokładnym SHA, przygotuj bezpieczny PR. NIE wykonuj automatycznie merge/deploy/produkcji, dopóki wszystkie bramki bezpieczeństwa i niezależna autoryzacja nie będą realnie potwierdzone.

## AKTUALIZACJA DLA PR #113

Specyfikacja wykonawcza ma pierwszeństwo w zakresie docelowym, jednak opis początkowego snapshotu w sekcji 1 jest historyczny. Zanim cokolwiek zmienisz, odczytaj aktualny HEAD, diffs, testy CI i rzeczywisty kontrakt API. W czasie dołączenia dokumentu do PR #113 jego gałąź wskazywała na `ef6d2010b7f1848fdab6f4b154a22a17b0420a39`. Strony publiczne i Command Center są już na tej gałęzi; **nie twórz ich ponownie**. Kontynuuj od audytu braków. Każdy nowy commit zmienia SHA i unieważnia wcześniejsze bramki.

## 1. STAN ŹRÓDEŁ ODCZYTANY NA 2026-10-18

- Repo: `https://github.com/krzysztofcieciwa07-ship-it/OLA`.
- Na `main` istnieją `web/index.html`, `app/main.py` (FastAPI), `app/nina.py`, `app/igor.py`, `app/nina_igor.py`, `app/replay.py`, `app/agent_runtime.py`, `app/chat_runtime.py`, `app/human_gate.py`, `app/decision_report.py`, `app/hashchain.py`, `app/database.py`, `app/revenue.py`, `app/stripe_webhook.py`, `tests/`, `scripts/`, `workstation/`.
- PR #113: `ui/ola-command-center-20261018`, HEAD podczas pierwszego odczytu `76a8eee16563caa99a87a974d8ad915a8c6bf771`, **OPEN/DRAFT**. PR deklaruje podłączenie już istniejącego Command Center do realnych endpointów, 4 lokalne testy kontraktowe, brak potwierdzonego pełnego browser E2E na realnym backendzie; zależy od PR #109.
- PR #109: `feat/nina-parallel-dag-engine-20261017`, HEAD podczas odczytu `c4a3843b9b6a7319fc212d60274597731a104a7c`, **OPEN**, NINA parallel DAG. Opis PR wspomina wcześniejsze udane workflow CI, ale nie jest to dowód produkcyjnego GO, obecności docelowego hosta ani niezależnego Human Gate.
- `main` udostępnia m.in.: `GET /health`, `GET /`, `POST /chat`, `POST /agent-run`, `POST /nina-run`, `POST /nina-run/{run_id}/approve`, `POST /evidence`, `GET /evidence/{record_id}`, `POST /audit`, `POST /checkout`, `GET /payment-success`, `POST /business-invoice-run`, `POST /stripe/webhook`. PR #109/#113 dodają / używają `POST /nina-workflow`, raport i zatwierdzanie workflow. **Sprawdź prawdziwy kontrakt na dokładnym finalnym SHA przez OpenAPI/testy** — nie zgaduj pól ani ról.
- Granica prawdy: `GET /health` zwraca tylko stan health tego serwisu; nie dowodzi, że Ollama, agenci, płatności, IGOR lub produkcja działają. CI PASS ≠ produkcja GO.

## 2. ZASADY NIEPODLEGAJĄCE NEGOCJACJI

1. `INSPECT -> MAP -> REUSE -> IMPLEMENT -> TEST -> EVIDENCE -> INDEPENDENT VERIFY -> HUMAN GATE -> DECISION`. Przed zmianami sporządź tabelę EXISTING / PARTIAL / MISSING / BLOCKED; wskaż ścieżkę pliku i dowód.
2. Jeden backend FastAPI, jeden faktyczny system OLA, jeden Command Center; publiczna strona i panel użytkownika mogą mieć osobne ścieżki/routing, ale wspólne komponenty, tokeny design system i API. Nie dodawaj drugiej autonomicznej platformy.
3. Brak danych demonstracyjnych pod etykietą LIVE. Stan nieznany = `UNKNOWN`; niedostępny = `UNAVAILABLE`; niezweryfikowany = `UNVERIFIED`; symulacja = `SIMULATION`; niepowodzenie = `FAILED/BLOCKED`. `VERIFIED` tylko dla określonego twierdzenia popartego dowodem.
4. Default-deny/fail-closed; RBAC, izolacja tenantów, brak autoapprove, brak automatycznego podpisu niezależnego recenzenta, brak kluczy w JS i w repo. Nie rozszerzaj znaczenia starego hasła VERIFIED z walidacji hash na atestację.
5. NINA wykonuje, IGOR niezależnie weryfikuje, Human Gate autoryzuje właściwy zakres i SHA. Odpowiedź modelu ≠ wynik wykonanej operacji.
6. Brak nowego merge do `main`, force-push, live deploy, obciążania infrastruktury, czyszczenia dysku czy aktywacji Stripe LIVE bez weryfikacji i odpowiedniej zgody.
7. Nie dodawaj Claude jako zależności; domyślnie użyj istniejących konfiguracji Ollama local/cloud i innych już istniejących providerów, jawnie rozdzielając ich provenance.

## 3. NOWA IDENTYFIKACJA WIZUALNA — KULA OLA

**Źródłem estetyki jest wskazany przez użytkownika obraz**, nie poprzednie błękitne, płaskie kule.

- Znak rozpoznawczy: duża **trójwymiarowa kula z elektrycznie niebieskim, wirującym rdzeniem**, opasana **złotą geometryczną siatką/pierścieniami**, ze szklistymi refleksami, delikatną aurą i szczegółami premium.
- Hero: kula w tle i w centrum kompozycji, bez zasłaniania tekstu; płynna animacja obrotu pierścieni, subtelnego pulsu rdzenia, lekkiego parallax, startowego rozświetlenia. Nie robić z tła ciężkiego wideo stale pobierającego zasoby.
- Paleta: #03050A (tło), #0B1120 (panel), #0070F3 (blue), #00D2FF (cyan), #C9A66B / #D6B56E (metaliczne złoto), #10B981 (potwierdzony zdrowy stan), #94A3B8 (muted), #FFFFFF (tekst). Złoto = marka/akcent, **nie** „PASS”.
- Teksty hero: `OLA di-OS`, `FROM OBJECTIVE TO VERIFIED RESULT.`, `DONE ≠ CLAIMED DONE`, `OPERATIONAL AI`. CTA `REQUEST A PILOT` i `OPEN COMMAND CENTER / VIEW DEMO` (demo wyraźnie oznaczone).
- Typografia: nowoczesny sans-serif, silny kontrast, mała liczba efektów typu glass, zrozumiała hierarchia. Ikony SVG, żadnego tekstu udającego schemat generowany przez AI.
- Animacje sterowane `prefers-reduced-motion`, zatrzymanie w tle, oszczędność baterii i GPU, płynne przejścia, opcja zatrzymania, brak wymuszonego scroll-lock, brak niekontrolowanych WebGL context leaków.
- Desktop 4K, 1440p, 1080p; tablet i telefon (w tym Android Galaxy Z Flip 3). DPR/responsive, LCP, alt, WCAG 2.2 AA, klawiatura/focus, czytelne na 200% zoom. Assety WebP/AVIF z PNG fallback; jeśli użyto 3D, fallback statyczny.
- Dostarcz **realną grafikę/asset kuli** z prawem użycia; nie używaj obrazka samego edytora kodu jako tła. Nie wymyślaj, że zdjęcie użytkownika jest już w repo — sprawdź i dołącz zaakceptowany plik.

## 4. MAPA WITRYNY PUBLICZNEJ — PRAWDZIWE PODSTRONY

Docelowe adresy (dostosować routing do FastAPI, zachować kompatybilność istniejącego `/` oraz deep linki):

| Ścieżka | Podstrona i funkcje |
|---|---|
| `/` | Hero z kulą, CTA, architektura 6 kroków, zalety bez nieudokumentowanych obietnic, funkcje, bezpieczeństwo, use cases, FAQ, cennik/pilot, footer. |
| `/product` | OLA jako produkt: Objective Intake, Decision Core, Multi-agent Orchestrator, NINA, IGOR, Policy Gate, Evidence, Replay, Human Gate, monitoring. Karty z realnymi linkami do szczegółów. |
| `/architecture` | Interaktywny diagram `Objective -> Plan/DAG -> NINA -> Runtime/Tools -> Evidence -> IGOR -> Policy -> Human Gate -> Replay -> Signed Result`; opis warstw L1–L5 i granic zaufania. |
| `/agents` | Role i zasady orkiestracji; zadania równoległe, zależności, retry, timeout, idempotencja, human-in-loop, provenance. |
| `/evidence` | Dlaczego hash-chain, zakres zapisu, niezależna weryfikacja, replay i świadome ograniczenia dowodów. |
| `/security` | Least privilege, default-deny, tenant isolation, RBAC, podpisy, supply chain, mTLS/TLS, zagrożenia i polityka disclosed limitations; nie udawać certyfikacji. |
| `/integrations` | Dostępne i planowane konektory, Ollama local/cloud, GitHub, narzędzia, webhooki; stan CONNECTED/DISCONNECTED/UNVERIFIED według API. |
| `/use-cases` | Automatyzacja firm, dowodowe workflow, audyt, obsługa klienta, CFR trening, praca na ZBook; fikcyjne case studies zakazane. |
| `/pricing` | Pakiety i zakres; ceny wyłącznie po potwierdzeniu decyzji handlowej, waluta i VAT. Oferta audytu/pilota może być pokazana jako projekt; brak fałszywych referencji i gwarancji. |
| `/pilot` | Formularz pilota: imię, firma, e-mail, przypadek użycia, wymagania, zgody; walidacja, anti-spam, rzeczywisty backend zgłoszeń, numer referencyjny, potwierdzenie stanu wysyłki. |
| `/contact` | Dane kontaktowe tylko jeśli zatwierdzone; kontakt z rzeczywistą obsługą backendu, bez `alert('sent')`. |
| `/docs` | Dokumentacja możliwości, API, quickstart, status implementacji, ograniczenia, integracje. |
| `/privacy`, `/terms` | Prawdziwe polityki, cookies bez mechanizmów śledzących jeśli nie są potrzebne; przygotować do prawnej weryfikacji. |

Dołączyć działające: top-nav + mobile menu, wyszukiwarkę dokumentacji (po realnej treści), breadcrumbs, aktywne menu, SEO/meta/OG, sitemapy/robots, 404/500, tryb językowy PL/EN, widoczne ładowanie i błędy, CTA i formularze. Nie robić martwych linków.

## 5. WEWNĘTRZNA APLIKACJA / COMMAND CENTER — ROZBUDOWA ISTNIEJĄCEGO PANELU

**To NIE jest nowy frontend.** Zachowaj `web/index.html` / PR #113 i rozszerzaj komponentami, w jednej architekturze routingu. Proponowane adresy docelowe poniżej. Wersja minimalna może zachować dotychczasowe zakładki i przejść do routingu po testach.

| Trasa / moduł | Komplet funkcji |
|---|---|
| `/app` Cockpit | Prawdziwe `/health`; stan silnika i integracji tylko z dostępnych endpointów; ostatnie runy, blokery, źródło, SHA, wersja, tenant, godzina odświeżenia, karty UNKNOWN przy braku danych, główne akcje. |
| `/app/assistant` NINA Chat | Rzeczywisty `POST /chat`, walidacja, historia bieżącej sesji, błędy 401/403/429/503, status modelu z backendu, przejście z odpowiedzi do rzeczywistego zadania, oznaczenie `MODEL OUTPUT ≠ VERIFIED RESULT`. |
| `/app/workflows` Planner/DAG | Ustawianie celu, priorytetu i ograniczeń; wizualizacja DAG, zależności i równoległości, statusy węzłów, run_id, logi, timeout, limit iteracji, zatrzymanie/anulowanie jeśli obsługiwane; endpointy PR #109. |
| `/app/execution` NINA Executor | `POST /nina-run` / `POST /agent-run` zgodnie z kontraktami; narzędzia tylko z allowlist, preflight policy check, jawne zatwierdzenie dla mutacji, output, elapsed time, evidence ID. |
| `/app/agents` Agenci | Rejestr **istniejących** agentów, ich możliwości, wymagane uprawnienia, provider/model, ostatni run, errors; żadnego fikcyjnego „24/24 active”. |
| `/app/igor` IGOR | Odczyt raportu i niezależna weryfikacja, verdict z powodami, source SHA, tip_hash, zakres sprawdzenia, oddzielenie `local hash verification` od zewnętrznej atestacji. |
| `/app/evidence` Evidence | Przeglądaj po ID, hash-chain/seq/prev_hash/record_hash, rodzaj dowodu, pochodzenie, eksport JSON jeśli backend umożliwia; sprawdzanie poprawności na serwerze; tamper test tylko w izolowanym środowisku. |
| `/app/audit` Audit | Rejestr zmian, filtrowanie, zakres tenantu; obecne `POST /audit` jest audytem kontrolowanym/symulacją i musi być tak opisany; historia read-only wymaga realnego endpointu. |
| `/app/replay` Replay | Wyświetl przebieg, wynik, porównanie z oryginałem i ograniczenia; brak przycisku udającego niezależny replay. |
| `/app/policy` Policy Gate | Prawdziwe reguły, wynik `ALLOW/BLOCK/REVIEW`, powód i źródło; edycja wyłącznie dla właściwych ról, historię zmian zapisać w audit. |
| `/app/human-gate` Human Gate | Odrębny reviewer, niezależność od autora, kontekst/zakres/expiry, `tip_hash`, source SHA i digest raportu; wymóg ponownej zgody po zmianie treści, token tylko w pamięci karty; bez „Approve all”. |
| `/app/health` Operacje | Status API, zależności, Ollama, baza, kolejki, obciążenie, SLI/SLO jeśli endpointy istnieją; refresh/polling z limitami, timestamp i przyczyna, UNKNOWN w przypadku błędu. |
| `/app/integrations` Integracje | Status providerów, uprawnienia, scope, test połączenia, webhook health, brak sekretów w kliencie; odłączony provider pokazuj jako odłączony. |
| `/app/revenue` Przychód | Faktyczne płatności i potwierdzenia backendu/Stripe; waluta, tenant, payout/runs, nie pokazuj zmyślonych kwot ani „LIVE” bez potwierdzenia. |
| `/app/admin` Administracja | Konta, role RBAC, tenants, feature flags, ustawienia retencji, eksport/restore z kontrolą, API key lifecycle, system notices; tylko przy backendowym enforced auth. |
| `/app/settings` Ustawienia | Motyw, język, reduced motion, profil, bezpieczny wybór modelu/providerów (na backendzie), ustawienia powiadomień, stan połączenia, wylogowanie/wyczyszczenie sesji. |
| `/app/workstation` ZBook | Stan CPU/RAM/GPU/dysków C i D, Docker/WSL2/Ollama i procesów tylko przez zaufanego lokalnego agenta; bez zdalnego udawania dostępu. Czyszczenie/kompresja: dry-run, podgląd, allowlista, backup/rollback, zgoda; bez formatowania D. |
| `/app/training` CFR | Po odnalezieniu istniejącej platformy: CFR-14/15/18, fault injection tylko w sandboxie, testy, SLI/SLO, scoring, anti-LLM, artefakty dowodowe; nie generuj drugiej platformy. |

Dla każdej pozycji implementuj także **podfunkcje**: deep link, filtrowanie, sortowanie, wyszukiwanie, paginację, obsługę pustego stanu, wykrywanie uprawnień, stan połączenia, kopiowanie identyfikatorów, eksport jeśli dostępny, dostępność i testy.

## 6. KONTRAKT FRONTEND ↔ BACKEND

- Jedno źródło konfiguracji API, najlepiej same-origin z istniejącym FastAPI. Żadnych domyślnych „localhost:3000” podszywających się pod serwer produkcyjny.
- Wygeneruj API client/types z rzeczywistego `/openapi.json` na dokładnym SHA albo uzgodnij istniejące modele/testy; nie wymyślaj schematów JSON.
- Wszystkie mutacje: jawny `loading`, retry tylko dla idempotentnych metod, timeout, cancel, correlation_id / run_id, obsługa 400/401/403/404/409/422/429/500/503 i ograniczona liczba żądań.
- Authentication: obecnie `X-API-Key` w istniejącym Command Center pozostaje wyłącznie w pamięci karty. Reviewer ma odrębny klucz. Nie używaj `localStorage`, cookies ani URL do przechowywania kluczy. Jeśli auth produktowy wymaga cookies, projektuj osobny **bezpieczny backend BFF** ze HttpOnly/Secure/SameSite/CSRF i tylko po zatwierdzeniu architektury.
- Autoryzacja jest egzekwowana **na backendzie**, nie tylko poprzez ukrycie przycisku. Każde żądanie tenant-scoped. Każda operacja mutująca powinna mieć server-side audit, idempotency key tam, gdzie to możliwe, i policy enforcement.
- Nie wstrzykuj odpowiedzi API jako HTML (`innerHTML`); stosuj `textContent`/bezpieczny renderer. CSP, no inline secrets, XSS protection, input validation, poprawne CORS/CSRF, SSRF guard dla URL-i.
- Formularz pilota nie ma obecnie potwierdzonego endpointu w `main`; albo integruj istniejącą obsługę zgłoszeń, albo dodaj minimalny endpoint z walidacją, anti-spam, zapisem/odbiorcą i testem E2E. Nie udawaj wysyłki.
- Marketing i Command Center mają wspólny design system (tokeny, assety, navbar/logo, footer, przyciski), ale aplikacja ma osobny shell (sidebar, tabelki, run details).

## 7. ARCHITEKTURA SYSTEMU I ZALEŻNOŚCI

Kanoniczne warstwy: **L1 Evidence Chain → L2 PolicyGate → L3 Decision Core → L4 Multi-Agent Orchestrator → L5 Governance**. Runtime docelowo istniejący Python/FastAPI/SQL DB — nie wymieniaj bazy ani runtime na podstawie estetycznych sugestii. Najpierw ustal z repo faktyczny DSN/model migracji; starsze środowiska mogą działać na SQLite, a docelowo PostgreSQL. Bez migracji danych na ślepo.

Przepływ: `OBJECTIVE → POLICY PREFLIGHT → PLAN DAG → NINA → REAL MODEL/TOOL → EVIDENCE (tenant, source_sha, run_id, hashes, provider/model) → IGOR INDEPENDENT CHECK → HUMAN GATE [gdy wymagane] → REPLAY/TAMPER TEST → SIGNED RESULT [tylko gdy jest realny podpis i trust root]`.

Do każdej akcji emituj/odczytuj stan zależności, rolę aktora, błędy, evidence references, czas operacji, retry, wersję polityki, model/provider i dowód egzekucji. IGOR nie może polegać wyłącznie na deklaracji NINA. Human Gate wiązany z konkretnym immutable SHA i digest/tip; po zmianie materiału autoryzacja wygasa. Utrzymaj separację `PROVENANCE VERIFIED`, `INTEGRITY VERIFIED`, `INDEPENDENT ATTESTATION VERIFIED`, `PRODUCTION APPROVED`.

## 8. ZBOOK, CHMURA I DYSTRYBUCJA

- ZBook Windows 11 Pro, 32 GB RAM; **C: Windows**, **D: dane robocze OLA** zgodnie z ostatnią decyzją. NIE formatuj ani nie czyść D automatycznie; przed pracą wykryj system plików, zajętość, wolne miejsce, Docker Desktop/WSL2 i obecne katalogi.
- ZBook UI/agent działa lokalnie i może łączyć się przez autoryzowany tunel (np. Tailscale) po testach. Panel nie uzyskuje zdalnego dostępu magicznie — wymaga rzeczywistego service/agent + tożsamości i logów.
- Uruchomienie developer/local: zestaw skryptów PowerShell `setup`, `up`, `health`, `test`, `down`, używający istniejącego Docker/compose, bez nowych zależności jeśli już są.
- Przygotować stronę mobilną PWA tylko jeśli można ją rzeczywiście instalować (manifest/service worker/HTTPS), bez zmyślonych możliwości background na Androidzie.
- Build/Docker: deterministyczny image, pinned dependencies, SBOM, skan bezpieczeństwa, digest zamiast mutable `latest`, provenance i rollback; produkcja tylko po bramce.

## 9. TESTY OBOWIĄZKOWE I DOWODY

**Front**: syntax/lint/typecheck, testy komponentów, accessibility/WCAG, keyboard-only, responsive 360px–4K, Chrome/Edge/Firefox, focus trap w modalach, formularze/CTA, i18n, reduced motion, bez błędów konsoli, LCP/CLS/INP i pakiet assetów.

**Integracja**: prawdziwy FastAPI+test DB, kontrakty OpenAPI, health success/failure, auth 401/403, przekroczone timeouty, odłączona Ollama, brak danych, błędy IGOR, odmowa policy, approval expiry, zapisywany audit, cross-tenant reject, XSS escaping; skonfigurowany real Ollama test osobno od mock.

**Dowód**: dla dokładnego commit SHA zapisz CI URL/run_id, test counts, environment, image digest, API schema hash, SLI, run_id/evidence IDs, hash artefaktów, niezależny verifier, negative tamper/wrong SHA/replay, screenshoty browser E2E. Nie zaliczaj testów symulacyjnych jako E2E real host.

**Security**: CSP, no secrets, authz, role matrix, threat-model frontend/API, supply chain, static/dependency scan, regression tests dla zgłoszonych P1. Kod unsigned lub niespełniona niezależna zgoda = NO-GO.

**Go/No-Go**: wszystkie obowiązkowe checks PASS na finalnym **niezmienionym** SHA, poprawny podpis uprawnionym kluczem, potwierdzony docelowy host, realne uprawnienia push/deploy, niezależny reviewer `APPROVED` związany z właściwym SHA/report digest/tip, aktualna ochrona main/rulesets, plan rollbacku i smoke test po deployu. Jeśli brakuje choć jednego dowodu: **PARTIAL/BLOCKED, PRODUCTION NO-GO**.

## 10. KOLEJNOŚĆ REALIZACJI (JEDNA LINIA PRACY)

**Faza 0 — Audyt:** zinwentaryzuj `main`, PR #109, PR #113, istniejące UI, pliki, moduły, endpointy, testy i storage; opisz rzeczywiste blokery, ustal zależność rebase/merge bez modyfikacji `main`.

**Faza 1 — Stabilizacja Command Center:** domknij PR #113 na bazie poprawnego PR #109, uzupełnij brakujące realne API flows, zabezpieczenia UI, testy 401/403/503/E2E, potwierdź brak regresji NINA/IGOR/Evidence.

**Faza 2 — Design System:** wdroż identyfikację kuli, gold/blue tokens, komponenty, responsive, accessibility, performant animation; porównaj desktop/mobile referencje.

**Faza 3 — Pełna strona publiczna:** routing, 12 publicznych stron, grafika, formularze, SEO, języki, prawdziwe CTA, strona dokumentacji; nie zniszcz wejścia do Command Center.

**Faza 4 — Moduły aplikacji:** rozbuduj istniejące zakładki o powyższe ścieżki i podfunkcje, tylko z realnym API, „UNAVAILABLE” dla braków; backendowe funkcje implementuj minimalnie z testami.

**Faza 5 — ZBook/staging:** test uruchomienia z D: bez formatowania, health, Docker, Ollama, CI i przeglądarkowe E2E, autoryzowany dostęp mobilny.

**Faza 6 — Release Gate:** niezależna inspekcja bezpieczeństwa, provenance/podpis, approval dokładnego SHA, staging smoke, decyzja GO/NO-GO. Bez automatycznego produkcyjnego merge.

## 11. FORMAT KOŃCOWEGO RAPORTU AGENTA

W jednym raporcie Markdown dostarcz:

1. **EXISTING / PARTIAL / MISSING / BLOCKED** dla każdego modułu z odnośnikiem do pliku i testu.
2. **Dokładną listę zmienionych plików i powodów**; zero nowych duplikatów runtime.
3. **Adresy stron** i screenshoty desktop/mobile, dowód prawdziwego działania każdego CTA, formularza i endpointu.
4. **Kontrakty API** i stany integracji z realnym środowiskiem.
5. **Test matrix** z liczbą i logami PASS/FAIL/SKIP, różnicą mock/live, nazwą środowiska, SHA.
6. **Security & provenance**: brak sekretów, RBAC/tenants, signed/unsigned, source/report binding, replay/tamper, granice dowodu.
7. **Staging URL, lokalny URL oraz instrukcję PowerShell dla ZBook**, tylko gdy naprawdę potwierdzone.
8. **Final GO/NO-GO** wraz z brakującymi wymaganymi autoryzacjami.
9. **Jeden najważniejszy kolejny krok**, jeśli nie ma GO.

## 12. BEZWZGLĘDNE KRYTERIA ODBIORU

- [ ] Istniejący backend, Command Center i funkcje zachowane, bez dublowania; żadnych fałszywych statusów.
- [ ] Nowy wizerunek złoto-niebieskiej kuli zgodny z referencją, widoczny i poprawnie animowany na desktop i telefonie.
- [ ] Wszystkie publiczne podstrony i prywatne moduły mają prawdziwe trasy, nawigację, loading/error/empty, UX i testy.
- [ ] Interakcje z rzeczywistym API są sprawdzone, a nieobsługiwane funkcje jawnie oznaczone; brak fikcyjnej symulacji jako produkcji.
- [ ] API key/reviewer auth, tenant isolation, policy veto, evidence/IGOR/Gate działają bez obejścia bezpieczeństwa.
- [ ] Wszystkie testy/CI/smoke na finalnym SHA; niezależny dowód zamiast deklaracji.
- [ ] Produkt uruchamialny lokalnie na ZBook D:, z rzeczywistą instrukcją/health oraz przygotowany do staging.
- [ ] Publiczne ceny/obietnice/certyfikacje wyłącznie prawdziwe i zatwierdzone.
- [ ] Merge / release tylko po autoryzowanym GO. W przeciwnym razie jednoznaczne NO-GO, bez obchodzenia bramki.

**Jedno zdanie definiujące ukończenie:** Użytkownik otwiera prawdziwą stronę OLA z nową kulą, przechodzi do jednego Command Center, uruchamia rzeczywistą NINA, obserwuje rzeczywiste zadanie i dowody, IGOR sprawdza je niezależnie, a system uczciwie pokazuje, czy i dlaczego wynik jest zweryfikowany oraz czy produkcja może zostać zatwierdzona.