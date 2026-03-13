import datetime
from enum import Enum
from dateutil.relativedelta import relativedelta
from momentum_client.manager import MomentumClientManager
from odk_tools.tracking import Tracker


class Markering(Enum):
    PASSIV= ("Passiv - Virksomhedsbank", "b15b54bb-d182-4b68-8534-bc4fb718862d", "Opgave - Porteføljeopfølgning - Passiv", "")
    KONTAKT = ("Kontakt - Virksomhedsbank", "2078ac36-b687-4723-bed7-2445e5c30a6f", "Opgave - Porteføljeopfølgning - Kontakt", "Opgave - Porteføljeopfølgning – kontakt")
    PARTNERSKAB = ("Partnerskab - Virksomhedsbank", "aa705e32-6388-4a9a-b4e4-3140fd529834", "Opgave - Porteføljeopfølgning - Partnerskab", "Opgave - Porteføljeopfølgning – Partnerskab")
    SAMARBEJDE = ("Samarbejde - Virksomhedsbank", "fa1a14f3-7b57-44d3-b784-fb44cef71866", "Opgave - Porteføljeopfølgning - Samarbejde", "Opgave - Porteføljeopfølgning – Samarbejde")
    
    @property
    def name(self):
        return self.value[0]
    
    @property
    def id(self):
        return self.value[1]
    
    @property
    def opgavenavn(self):
        return self.value[2]
    
    @property
    def tidl_opgavenavn(self):
        return self.value[3]
        


class TestMarkering(Enum):
    KONTAKT = ("Kontakt – Virksomhedsbank", "e31984ba-fde2-4e41-8cc6-b1db51994d92", "Opgave - Porteføljeopfølgning - Kontakt")
    PARTNERSKAB = ("Partnerskab – Virksomhedsbank", "b0c52d99-f739-49d8-8532-417f224fa757", "Opgave - Porteføljeopfølgning - Partnerskab")
    SAMARBEJDE = ("Samarbejde – Virksomhedsbank", "9cce6ea2-6b0f-4631-a9fd-e2f20655ebe9", "Opgave - Porteføljeopfølgning - Samarbejde")
    
    @property
    def name(self):
        return self.value[0]
    
    @property
    def id(self):
        return self.value[1]

    @property
    def opgavenavn(self):
        return self.value[2]
    
    @property
    def tidl_opgavenavn(self):
        return ""


