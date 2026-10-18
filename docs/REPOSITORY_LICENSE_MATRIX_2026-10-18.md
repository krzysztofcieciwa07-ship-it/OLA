# Granice repozytoriów i licencji — dwa profile (odczyt 2026-10-18)

| Repozytorium | Faktyczny stan | Zasada licencyjna / rekomendacja |
| --- | --- | --- |
| `krzysztofcieciwa07-ship-it/OLA` | PUBLIC, Unlicense | Kanoniczne źródło historyczne. Nie twierdzić, że stare uprawnienia zniknęły. Zweryfikować prawa nowych modułów. |
| `krzys167-crypto/OLA` | PUBLIC, fork OLA, Unlicense | Nie traktować jako prywatnej kopii. Występują liczne rozbieżne pliki; selektywny audyt, bez automatycznego scalania. |
| `krzysztofcieciwa07-ship-it/vantage` | PUBLIC, osobny prototyp, brak LICENSE w drzewie `main` | Prawa autorskie i warunki licencji do decyzji; nie zakładać automatycznie Unlicense. |
| `krzys167-crypto/vantage` | PUBLIC, fork ww. | Kopia publiczna; kontrolować pochodzenie, nie publikować zastrzeżonych nowych zmian. |
| `krzysztofcieciwa07-ship-it/Vantage-v0.3` | PRIVATE, puste repo wg audytu | Prywatność tego repo nie czyni drugiego repo Vantage-v0.3 prywatnym. |
| `krzys167-crypto/Vantage-v0.3` | PUBLIC, niezależne, zawiera kod | Zidentyfikować, które elementy są własne/pożyczone. Przed decyzją o ukryciu zabezpieczyć dowody historycznej publikacji. |
| `krzys167-crypto/ola-evidence-gateway` | PUBLIC, README-only na `main` | Nie mylić dokumentacji koncepcyjnej z odrębnym runtime; zachować pochodzenie. |
| `krzysztofcieciwa07-ship-it/ola-evidence-gateway` | PUBLIC fork poprzedniego | Unikać duplikowania Evidence w OLA. |
| `quantum-ai-chatbot` na obu profilach | PUBLIC; istnieje śledzony plik `.env` | Sprawdzić konfigurację Supabase, RLS oraz czy klucze nie są uprzywilejowane; nie cytować wartości. |
| `MetaGPT`, `cli`, `ai`, `swarmclaw` i pozostałe forki cudze | PUBLIC forki projektów trzecich | Oryginalne licencje, zachowanie NOTICE/atrybucji, brak samowolnego przypisywania własności. |

## Polityka klasyfikacji publikacji (projekt do akceptacji)

- **PUBLIC:** zatwierdzona strona produktu, informacje prasowe i demonstracje z bezpiecznymi, niewrażliwymi danymi; historyczne publiczne repozytoria z właściwą informacją o licencji.
- **PRIVATE:** przyszły własny kod komercyjny po potwierdzeniu praw, modele, know-how, logi klientów, dostępy, umowy, cenniki niepubliczne, dokumenty prawne i produkcyjne.
- **REVIEW / BLOCKED:** migrowane moduły z publicznych forków, własność cudza, nieznane komponenty, publikacje bez jasnej licencji i zasoby zawierające potencjalne sekrety.

## Bezpieczna sekwencja

1. Nie zmieniać publicznej licencji w ciemno ani nie usuwać starych tagów.
2. Ustalić i potwierdzić właściciela praw.
3. Przeprowadzić pełny skan zawartości i historii wszystkich relewantnych repozytoriów.
4. Założyć PRIVATE dla NOWYCH, jasno wyodrębnionych komponentów prawnie własnych.
5. Dopiero po potwierdzeniu dokonać prospektywnego licencjonowania i ustawień prywatności.
6. Publiczny frontend i materiały promocyjne wydzielić i zatwierdzić osobno.
7. Wymagać przed wdrożeniem podpisanego prawa do publikacji wraz z release SHA.

To jest mapa ryzyk; nie stanowi dowodu zgodności, zmiany widoczności ani decyzji prawnika.
