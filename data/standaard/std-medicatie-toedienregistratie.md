---
id: std-med-toedienen
titel: Toedienregistratie en de toedienlijst
bron: standaard
type: handleiding
module: Medicatie
versie: "2025.1"
---
> Illustratieve testdocumentatie voor het prototype. Geen officiële ChipSoft-documentatie.

# Toedienregistratie

## De toedienlijst
De toedienlijst toont per patiënt alle geplande toedieningen op basis van de actieve voorschriften. Toedieningen hebben een status: gepland, toegediend, niet toegediend of te laat. Te late toedieningen worden na het ingestelde tijdvenster rood gemarkeerd.

## Toediening registreren met barcode
Scan eerst het polsbandje van de patiënt en daarna de barcode op de verpakking van het geneesmiddel. Het systeem controleert of patiënt, middel, dosis en tijdstip overeenkomen met het voorschrift. Bij een afwijking verschijnt een waarschuwing en moet de toediening bewust worden bevestigd of afgebroken.

## Foutmelding: "Barcode niet herkend"
Deze melding betekent dat de gescande code niet gekoppeld is aan een artikel in het geneesmiddelenbestand. Mogelijke oorzaken: een nieuwe verpakking of leverancier die nog niet in het artikelbestand staat, een beschadigde barcode of een scanner die in de verkeerde modus staat. Registreer de toediening handmatig met de reden "barcode niet herkend" en meld het artikel bij de apotheek zodat het artikelbestand wordt bijgewerkt.

## Niet toegediend registreren
Wordt een geplande toediening niet gegeven, registreer dan **Niet toegediend** met een reden (bijvoorbeeld patiënt weigert, patiënt nuchter, middel niet op voorraad). Laat een geplande toediening niet open staan; open toedieningen tellen mee in de rapportage te late toedieningen.

## Dubbele controle
Voor geneesmiddelen die in het geneesmiddelenbestand als hoog-risico zijn gekenmerkt, vraagt het systeem om een **dubbele controle**. Een tweede zorgverlener bevestigt met eigen inloggegevens. Welke middelen hieronder vallen, wordt lokaal ingericht.
