# QA Job Finder

Program tworzy raport ofert QA według lokalnego profilu wyszukiwania. Twój profil,
wynagrodzenie, lokalizacja i umiejętności nie są częścią repozytorium.

`main.py` pobiera publiczne oferty z JustJoinIT, No Fluff Jobs, RocketJobs oraz
publicznych wyników LinkedIn Jobs. Każdy link jest otwierany i sprawdzany przed
dodaniem do raportu.

`companies_main.py` jest niezależnym monitorem oficjalnych stron karier firm.
Baza znajduje się w `config/companies.json`; każda firma ma kategorię, priorytet,
miasto i adres strony kariery. Parser wykrywa widoczne linki do ofert QA oraz
najpopularniejsze zewnętrzne systemy rekrutacyjne (ATS).

## Uruchomienie

### Prywatny profil wyszukiwania

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

`config/search_profile.json` jest ignorowany przez Git. Nie dodawaj go ręcznie do
commita. Do repozytorium trafia tylko `config/search_profile.example.json`, który
jest neutralnym szablonem bez Twoich danych.

### Uruchamianie raportów

```powershell
python -m pip install -r requirements.txt --user
python main.py

# Codzienny monitoring firm Tier S
python companies_main.py

# Pełne skanowanie wszystkich firm
python companies_main.py --all
```

Po zakończeniu raporty znajdują się w katalogu `reports`:

- `report.xlsx` — raport w Excelu z klikalnymi linkami;
- `report.html` — raport w przeglądarce z przyciskiem „Otwórz ofertę”.

Raport ze stron firm trafia osobno do `reports/companies/company_report.xlsx`
oraz `reports/companies/company_report.html`.

Program nie dopisuje ofert na siłę: jeśli mniej pozycji przejdzie wszystkie filtry
i kontrolę linków, raport będzie krótszy od ustawionego limitu.
