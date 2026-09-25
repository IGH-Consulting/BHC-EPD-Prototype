---
id: std-med-verificatie
titel: Medicatieverificatie bij opname en ontslag
bron: standaard
type: handleiding
module: Medicatie
versie: "2025.1"
---
> Illustratieve testdocumentatie voor het prototype. Geen officiële ChipSoft-documentatie.

# Medicatieverificatie

## Thuismedicatie ophalen
Bij opname haal je de thuismedicatie van de patiënt op via **Externe medicatiegegevens ophalen**. Hiervoor is toestemming van de patiënt voor gegevensuitwisseling nodig. De opgehaalde gegevens verschijnen als voorstel in het scherm medicatieverificatie en worden niet automatisch voorgeschreven.

## Verificatie vastleggen
Per middel geef je aan: voortzetten, wijzigen, tijdelijk stoppen of stoppen. Na het doorlopen van alle regels zet je de verificatiestatus op **Geverifieerd**. De status is zichtbaar in de patiëntenlijst via een icoon.

## Foutmelding: "Geen externe gegevens beschikbaar"
Deze melding verschijnt als er geen toestemming voor uitwisseling is geregistreerd, als het BSN niet geverifieerd is, of als de externe bron tijdelijk niet bereikbaar is. Controleer eerst toestemming en BSN-verificatie in de patiëntgegevens.

## Ontslagmedicatie
Bij ontslag wordt de ontslagmedicatie vastgesteld in het ontslagscherm. Het medicatieoverdrachtsdocument wordt automatisch gegenereerd en kan naar de openbare apotheek en huisarts worden verstuurd.
