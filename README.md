# QA Job Finder

Program tworzy raporty ofert QA według lokalnego profilu wyszukiwania. Twój profil,
wynagrodzenie, lokalizacja i umiejętności nie są częścią repozytorium.

## Skrypty

| Skrypt | Źródło ofert | Raport |
|---|---|---|
| `portals_main.py` | portale: JustJoinIT, No Fluff Jobs, RocketJobs, Pracuj.pl, LinkedIn Jobs | `reports/portals/portals_report.*` |
| `companies_main.py` | oficjalne strony karier firm z `config/companies.json` | `reports/companies/company_report.*` |
| `public_main.py` | budżetówka: nabory.kprm.gov.pl, ogłoszenia gov.pl + instytucje z `config/public_institutions.json` | `reports/public/public_report.*` |
| `run_all.py` | uruchamia trzy powyższe po kolei | każdy w swoim katalogu |

Każdy raport powstaje w dwóch wersjach: `.xlsx` (Excel z klikalnymi linkami)
i `.html` (przeglądarka, przycisk „Otwórz ofertę”). Wszystkie skrypty używają
tych samych filtrów profilu, a każdy link jest otwierany i sprawdzany przed
dodaniem do raportu. Program nie dopisuje ofert na siłę: jeśli mniej pozycji
przejdzie filtry i kontrolę linków, raport będzie krótszy od limitu.

## Analiza treści ofert

Po weryfikacji linku program czyta pełny opis oferty (z danych strukturalnych
strony; dla Pracuj.pl — przez Chromium) i:

- **odrzuca oferty wymagające języka obcego innego niż angielski** (niemiecki,
  francuski, włoski…). Wzmianka w tytule („Tester with German”) wyklucza zawsze;
  w opisie — tylko jako wymaganie („znajomość języka niemieckiego”, „fluent
  German”), a nie gdy język jest „mile widziany” albo gdy chodzi o rynek
  („for the German market”);
- **szacuje udział testów manualnych** — kolumna **Manual / automat**, np.
  `80% manual / 20% automat · manual: przypadki testowe, eksploracyjne ·
  automat: Selenium`. Wpływa na ocenę (100% manual: +5, 0%: −5); oferty poniżej
  25% manualnych z wyraźną automatyzacją są odrzucane jak stanowiska
  automatyzujące.

## Lista ofert w Excelu (statusy)

Plik `.xlsx` każdego raportu to trwała lista ofert. W pomarańczowej kolumnie
**Status** wybierasz z listy: Nowa / Obejrzana / CV wysłane / Rozmowa /
Odrzucona / Nie interesuje mnie. Tytuł w kolumnie **Stanowisko** jest linkiem
do oferty (kolumna „Link” jest ukryta — program rozpoznaje po niej oferty).

Status jest wspólny dla tej samej oferty we wszystkich listach (Portale /
Firmy / Budżetówka): oferta jest rozpoznawana po linku albo po tytule i nazwie
firmy bez formy prawnej („Sii Polska Sp. z o.o.” = „Sii”). Bardziej zaawansowany
status wygrywa — „CV wysłane” ustawione w Portalach pojawi się też w Firmach.

Przy kolejnym uruchomieniu program wczytuje poprzedni plik i przenosi statusy (oferty dopasowuje po linku, a gdy link się zmieni — po firmie
i tytule). Nowe oferty dostają status „Nowa” (zielone tło) i trafiają na
górę. Oferty z wysłanym CV, odrzucone itp. są wyszarzone. Oferty, których nie
ma w bieżącym wyszukiwaniu, nie są usuwane — mają „Nie” w kolumnie „W ostatnim
wyszukiwaniu” i są przekreślone.

**Zamknij plik w Excelu przed uruchomieniem skryptu.** Jeśli będzie otwarty,
program zapisze kopię `… (kopia RRRR-MM-DD_GGMM).xlsx` i ostrzeże — statusy
wpisane w kopii nie zostaną przeniesione.

