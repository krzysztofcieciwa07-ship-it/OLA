# Publiczne repozytoria — katalog OLA di-OS
Aktualizacja: **2026-11-02** · właściciel: `krzysztofcieciwa07-ship-it` · zakres: **wyłącznie 9 publicznych repozytoriów**.

> Ten katalog porządkuje odpowiedzialność i stan dowodów. Nie stwierdza, że jakikolwiek backend jest wdrożony produkcyjnie. STATUS ≠ CI ≠ RUNTIME ≠ VERIFIED. Stan zmienia się tylko po nowym sprawdzeniu. Osobne prywatne repozytoria nie są przedmiotem tego dokumentu.

## Mapa i granice odpowiedzialności

| Repozytorium | Rodzaj / pochodzenie | Rola w portfolio | Ustalony stan |
| --- | --- | --- | --- |
| [OLA](https://github.com/krzysztofcieciwa07-ship-it/OLA) | własne | **CORE** — API, agent runtime, Evidence, workflow | kod istnieje; zintegrowana produkcja NIEZWERYFIKOWANA |
| [vantage](https://github.com/krzysztofcieciwa07-ship-it/vantage) | własne | **SECURITY_GATE** — prototyp kontroli ryzyka | kod i testy; niezależne CI provenance: ostatni sprawdzony przebieg FAIL |
| [ola-evidence-gateway](https://github.com/krzysztofcieciwa07-ship-it/ola-evidence-gateway) | fork | **SPEC** — koncepcja warstwy dowodowej | repo zawiera README i ustawienia, bez uruchamialnego backendu |
| [quantum-ai-chatbot](https://github.com/krzysztofcieciwa07-ship-it/quantum-ai-chatbot) | fork | **SEPARATE_EXPERIMENT** — chatbot mobilny | ma kod aplikacji; nie utożsamiać z komunikatorem NOVA |
| [ai](https://github.com/krzysztofcieciwa07-ship-it/ai) | fork | **EXTERNAL_REFERENCE** — AI SDK | nieudowodniona integracja z OLA |
| [cli](https://github.com/krzysztofcieciwa07-ship-it/cli) | fork | **EXTERNAL_REFERENCE** — GitHub CLI | NIE jest to Codex CLI ani własne CLI OLA |
| [MetaGPT](https://github.com/krzysztofcieciwa07-ship-it/MetaGPT) | fork | **EXTERNAL_REFERENCE** — framework agentowy | nieudowodniona integracja z OLA |
| [swarmclaw](https://github.com/krzysztofcieciwa07-ship-it/swarmclaw) | fork | **EXTERNAL_REFERENCE** — runtime agentów | nieudowodniona integracja z OLA |
| [uygulamali-kriptografi](https://github.com/krzysztofcieciwa07-ship-it/uygulamali-kriptografi) | fork | **EDUCATIONAL_REFERENCE** — ćwiczenia z kryptografii | materiał edukacyjny, nie komponent produkcyjny OLA |

**Bilans: 2 własne repozytoria + 7 forków.** Fork pozostaje pochodną cudzej pracy; nie oznacza własnej, zweryfikowanej implementacji. Sam projekt NOVA i najnowsze lokalne poprawki Codex nie są automatycznie obecne w tych repozytoriach.

## Co wymaga decyzji

1. **P0 — Vantage:** zbadać [nieudany niezależny przebieg provenance z 2026-10-29](https://github.com/krzysztofcieciwa07-ship-it/vantage/actions/runs/40969041489). Nowszy od historycznej deklaracji README. Nie promować podpisów/pochodzenia jako aktualnie zaliczonych.
2. **P0 — OLA:** powiązać kod, testy, dowody wykonania i wdrożenie z tym samym SHA. [GitHub Actions](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions) potwierdzają określone workflow, nie automatycznie całego systemu.
3. **P1 — Evidence Gateway:** repo zawiera obecnie dokumentację; nie przedstawiać go jako osobnego działającego serwera. Pole homepage wskazuje na niepowiązaną pogodową witrynę i wymaga ręcznej korekty w ustawieniach repozytorium.
4. **P1 — Quantum Chatbot:** publicznie śledzony `.env` zawiera nazwane parametry Supabase, w tym klucz anonimowy klienta. To nie jest automatycznie tajny klucz serwerowy; mimo to trzeba przejrzeć politykę konfiguracji, historię, OAuth i reguły RLS. Nie publikować wartości w raportach.
5. **P1 — Metadane:** `OLA`, `vantage`, `ola-evidence-gateway` i `uygulamali-kriptografi` mają puste opisy; wszystkie 9 repozytoriów mają puste topics. Zmienić dopiero po zatwierdzeniu nazw i ról, przez ustawienia GitHub (aktualny konektor nie obsługuje edycji tych pól).
6. **P2 — Forki:** nie archiwizować, kasować, synchronizować upstream ani przenosić licencji automatycznie. Utrzymywać rozdział: referencja / eksperyment / rdzeń.

## Zasada 10/10

- **Source present**: pliki są w GitHub.
- **Tests passed**: wskazane testy dla wskazanego SHA zakończyły się bez błędów.
- **Runtime verified**: określona instancja uruchomiona i sprawdzona w określonym czasie.
- **System accepted**: wszystkie krytyczne bramki E2E i bezpieczeństwa zaliczone, dowody niezależnie sprawdzone.

`UNKNOWN` / `NOT_VERIFIED` / nieaktualne raporty **nie przechodzą** jako gotowość produkcyjna.

## Reguły porządkowe

- `OLA` jest kanonicznym punktem odniesienia portfolio, ale nie nadpisuje innych repozytoriów.
- Zmiany dokumentacyjne idą przez osobne gałęzie i pull requesty; bez force-push i bez automatycznego merge.
- Kod forków pozostaje nietknięty, dopóki nie ma udokumentowanej decyzji o integracji i zgodności z licencją.
- Żadne tokeny, hasła, klucze prywatne ani lokalne `.env` nie trafiają do katalogu.
- Przed uznaniem statusu za zielony wymagać artefaktu, SHA, testu negatywnego i zakresu weryfikacji.

Maszynowy rejestr: [REPOSITORY_CATALOG.json](REPOSITORY_CATALOG.json).
