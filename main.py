from collectors.justjoinit import JustJoinItCollector
from collectors.nofluffjobs import NoFluffJobsCollector
from filter import filter_offers
from report import export

offers=[]
offers.extend(JustJoinItCollector().collect())
offers.extend(NoFluffJobsCollector().collect())
offers=filter_offers(offers)
export(offers)
print(f"Generated report with {len(offers)} offers")
