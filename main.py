import asyncio
import logging
import sys

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential, WorkItemStatus
from momentum_client.manager import MomentumClientManager
from odk_tools.tracking import Tracker
from odk_tools.reporting import report
from proces.momentum_service import MomentumService, Markering, TestMarkering
from proces.models import Virksomhed

momentum: MomentumClientManager
tracker: Tracker
porteføljeansvarligekode: str
kontakt_til_virksomhed_kode: str
porteføljeansvarliges_id: str
procesnavn = "Kontrol af virksomhedsmarkeringer og opgaver i Momentum"

async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Henter virksomheder")
    virksomheder = momentum_service.hent_virksomheder_med_markeringer()

    if virksomheder is not None:
        for virksomhed in virksomheder['data']:
            virksomhed_obj = Virksomhed(
                cvr=virksomhed['cvr'],
                pNummer=virksomhed['pNumber'], 
                virksomhedsnavn=virksomhed['displayName'], 
            )
            workqueue.add_item(virksomhed_obj.model_dump(), str(virksomhed_obj.pNummer))        


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)
    # Id for porteføljeansvarlige findes, Porteføljeansvarlig
    # Porteføljeansvarlig findes ikke i EDU, Støtte-kontaktperson kan anvendes til EDU
    porteføljeansvarligekode = momentum_service.find_taksonomi_id("CASEWORKER_RESPONSIBILITY", "Porteføljeansvarlig")
    kontakt_til_virksomhed_kode = momentum_service.find_taksonomi_id("JOURNAL_TYPES_COMPANY", "Kontakt til virksomhed")
    bemærkning: str

    for item in workqueue:
        with item:
            try:
                bemærkning = ""
                virksomhedsinfo = Virksomhed(**item.data)
                # Hent virksomhed
                logger.info("Henter virksomhed")
                virksomhed = momentum.virksomheder.hent_virksomhed_med_cvr_og_pnummer(cvr=virksomhedsinfo.cvr, pNummer=virksomhedsinfo.pNummer)

                if virksomhed is None:
                    raise ValueError("Virksomhed ikke fundet i Momentum")
                
                # Hent virksomhedsoverblik 
                logger.info(f"Henter virksomhedsoverblikket for {virksomhedsinfo.virksomhedsnavn}")
                virksomhedsoverblik = momentum.virksomheder.hent_en_virksomheds_overblik(virksomhed["id"])

                if virksomhedsoverblik is None:
                    raise ValueError("Kunne ikke hente overblik")
                
                # Henter markeringer
                logger.info("Henter markeringer på virksomhed")
                markeringer = momentum.markeringer.hent_markeringer(virksomhed["id"])
                if markeringer is None:
                    raise ValueError("Kunne ikke hente markeringer")
                
                logger.info("Henter opgaver på virksomhed")
                opgaver = momentum.opgaver.hent_opgaver_på_virksomhed(virksomhed["id"])
                
                # Kontrol af om virksomhed er aktiv
                if virksomhedsoverblik["isActive"] == False:
                    # Ikke aktiv, vi lukker alt og går til næste item
                    logger.info("Virkomhed ikke aktiv, markeringer, opgaver lukkes og fjerner sagsbehandler fra overblik")
                    try:
                        momentum_service.luk_markgeringer(markeringer)
                        momentum_service.luk_opgaver(opgaver)
                        momentum_service.opdater_sagsbehandlere_på_overblik(virksomhed["id"], [])
                    except Exception:
                        bemærkning = "Ikke muligt at lukke alt på ikke aktiv virksomhed"
                        raise WorkItemError("Fejl ved lukning af markeringer, opgaver og sagshandlere(overblik)")
                    logger.info("Alt lukket på virksomhed, forsætter til næste item")
                    tracker.track_task(procesnavn)                           
                    continue

                # Skal kun have en porteføljeansvarlige, id'et gemmes til senere
                logger.info("Kontrollerer om der kun er en porteføljeansvarlige")
                porteføljeansvarlige = [cw for cw in virksomhedsoverblik["responsibleCaseworkers"] if cw["responsibilityCode"] == porteføljeansvarligekode]
                if len(porteføljeansvarlige) == 1:
                    logger.info("En fundet fundet, gemmer id")
                    porteføljeansvarliges_id = porteføljeansvarlige[0]["caseworkerId"]
                else:
                    logger.info("For mange eller ingen porteføljeansvarlige fundet, sender til rapport og forsætter til næste item")
                    report(
                            "kontrol_af_virksomhedsmarkeringer_og_opgaver_i_momentum",
                            "Manuel",
                            json={
                                "P-nummer": virksomhedsinfo.pNummer,
                                "Virksomhedsnavn": virksomhedsinfo.virksomhedsnavn,
                                "Bemærkning": "0 eller flere porteføljeansvarlige på virksomhed"
                            }
                        )
                    tracker.track_partial_task(procesnavn)   
                    continue
                                               
                # Finder markeringer som relevante
                markeringer = momentum_service.find_relevante_markeringer(markeringer, False)

                if any(
                    markering["tag"]["title"] == "Passiv - Virksomhedsbank"
                    for markering in markeringer
                ):
                    # Fjern porteføljeansvarlige og luk opgaver her
                    logger.info("Passiv virksomhedsbank, lukker porteføljeopgaver")
                    try:
                        momentum_service.find_og_luk_porteføljeopgaver(opgaver)
                    except Exception:
                        logger.info("Det var ikke muligt at lukke opgaver, sender til manuel")
                        bemærkning = "Passiv - virksomhedsbank, det var ikke muligt at lukke porteføljeopgaver"
                        raise WorkItemError("Fejl ved lukning af porteføljeopgaver")
                    logger.info("Portføljeopgaver lukket, forsætter til næste item")
                    tracker.track_task(procesnavn)   
                    continue

                # Har 1 markeringen med en slutdato, skal opgaver med "porteføljeopfølgning" i titlen lukkes, og porteføljeansvarlige fjernes              
                if len(markeringer) == 1 and markeringer[0]["end"] is not None:
                    
                    logger.info("Har 1 markering med slutdato, forsøger at lukker porteføljeopgaver og ansvarlige")
                    try:
                        momentum_service.find_og_luk_porteføljeopgaver(opgaver)
                        momentum_service.find_og_luk_porteføljeansvarlige(virksomhedsoverblik, virksomhed, porteføljeansvarligekode)
                    except:
                        logger.info("Det var ikke muligt at lukke opgaver og fjerne ansvarlige, sender til manuel")
                        bemærkning = "Det var ikke muligt at lukke porteføljeopgaver og/eller fjerne porteføljeansvarlige på virksomhed"
                        raise WorkItemError("Fejl ved lukning af porteføljeopgaver, og fjernelse af porteføljeansvarlige")
                    logger.info("Porteføljeopgaver lukket og ansvarlige fjernet, forsætter til næste item")
                    tracker.track_task(procesnavn)                     
                    continue

                logger.info("Tjekker om der er markeringer der skal have opgaver")                
                markeringer = momentum_service.find_markerninger_der_skal_have_ogpaver(opgaver, markeringer, False)
                
                if markeringer is not None and len(markeringer) > 0:
                    logger.info("Markeringer fundet, opretter opgaver til dem")
                    momentum_service.opret_opgaver_for_markeringer(markeringer, virksomhed, kontakt_til_virksomhed_kode, porteføljeansvarliges_id)
                    logger.info("Opgave/opgaver oprettet på virksomheden, forsætter til næste item")
                    tracker.track_task(procesnavn)
                    continue
                
                logger.info("Alt godt, forsætter til næste item")
                tracker.track_partial_task(procesnavn)
                        
                
            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {virksomhedsinfo}. Error: {e}")
                logger.info("Fejl sendes til rapport")
                report(
                            "kontrol_af_virksomhedsmarkeringer_og_opgaver_i_momentum",
                            "Manuel",
                            json={
                                "P-nummer": virksomhedsinfo.pNummer,
                                "Virksomhedsnavn": virksomhedsinfo.virksomhedsnavn,
                                "Bemærkning": bemærkning
                            }
                        )
                tracker.track_partial_task(procesnavn)
                item.fail(str(e))
            except ValueError as e:
                logger.info(f"Forkert eller ingen værdig fået på item: {virksomhedsinfo}, fejl: {e}")
                item.fail(str(e))


if __name__ == "__main__":
    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # Initialize external systems for automation here..
    tracker_credentials = Credential.get_credential("Odense SQL Server")
    tracker = Tracker(
        username=tracker_credentials.username,
        password=tracker_credentials.password
    )
    
    momentum_credential = Credential.get_credential("Momentum - produktion")
    momentum = MomentumClientManager(
        base_url=momentum_credential.data["base_url"],
        client_id=momentum_credential.username,
        client_secret=momentum_credential.password,
        api_key=momentum_credential.data["api_key"],
        resource=momentum_credential.data["resource"],
    )

    momentum_service = MomentumService(
        momentum,
        tracker
    )

    # Queue management
    if "--queue" in sys.argv:
        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
