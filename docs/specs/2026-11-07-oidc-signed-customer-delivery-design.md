# OLA — Human Identity, atestacja IGOR i podpisany pakiet klienta

Status: kierunek zaakceptowany; poprawiony po audycie 2026-11-07.
Baza kodu: PR #189, head 8e56b33df9a3e2806f3709fca90b07e4e595d28f.
Zakres: uwierzytelnianie operatorów, SoD, administracja rolami, podpisane pakiety per zamówienie i bezpieczne dostarczenie.
Poza zakresem: merge PR #189, konfiguracja produkcyjnego IdP/KMS/TSA/storage, Stripe LIVE i produkcyjny deploy.

## 1. Decyzja

OLA otrzyma neutralną warstwę Human Identity. Pierwszym adapterem operatorów będzie OIDC Authorization Code + PKCE S256. OIDC potwierdza konto u dostawcy, ale nie dowodzi, że dwa konta należą do dwóch różnych osób. SoD porównuje więc zaufany, pseudonimowy person_key pochodzący z HR/SCIM lub zatwierdzonego claimu IdP, a nie sam issuer+subject ani e-mail. Brak wiarygodnego person_key blokuje akcje krytyczne.

Klucze API pozostają dla maszyn. Nie są zamiennikiem człowieka. Polityka tenanta przechodzi jednokierunkowo LEGACY_API → OIDC_REQUIRED. Po aktywacji nie ma powrotu do API key. Próba downgrade'u, brak MFA, membership lub person_key oznaczają BLOCKED, nie fallback. Polityka jest przechowywana w bazie i zapisywana w Evidence; nie można jej wyłączyć flagą środowiskową.

Pakiet klienta ma dwa podpisy: niezależną atestację IGOR i podpis wydawcy OLA. Klucze i uprawnienia do podpisywania muszą mieć osobne granice zaufania. API OLA nie może użyć klucza IGOR, a IGOR nie może użyć klucza OLA. Bez osobnego podpisu IGOR pakiet nie może mieć statusu VERIFIED ani być wydany produkcyjnie.

OIDC służy operatorom, nie musi być wymagane dla każdego klienta pobierającego raport. Odbiorca używa oddzielnego adaptera uwierzytelniania: OIDC klienta korporacyjnego lub WebAuthn/passkey dla klienta zewnętrznego. API key nie jest metodą pobrania.

## 2. Stan źródłowy i Replit

PR #189 jest open/Draft, head 8e56b33df9a3e2806f3709fca90b07e4e595d28f, baza main, 59 plików i 122 commity. Nowy etap jest osobną gałęzią potomną PR #189; nie zmienia jego head i nie trafia bezpośrednio do main.

Na tym SHA main.py traktuje Bearer jako API key, a pola requester/approver/reviewer wskazują api_keys.id. report_review.py już sprawdza tenant/order, NINA/IGOR/provenance/replay, digest raportu i pełny tenant Evidence chain; tę kontrolę zachowujemy. Istnieje GET /checkout-orders/{order_id}/report, który zwraca JSON pierwotnemu requesterowi z API key i zapisuje revenue.report_delivered. To istniejący JSON retrieval, a nie podpisany pakiet z niezależnym recipientem.

Raport Replit opisuje registry i samodzielny HTML recenzenta. Wskazuje inne lokalne źródło: branch integration/pr155-010b507-20261103, HEAD a2a32da54c77c952a5b097ce0740c1b0b946b1eb. Nie jest to kompletne repo ani dowód integracji. HTML używa API key i endpointów /nina-workflow/{runId}/report, /evidence?run_id=… oraz /nina-workflow/{runId}/approve. Statyczny opis nie dowodzi, że endpointy istnieją w obecnym API. Panel pozostaje referencją do późniejszego testu, nie źródłem prawdy. Registry 127 pozycji zawiera deklarowane statusy; dwa ZIP-y źródłowe wymienione w manifeście nie były w dostarczonym archiwum.

## 3. Tożsamość i MFA

OIDC flow: Authorization Code, PKCE S256, jednorazowe state i nonce, exact redirect URI, walidacja podpisu/JWKS, iss, aud, azp jeśli występuje, sub, exp, iat, nonce i ochrona issuer mix-up. Issuer/discovery/JWKS/client ID/redirect URI pochodzą wyłącznie z zatwierdzonej konfiguracji tenanta, nigdy z requestu.

