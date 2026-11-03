# OLA di-OS — pionowy przepływ v0.1: ustalenie wersji, tożsamości i danych

Stan: **kandydat na izolowanej gałęzi**, nie wersja zatwierdzona ani produkcja. Data: 2026-11-03.

## 1. Jedno źródło kodu

- Kanoniczne repozytorium: [OLA](https://github.com/krzysztofcieciwa07-ship-it/OLA), gałąź domyślna `main` (podczas audytu SHA `f9dce999ec4447d80b23ce5ac6aa5a840f7e6144`).
- Kandydat z poprawkami API i CI: [PR #148](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/148), SHA `896741988374d20de80b46350a3c541e50d0f42c`, potwierdzone 19/19 CI na tym SHA.
- Kandydat z `/readyz` i trwałym stagingiem: [PR #156](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/156), SHA `69ecdee932c74636f8177e5723bbaf2d18d2b805`, 15/15 workflow na tym SHA.
- Ta zmiana: [PR #159](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/159), **oparta na PR #156**. Jej własny SHA podlega ponownym testom.
- Żaden SHA nie jest formalnie zatwierdzoną wersją produkcyjną bez niezależnego przeglądu, ochrony `main`, podpisu źródła, zweryfikowanego obrazu i dowodu wdrożenia.

## 2. Tożsamości i granice uprawnień

| Rola | Gdzie istnieje | Identyfikator przechowywany w dowodzie | Zasada |
| --- | --- | --- | --- |
| Tenant OLA | SQLite `tenants.id` | `tenant_id` (UUID) | Izolacja wszystkich żądań i rekordów |
| Operator/requester OLA | SQLite `api_keys.id` | `requester_id` (ID klucza, **nie jego wartość**) | Klucz `X-API-Key` do rozpoczęcia zadania |
| Drugi operator/reviewer | Osobne `api_keys.id` w **tym samym** tenant | `approver_id` | Bearer token, wymagana inna tożsamość niż requester |
| NINA/IGOR | Zaufane moduły OLA runtime | `run_id`, `record_type`, `producer=ola_runtime` | Nie są osobnymi kontami operatora i nie mają samodzielnej władzy deploy |
| Vantage | Oddzielne publiczne repozytorium / projekt | Brak zaufanego zewnętrznego `policy_receipt` w tym przebiegu | Status **NOT_CONNECTED**, brak produkcyjnego ALLOW |
| NOVA | Osobna domena tożsamości, obecnie niepotwierdzona | Brak mapowania użytkownik↔operator | Nie wolno zakładać wspólnego SSO/tenantu |
| Supabase analytics | `analytics_workspaces`, polityki RLS | **Brak mapowania** `ola_tenant_id` → `analytics_workspace_id` | Nie łączyć ID ani tabel po podobieństwie nazw |

**Kredencjały:** tylko losowe wartości w bezpiecznym kanale. Nie przechowywać API key w `localStorage`, logach, evidence ani URL. `api_key_fingerprint` używa **scrypt + tajny per-deployment `OLA_API_KEY_PEPPER`**, nie historycznego PBKDF2 opisanego w Drive. Wybór operacyjnego Identity Broker/MFA pozostaje `BLOCKED`.

## 3. Mapa danych bez nieautoryzowanej migracji

| Rekord | Źródło prawdy | Mapowanie na `ola.operation.v1` | Trwałość / ryzyko |
| --- | --- | --- | --- |
| `tenants.id` | `OLA/app/models.py` | `tenant_id` | SQLite z wolumenem, offsite backup niezweryfikowany |
| `api_keys.id` | `OLA/app/models.py` | `actor.subject_id`, `requester_id` lub `approver_id` | Identyfikuje **klucz**, nie imienne konto / MFA |
| NINA `runtime.run_id` | `/nina-run` | `operation_id = correlation_id = run_id` | Jeden UUID dla pierwszego pionowego przepływu |
| `provenance.runtime` | `evidence_records` V2 | task, declared commit, provider/model, result | Wewnętrzne powiązanie, **nie niezależny certyfikat** |
| `decision.candidate` | `evidence_records` V2 | local policy fields + `EXECUTION_ALLOWED` | Sześć pól obejmuje **pięć statusów kanonicznych + diagnostykę** |
| `human.approval` | `evidence_records` V2 | approval, same-tenant reviewer ID, previous tip | `APPROVED_FOR_REVIEW_ONLY`, nie production authorization |
| `record_hash` + `prev_hash` | OLA ledger SQLite | receipt.evidence_id, receipt.chain_tip | SHA-256 integralności wewnętrznej, bez zewnętrznego podpisu |
| `analytics_workspaces.id` | Supabase Postgres | **UNMAPPED** | Nie kopiować ledgeru ani nie wymyślać relacji między bazami |
| NOVA user ID / message ID | Niepotwierdzony runtime NOVA | **UNMAPPED** | Nie kopiować zaszyfrowanych treści do Evidence |

Wersja 0.1 **nie tworzy tabel**, nie migruje danych, nie wywołuje Stripe, Supabase, Vantage ani Codex.

## 4. Jeden rzeczywisty przepływ lokalny

1. Operator poświadcza się przez `X-API-Key` → serwer mapuje `api_keys.id` i `tenant_id`.
2. `POST /nina-run` wykonuje **rzeczywisty OLA runtime**, z jedną z istniejących dozwolonych możliwości (`safe_expression`).
3. Lokalny NINA allowlist podejmuje decyzję. **Osobny Vantage nie jest połączony** i nie zwraca dowodu ALLOW.
4. OLA zapisuje serwerowe rekordy V2 `provenance.runtime` oraz `decision.candidate`; IGOR bada kompletny łańcuch i replay.
5. Panel/operator pobiera stan ponownie przez tenant-scoped API z weryfikacją ledgera; wyświetla stan z serwera, nie wartość `verified` z frontendowego mocka.
6. Drugi operator, z innym `api_keys.id` w tym samym tenant, może wyrazić zgodę lokalną `POST /nina-run/{run_id}/approve`, z wiązaniem do konkretnego tip hash. Powtórzenie ma być odrzucone.
7. Wynik: **local candidate reviewed**. Nadal **NO-GO** dla zewnętrznego zadania, wdrożenia, płatności czy danych produkcyjnych.

## 5. Warunki brakujące do połączenia z osobnym Vantage

- Zatwierdzony protokół `policy_decision` z `run_id`, `tenant_id`, `action`, `risk`, wygaśnięciem i podpisaną referencją dowodu.
- Zaufane identyfikatory usług i wymagane uwierzytelnianie między OLA a Vantage; ochrona przed replay i cross-tenant.
- Weryfikator podpisu/atestacji w OLA z testami negatywnymi, bez `human_approved: true` z przeglądarki.
- Wdrożenie osobnego Vantage na hosta, monitorowanie i test fail-closed przy niedostępności.
- Dopiero wtedy można zmienić `VANTAGE_NOT_CONNECTED` na rzeczywistą decyzję polityki. **Nie wpisywać fikcyjnego PASS.**

## 6. Kryteria odbioru pionowego przepływu

- [ ] Red/green dla rzeczywistego zatwierdzenia drugim kluczem API
- [ ] Samozatwierdzenie, inne tenant i replay → odmowa
- [ ] Weryfikacja pełnej sekwencji dowodów i ponowny odczyt po zapisie
- [ ] Browser UI pracuje wyłącznie z lokalnymi endpointami i nie przechowuje kluczy
- [ ] Przy wyłączonym Vantage wszystkie odpowiedzi mówią jawnie `NOT_CONNECTED`
- [ ] Końcowy `pytest` i pełne CI na dokładnym SHA bez nieudanych kontroli
- [ ] Niezależny przegląd i decyzja o merge; osobny podpisany GO na produkcję

**Status systemu:** `BLOCKED`, nawet jeśli lokalny pionowy test zakończy się `PASS`.
