# Task Assigniator

Et lille Python-værktøj til at fordele opgaver tilfældigt mellem studerende ud fra en CSV-fil.

Scriptet:
- læser studerende fra en semikolon-separeret CSV,
- læser opgavefiler fra en mappe,
- fordeler opgaver i runder (alle opgaver bruges én gang, før genbrug),
- kan lave nytildeling til reeksamen ud fra den oprindelige audit-fil,
- genererer en HTML-oversigt,
- opretter en audit-log med signatur,
- kan verificere audit-filen bagefter.

## Krav

- Python 3.9+ (anbefalet)
- Ingen eksterne pakker kræves

Til web-versionen:
- Flask og gunicorn (installeres via requirements.txt)
- Docker (hvis du vil kore i container)

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

Du kan også verificere en bestemt audit-fil direkte, f.eks. ved nytildeling:

```powershell
python task-assigniator.py verify tasks\reassigned_tasks_audit.json
```

### 3) Tildel nye opgaver til reeksamen

Brug en ny CSV med de studerende, der skal have en ny opgave, samt audit-filen fra den oprindelige tildeling:

```powershell
python task-assigniator.py reassign reexam_students.csv tasks tasks\assigned_tasks_audit.json
```

I denne tilstand:
- opgavepuljen skal være den samme som ved den oprindelige tildeling,
- audit-filen fra første kørsel verificeres først,
- hver studerende får en ny opgave fra samme pulje,
- ingen studerende kan få den samme opgave, som de allerede har haft.

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

Ved `reassign` oprettes i stedet:

- reassigned_tasks.html
	- HTML-tabel med nytildelingen
- reassigned_tasks_audit.json
	- audit-oplysninger om input, output, den nye tildeling og reference til den oprindelige audit-fil
- reassigned_tasks_audit.sig
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

## Web-app (Flask)

Der er tilfojet en Flask-app i filen `app.py`, som genbruger den eksisterende logik i `task-assigniator.py`.

Web-app'en giver dig:
- upload af CSV til `assign` eller `reassign`
- upload af original audit-fil ved `reassign`
- valgfri upload af tasks som `.zip` (erstatter nuvaerende taskfiler)
- download af genererede outputfiler direkte i browseren

### Kør lokalt

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:TASK_ASSIGNMENT_AUDIT_KEY = "din-hemmelige-noegle"
python app.py
```

Åbn herefter:

```text
http://localhost:8000
```

Generer filer via formularen og hent dem via Download-sektionen.

### Upload af tasks som ZIP (sikkerhed)

Ja, det kan gores sikkert, hvis man validerer ZIP-indholdet. Web-app'en validerer nu:
- filtypen skal vaere `.zip`
- max ZIP-storrelse: 20 MB
- max antal filer: 500
- blokerer usikre stier (fx `../` og absolute stier)
- gemmer kun filer med sikre filnavne
- overskriver eksisterende taskfiler (ikke output/audit-filer)

Det reducerer risikoen markant. Som ekstra praksis bor du stadig kun acceptere ZIP-filer fra kilder, du stoler pa.

## Kør i Docker container

Byg image:

```powershell
docker build -t task-assigniator-web .
```

Start container:

```powershell
docker run --rm -p 8000:8000 -e TASK_ASSIGNMENT_AUDIT_KEY="din-hemmelige-noegle" task-assigniator-web
```

Åbn:

```text
http://localhost:8000
```

Bemærk:
- Appen forventer en `tasks/` mappe i containeren med opgavefiler.
- Download links henter filer fra `tasks/` (fx `assigned_tasks.html`, `assigned_tasks_audit.json`, `assigned_tasks_audit.sig`).
