# OLA di-OS — granice licencji i własności intelektualnej

**Stan:** LEGAL REVIEW REQUIRED / PUBLIC RELEASE NO-GO w zakresie nowej deklaracji praw wyłącznych.  
**Data audytu:** 2026-10-18.  
**Zakres:** oba profile GitHub: `krzysztofcieciwa07-ship-it`, `krzys167-crypto`.  
**To jest dokument polityki i planu zmian, a NIE nowa licencja dla istniejącego kodu.**

## Fakty potwierdzone

1. `krzysztofcieciwa07-ship-it/OLA` jest publiczne; plik `LICENSE` na `main` zawiera pełną **Unlicense** od pierwszego commita 2026-08-08 (`23a946d88d23668c9c8ab458def1213cb79b59b5`).
2. `krzys167-crypto/OLA` jest publicznym forkiem tego repozytorium i również zawiera Unlicense.
3. Historia `main` zawiera commity zapisane pod dwoma kontami; same loginy GitHub nie dowodzą tożsamości prawnej autora, przeniesienia praw ani zgody wszystkich uprawnionych.
4. `krzysztofcieciwa07-ship-it/Vantage-v0.3` ma widoczność PRIVATE, lecz **oddzielne** `krzys167-crypto/Vantage-v0.3` ma widoczność PUBLIC.
5. Nie dokonano pełnego audytu wszystkich historycznych wydań, forków osób trzecich, zależności ani statusu znaków towarowych.

## Decyzja właściciela z 2026-10-18: osoba fizyczna

Operator projektu wskazał, że **nie ma firmy** i chce zachować prawa majątkowe do **własnych, przyszłych, oryginalnych modułów** we własnym imieniu jako osoba fizyczna. Status: **USER-DECLARED OWNER MODEL / LEGAL TITLE UNVERIFIED**.

- Nie wpisywać fikcyjnej spółki ani nie zgadywać nazwiska z loginu GitHub.
- Dokładna tożsamość prawna, kraj prawa właściwego, relacje pracy/zlecenia oraz wkład współautorów muszą być zweryfikowane **przed** podpisaniem właściwej umowy lub zamieszczeniem imiennego copyright notice.
- Dwa profile GitHub nie dowodzą, że wszystkie commity są utworami jednej osoby.
- Jeżeli nowy kod powstawał w ramach stosunku pracy, sprawdzić przepisy i umowę: np. belgijskie przepisy przewidują odrębne reguły dla programów tworzonych przez pracownika.
- Docelowe przyszłe repo prywatne ma być własnością osoby fizycznej lub jej kontrolowanego konta; po założeniu firmy dopiero osobnym pisemnym dokumentem można rozważyć licencję lub przeniesienie majątkowych praw autorskich.
- Git commit, wpis w README i czat **nie są podpisaną umową przeniesienia praw**, a ten dokument nie ustala wyłącznej własności wcześniejszych utworów Unlicense.

Wymagane dane do formalnego dokumentu: pełne imię i nazwisko właściciela (przechowywać prywatnie do zatwierdzenia publikacji), identyfikacja objętych nowych utworów i ich początkowych SHA, data skuteczności, lista współtwórców i udokumentowane prawa do wkładów zewnętrznych.

Źródło właściwego rozróżnienia: https://economie.fgov.be/en/themes/intellectual-property/intellectual-property-rights/copyright-and-related-rights/copyright/intellectual-property-software/creation-computer-program/who-holds-copyright-software

## Co Unlicense oznacza i czego NIE możemy obiecać

Unlicense stanowi bardzo szerokie zezwolenie / deklarację oddania dzieła do domeny publicznej. Osoby korzystające z wcześniej opublikowanych wersji mogły nabyć uprawnienia do ich kopiowania, modyfikacji, dystrybucji i komercyjnego użycia. Usunięcie pliku, zamknięcie repozytorium lub dopisanie tekstu „All Rights Reserved” NIE cofa automatycznie tych praw, kopii ani wcześniejszych forków. Nie należy usuwać historii, aby stwarzać przeciwne wrażenie.

Właściciel praw do NOWYCH, odrębnych elementów może zdecydować o restrykcyjnych warunkach publikacji przyszłych prac, jeśli posiada wymagane prawa i nie narusza licencji składników trzecich. Kod zaczerpnięty z historycznych wersji Unlicense nie staje się wyłączny przez samo umieszczenie go w nowym produkcie.

## Polityka od teraz — do zatwierdzenia przez właściciela praw

- **NIE publikować nowego tajnego kodu, danych klientów, kluczy, modeli, podpisów ani pakietów komercyjnych** w publicznych repozytoriach obu profili. Kody klientów i sekrety pozostają tylko w kontrolowanej infrastrukturze prywatnej.
- **Rozdzielić nowe moduły komercyjne** do repozytorium PRIVATE o określonym właścicielu praw i formalnie zatwierdzonych warunkach przed pierwszą publikacją. Samo publiczne repo OLA pozostaje pod dotychczasową licencją do świadomego, prawidłowego zakończenia migracji.
- **Zachować Unlicense dla wersji historycznych** i jawnie oznaczyć granicę, od której ewentualne nowe utwory będą objęte innym tekstem licencyjnym; wskazać konkretne pliki/release SHA i autorstwo.
- **Forka cudzych projektów** (m.in. `MetaGPT`, `ai`, `cli`, `swarmclaw`) nie przelicencjonowywać jak własnego produktu. Zachować ich licencje, notices i wymagania atrybucji.
- **Markę OLA, logo i komercyjne materiały** rozpatrywać osobno od licencji kodu; sprawdzić prawa do grafiki i ewentualną rejestrację znaku, nie deklarować niezarejestrowanego znaku jako zarejestrowanego.
- **Nie scalać PR z nowymi roszczeniami prawnymi** bez podpisanego właściciela praw, rozliczenia autorstwa i opinii prawnej odpowiedniej dla jurysdykcji.
- Ustawić wymagane recenzje dla zmian `LICENSE`, `NOTICE`, `docs/LICENSING*`, dla widoczności repo oraz publikacji wydań. Zmiany polityki publikacji mają wymagać świadomej decyzji człowieka.

## Bramki prawne: NO-GO dopóki brak dowodów

- [ ] LEGAL-1: wskazany prawny właściciel majątkowych praw autorskich (osoba lub podmiot), dokumentacja prawa do kodu stworzonego na obu kontach;
- [ ] LEGAL-2: inwentaryzacja wszystkich współtwórców, źródeł generowanych/przeniesionych, zależności oraz treści trzecich;
- [ ] LEGAL-3: potwierdzony zakres historycznej Unlicense i ocena możliwości prospektywnego licencjonowania przez prawnika;
- [ ] LEGAL-4: zatwierdzony model licencji na przyszłość (proprietary / dual license / inny), obowiązujący wyłącznie od jednoznacznej granicy;
- [ ] LEGAL-5: utworzone prywatne repo i potwierdzone zabezpieczenia GitHub (wymagana recenzja, branch rulesets, sekrety, skanowanie); publiczne forki nadal istnieją;
- [ ] LEGAL-6: podpisana decyzja prawna powiązana z konkretnymi SHA i projektem (nie mylić z lokalnym Human Gate wykonywania zadań);
- [ ] LEGAL-7: osobna walidacja bezpieczeństwa i produkcyjnego GO.

**Zasada:** UNKNOWN nie staje się VERIFIED bez dowodu. Ten dokument sam w sobie nie zmienia `LICENSE`.

Źródła: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository ; https://opensource.org/license/unlicense ; https://opensource.guide/legal/