Raport `.html` pokazuje te same oferty: na górze do przejrzenia, niżej zwinięte
„Załatwione” i „Nie ma ich w ostatnim wyszukiwaniu”.

## Arkusze Google (statusy z telefonu)

Zamiast lokalnego Excela listę ofert można trzymać w Arkuszu Google
(zakładki Portale / Firmy / Budżetówka) i zmieniać statusy z dowolnego
urządzenia. Program czyta arkusz tuż przed zapisem, więc statusy ustawione
w telefonie są zachowane. Lokalny Excel nadal powstaje jako kopia zapasowa.
Jeśli Google nie odpowie, program **nie nadpisuje** arkusza (zapisuje tylko
Excel) i zgłasza to w mailu.

Jednorazowa konfiguracja (ok. 15 minut):

1. <https://console.cloud.google.com/> → utwórz projekt (np. `qa-job-finder`).
2. **APIs & Services → Library** → wyszukaj **Google Sheets API** → **Enable**.
3. **IAM & Admin → Service Accounts → Create service account** (nazwa np.
   `qa-job-finder`, role można pominąć) → wejdź w konto → **Keys → Add key →
   Create new key → JSON**. Zapisz pobrany plik jako
   `config/google_service_account.json` (plik jest ignorowany przez Git —
   to hasło do arkusza, nie wysyłaj go nikomu).
4. Utwórz pusty arkusz na <https://sheets.google.com> → **Udostępnij** →
   wklej adres konta usługi (`…@….iam.gserviceaccount.com`, pole
   `client_email` w pliku JSON) z uprawnieniem **Edytor**.
5. Skopiuj `config/sheets.example.json` jako `config/sheets.json` i wpisz
   `spreadsheet_id` — fragment adresu arkusza między `/d/` a `/edit`.
6. Uruchom `python setup_sheets.py` — sprawdzi dostęp, utworzy zakładki
   i przeniesie do nich obecne statusy z lokalnych plików Excel.

Konto usługi widzi wyłącznie arkusze, które mu udostępnisz.

## Cotygodniowy raport mailem

`run_all.py --email` po zakończeniu wysyła na Gmail link do arkusza (gdy
Arkusze Google są skonfigurowane), listę nowych ofert, sekcję **problemów ze
źródłami** (portal bez ofert, zablokowana strona, nieaktualny adres,
niedostępny ATS lub arkusz) oraz trzy pliki Excel w załącznikach. Załączniki
wyłączysz w `config/notify.json`: `"attach_reports": false`.

Jednorazowa konfiguracja:

1. Włącz weryfikację dwuetapową na koncie Google i utwórz hasło aplikacji:
   <https://myaccount.google.com/apppasswords>.
2. Ustaw adresy w `config/notify.json` (szablon: `config/notify.example.json`;
   plik jest ignorowany przez Git).
3. Uruchom `python setup_email.py` — zapyta o hasło aplikacji, zapisze je
   w Menedżerze poświadczeń Windows (nie w pliku) i wyśle mail testowy.

Harmonogram: zadanie „QA Job Finder” w Harmonogramie zadań Windows uruchamia
`scheduled_run.cmd` w poniedziałki i czwartki o 8:00. Mail przychodzi tylko
wtedy, gdy są nowe oferty albo problem ze źródłami. Jeśli komputer był wtedy
wyłączony, zadanie wykona się po jego włączeniu. Log ostatniego przebiegu:
`reports/logs/last_run.log`. `scheduled_run.cmd` zawiera ścieżkę do Pythona
(`C:\Python312\python.exe`) — zmień ją, jeśli Python jest gdzie indziej.

Zmiana terminu (PowerShell):

