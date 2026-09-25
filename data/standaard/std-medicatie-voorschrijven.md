---
id: std-med-voorschrijven
titel: Medicatie voorschrijven en medicatiebewaking
bron: standaard
type: handleiding
module: Medicatie
versie: "2025.1"
---
> Illustratieve testdocumentatie voor het prototype. Geen officiële ChipSoft-documentatie.

# Medicatie voorschrijven

## Een nieuw medicatievoorschrift aanmaken
Open het dossier van de patiënt en kies in het medicatieoverzicht voor **Nieuw voorschrift**. Zoek het geneesmiddel op stofnaam, merknaam of via een favoriet. Vul dosering, frequentie, toedieningsweg en startmoment in. Bij een zo-nodig voorschrift vul je ook de indicatie en de maximale dosering per 24 uur in. Het voorschrift wordt pas actief na **Accorderen**.

## Medicatiebewaking
Tijdens het voorschrijven controleert de medicatiebewaking automatisch op interacties, contra-indicaties, dubbelmedicatie, allergieën en overschrijding van doseringsregels. Signalen worden getoond in een pop-up met een ernstniveau (informatief, waarschuwing, ernstig).

Een ernstig signaal kan alleen worden overruled met een **reden van overrulen**. Vanaf versie 2025.1 is het invullen van een reden verplicht voor alle signalen met niveau waarschuwing of hoger. Overrulede signalen zijn zichtbaar voor de apotheek in het werkoverzicht medicatiebewaking.

## Veelvoorkomende melding: "Doseringsregel overschreden"
Deze melding verschijnt wanneer de ingevoerde dosis hoger is dan de maximale dosering uit de doseringsregels, vaak door een verkeerde eenheid (mg in plaats van microgram) of een onjuist patiëntgewicht. Controleer eerst het actuele gewicht in het dossier; doseringsregels voor kinderen en nierfunctie rekenen met gewicht en eGFR. Is het gewicht verouderd, werk dit bij en herbereken het voorschrift.

## Voorschrift wijzigen of stoppen
Een actief voorschrift wijzig je via **Wijzigen**; er ontstaat dan een nieuwe versie en de oude wordt gestopt. Stoppen doe je via **Stoppen** met een stopreden. Gestopte medicatie verdwijnt na de ingestelde periode van de toedienlijst.
