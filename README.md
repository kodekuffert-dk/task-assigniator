# Task Assigniator

Et lille Python-værktøj til at fordele opgaver tilfældigt mellem studerende ud fra en CSV-fil.

Scriptet:
- læser studerende fra en semikolon-separeret CSV,
- læser opgavefiler fra en mappe,
- fordeler opgaver i runder (alle opgaver bruges én gang, før genbrug),
- genererer en HTML-oversigt,
- opretter en audit-log med signatur,
- kan verificere audit-filen bagefter.

## Krav

- Python 3.9+ (anbefalet)
- Ingen eksterne pakker kræves

## Forventet struktur

Eksempel:

```text
project/
	task-assigniator.py
	students.csv
	tasks/
		opgave-1.md
		opgave-2.md
		opgave-3.md
```

Bemærk:
- Alle filer i opgavemappen betragtes som opgaver, undtagen:
	- assigned_tasks.md
	- assigned_tasks.html
	- assigned_tasks_audit.json

## Miljøvariabel (påkrævet)

Før kørsel skal du sætte en nøgle til audit-signering:

PowerShell:

```powershell
$env:TASK_ASSIGNMENT_AUDIT_KEY = "din-hemmelige-noegle"
```

CMD:

```cmd
set TASK_ASSIGNMENT_AUDIT_KEY=din-hemmelige-noegle
```

## CSV-format

CSV læses med semikolon som separator.

Header-række forventes. Scriptet forsøger automatisk at finde kolonner for nummer og navn.

Typiske overskrifter for nummer:
- nummer
- studentnr
- studienummer
- nr
- id
- number

Typiske overskrifter for navn:
- navn
- name
- fulde navn
- full name

Hvis headers ikke matcher, bruges fallback:
- kolonne 1 som nummer
- kolonne 2 som navn (hvis den findes)

Eksempel:

```csv
nummer;navn
12345;Anna Jensen
12346;Jonas Nielsen
```

## Brug

### 1) Tildel opgaver

```powershell
python task-assigniator.py assign students.csv tasks
```

Bagudkompatibel form virker også:

```powershell
python task-assigniator.py students.csv tasks
```

### 2) Verificer audit

```powershell
python task-assigniator.py verify tasks
```

Ved succes returneres en OK-meddelelse. Ved fejl returneres FAILED og exit-kode 2.

## Output

Scriptet opretter følgende i opgavemappen:

- assigned_tasks.html
	- HTML-tabel med Nummer, Navn og Opgave
- assigned_tasks_audit.json
	- audit-oplysninger om input, output og tildelinger
	- indeholder HMAC-SHA256 signaturfelt
- assigned_tasks_audit.sig
	- signaturen i separat fil

## Sikkerhed og sporbarhed

- Studerendes nummer gemmes som SHA256-hash i audit-filen.
- Audit-payload signeres med HMAC-SHA256 med nøglen fra TASK_ASSIGNMENT_AUDIT_KEY.
- verify-kommandoen validerer både signatur i JSON og evt. .sig-fil.

## Fejl du kan møde

- Task directory does not exist
	- opgavemappen findes ikke
- No task files found in directory
	- opgavemappen er tom (efter filtrering)
- Input CSV must contain a header and at least one student row
	- CSV mangler data
- Missing audit key. Set environment variable TASK_ASSIGNMENT_AUDIT_KEY.
	- miljøvariablen er ikke sat

## Hurtig test

1. Opret en lille students.csv med 2-3 studerende.
2. Opret en tasks-mappe med et par opgavefiler.
3. Sæt TASK_ASSIGNMENT_AUDIT_KEY.
4. Kør assign.
5. Kør verify.

Hvis verify er OK, er audit-filen ikke blevet ændret siden generering.