```powershell
Set-ScheduledTask -TaskName "QA Job Finder" -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Thursday -At "08:00")
Start-ScheduledTask -TaskName "QA Job Finder"        # uruchom teraz, na próbę
Unregister-ScheduledTask -TaskName "QA Job Finder"   # usuń harmonogram
```

## Uruchomienie

```powershell
python -m pip install -r requirements.txt --user
python -m playwright install chromium   # jednorazowo, tylko dla opcji --render

python portals_main.py      # 1. portale
python companies_main.py    # 2. strony firm (domyślnie priorytet S)
python public_main.py       # 3. budżetówka (domyślnie wszystkie priorytety)
python run_all.py           # 4. wszystko (firmy i instytucje: wszystkie priorytety)
```

Opcje `companies_main.py` i `public_main.py`:

```powershell
--all                      # wszystkie priorytety (S, A, B)
--tiers S A                # wybrane priorytety
--company Sii Tietoevry    # tylko wybrane wpisy (fragment nazwy)
--category erp_wms         # tylko wybrane kategorie (companies_main.py)
--render                   # dodatkowo renderuj strony ładowane JavaScriptem (wolniej)
--verbose                  # wynik i metoda dla każdego wpisu (diagnostyka bazy)
--skip-nabory              # public_main.py: pomiń nabory.kprm.gov.pl
```

Opcje `run_all.py`: `--tiers`, `--render`, `--email` (mail tylko przy nowych ofertach
albo problemach ze źródłami), `--email-always`, `--skip portals companies public`.

Pracuj.pl blokuje zwykłe zapytania (Cloudflare), więc jest odczytywany przez
Chromium bez okna — wymaga jednorazowego `python -m playwright install chromium`.

Na końcu skrypty stron karier wypisują wpisy zablokowane (401/403/429),
z nieaktualnym adresem (404, strona błędu, przekierowanie na stronę główną,
certyfikat innej domeny) oraz błędy techniczne — to lista wpisów w bazie do
poprawienia.

## Prywatny profil wyszukiwania

Przed pierwszym uruchomieniem skopiuj szablon i uzupełnij go własnymi warunkami:

```powershell
Copy-Item config/search_profile.example.json config/search_profile.json
```

Edytuj wyłącznie `config/search_profile.json`. Plik zawiera:

- `location` — miasto, jego wersję używaną w adresach portali, zgoda na remote i hybrydę poza miastem;
- `salary` — minimalne i preferowane stawki oraz decyzję, czy zostawiać oferty bez widełek;
- `job_titles` — stanowiska, które mają wejść do raportu, oraz tytuły do wykluczenia;
- `matching_skills` — umiejętności i punkty wpływające na dopasowanie;
- `filtering` — minimalny wynik oraz limity weryfikacji i raportu.

Pola opcjonalne (starsze profile działają bez nich):

- `location.country` — kraj ofert ze stron karier (domyślnie `Poland`);
- `location.city_aliases` — inne pisownie miasta, np. `["Warsaw"]` dla Warszawy
  (polskie znaki są porównywane bez ogonków, więc `Wroclaw` == `Wrocław`);
- `job_titles.career_search_keywords` — frazy wysyłane do wyszukiwarek ATS
  (Workday, SmartRecruiters, SuccessFactors, Phenom); domyślnie
  `["QA", "tester", "testów", "test engineer"]`;
- `job_titles.public_sector_include` — dodatkowe słowa tytułów w budżetówce,
  gdzie stanowiska są urzędowe („Specjalista ds. testów”); domyślnie m.in.
  `tester`, `testów`, `testowania`, `jakości oprogramowania`;
- `job_titles.public_sector_seniority_exclude` — stanowiska kierownicze do
  pominięcia w budżetówce; domyślnie `kierownik`, `naczelnik`, `dyrektor`.

`config/search_profile.json` jest ignorowany przez Git. Nie dodawaj go ręcznie do
commita. Do repozytorium trafia tylko `config/search_profile.example.json`, który
jest neutralnym szablonem bez Twoich danych.