class MomentumService:
    def __init__(
            self,
            momentum: MomentumClientManager,
            tracker: Tracker
            ):
        
        self.momentum = momentum
        self.tracker = tracker
    
    def hent_virksomheder_med_markeringer(self) -> dict| None:
        query = [
            {
                "customFilter": "active",
                "fieldName": "tags/id",
                "values": [None, None, None, None] + [markering.id for markering in Markering]
            }
        ]

        result = self.momentum.virksomheder.hent_virksomheder(filters=query)

        if result is None or 'data' not in result:
            return None
        
        return result
    
    def luk_markgeringer(self, markeringer: dict):       
        for markering in markeringer:
                if markering["end"] is None:
                    self.momentum.markeringer.afslut_markering(
                        markering=markering,
                        slut_dato=datetime.datetime.now().date()
                    )

    
    def luk_opgaver(self, opgaver: list[dict]):
        status = self.momentum.opgaver.Status.aflyst
        for opgave in opgaver:
            if opgave["stateName"] != "Aflyst" and opgave["stateName"] != "Gennemført":
                    self.momentum.opgaver.opdater_opgave_status(opgave["id"], status)
    
    def opdater_sagsbehandlere_på_overblik(self, virksomhedsid:str, sagsbehandler_query:list):

        response = self.momentum.virksomheder.opdater_sagsbehandlere_på_overblik(virksomhedsid, sagsbehandler_query)
        
    def find_taksonomi_id(self, taksonomi_navn:str) -> str:
        taksonomier = self.momentum.taksonomier.hent_alle_taksonomier()

        porteføljeansvarlig = []
        for taksonomi in taksonomier:
            for item in taksonomi .get("items", []):
                if item.get("name") == taksonomi_navn:
                    porteføljeansvarlig.append({
                        "taxonomy_code": item["code"],
                    })
        
        if len(porteføljeansvarlig) == 1:
            return porteføljeansvarlig[0]["taxonomy_code"]
        else:
            raise ValueError("Fandt ikke korrekt taksonomi")
    
    def find_relevante_markeringer(self, markeringer:dict, test:bool) -> list[dict]:       
        markering_enum = TestMarkering if test else Markering
        markeringsider = {m.id for m in markering_enum}
        
        relevante_markeringer = []
        today = datetime.date.today()

        for markering in markeringer:
            # Håndtering af end format så vi kan tjekke om den er overskredet eller None
            end_date = datetime.datetime.fromisoformat(markering["end"]).date() if markering["end"] else None
            # Vi skal bruge markeringer der som har rigtige id og som ikke er afsluttet eller har en slutdato
            if markering["tag"]["id"] in markeringsider and (end_date is None or end_date >= today):
                relevante_markeringer.append(markering)
        
        return relevante_markeringer

    def find_og_luk_porteføljeopgaver(self, opgaver: dict):
        porteføljeopfølgning_opgaver = [opgave for opgave in opgaver if "porteføljeopfølgning" in opgave["title"].lower() and (opgave["stateName"] != "Gennemført" and opgave["stateName"] != "Aflyst")]
        if len(porteføljeopfølgning_opgaver) > 0:
            self.luk_opgaver(porteføljeopfølgning_opgaver)

    def find_og_luk_porteføljeansvarlige(self, virksomhedsoverblik: dict, virksomhed: dict, porteføljeansvarligekode: str):
        if len(virksomhedsoverblik["responsibleCaseworkers"]) > 0 and virksomhedsoverblik["responsibleCaseworkers"] is not None:
            sagsbehandlere = [cw for cw in virksomhedsoverblik["responsibleCaseworkers"] if cw["responsibilityCode"] != porteføljeansvarligekode]       
            self.opdater_sagsbehandlere_på_overblik(virksomhed["id"], sagsbehandlere)
        
    def find_markerninger_der_skal_have_ogpaver(self, opgaver: dict, markeringer: dict, test: bool = True) -> list[dict]:
        markering_enum = TestMarkering if test else Markering
        
        markeringer_der_skal_have_opgave = []

        for markering in markeringer:

            markering_skal_have_opgave = True
            matchet_enum = next((m for m in markering_enum if m.name == markering["tag"]["title"]), None)

            if matchet_enum is None:
                continue

            for opgave in opgaver:
                # Tjekker om der er en opgave for den pågældende markering, med korrekt status
                if (opgave["title"] == matchet_enum.opgavenavn or opgave["title"] == matchet_enum.tidl_opgavenavn) and (opgave["stateName"] == "Planlagt" or opgave["stateName"] == "I gang"):
                    # Er der en slut dato på markeringen, skal denne opgave afsluttes, og der skal senere oprettes en ny opgave for markeringen
                    if markering["end"] is not None:
                        self.momentum.opgaver.opdater_opgave_status(opgave["id"], self.momentum.opgaver.Status.gennemført)
                        markering_skal_have_opgave = True
                    else:
                        # Der er allerede en opgave for markering 
                        markering_skal_have_opgave = False
                        break
            
            if markering_skal_have_opgave:
                markeringer_der_skal_have_opgave.append(markering)
                
        return markeringer_der_skal_have_opgave
    
    def opret_opgaver_for_markeringer(self, markeringer: dict, virksomhed: dict, kontakt_til_virksomhedskode: str, sagsbehandlerid: str):

        # Opgaver skal have en falddato som beregnes udfra eksisterende journalnotater
        journalnotater = self.momentum.journalnotater.hent_journalnotater(virksomhed["id"])

        if journalnotater is not None:
            # Find relevante journalnotater med korrekt journalTypeCode og "Porteføljeopfølgning" i titel
            relevante_journalnotater = [
                jn for jn in journalnotater
                if jn.get("journalTypeCode") == kontakt_til_virksomhedskode
                and "porteføljeopfølgning" in jn["title"].lower()
            ]
                    # Find det nyeste journalnotat
        if relevante_journalnotater:
            nyeste_journalnotat = max(relevante_journalnotater, key=lambda jn: jn.get("createdAt") or "")
        else:
            nyeste_journalnotat = None
        
        
        beskrivelse: str

        for markering in markeringer:
            markering_titel = markering["tag"]["title"].lower()
            
            # Udtræk markeringstype (f.eks. "Partnerskab" fra "Partnerskab - Virksomhedsbank")
            markeringstype = markering["tag"]["title"].split(" – ")[0].split(" - ")[0]
            
            # Sæt tekst og frekvens baseret på markeringstype
            if "partnerskab" in markering_titel or "samarbejde" in markering_titel:
                frekvens_tekst = "Der skal gennemføres 4 kontakter årligt, svarende til én hver 3. måned"
                frekvens = 3
            else:
                frekvens_tekst = "Der skal gennemføres 2 kontakter årligt, svarende til én pr. halvår"
                frekvens = 6
            
            # Beregn falddato baseret på nyeste journalnotat
            today = datetime.date.today()
              
            if nyeste_journalnotat is not None:
                notat_oprettelsesdato = datetime.datetime.fromisoformat(nyeste_journalnotat["createdAt"]).date()
                            
                if notat_oprettelsesdato + relativedelta(months=frekvens) < today:
                    falddato = today + relativedelta(months=frekvens)
                else:
                    falddato = notat_oprettelsesdato + relativedelta(months=frekvens)
            else: 
                falddato = today + relativedelta(months=frekvens)
            
            beskrivelse = f"""Virksomhedsbank {markeringstype}:
                {frekvens_tekst}
                - Under kontakten skal følgende emner berøres/gennemgås:
                - Virksomhedens tilstand/trivsel/udvikling
                    - Tilgang/afgang ordre, medarbejdere o. lign.
                - Virksomhedens behov for rekruttering her og nu + fremtidig (VITAS, JobAG)
                    - Herunder praktik, løntilskud, voksenlærling, fleksjob og ordinære job
                    - Dvs. jobcenterets produkter (produktmappen)
                - Virksomhedens tilfredshed med samarbejdet
                    - Herunder virksomhedsbankstatus
                - Virksomhedens kontaktpersoner
                - Evt. mulige kampagne, f.eks. jobmesse, voksenlærlinge o. lign.
                - Ovenstående noteres under notater + formålet "Porteføljeopfølgning" samt notering/opdatering, jf. registreringspraksis."""
            
            sagsbehandler = {
                "id": sagsbehandlerid
            }

            self.momentum.opgaver.opret_opgave(
                virksomhed,
                [sagsbehandler], 
                falddato, 
                f"Opgave - Porteføljeopfølgning - {markeringstype}", 
                beskrivelse,
                borger_opgave=False
            )


    


        




