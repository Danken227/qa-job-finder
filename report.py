from pathlib import Path
import pandas as pd

def export(offers):
    df=pd.DataFrame([o.__dict__ for o in offers])
    Path("reports").mkdir(exist_ok=True)
    df.to_excel("reports/report.xlsx",index=False)
    df.to_html("reports/report.html",index=False)