Sesja aplikacji jest serwerowa: losowy opaque ID w cookie, hash ID w bazie. Cookie Secure, HttpOnly, SameSite=Lax. State-changing requests mają CSRF protection. Tokeny, code_verifier i pełne claimy nie trafiają do logów ani Evidence. auth_time i step-up wymagane przy zatwierdzaniu wykonania, raportu i zmianie uprawnień, nie przy zwykłym logowaniu. MFA uznawane tylko przez jawną mapę zatwierdzonych wartości acr/amr; brak mapy to BLOCK.

issuer+subject identyfikuje konto, nie człowieka. person_key musi pochodzić z HR/SCIM lub zaufanego claimu. Dwa konta z tym samym person_key to ta sama osoba w SoD. Brak lub niejednoznaczność daje 403 SOD_IDENTITY_UNVERIFIED. OLA nie deklaruje KYC. Jeden aktywny issuer dla operatorów na tenant; zmiana wymaga kontrolowanej migracji.

Rekomendowany adapter: Authlib 1.9.5, exact pin i monitoring advisories. PyPI podaje wydanie z 2026-11-05, a changelog wskazuje poprawki bezpieczeństwa JOSE w serii 1.9.4–1.9.5. Aplikacja nadal musi jawnie ograniczyć algorytmy i walidować iss/aud.

## 4. Membership, role i prywatność

Role: requester, execution_approver, report_reviewer, recipient, tenant_identity_admin. Approver ma inny person_key niż requester; reviewer różni się od obu. Recipient otrzymuje grant do pojedynczego order, bez automatycznych pozostałych ról.

Tenant admin nie może nadać sobie krytycznej roli, zatwierdzić własnej zmiany ani samodzielnie wykonać całej ścieżki podniesienia uprawnień. Zmiana ról krytycznych i grantów wymaga dual-control przez dwóch różnych person_key. Bootstrap pierwszego administratora wykonuje zaufany operator platformy poza publicznym API. Każda zmiana issuer, membership, roli, HR mapping lub recipient grant zapisuje Evidence z aktorem, zatwierdzającym, zakresem i uzasadnieniem.

Evidence przechowuje wyłącznie losowy pseudonimowy principal_ref/person_ref, tenant/order, rolę, decyzję, uzasadnienie, auth_time, MFA, UTC timestamp i hash. Mapowanie issuer+subject+person_key jest w mutowalnej tabeli identity, poza append-only Evidence. Usunięcie mapowania/crypto-shredding nie usuwa historii decyzji, ale pozostawia nieidentyfikowalny ślad. Retencja wymaga osobnej polityki klienta.

## 5. Pakiet dowodowy

Struktura logiczna: manifest.json, manifest.sig, igor/attestation.json, igor/attestation.sig, report/report.json, evidence/order-evidence.ndjson, provenance/source-runtime.json, verification/README.txt.

manifest.json jest kanonicznym JSON. manifest.sig to Base64URL podpisu Ed25519 nad dokładnymi bajtami manifestu; po dekodowaniu ma 64 bajty. IGOR podpisuje osobny kanoniczny attestation payload swoim kluczem. Manifest wiąże digest attestation i igor_key_id. Pliki kontrolne (manifest i sygnatury/attestation) nie są włączane do własnej listy hashy. ZIP ma stałą kolejność, mtime, permissions i deterministyczną kompresję; symlinki, duplikaty ścieżek i path traversal są odrzucane.

Dwa PEM-y w jednym procesie nie dają niezależności. Klucze OLA/IGOR muszą być odseparowane przez osobne signer services i security principals. Brak niezależnej atestacji IGOR blokuje wydanie. cryptography 50.0.2 jest rekomendowana do testowego adaptera Ed25519; produkcja wymaga zatwierdzonego KMS/HSM/provider, którego obsługa Ed25519 została sprawdzona, nie założona.

Manifest zawiera osobno approved_at/approved_tip_hash i signed_at/signing_tip_hash, report_sha256, source SHA, image digest, key IDs, statusy NINA/IGOR/provenance/replay/privacy i jawny profil bramek. NDJSON jest filtrowanym wyciągiem order-scoped. Oryginalny record_hash pozostaje referencją, ale klient nie może przeliczyć pełnego tenant chain po filtrowaniu/pseudonimizacji. Weryfikator sprawdza podpisy, skróty plików, order binding i status key IDs; nie twierdzi, że odtworzył pełny tenant chain.

