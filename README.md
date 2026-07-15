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

Program pobiera publiczne oferty z JustJoinIT, No Fluff Jobs, RocketJobs oraz
publicznych wyników LinkedIn Jobs. Każdy link jest otwierany i sprawdzany przed
dodaniem do raportu.

## Uruchomienie

```powershell
python -m pip install -r requirements.txt --user
python main.py
```

Po zakończeniu raporty znajdują się w katalogu `reports`:

- `report.xlsx` — raport w Excelu z klikalnymi linkami;
- `report.html` — raport w przeglądarce z przyciskiem „Otwórz ofertę”.

Program nie dopisuje ofert na siłę: jeśli mniej niż 10 pozycji przejdzie wszystkie
filtry i kontrolę linków, raport będzie krótszy.
