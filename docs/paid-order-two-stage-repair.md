# OLA — naprawa płatności i raportu klienta (dwa etapy)

Data: 2026-11-07
Zakres bazowy: PR #189, tree SHA `0200208e7564b075b93773586809ad69ef374920`.

## Etap 1 — prywatność danych zadania przy płatności

- Nowa sesja Stripe otrzymuje wyłącznie identyfikatory produktu/oferty, `tenant_id`, `order_id` i `request_hash` (SHA-256 zakresu zadania). Nie wysyła `metadata[task]`.
- Pełna treść zadania jest przechowywana w `checkout_orders.task` i pobierana przez OLA po zweryfikowaniu zamówienia, tenant, sesji i skrótu.
- Nowy `StripeEvent` nie zapisuje `task`; `stripe.payment_confirmed` i `revenue.checkout_created` zapisują skrót, a nie treść.
- Stare rekordy SQLite/PostgreSQL przenoszą `stripe_events.task` do odpowiadającego zamówienia (po `payment_event_id`), następnie czyszczą kopię w tabeli `stripe_events.task`.
- Obsługa starych, już utworzonych sesji Stripe zachowuje tryb zgodności: jeżeli sesja zawiera historyczne `metadata.task`, OLA może odczytać tę wartość i zapisać ją wyłącznie do prywatnego `checkout_orders.task`, ale tylko po zgodności SHA-256 z zamówieniem. Nie zapisuje jej ponownie w StripeEvent ani nowym dowodzie płatności.

## Etap 2 — niezależna kontrola i dostarczenie raportu

- Odpowiedź ponownego `POST /checkout` nie zwraca `execution_result`, raportu ani treści zadania. Zwraca wyłącznie status, identyfikator zamówienia, skrót raportu i stan bramki.
- `POST /checkout-orders/{order_id}/review-report` wymaga klucza API przypisanego do tej samej dzierżawy z rolą `report_reviewer`, inną tożsamością niż zamawiający i zatwierdzający wykonanie.
- Recenzent podaje `report_sha256`, aktualny `tip_hash` i uzasadnienie. OLA niezależnie przelicza skrót raportu, sprawdza statusy NINA/IGOR/provenance/replay, integralność łańcucha i dokładnie jeden dowód `revenue.execution_completed`.
- Akceptacja zapisywana jest transakcyjnie w `checkout_report_reviews` i jako zaufany dowód `human.customer_report_approval`.
- `GET /checkout-orders/{order_id}/report` zwraca raport dopiero po akceptacji i tylko kluczowi API pierwotnego zamawiającego. Doręczenie jest zapisane w `revenue.report_delivered`; ponowne pobranie zwraca ten sam raport i nie tworzy drugiego zdarzenia doręczenia.

## Granice i ryzyka, których ta naprawa nie usuwa

1. `request_hash` to zwykły SHA-256 bez klucza. Nie ujawnia treści bezpośrednio, ale bardzo przewidywalne zadania mogą być podatne na atak słownikowy. Lepszym kolejnym krokiem jest HMAC z sekretem OLA lub hash z losową solą przechowywaną wyłącznie wewnętrznie.
2. Pełny tekst zadania pozostaje przechowywany w bazie OLA (`checkout_orders.task` i `checkout_execution_jobs.task`) bez szyfrowania aplikacyjnego. Potrzebne są kontrola dostępu do bazy, szyfrowanie dysku/backupów i polityka retencji.
3. Historyczne `EvidenceRecord` są append-only i mogą nadal zawierać zadania z wcześniejszych wersji. Nie są przepisywane, ponieważ naruszyłoby to historyczny SHA-chain. Wymaga to osobnej polityki retencji/ewentualnego crypto-shredding, bez fałszowania historii.
4. Historyczne obiekty i zdarzenia Stripe już utworzone ze starą `metadata.task` pozostają w Stripe. Ta zmiana zapobiega nowym zapisom i obsługuje stare sesje, ale nie usuwa historycznych danych po stronie Stripe.
5. `report_reviewer` jest rolą przypisaną do klucza API. Weryfikuje różną tożsamość techniczną i uprawnienie, ale **nie dowodzi, że za kluczem stoi inna osoba**. SSO/IdP, MFA, indywidualny operator, unieważnianie sesji i audyt logowania nadal są wymagane przed produkcją.
6. Dostarczenie następuje przez uwierzytelnione API; nie wdrożono jeszcze e-maila, jednorazowych linków, limitów pobrań, revokacji i potwierdzenia odbioru przez klienta.
7. Migracja PostgreSQL wymaga uruchomienia jako rola migracyjna. Nie oznacza automatycznego przeniesienia całej bazy SQLite do PostgreSQL.

## Weryfikacja

- Testy obejmują brak `metadata[task]`, zapis zadania tylko w prywatnym zamówieniu, hash-only webhook, brak raportu w odpowiedzi checkout retry, odmowę przed recenzją, odrzucenie recenzenta bez właściwej roli, odmienność recenzenta od zamawiającego/akceptującego, zgodność skrótu i tipa oraz doręczenie tylko pierwotnemu zamawiającemu.
- Pełny wynik testów i status testu PostgreSQL należy traktować oddzielnie. Test integracyjny PostgreSQL jest pominięty, gdy nie ma `OLA_TEST_POSTGRES_URL`.
- Zmiana nie włącza Stripe LIVE, nie wykonuje merge i nie publikuje aplikacji.