Profile:
- CUSTOMER_BUNDLE_SANDBOX_V1: report digest, chain at approval/signing, NINA, niezależny podpis IGOR, podpis OLA, privacy/allowlist, order binding. Brak opcjonalnego provenance daje PARTIAL, nigdy VERIFIED.
- CUSTOMER_BUNDLE_PRODUCTION_V1: dodatkowo source/image provenance, HR person_key, MFA, niezależne custody signerów, TSA/transparency proof, szyfrowany trwały storage i aktywna polityka OIDC. Każde UNKNOWN/PARTIAL/NOT_AVAILABLE oznacza BLOCKED.

signed_at jest deklaracją wystawcy. Produkcja wymaga zewnętrznego RFC 3161 timestamp token lub równoważnego niezależnego transparency log. Weryfikator rozróżnia VALID_NOW, VALID_AT_TRUSTED_TIMESTAMP, REVOKED, UNKNOWN_KEY i UNTRUSTED_TIMESTAMP; nie ufa samemu polu czasu w JSON.

## 6. Pakiet, grant i próby pobrania

To osobne cykle:
- Bundle: PENDING → SIGNED → EXPIRED | REVOKED | INVALID.
- Grant: ACTIVE | EXPIRED | REVOKED; zakres tenant+order+recipient. Grant może istnieć przed podpisaniem bundle.
- Delivery attempt: oddzielny rekord per bundle+recipient+attempt_no, status AUTHORIZED | BLOCKED | STARTED | COMPLETED | FAILED. Acknowledgement jest osobnym zdarzeniem.

RECIPIENT_BLOCKED jest wynikiem próby, nie stanem pakietu. BUNDLE_EXPIRED/REVOKED/INVALID dotyczą pakietu. Każde ponowne pobranie tworzy nową próbę. Revoke grantu i start streamu są serializowane. COMPLETED powstaje dopiero po zakończeniu transferu; ACK wymaga jawnej czynności odbiorcy. Nie twierdzimy, że klient przeczytał raport.

## 7. Komponenty i fail-closed

Odpowiedzialności: HumanIdentityProvider, HumanSessionStore, TenantMembershipPolicy, HumanGatePolicy, BundleBuilder, IgorAttestor, OlaBundleSigner, BundleVerifier, RecipientAuthProvider (OIDC klienta albo WebAuthn), RecipientGrantService, DeliveryAttemptService, timestamp/storage adapters.

Blokada przy unknown issuer, błędnym state/nonce/PKCE/JWKS/aud/algorithm, braku membership/person_key/MFA/fresh auth, konflikcie SoD, samonadaniu admina, niezatwierdzonej zmianie roli, braku grantu, zmianie digest/chain, braku podpisu IGOR/OLA, błędzie KMS/TSA/storage, revoked/expired pakiecie i nieznanej konfiguracji. Brak podpisu IGOR nigdy nie może być nazwany IGOR_VERIFIED.

## 8. Migracje i kryteria GO

Migracje PostgreSQL addytywne przez migration role; API startup tylko weryfikuje schemat. SQLite otrzymuje równoważne migracje. Nowe tabele: tenant_identity_providers, human_principals, tenant_memberships, tenant_identity_policies, human_sessions, role_change_requests, recipient_grants, customer_delivery_bundles, delivery_attempts i trusted_signing_keys. Historyczne API-key actors zostają LEGACY_UNVERIFIED; bez backfillu.

CI GO wymaga monotonicznej polityki i negatywnego downgrade testu; OIDC state/nonce/PKCE/issuer/audience/JWKS tests; SoD na person_key; dual-control admin; osobnych podpisów IGOR/OLA; deterministycznego ZIP i offline verifiera; rozdzielenia bundle/grant/attempt; testów SQLite/PostgreSQL.

Production GO dodatkowo wymaga rzeczywistego IdP + HR/SCIM mapping + MFA, dwóch signer services z niezależnym custody, Ed25519-capable KMS/HSM, TSA/transparency, encrypted storage/retention, testu klienta offline, source/image provenance na zatwierdzonym main, restore, TLS/DNS/SLO i prawdziwego pobrania przez klienta. CI/staging nie jest tym dowodem.

Kolejność: (1) identity policy i migracje, (2) OIDC server-side sessions + HR/SCIM principal, (3) SoD + dual-control i podpięcie Human Gate, (4) dual signer + bundle + offline verifier + TSA, (5) recipient adapters, grants/attempts, storage i dopiero po weryfikacji pochodzenia panelu Replit.

Otwarte decyzje zewnętrzne: IdP/MFA mapping, HR/SCIM person_key, bootstrap admina, KMS/HSM z Ed25519, dwa niezależne principals signerów, TSA/transparency, storage/retention, recipient adapter i public-key pinning. Rekomendacja pakietu v1: JSON+NDJSON, bez PDF.
