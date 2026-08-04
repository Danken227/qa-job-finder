# QA Job Finder

Program tworzy raport ofert QA dopasowanych do następującego profilu:

- Wrocław lub praca w 100% zdalna;
- Manual QA / Tester / QA Engineer / Test Engineer;
- SQL, REST API, Postman, Jira i Confluence jako silne atuty;
- ERP/WMS jako dodatkowy plus;
- Playwright jest akceptowany, jeśli oferta nie jest stanowiskiem stricte automatyzacyjnym;
- UoP: minimum 14 000 zł brutto;
- B2B: minimum 100 zł/h, z priorytetem od 110 zł/h;
- oferty bez widełek pozostają w raporcie.

`main.py` pobiera publiczne oferty z JustJoinIT, No Fluff Jobs, RocketJobs oraz
publicznych wyników LinkedIn Jobs. Każdy link jest otwierany i sprawdzany przed
dodaniem do raportu.

`companies_main.py` jest niezależnym monitorem oficjalnych stron karier firm.
Baza znajduje się w `config/companies.json`; każda firma ma kategorię, priorytet,
miasto i adres strony kariery. Parser wykrywa widoczne linki do ofert QA oraz
najpopularniejsze zewnętrzne systemy rekrutacyjne (ATS).

## Uruchomienie

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
