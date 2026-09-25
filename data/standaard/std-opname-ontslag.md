---
id: std-opname-ontslag
titel: Opname, overplaatsing en ontslag
bron: standaard
type: handleiding
module: Patiëntlogistiek
versie: "2025.1"
---
> Illustratieve testdocumentatie voor het prototype. Geen officiële ChipSoft-documentatie.

# Opname en ontslag

## Opname registreren
Een opname registreer je vanuit de opnameplanning of direct via **Nieuwe opname**. Kies specialisme, afdeling, opnamereden en behandelaar. Na het toewijzen van een bed verschijnt de patiënt op de afdelingslijst.

## Overplaatsen
Via **Overplaatsen** verplaats je de patiënt naar een ander bed of een andere afdeling. Actieve voorschriften en orders gaan mee. Controleer na overplaatsing of afdelingsgebonden ordersets nog van toepassing zijn.

## Ontslag
Ontslag verloopt in twee stappen: eerst **Ontslag voorbereiden** (voorlopige ontslagdatum, bestemming, ontslagmedicatie), daarna **Ontslag afronden**.

## Foutmelding: "Opname kan niet worden afgesloten: openstaande orders"
Deze melding verschijnt als er nog orders met status gepland of in behandeling aan de opname gekoppeld zijn. Open het ordersoverzicht, filter op de huidige opname en annuleer of rond de openstaande orders af. Labaanvragen die al zijn afgenomen kunnen niet worden geannuleerd; die moeten eerst een uitslag of annuleringsbericht van het lab krijgen.
