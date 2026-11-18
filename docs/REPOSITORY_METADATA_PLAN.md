# GitHub — plan metadanych dla wszystkich publicznych repozytoriów
Snapshot: 2026-11-12 · **PROPOZYCJE, NIE ZMIANY WYKONANE**.

Ten dokument nie dowodzi działania usług. Opisy i topics wymagają ręcznej zmiany w **Settings → General / About**. Połączenie GitHub użyte do tego PR nie udostępnia funkcji edycji opisu, tematów ani homepage repozytorium.

| Repo | Proponowany opis (maks. 160 znaków) | Topics (propozycja) | Homepage |
|---|---|---|---|
| [OLA](https://github.com/krzysztofcieciwa07-ship-it/OLA) | OLA di-OS core: FastAPI execution gates, evidence records, agent workflows and reproducible verification (development). | `ola-dios`, `fastapi`, `evidence`, `ai-agents`, `security` | Zostawić puste, dopóki publiczne API/portal nie przejdzie testów. |
| [vantage](https://github.com/krzysztofcieciwa07-ship-it/vantage) | Vantage: experimental deny-by-default execution and provenance verification gate for OLA di-OS. | `ola-dios`, `security-gate`, `provenance`, `prototype` | Brak zweryfikowanego serwisu, pozostawić puste. |
| [ola-evidence-gateway](https://github.com/krzysztofcieciwa07-ship-it/ola-evidence-gateway) | OLA Evidence Gateway specification and evidence model (documentation only, not a running service). | `ola-dios`, `specification`, `evidence`, `documentation` | **Usunąć** niepowiązany adres pogodowy; nie zastępować niezweryfikowaną domeną. |
| [quantum-ai-chatbot](https://github.com/krzysztofcieciwa07-ship-it/quantum-ai-chatbot) | Experimental Supabase-backed AI chatbot fork; separate from OLA's NOVA communicator. | `chatbot`, `supabase`, `experimental`, `fork` | Pozostawić tylko po przetestowaniu aktualnego adresu. |
| [ai](https://github.com/krzysztofcieciwa07-ship-it/ai) | Fork of AI SDK for TypeScript — upstream research/reference; not an integrated OLA service. | `ai-sdk`, `typescript`, `fork`, `reference` | Zachować stronę oficjalnego projektu z oznaczeniem pochodzenia. |
| [cli](https://github.com/krzysztofcieciwa07-ship-it/cli) | Fork of GitHub CLI — external development tool, not OpenAI Codex CLI. | `github-cli`, `golang`, `fork`, `reference` | Zachować URL oficjalnego GitHub CLI. |
| [MetaGPT](https://github.com/krzysztofcieciwa07-ship-it/MetaGPT) | Fork of MetaGPT multi-agent framework — research/reference, not verified as an OLA runtime. | `metagpt`, `multi-agent`, `fork`, `reference` | Zachować tylko jeśli strona nadal odpowiada aktualnemu upstream. |
| [swarmclaw](https://github.com/krzysztofcieciwa07-ship-it/swarmclaw) | Fork of SwarmClaw agent runtime — reference implementation, not verified as an OLA module. | `agents`, `runtime`, `fork`, `reference` | Zachować oficjalny adres upstream. |
| [uygulamali-kriptografi](https://github.com/krzysztofcieciwa07-ship-it/uygulamali-kriptografi) | Fork of an applied cryptography learning project (Rust and mdBook). | `cryptography`, `rust`, `mdbook`, `education`, `fork` | Puste, chyba że strona podręcznika zostanie potwierdzona. |

## Przed zatwierdzeniem zmian

- Zweryfikować każdy proponowany opis z rzeczywistym zakresem kodu oraz zgodnością z licencją/upstream.
- Nie usuwać, nie archiwizować, nie zmieniać domyślnej gałęzi i nie synchronizować forków automatycznie.
- Utrzymać 2 samodzielne repozytoria OLA/vantage jako priorytet, a forki jako oddzielne źródła zależności.
- Oddzielnie udokumentować wynik bezpieczeństwa projektu chatbota: publiczny `.env` nie powinien przechowywać sekretów serwerowych; wskazany plik zawierał nazwane pola klienta Supabase, ale to nie zastępuje audytu Git historii.
- Nie promować "10/10" na podstawie samego uporządkowania GitHub.

## Repozytoria przypięte na profilu — sugestia

1. OLA — rdzeń.
2. vantage — kontrola wykonania.
3. ola-evidence-gateway — tylko jeśli opis jasno mówi "documentation-only".
4. quantum-ai-chatbot — tylko po kontroli bezpieczeństwa i ustaleniu odrębnej roli.

Pozostałe forki są dostępne w zakładce Repositories; nie trzeba ich prezentować jako własnych modułów OLA.

Powiązane: [katalog repozytoriów](REPOSITORY_CATALOG.md) · [rejestr JSON](REPOSITORY_CATALOG.json).


## Stan wykonania metadanych — 2026-11-12

Opisy repozytoriów `OLA` i `vantage` nadal są puste w odczycie GitHub. Dostępna integracja GitHub pozwala odczytywać repozytoria i zmieniać pliki/PR, ale nie udostępnia operacji edycji `description`, `topics` ani `homepage`. Proponowane opisy i topics pozostają więc **do ręcznego ustawienia** w `Settings → General → About`; nie oznaczam ich jako wykonanych.


## Revalidation — 2026-11-18

The descriptions and topics above remain **proposals only**; no GitHub About fields, topics, or homepage values were changed.

Current exact repository baselines:
- OLA main: `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`; 91 open PRs. PR #262 has 22/22 observed workflows successful on its exact PR head, but main-only production attestation and independent review are still missing.
- Vantage main: `991445100a3ddfae85bef0d0f9f7680373658d5f`; 7 open PRs. PR #38 has 2/2 exact-head workflows successful; it remains draft and requires independent review.
- Quantumy main: `8ae603dcefd7eebdd54acc36954225bf1454d928`; 1 open PR. Replacement PR #5 passes Security Gate on exact head `43826ca3098b7ebd0120377d76491f7d1ca0ccf4`; Supabase migration, pg_cron execution and live OAuth remain unverified.
- Evidence Gateway main: `0f13cb6aa20bb933524a79f7458ad9aec82178cf`; 1 open documentation-only PR. The service is not implemented.

The current public About descriptions are still to be set manually. Keep all external-reference forks labelled as forks and preserve their upstream attribution.