## Jak działają skrypty stron karier

`companies_main.py` i `public_main.py` dla każdego wpisu z bazy kolejno:

1. pobierają oferty z publicznego API systemu rekrutacyjnego (ATS) wskazanego
   w bazie albo wykrytego w kodzie strony — obsługiwane: Workday,
   SmartRecruiters, Greenhouse, Lever, Workable, Teamtailor, Recruitee, Ashby,
   Traffit, eRecruiter, SAP SuccessFactors i Phenom;
2. czytają oferty opublikowane jako schema.org/JobPosting (JSON-LD);
3. szukają na stronie linków do ofert z pasującym tytułem;
4. przechodzą na podstrony typu „Oferty pracy” / „Open positions”;
5. z opcją `--render` renderują w Chromium strony, które ładują listę
   ofert JavaScriptem i nie dały wyniku statycznie.

Do raportu trafiają tylko oferty w kraju z profilu (domyślnie Polska), zdalne
albo bez podanej lokalizacji — globalne ATS-y korporacji zwracają oferty
z całego świata.

## Budżetówka

`public_main.py` łączy trzy źródła:

- **nabory.kprm.gov.pl** — wszystkie ogłoszenia służby cywilnej (ministerstwa,
  urzędy wojewódzkie, KAS, Policja — pracownicy cywilni, inspekcje). Tytuł na
  liście to tylko stanowisko urzędnicze („specjalista”), więc program pobiera
  szczegóły („Do spraw: testowania oprogramowania”, komórka) i na nich sprawdza
  słowa kluczowe;
- **API ogłoszeń gov.pl** — ok. 300 instytucji spoza służby cywilnej
  (instytuty badawcze, Zakład Informatyki Lasów Państwowych, Wody Polskie…);
- **`config/public_institutions.json`** — instytucje z własnymi stronami ofert:
  COI (mObywatel), Centrum e-Zdrowia, NASK, CUI Wrocław, ZUS, NFZ, Policja, BGK…

Część serwerów BIP (Wrocław, Policja) wysyła niepełny łańcuch certyfikatów
SSL. Pakiet `truststore` (w `requirements.txt`) korzysta z magazynu
certyfikatów Windows, który go uzupełnia — bez wyłączania weryfikacji.

## Bazy firm i instytucji

`config/companies.json` (firmy) i `config/public_institutions.json`
(budżetówka) mają ten sam format. Minimalny wpis:

```json
{"name": "Firma", "category": "software_house", "priority": "B",
 "careers_url": "https://firma.pl/kariera"}
```

- `priority` — `S` (sprawdzane codziennie, domyślnie w `companies_main.py`),
  `A`, `B` (pełne skanowanie z `--all`);
- `category` — jedna z: `erp_wms`, `software_house`, `product`, `enterprise`,
  `finance`, `logistics`, `automotive_industrial`, `public`.

Pola opcjonalne:

- `jobs_url` — strona z listą ofert, jeśli inna niż strona kariery;
- `ats` — tablica ofert w ATS, np. `"https://apply.workable.com/firma/"`,
  `"https://firma.wd3.myworkdayjobs.com/External"` albo — dla platform pod
  domeną firmy — `{"type": "teamtailor", "url": "https://jobs.firma.com"}`
  (typy `teamtailor`, `successfactors`, `phenom`). Można podać listę;
- `enabled: false` — wyłącza wpis bez usuwania go z bazy;
- `notes` — komentarz, ignorowany przez program.

Wskazanie `ats` jest najpewniejsze: API zwraca pełną listę ofert z lokalizacją
i trybem pracy, niezależnie od wyglądu strony kariery.

## Testy

```powershell
python -m pip install -r requirements-dev.txt --user
python -m pytest
```

Testy nie łączą się z internetem i używają profilu testowego
(`tests/fixtures/search_profile.json`), a nie Twojego `config/search_profile.json`.
