# OLA di-OS: wspólny operation_id i rozdzielone granice usług (v1)

Status na 2026-11-03: **Vantage↔OLA = pilot verified in real two-container CI**; Codex Bridge i NOVA = **NOT_CONNECTED**. Nie uruchamiano infrastruktury produkcyjnej.

## Kanoniczna tożsamość operacji

`operation_id` to serwerowo wygenerowany UUID w OLA, będący również `run_id` dla NINA, IGOR, lokalnego replay i Evidence Vault. Jest **niezmiennym identyfikatorem korelacji**, nie kluczem autoryzacyjnym. Samo podanie poprawnego UUID **nie przyznaje dostępu do tenantu ani prawa do działania**.

| Komponent | Przenoszone ID | Uprawnienia | Przechowywanie |
| --- | --- | --- | --- |
| OLA Core | `tenant_id`, `operation_id`, `requester_key_id` | Uwierzytelniony requester per tenant | SQLite Evidence V2 i jawna wersja schematu |
| Vantage AFE | Identyczne `tenant_id` + `operation_id`, digest zadania i action | HMAC OLA→Vantage, podpis Ed25519 Vantage→OLA, TTL 30 s, nonce odporny na replay | Osobna baza nonce Vantage; podpisany receipt w Evidence V2 OLA |
| IGOR | Identyczne `tenant_id`, `run_id`, `source_commit`, tip hash | Lokalny read-only verifier; podpis Vantage weryfikowany ponownie przy readback | Dowody, wynik i kontrola integralności |
| Codex Bridge | **Wymagany** identyczny `operation_id` + lokalny `codex_job_id` | Osobna tożsamość serwisowa, allowlista repo, limit operacji, podpisana zgoda **na konkretną akcję** | Osobny rejestr jobs/commands, tylko hash potwierdzenia do OLA |
| NOVA | **Wymagany** identyczny `operation_id` + lokalny `conversation_id`/`message_id` | Osobne użytkownicy, sesje i E2EE; tenant mapping jawnie potwierdzony | Osobna baza komunikatora, OLA dostaje wyłącznie metadane i hash zdarzenia |

## Podpisany Vantage receipt: rzeczywisty kontrakt

- Wejście: `POST /operator/guarded-run` w OLA (X-API-Key); NINA nie rozpocznie działania przed poprawną odpowiedzią z osobnego Vantage.
- OLA żąda dokładnie `action=safe_expression`, podpisuje HMAC żądanie z nonce i czasem; Vantage uruchamia **prawdziwy AFE/VantageGate**.
- Vantage odpowiada `receipt + Ed25519 signature`; OLA weryfikuje klucz publiczny, tożsamość nadawcy, kontekst, `operation_id`, tenant, digest zadania, nonce, SHA źródła oraz TTL.
- Brak komunikacji, zły podpis, wygaśnięcie, obcy tenant, nieznana akcja, `BLOCK` albo `HUMAN_APPROVAL` → **BLOCK, zero agent execution**.
- OLA przechowuje oryginalny, podpisany receipt jako `verification.vantage_policy` w Evidence V2. Odczyt historyczny ponownie sprawdza podpis, ale **nie traktuje wygasłego receipt jako nowego pozwolenia na wykonanie**.
- Mode `OLA_VANTAGE_ENFORCED=1` blokuje bezpośrednie `/nina-run`. Chroniony endpoint `/operator/guarded-run` sam fail-closed nawet bez tej flagi.
- Samo ALLOW z heurystycznego AFE zezwala **wyłącznie** na ograniczony lokalny test `safe_expression`. `production_authorized=false` zawsze.

## Kontrakt Codex Bridge, wymagany do następnej implementacji

Wywołanie w przyszłości `POST /v1/jobs`:

```json
{
  "schema": "ola.codex.job.request.v1",
  "operation_id": "uuid z OLA",
  "tenant_id": "uuid z OLA",
  "action": "read_repo_or_propose_patch",
  "repository": "allowlisted_owner/allowlisted_repo",
  "requested_by": "id operatora API key w OLA",
  "task_digest_sha256": "64 znaki hex",
  "vantage_receipt_digest_sha256": "64 znaki hex",
  "expires_at": 0,
  "nonce": "unikalne 128-bit"
}
```

**Ten JSON to propozycja interfejsu, NIE działający endpoint.** Bridge musi uwierzytelnić OLA osobnym kluczem usługi, odtworzyć i zweryfikować zgodę na **konkretny action/repo**, ograniczyć sandbox/FS/network, rejestrować `codex_job_id` i `operation_id`, a wynik podpisać, nie przyjmować go z frontendowego `status=PASS`. Żadnego shell/deploy/push na podstawie `safe_expression ALLOW`.

## Kontrakt NOVA, wymagany do następnej implementacji

Zdarzenie metadanych `nova.operation.update.v1`:

```json
{
  "schema": "nova.operation.update.v1",
  "operation_id": "uuid z OLA",
  "tenant_id": "uuid z OLA",
  "event_id": "unikalny uuid NOVA",
  "status": "BLOCKED|REVIEW_REQUIRED|APPROVED_FOR_REVIEW_ONLY",
  "evidence_tip_sha256": "64 znaki hex",
  "occurred_at": "RFC3339 UTC",
  "content": null
}
```

**To propozycja, NIE działający WebSocket.** NOVA ma zachować własne konta, podpisane tokeny sesji, E2EE i bazę. Nie wolno kopiować do OLA treści rozmów, kluczy E2EE ani tokenów sesji. NOVA musi weryfikować tenant membership i operację przed pokazaniem powiadomienia, odrzucać replay zdarzeń i zwracać osobne potwierdzenie odbioru z `operation_id`.

## Source inventory i bramki

Dostępne GitHub: `OLA`, `vantage`, `ola-evidence-gateway` (README bez implementacji), `quantum-ai-chatbot` (nie stanowi potwierdzonego kodu NOVA); osobne aktualne źródło serwera **NOVA** i kanonicznego **OLA Codex Bridge** nie zostało wskazane. Nie integruj losowego czatu lub narzędzia Codex pod ich nazwami.

Do produkcyjnego GO wymagane: zaakceptowane PR, ochrona `main`, niezależny signer image/provenance, trwała baza Vantage nonce i backup, TLS/mTLS, odrębna identity federation, realne scenariusze offline/restart oraz E2E NOVA/Codex z negatywnymi testami.

**Jedyny zatwierdzony zakres pilotowy:** dwa osobne kontenery OLA+Vantage / Ed25519 / lokalna arytmetyka / Evidence V2. Status całego di-OS: `BLOCKED`.
