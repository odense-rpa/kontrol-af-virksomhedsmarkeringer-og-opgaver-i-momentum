import datetime
import logging
from enum import Enum
from functools import cached_property
from automation_server_client import WorkItemError
from dateutil.relativedelta import relativedelta
from momentum_client.manager import MomentumClientManager
from odk_tools.tracking import Tracker
from proces.models import Virksomhed, VirksomhedsKontekst

logger = logging.getLogger(__name__)


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

    @cached_property
    def porteføljeansvarlig_kode(self) -> str:
        # Porteføljeansvarlig findes ikke i EDU, Støtte-kontaktperson kan anvendes til EDU
        return self.find_taksonomi_id("CASEWORKER_RESPONSIBILITY", "Porteføljeansvarlig")

    @cached_property
    def kontakt_til_virksomhed_kode(self) -> str:
        return self.find_taksonomi_id("JOURNAL_TYPES_COMPANY", "Kontakt til virksomhed")

    def hent_virksomheder_til_kø(self) -> list[Virksomhed]:
        resultat = self.hent_virksomheder_med_markeringer()
        if resultat is None:
            return []
        return [
            Virksomhed(cvr=v['cvr'], pNummer=v['pNumber'], virksomhedsnavn=v['displayName'])
            for v in resultat['data']
        ]

    def hent_virksomhedskontekst(self, cvr: int, pnummer: int) -> VirksomhedsKontekst:
        virksomhed = self.momentum.virksomheder.hent_virksomhed_med_cvr_og_pnummer(cvr=cvr, pNummer=pnummer)
        if virksomhed is None:
            raise ValueError("Virksomhed ikke fundet i Momentum")

        overblik = self.momentum.virksomheder.hent_en_virksomheds_overblik(virksomhed["id"])
        if overblik is None:
            raise ValueError("Kunne ikke hente overblik")

        markeringer = self.momentum.markeringer.hent_markeringer(virksomhed["id"])
        if markeringer is None:
            raise ValueError("Kunne ikke hente markeringer")

        opgaver = self.momentum.opgaver.hent_opgaver_på_virksomhed(virksomhed["id"])
        return VirksomhedsKontekst(virksomhed, overblik, markeringer, opgaver)

    def luk_alt_på_inaktiv_virksomhed(self, virksomhed_kontekst: VirksomhedsKontekst):
        logger.info("Virksomhed ikke aktiv, lukker markeringer, opgaver og sagsbehandlere på overblik")
        try:
            self.luk_markgeringer(virksomhed_kontekst.markeringer)
            self.luk_opgaver(virksomhed_kontekst.opgaver)
            self.opdater_sagsbehandlere_på_overblik(virksomhed_kontekst.virksomhed["id"], [])
        except Exception as e:
            raise WorkItemError("Ikke muligt at lukke alt på ikke aktiv virksomhed") from e

    def luk_porteføljeopgaver_for_passiv(self, virksomhed_kontekst: VirksomhedsKontekst):
        logger.info("Passiv virksomhedsbank, lukker porteføljeopgaver")
        try:
            self.find_og_luk_porteføljeopgaver(virksomhed_kontekst.opgaver)
        except Exception as e:
            raise WorkItemError("Passiv - virksomhedsbank, det var ikke muligt at lukke porteføljeopgaver") from e

    def luk_porteføljeopgaver_og_ansvarlige(self, virksomhed_kontekst: VirksomhedsKontekst, porteføljeansvarlig_kode: str):
        logger.info("Har 1 markering med slutdato, lukker porteføljeopgaver og ansvarlige")
        try:
            self.find_og_luk_porteføljeopgaver(virksomhed_kontekst.opgaver)
            self.find_og_luk_porteføljeansvarlige(
                virksomhed_kontekst.overblik, virksomhed_kontekst.virksomhed, porteføljeansvarlig_kode
            )
        except Exception as e:
            raise WorkItemError(
                "Det var ikke muligt at lukke porteføljeopgaver og/eller fjerne porteføljeansvarlige på virksomhed"
            ) from e

    def find_porteføljeansvarlig_id(self, overblik: dict, porteføljeansvarlig_kode: str) -> str | None:
        """Id på porteføljeansvarlig, eller None hvis der ikke er præcis én."""
        logger.info("Kontrollerer om der kun er en porteføljeansvarlig")
        porteføljeansvarlige = [
            cw for cw in overblik["responsibleCaseworkers"]
            if cw["responsibilityCode"] == porteføljeansvarlig_kode
        ]
        if len(porteføljeansvarlige) == 1:
            return porteføljeansvarlige[0]["caseworkerId"]
        logger.info("For mange eller ingen porteføljeansvarlige fundet")
        return None

    @staticmethod
    def har_passiv_markering(markeringer: list[dict]) -> bool:
        return any(m["tag"]["title"] == Markering.PASSIV.name for m in markeringer)

    @staticmethod
    def har_kun_afsluttet_markering(markeringer: list[dict]) -> bool:
        return len(markeringer) == 1 and markeringer[0]["end"] is not None

    @staticmethod
    def beregn_falddato(nyeste_journalnotat: dict | None, frekvens: int) -> datetime.date:
        today = datetime.date.today()
        if nyeste_journalnotat is None:
            return today + relativedelta(months=frekvens)
        oprettet = datetime.datetime.fromisoformat(nyeste_journalnotat["createdAt"]).date()
        if oprettet + relativedelta(months=frekvens) < today:
            return today + relativedelta(months=frekvens)
        return oprettet + relativedelta(months=frekvens)

    @staticmethod
    def byg_beskrivelse(markeringstype: str, frekvens_tekst: str) -> str:
        return f"""Virksomhedsbank {markeringstype}:
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
        
    def find_taksonomi_id(self, taksonomi_gruppe: str, taksonomi_navn:str) -> str:
        taksonomier = self.momentum.taksonomier.find_taksonomi_gruppe(taksonomi_gruppe)

        porteføljeansvarlig = []
        
        for item in taksonomier.get("taxons", []):
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
        if virksomhedsoverblik["responsibleCaseworkers"]:
            sagsbehandlere = [cw for cw in virksomhedsoverblik["responsibleCaseworkers"] if cw["responsibilityCode"] != porteføljeansvarligekode]       
            self.opdater_sagsbehandlere_på_overblik(virksomhed["id"], sagsbehandlere)
        
    def find_markerninger_der_skal_have_ogpaver(self, opgaver: dict, markeringer: dict, test: bool = True) -> list[dict]:
        logger.info("Tjekker om der er markeringer der skal have opgaver")
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

        logger.info("Markeringer fundet, opretter opgaver til dem")
        # Opgaver skal have en falddato som beregnes udfra eksisterende journalnotater
        journalnotater = self.momentum.journalnotater.hent_journalnotater(virksomhed["id"]) or []

        # Find relevante journalnotater med korrekt journalTypeCode og "Porteføljeopfølgning" i titel
        relevante_journalnotater = [
            jn for jn in journalnotater
            if jn.get("journalTypeCode") == kontakt_til_virksomhedskode
            and "porteføljeopfølgning" in jn["title"].lower()
        ]
        nyeste_journalnotat = max(relevante_journalnotater, key=lambda jn: jn.get("createdAt") or "", default=None)

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

            self.momentum.opgaver.opret_opgave(
                virksomhed,
                [{"id": sagsbehandlerid}],
                self.beregn_falddato(nyeste_journalnotat, frekvens),
                f"Opgave - Porteføljeopfølgning - {markeringstype}",
                self.byg_beskrivelse(markeringstype, frekvens_tekst),
                borger_opgave=False
            )
