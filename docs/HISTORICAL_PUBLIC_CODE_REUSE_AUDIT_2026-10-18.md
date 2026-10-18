# OLA di-OS — kontrola publicznego reuse kodu historycznego

**Data:** 2026-10-18  
**Metoda:** odczyt GitHub API repozytoriów, publicznego drzewa, wykrywanej licencji i forków, globalne wyszukiwanie kodu/stron.  
**Klasyfikacja:** PARTIAL. Brak dostępu do prywatnych forków, zwykłych klonów, statystyk indywidualnych pobrań oraz dowodów faktycznego zewnętrznego wdrożenia.

## Weryfikowalne obserwacje

| Fakt | Dowód / zakres |
|---|---|
| `krzysztofcieciwa07-ship-it/OLA` | PUBLIC, Unlicense, `forks_count=1`, `stargazers_count=1`, `subscribers_count=0` z odczytu GitHub API w czasie audytu. |
| `krzys167-crypto/OLA` | PUBLIC fork oryginalnego repo; `parent=krzysztofcieciwa07-ship-it/OLA`. |
| Historia licencji | Unlicense dodana w pierwszym commicie `23a946d88d23668c9c8ab458def1213cb79b59b5` (2026-08-08); historyczne uprawnienia nie zostają automatycznie cofnięte. |
| Publiczne GitHub Releases z repo głównego | Dla zapytania `/releases?per_page=100` API zwróciło pustą listę; nie wyklucza artefaktów Actions, tagów, nierejestrowanej dystrybucji lub kopii poza GitHubem. |
| Zewnętrzny ślad nazwy | `KRZYSZTOF167/range-engine`: publiczne repo z jednym README o OLA di-OS, utworzone 2026-06-29, bez potwierdzonego skopiowanego silnika. Tożsamość właściciela tego konta niezweryfikowana. |
| Globalne wyszukiwanie | W badanych zapytaniach nie ustalono wiarygodnego, **niepowiązanego** wdrożenia/komercyjnej odsprzedaży kodu OLA. Wyniki zawierały liczne homonimy i ogólne „OLA”. Nie jest to dowód braku reuse. |

## Pytanie: czy ktoś już może używać starych wersji?

**TAK — prawna i techniczna możliwość istnieje.** Istniejący plik LICENSE udziela bardzo szerokich uprawnień publicznych do opublikowanego wcześniej kodu; pliki można było pobrać bez zalogowania. Nie potrzeba forka w GitHub, by użyć kodu. **Nie potwierdzono** poza wskazanymi kontami faktycznego wykorzystania kodu przez osobę trzecią. Nie możemy ustalić, czy istnieją kopie prywatne, komercyjne wykorzystanie offline lub użycie bez atrybucji.

GitHub Docs wprost wskazuje, że po zmianie repozytorium na prywatne wcześniejsze forki i lokalne kopie nadal mogą istnieć:
https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository

## Granice ochrony

- Dotychczasowej Unlicense nie można uczciwie przedstawić jako cofniętej przez nowy dokument.
- Zmiana na PRIVATE ograniczy widoczność przyszłego kodu w tym repo, ale nie odzyska wcześniejszych kopii.
- Odrębne, oryginalne NOWE moduły mogą mieć inne warunki, jeśli właściciel ma do nich prawa oraz zostaną one jasno odgraniczone od wcześniej licencjonowanych utworów.
- Komercyjna oferta może opierać się także na usłudze, infrastrukturze, tajemnicy przedsiębiorstwa, hostowanym runtime, utrzymaniu, wsparciu i certyfikowanych dowodach, bez prób cofania praw Unlicense.
- Obecne publiczne PR #109/#113 ujawniają nowy kod. Żaden dokument w tym PR nie sprawia, że ich opublikowane zawartości stają się tajne.

## Brakujące dowody do pełnego stwierdzenia „nikt nie używa”

Nie ma publicznej metody gwarantującej brak pobranych klonów i komercyjnego wykorzystania w infrastrukturze cudzej. Możliwy jest jedynie audyt ograniczonego zakresu, powtarzany monitoring, obsługa zgłoszeń i działania prawne przy **konkretnym, udowodnionym** naruszeniu praw nadal przysługujących właścicielowi. Reuse zgodny z historyczną Unlicense nie stanowi samo przez się naruszenia.

## Otwarte bramki

- [ ] Potwierdzenie legalnego imienia/nazwiska twórcy i prawa do określonych oryginalnych modułów.
- [ ] Inwentaryzacja autorskiej twórczości vs kod wcześniejszy vs osoby trzecie vs fork.
- [ ] Prywatna infrastruktura dla przyszłych prac komercyjnych i kontrola publikacji.
- [ ] Przegląd zasad GitHub `main`, zatwierdzeń i skanowania sekretów.
- [ ] Okresowy monitoring publicznych forków/kopii z wykrywaniem potwierdzonych przypadków użycia.

**Wynik: HISTORICAL REUSE LEGALLY POSSIBLE; THIRD-PARTY USE NOT VERIFIED; CANNOT RULE OUT PRIVATE/OFFLINE COPIES.**
