from dataclasses import dataclass

@dataclass
class JobOffer:
    company:str
    title:str
    location:str
    remote:str
    salary:str
    url:str
    source:str

class BaseCollector:
    def collect(self):
        raise NotImplementedError
