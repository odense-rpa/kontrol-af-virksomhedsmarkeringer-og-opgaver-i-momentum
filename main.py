import asyncio
import logging
import sys

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential, WorkItemStatus
from momentum_client.manager import MomentumClientManager
from odk_tools.tracking import Tracker
from odk_tools.reporting import report
from proces.momentum_service import MomentumService
from proces.models import Virksomhed

momentum: MomentumClientManager
tracker: Tracker
momentum_service: MomentumService
procesnavn = "Kontrol af virksomhedsmarkeringer og opgaver i Momentum"
rapportnavn = "kontrol_af_virksomhedsmarkeringer_og_opgaver_i_momentum"

def rapporter_manuel(virksomhedsinfo: Virksomhed, bemærkning: str):
    report(
        rapportnavn,
        "Manuel",
        json={
            "P-nummer": virksomhedsinfo.pNummer,
            "Virksomhedsnavn": virksomhedsinfo.virksomhedsnavn,
            "Bemærkning": bemærkning
        }
    )


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Henter virksomheder")
    for virksomhed in momentum_service.hent_virksomheder_til_kø():
        workqueue.add_item(virksomhed.model_dump(), str(virksomhed.pNummer))


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)
    # Slår taksonomikoderne op med det samme, så processen fejler tidligt hvis de mangler
    momentum_service.porteføljeansvarlig_kode
    momentum_service.kontakt_til_virksomhed_kode

    for item in workqueue:
        with item:
            try:
                virksomhedsinfo = Virksomhed(**item.data)

                logger.info(f"Henter data for {virksomhedsinfo.virksomhedsnavn}")
                virksomhed_kontekst = momentum_service.hent_virksomhedskontekst(virksomhedsinfo.cvr, virksomhedsinfo.pNummer)

                # Inaktiv virksomhed: luk alt og gå til næste item
                if not virksomhed_kontekst.overblik["isActive"]:
                    momentum_service.luk_alt_på_inaktiv_virksomhed(virksomhed_kontekst)
                    tracker.track_task(procesnavn)
                    continue

                # Skal kun have én porteføljeansvarlig, id'et gemmes til senere
                porteføljeansvarlig_id = momentum_service.find_porteføljeansvarlig_id(
                    virksomhed_kontekst.overblik, momentum_service.porteføljeansvarlig_kode
                )
                if porteføljeansvarlig_id is None:
                    rapporter_manuel(virksomhedsinfo, "0 eller flere end 1 porteføljeansvarlige på virksomhed")
                    tracker.track_partial_task(procesnavn)
                    continue

                # Finder de markeringer som er relevante
                markeringer = momentum_service.find_relevante_markeringer(virksomhed_kontekst.markeringer, False)

                # Passiv virksomhedsbank: luk porteføljeopgaver
                if momentum_service.har_passiv_markering(markeringer):
                    momentum_service.luk_porteføljeopgaver_for_passiv(virksomhed_kontekst)
                    tracker.track_task(procesnavn)
                    continue

                # Kun 1 markering og den har en slutdato: luk porteføljeopgaver og fjern porteføljeansvarlige
                if momentum_service.har_kun_afsluttet_markering(markeringer):
                    momentum_service.luk_porteføljeopgaver_og_ansvarlige(virksomhed_kontekst, momentum_service.porteføljeansvarlig_kode)
                    tracker.track_task(procesnavn)
                    continue

                # Markeringer uden opgave skal have oprettet en
                markeringer_uden_opgave = momentum_service.find_markerninger_der_skal_have_ogpaver(virksomhed_kontekst.opgaver, markeringer, False)
                if markeringer_uden_opgave:
                    momentum_service.opret_opgaver_for_markeringer(
                        markeringer_uden_opgave,
                        virksomhed_kontekst.virksomhed,
                        momentum_service.kontakt_til_virksomhed_kode,
                        porteføljeansvarlig_id,
                    )
                    tracker.track_task(procesnavn)
                    continue

                logger.info("Alt godt, fortsætter til næste item")
                tracker.track_partial_task(procesnavn)

            except WorkItemError as e:
                # Blød fejl: teksten fra servicen bruges som bemærkning i rapporten
                logger.error(f"Error processing item: {virksomhedsinfo}. Error: {e}")
                rapporter_manuel(virksomhedsinfo, str(e))
                tracker.track_partial_task(procesnavn)
                item.fail(str(e))
            except ValueError as e:
                logger.info(f"Forkert eller ingen værdig fået på item: {item.data}, fejl: {e}")
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
