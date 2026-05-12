# TRANSFER DOCUMENTARE LUCRARE DE LICENȚĂ - TORII

**Data:** 11 mai 2026
**Destinație:** Claude Web Interface pentru continuare pe alt laptop
**Proiect:** Torii - Orchestrare CI/CD Orientată pe Evenimente

---

## SECȚIUNEA 1: INFORMAȚII ESENȚIALE PENTRU CONTINUARE

### 1.1 Descrierea Proiectului

**Titlul lucrării:**
*Orchestrare CI/CD Orientată pe Evenimente: Fuziune Speculativă, Pipeline-uri Dependente și Abstractizarea Configurației*

**Autor:** Catalin Ionescu
**Tip:** Lucrare de Diplomă/Licență
**Limbă:** Română
**Status:** În dezvoltare - Faza 2 (Documentare academică)

### 1.2 Obiective Principale

1. Proiectare și implementare a unui sistem CI/CD complet orientat pe evenimente
2. Integrare cu Gerrit pentru code review
3. Implementare a fuziunilor speculative (pre-merge testing)
4. Gestionare sofisticată a dependențelor între pipeline-uri
5. Documentare academică comprehensivă

### 1.3 Starea Actuală a Lucrării

**Faza 1 - ✅ COMPLETATĂ: Implementare Scheduler**
- ✅ Refactoring complet din async (FastAPI) la threading-sync
- ✅ Integrare cu GerritEventProcessor și GerritRestConnection existente
- ✅ Implementare sistem Redis pentru stocarea stărilor
- ✅ Implementare verificare approvals
- ✅ Implementare pipeline managers (Check/Gate/Report)
- ✅ Curățare cod (îndepărtare emoji-uri, simplificare comentarii)
- ✅ Documentare SCHEDULER_FLOW.md (300+ linii)

**Faza 2 - ⏳ ÎN PROGRES: Documentare Academică (CAPITOLUL 1)**
- ✅ 1.1 Motivația alegerii lucrării (13 linii)
- ⏳ 1.2 Obiectivele generale ale lucrării (VIITOR)
- ⏳ 1.3 Relevanța științifică și noutate (VIITOR)
- ⏳ 1.4 Strategia cercetării și metodologie (VIITOR)
- ⏳ 1.5 Instrumente și infrastructură (VIITOR)
- ⏳ 1.6 Limitele și delimitările (VIITOR)

**Faze Viitoare - ❌ NU S-A INIȚIAT:**
- Capitolul 2: Stadiul Actual și Fundamentele Teoretice
- Capitolul 3: Arhitectura Globală Torii
- Capitolul 4: Gestionarea Modificărilor (Merger)
- Capitolul 5: Planificarea Sarcinilor (Scheduler Detaliat)
- Capitolul 6: Subsistemul Executor/Worker
- Capitolul 7: Platforma Web UI
- Capitolul 8: Evaluarea Performanțelor

---

## SECȚIUNEA 2: TABEL DE CONȚINUT COMPLET (CUPRINS)

### Capitolul 1: Introducere (Memoriu Tehnico-Justificativ)

```
1.1 Motivația alegerii lucrării ....................................... ✅ COMPLETAT
1.2 Obiectivele generale ale lucrării .................................
1.3 Relevanța științifică și gradul de noutate .......................
1.4 Strategia cercetării și metodologia folosită .....................
1.5 Instrumente și infrastructură ....................................
1.6 Limitele și delimitările lucrării ................................
```

### Capitolul 2: Stadiul Actual și Fundamentele Teoretice

```
2.1 Deficiențe și limitări în platformele tradiționale de integrare
2.2 Platformele predominante pe piață
    2.2.1 Jenkins
    2.2.2 GitLab CI/CD
    2.2.3 GitHub Actions
2.3 Paradigma sistemelor distribuite de evaluare a codului via Gerrit
2.4 Arhitecturi orientate pe evenimente (Event-Driven)
    2.4.1 Caracteristicile și beneficiile arhitecturilor event-driven
    2.4.2 Brokerajul de mesaje prin Apache Kafka
2.5 Fuziuni speculative și stări predicate în VCS
```

### Capitolul 3: Arhitectura Globală a Sistemului Torii

```
3.1 Topologia microserviciilor și orchestrarea containerizată
    3.1.1 Decompoziția funcțională în module
    3.1.2 Comunicația inter-servicii
3.2 Ciclul de viață al unui eveniment din Gerrit
    3.2.1 Ingestia și normalizarea fluxurilor de date
    3.2.2 Rutarea și prioritizarea evenimentelor
3.3 Paradigma "Configuration as Code"
    3.3.1 Definiția și avantajele abstractizării declarative
    3.3.2 Structura fișierelor YAML (jobs.yaml, pipelines.yaml, projects.yaml)
```

### Capitolul 4: Gestionarea Modificărilor și Evaluarea Stărilor Speculative (Modulul Merger)

```
4.1 Conceptul de integrare speculativă
    4.1.1 Definirea stărilor speculative și a matricei de testare
    4.1.2 Abstractizarea operațiunilor de versionare
4.2 Implementarea Git Merger
    4.2.1 Arhitectura internă a modulului merger
    4.2.2 Operații atomice de fuziune și ștergere
    4.2.3 Gestionarea conflictelor și racei conditions
4.3 Asigurarea proprietății de invarianță a stării (State Hygiene)
4.4 Topologii de flux (Pipeline Managers)
```

### Capitolul 5: Planificarea și Distribuția Sarcinilor (Modulul Scheduler)

```
5.1 Modelarea matematică a job-urilor
5.2 Alocarea și prioritizarea resurselor
5.3 Prelucrarea cererilor concurente
```

### Capitolul 6: Subsistemul Izolat de Execuție (Worker/Executor)

```
6.1 Principiile izolării spațiului de execuție
6.2 Captarea și procesarea log-urilor
6.3 Sincronizarea bidirecțională a statusului
```

### Capitolul 7: Componenta de Vizualizare și Sincronizare (Platforma Web UI)

```
7.1 Arhitectura frontend și decuplarea nivelului de prezentare
7.2 Integrarea cu backend și polling/socket logic
7.3 Trasabilitatea și maparea stării în timp real
```

### Capitolul 8: Evaluarea Performanțelor și Validarea Arhitecturii

```
8.1 Scenarii de testare izolate
8.2 Scenarii de testare la sarcină constantă
8.3 Analiza consumului de resurse și latențelor de rețea
```

---

## SECȚIUNEA 3: SECȚIUNI SCRISE COMPLETE

### 1.1 Motivația Alegerii Lucrării

Industria dezvoltării software moderne se confruntă cu o provocare fundamentală: volumul exponențial de cod generat zilnic necesită mecanisme robuste de validare și asigurare a calității. Conform rapoartelor sectorului, viteza de livrare a funcționalităților s-a accelerat semnificativ în ultimul deceniu, însă calitatea și fiabilitatea codului nu au evoluat cu aceeași progresie. Codul untested, integrat necontrolat în sisteme în producție, introduce bugs critice, vulnerabilități de securitate și poate provoca defectări catastrofale cu impact asupra milioane de utilizatori.

Situația devine mai critică în contextul microserviciilor, unde o singură eroare într-o componentă poate declanșa efecte în cascadă în întregul sistem. Platformele tradiționale de integrare continuă, cum ar fi Jenkins sau GitLab CI/CD, prezintă limitări arhitecturale: lipsa unei paradigme cu adevărat orientate pe evenimente, lipsa abstractizării configurației și imposibilitatea de a implementa fuziuni speculative pentru testarea într-o stare virtuală a codului înainte de integrare.

Torii propune o reimaginare a procesului de integrare continuă prin introducerea unei arhitecturi complet orientate pe evenimente, coupled cu mecanisme avansate de testare speculativă și gestionare sofisticată a dependențelor pipeline. Lucrarea prezintă un sistem robust pentru evaluarea automată, izolată și distribuită a modificărilor de cod, permițând unei organizații să livreze software de înaltă calitate cu încredere și viteză, reducând semnificativ riscul introducerii regresiilor în producție.

---

## SECȚIUNEA 4: DOCUMENTARE ARHITECTURĂ - FLOW SCHEDULER

### 4.1 Descriere de Ansamblu

Torii scheduler este un sistem de procesare a evenimentelor bazat pe threading care monitorizează schimbările din Gerrit și le rutează prin pipeline-uri CI/CD configurabile (Check, Gate, Report). Schimbările trec printr-o serie de componente care îmbogățesc evenimentele, verifică aprobările și gestionează execuția pipeline-urilor bazată pe cozi.

### 4.2 Componente Principale

#### 1. Kafka Consumer (`KafkaConnection`)
- **Rol:** Extrage evenimentele brute din Gerrit din topic-ul Kafka `gerrit-stream-events`
- **Tip:** `threading.Thread` (daemon)
- **Output:** Pune evenimentele JSON brute în `event_queue`
- **Ciclu de viață:** Se execută continuu, polling Kafka pentru noi evenimente

#### 2. Event Enricher (`GerritEventProcessor`)
- **Rol:** Îmbogățește evenimentele Kafka brute cu detaliile complete ale schimbării din Gerrit API
- **Tip:** `threading.Thread` (daemon)
- **Input:** Evenimente brute din `KafkaConnection.event_queue`
- **Proces:**
  1. Parseaza JSON brut din Kafka
  2. Extrage change ID
  3. Apelează `GerritRestConnection.getChange(change_id)` pentru a obține detaliile complete
  4. Creează obiectul `GerritTriggerEvent` cu date îmbogățite
  5. Dispozitiv către scheduler via `gerrit_connection.sched.addEvent(event)`
- **Output:** Obiecte `GerritTriggerEvent` îmbogățite trimise la SchedulerQueue

#### 3. Scheduler Queue (`SchedulerQueue`)
- **Rol:** Orchestratorul principal care ia decizii de rutare și gestionează pipeline-urile
- **Tip:** `threading.Thread` (daemon)
- **Input:** Evenimente îmbogățite din `GerritEventProcessor` via metoda `addEvent()`
- **Componente interne:**
  - `event_queue`: `queue.Queue` nemarginită pentru buffering-ul evenimentelor primite
  - `pipelines`: Dict mapând ID-uri pipeline la instanțe pipeline manager
  - `config`: `ConfigurationLoader` pentru configurația bazată pe YAML
  - `approval_verifier`: Verifică dacă schimbarea are labelurile necesare
  - `redis`: Client `TorriRedis` pentru stocarea persistentă a stării

#### 4. Redis State Store (`TorriRedis`)
- **Rol:** Persistează starea schimbării, cozile pipeline-urilor, blocaje și tracking-ul compilării
- **Tip:** Wrapper Redis sincron simplu
- **Thread-Safe:** Da (operațiile Redis sunt atomice)
- **Modele de chei:**
  - `torri:change:{change_id}:state` - Starea curentă a unei schimbări
  - `torri:pipeline:{pipeline_id}:queue` - Coada FIFO a ID-urilor schimbării
  - `torri:pipeline:{pipeline_id}:window` - Starea ferestrei de concurență
  - `torri:buildset:{buildset_id}:state` - Tracking-ul tentativei de execuție a job-urilor
  - `torri:lock:pipeline:{pipeline_id}` - Blocaj distribuit pentru acces la pipeline
  - `torri:lock:global:merge` - Blocaj global de fuziune

#### 5. Pipeline Managers (`CheckPipeline`, `GatePipeline`, `ReportPipeline`)
- **Rol:** Gestionează cozire și concurență pentru fiecare tip de pipeline
- **Stocarea:** În Redis, încarcate în memorie pentru acces rapid
- **Responsabilități:**
  - Înlocuiesc schimbări (adaugă la coada Redis)
  - Dezactualiza schimbări (pop din coada Redis)
  - Urmăresc dimensiunea ferestrei (câte schimbări pot rula concurent)
  - Urmăresc numărul activ (câte rulează în prezent)
  - Gestionează seturi de construcție (tentative de execuție a job-urilor)

### 4.3 Ciclul de Viață al Prelucrării Schimbării

#### Faza 1: Recepția Evenimentelor
```
1. Topic Kafka: gerrit-stream-events primește eveniment nou
2. Thread KafkaConnection sondează Kafka
3. JSON brut pus în KafkaConnection.event_queue
4. GerritEventProcessor citește din event_queue
5. Eveniment despachetat la GerritEventProcessor._on_event(raw_data)
```

#### Faza 2: Îmbogățirea Evenimentelor
```
1. Extrage numărul schimbării din evenimentul brut
2. Apelează gerrit_connection.getChange(change_number)
3. GerritRestConnection prelucrează detaliile complete ale schimbării din Gerrit API
4. Răspunsul țintuit în cache LRU (max 10k schimbări)
5. Creează GerritTriggerEvent cu date îmbogățite
6. Apelează gerrit_connection.sched.addEvent(enriched_event)
```

**Rezultat:** Obiect GerritTriggerEvent cu detalii complete, inclusiv labeluri curente

#### Faza 3: Verificarea Aprobărilor
```
1. Eveniment recepționat în SchedulerQueue.addEvent()
2. Pus în event_queue intern (buffering asincron)
3. SchedulerQueue.run() loop recuperează eveniment cu timeout 1s
4. Apelează approval_verifier.verify_project_approval(change_id, project_name)
5. Încarcă config proiect: care labeluri de aprobare sunt necesare?
6. Extrage labelurile curente din obiectul schimbării
7. Compară: dacă orice label necesar < valoare necesară, NEGA
8. Dacă aprobat, procedează la rutarea pe pipeline
9. Dacă nu aprobat, postează mesaj la Gerrit și SARE schimbarea
```

**Exemplu de verificare a aprobării:**
```yaml
# projects.yaml
my-project:
  approval_labels:
    - name: "Code-Review"
      value: 1          # Necesită +1 de la revisor
    - name: "Verified"
      value: 1          # Necesită +1 de la CI (gate pipeline)
```

**Logică de decizie:**
- Dacă Code-Review < +1: NU APROBAT → Salt la mesaj Gerrit
- Dacă Code-Review >= +1 ȘI Verified < +1: APROBAT doar pentru pipeline Check
- Dacă amândoi >= +1: APROBAT pentru toate pipeline-urile (inclusiv Gate)

#### Faza 4: Rutarea pe Pipeline și Cozire
```
1. Obține lista de pipeline-uri din config proiect
2. Pentru fiecare pipeline (check, gate, report):
   a. Apelează approval_verifier.verify_pipeline_approval(change_id, pipeline_id)
   b. Dacă aprobat:
      - Apelează pipeline.enqueue_change(change_id)
      - Pipeline adaugă la coada Redis: RPUSH torri:pipeline:{id}:queue change_id
      - Returnează poziția în coadă (1-based)
   c. Dacă nu aprobat: Logare și salt
3. Creează ChangeInfoModel cu state=QUEUED
4. Salvează change_state în Redis
5. Logare: "Change {id} queued to pipelines: [check, gate]"
```

**Exemplu de rezultat în Redis:**
```
LRANGE torri:pipeline:check:queue 0 -1
→ ["12345", "12344", "12343"]  # Poziția 1 pentru change 12345

SET torri:change:12345:state {
  "change_id": "12345",
  "project_name": "my-project",
  "branch": "main",
  "state": "queued",
  "buildsets": [],
  "queue_position": 1,
  "created_at": "2026-05-11T10:30:45.123456"
}
```

#### Faza 5: Prelucrarea Pipeline (Viitor - Nu Este Implementat Încă)
```
DEQUEUE LOOP (ar rula periodic):
1. Pentru fiecare pipeline:
   a. Verifica fereastra: dacă active_count < window_size:
      - Poate dezactualiza și începe prelucrarea
   b. Apelează pipeline.dequeue_change()
      - LPOP torri:pipeline:{id}:queue
      - Obține primul change ID din coadă
   c. Creează BuildSet (tentativa de execuție a job-ului)
   d. Dispozitiv de job-uri la executor
   e. Sondaj pentru completare job
   f. Actualizare fereastră pipeline (decrementare active_count la completare)
   g. Dacă succes Gate pipeline + pipeline.should_merge():
      - Declanșează merger pentru fuziunea schimbării în ramura de bază
```

### 4.4 Configurație

#### projects.yaml
```yaml
my-project:
  merge_strategy: merge              # merge | rebase | squash | cherry-pick
  approval_labels:
    - name: "Code-Review"
      value: 1                        # Min +1 necesar
      blocking: false
  pipelines:
    - check                           # Rută la pipeline check
    - gate                            # Rută la pipeline gate

another-project:
  merge_strategy: squash
  approval_labels:
    - name: "Code-Review"
      value: 2                        # Min +2 (mai strict)
  pipelines:
    - check
    - gate
    - report
```

#### pipelines.yaml
```yaml
check:
  name: "Verification Pipeline"
  type: check                         # Nu poate declanșa fuziune
  window_size: 5                      # Până la 5 schimbări în paralel
  jobs:
    - lint
    - unit-tests
    - code-coverage

gate:
  name: "Merge Gating Pipeline"
  type: gate                          # Poate declanșa fuziune
  window_size: 1                      # Prelucrare serială (una câte una)
  jobs:
    - integration-tests
    - security-scan

report:
  name: "Post-Merge Report"
  type: report                        # După fuziune
  window_size: 10
  jobs:
    - generate-metrics
```

---

## SECȚIUNEA 5: STRUCTURA CODULUI SCHEDULER

### 5.1 Locație și Fișiere

Toate fișierele scheduler sunt localizate în: `/home/cata/Desktop/Torii/microservices/Torri/src/torri/scheduler/`

### 5.2 Fișiere Implementate

**1. `__init__.py` (30 linii)**
- Export pachete
- Importații principale din modulele scheduler

**2. `scheduler_queue.py` (~160 linii)**
- Clasa principală: `SchedulerQueue(threading.Thread)`
- Metodă principală: `run()` - event loop principal
- Metodă intrare: `addEvent(event)` - numită de GerritEventProcessor
- Inițializare: `_initialize_pipelines()`
- Procesare: `_process_event(event)`

**3. `redis_client.py` (~180 linii)**
- Clasă: `TorriRedis` - wrapper Redis sincron thread-safe
- Operații coadă: `queue_enqueue()`, `queue_dequeue()`, `queue_length()`, etc.
- Operații stare: `set_state()`, `get_state()`, `update_state()`
- Blocaje: `acquire_lock()`, `release_lock()`
- Pub/Sub: `publish_event()`

**4. `config_loader.py` (~210 linii)**
- Clasă: `ConfigurationLoader`
- Metoda principală: `load_all()` - încarcă 3 fișiere YAML
- Parsare: `_parse_projects()`, `_parse_pipelines()`, `_parse_jobs()`
- Validare: `_validate_references()` - verifică referințe încrucișate
- Modele Pydantic: `ProjectConfig`, `PipelineConfig`, `JobConfig`, etc.

**5. `approval_verifier.py` (~120 linii)**
- Clasă: `ApprovalVerifier`
- Metodă principală: `verify_project_approval(change_id, project_name)` → (bool, motiv)
- Integrare: Folosește `GerritRestConnection` din `torri.gerrit.gerritconnection`
- Logică: Compară labelurile necesare vs. valorile efective pe schimbare

**6. `pipeline_manager.py` (~380 linii)**
- Clasă de bază: `BasePipelineManager` (abstract)
- Subclase: `CheckPipeline`, `GatePipeline`, `ReportPipeline`
- Metodă fabrică: `create_pipeline(type, id, redis)`
- Operații coadă: `enqueue_change()`, `dequeue_change()`, `get_queue_items()`
- Gestionare fereastră: `get_window_size()`, `can_dequeue()`, `update_window()`
- Modele: `ChangeState` enum, `BuildSetModel`, `ChangeInfoModel`

**7. `message_template.py` (~230 linii - CURĂȚAT)**
- Clasă: `MessageTemplate`
- Metode de mesaj: `get_enqueued_message()`, `get_started_message()`, `get_success_message()`, etc.
- Substitutie: `_substitute()` - înlocuiți {var} cu valori
- Status: CURĂȚAT - fără emoji-uri, comentarii simplificate

**8. `url_utils.py` (minimal)**
- Utilități URL
- Status: Prezent dar neutilizat

### 5.3 Integrare cu Componente Existente

**Integrări existente (NU CREATE NEPLICATE):**
- `GerritEventProcessor` (din `torri.gerrit`) - Trimite evenimente la scheduler
- `GerritRestConnection` (din `torri.gerrit.gerritconnection`) - Apare pentru detalii schimbare
- `KafkaConnection` (din `torri.kafka`) - Sursa brută de evenimente

**Punct de integrare principal:**
```python
# În gerrit_connection.py
self.sched = SchedulerQueue(redis_client, config_loader)
self.sched.start()  # Inițiază thread-ul daemon
```

---

## SECȚIUNEA 6: INSTRUCȚIUNI PENTRU CONTINUARE PE ALT LAPTOP (PENTRU CLAUDE)

### 6.1 Context Inițial când se Primește Acest Document

Proiectul Torii este o platformă CI/CD modernă orientată pe evenimente. Acesta se află în **Faza 2: Documentare Academică**. Implementarea scheduler-ului (Faza 1) a fost finalizată și este în stare de producție.

### 6.2 Sarcini Principale Rămase

**Pentru Capitolul 1 (Introducere):**
Sunt 5 secțiuni rămase după secțiunea 1.1 deja scrisă:

1. **1.2 Obiectivele generale ale lucrării** (~15-20 linii)
   - Obiectivele tehnice și academice ale proiectului
   - Cum contribuie Torii la industrie
   - Inovații specifice

2. **1.3 Relevanța științifică și gradul de noutate** (~15-20 linii)
   - Ce este nou în abordarea aceasta
   - Cum se diferențiază de soluțiile existente
   - Contribuții la cunoștințele în CI/CD

3. **1.4 Strategia cercetării și metodologia folosită** (~20-25 linii)
   - Metodologia de develop (event-driven, threading-based)
   - Cum s-a integrat cu componentele existente
   - Enfiteutic utilizat (threading vs. async, queue-based)

4. **1.5 Instrumente și infrastructură** (~15-20 linii)
   - Tehnologiile utilizate (Kafka, Redis, Gerrit, Python, Docker)
   - Infrastructure stack (compose, containerizare)
   - Serviciile componente

5. **1.6 Limitele și delimitările lucrării** (~15-20 linii)
   - Scopul covered (scheduler, nu executor cu plinul)
   - Out-of-scope items (machine learning pentru scheduling, advanced monitoring)
   - Asumpții de design

### 6.3 Instrucțiuni de Stil pentru Capitolul 1

**Ton Academic:**
- României, formal, terminologie tehnică
- Structurat în paragrafe cu 2-3 propoziții pe topic
- Progresiu logică: General → Specific la Torii
- Referințe implicite la soluții existente (Jenkins, GitLab CI/CD)

**Lungime Referință:**
- 1.1 Motivația: 13 linii (3 paragrafe)
- Lungimi așteptate pentru 1.2-1.6: 15-25 linii fiecare

**Conținut Referință din 1.1 pentru Stil:**
```
Industria desarrollării software moderne se confruntă cu provocări fundamentale...
Situația devine mai critică în contextul microserviciilor...
Torii propune o reimaginare...
```

### 6.4 După Finalizarea Capitolului 1

**Capitolul 2: Stadiul Actual și Fundamentele Teoretice**
- Trebuie să acopere platformele existente (Jenkins, GitLab, GitHub Actions)
- Explicare de arhitecturi event-driven
- Context Gerrit și distributed testing
- ~~Fuziuni speculative (concept)

**Capitolul 3: Arhitectura Globală**
- Topologie microservicii
- Ciclul de viață eveniment
- Configuration as Code paradigm
- Puede inclua diagrame (ASCII sau referință la figuri)

**Capitolele 4-8:** Vor urma pattern-ul similar, cu focus pe moduledemorse specifice (merger, scheduler, executor, UI, performance)

### 6.5 Resurse Disponibile în Proiect

**Fișiere documentare existente:**
- `SCHEDULER_FLOW.md` - Documentare completă a scheduler
- `1.1_MOTIVATIA_ALEGERII_LUCRARII.md` - Secțiunea 1.1 scrisă
- `CUPRINS_LUCRARE_LICENTA.md` - Tabel de conținut complet
- `README.md` - Descriere de ansamblu proiect
- `README_TESTING.md` - Documentare testare
- `MERGER_ARCHITECTURE.rst` - Detalii merger

**Fișiere cod principais:**
- `microservices/Torri/src/torri/scheduler/` - Întreaga implementare scheduler
- `microservices/Torri/src/torri/merger/` - Implementare merger
- `microservices/Torri/src/torri/gerrit/` - Integrare Gerrit
- `compose/` - Docker compose configurare

### 6.6 Convenții de Codificare / Stil de Cod

**Scheduler Implementation (de referință):**
- Threading-based (NU async/await)
- Logging via `shared.logger_setup.get_logger()`
- Redis pentru starem și cozi
- Pydantic pentru data validation
- YAML pentru configurație
- Comments: Minimal, doar unde logica e complexă
- Fără emoji în cod
- Docstrings: Single-line pentru metode simple

**Fișiere de Documentație:**
- Markdown format
- Secții cu `###` pentru subsecțiuni
- Code blocks cu triple backticks
- București: `metoda()`, `variabil`, `ClassName`
- Linii lungi sunt OK, dar cuvinte complete (nu abrevieri)

---

## SECȚIUNEA 7: CONTEXT TEHNIC PENTRU IMPLEMENTARE

### 7.1 Stack Tehnologic

```
Backend:
  - Python 3.9+
  - Threading (pentru concurrence, NU async)
  - Redis (stare persistentă, cozi)
  - Kafka (brokeraj mesaje)
  - Pydantic (data validation, models)
  - YAML (configurație declarativă)

Version Control:
  - Gerrit (code review + VCS)
  - Git CLI

Containerizare:
  - Docker
  - Docker Compose

UI (viitor):
  - React/TypeScript
  - Tailwind CSS

Servicii Externe:
  - Jenkins (executor - viitor)
  - Gearman (job dispatcher - viitor)
```

### 7.2 Principii de Arhitectură

1. **Event-Driven:** Tot sistemul e triggered de evenimente din Gerrit
2. **Distributed State:** Starea in Redis, NU în-memorie
3. **Thread-Safe:** Toate operațiile Redis sunt atomic, lock-uri distribuite
4. **Configuration as Code:** Pipelines/jobs definite în YAML, NU hardcoded
5. **DRY (Don't Repeat Yourself):** Refolosire componente existente, NU duplicare

### 7.3 Fluxul Complet al unei Schimbări (End-to-End)

```
1. Developer trimite commit → Gerrit
2. Gerrit emite eveniment (patchset-created)
3. Kafka consomer citește eveniment
4. GerritEventProcessor îmbogățește cu detalii complete
5. SchedulerQueue primește eveniment îmbogățit
6. Verifica aprobări (Code-Review, Verified, etc.)
7. Dacă aprobat, rutează pe pipeline-uri (check, gate, report)
8. Pipeline manager-ii pun schimbarea în coada Redis
9. [VIITOR] Executor depop din coadă și lansează job-uri
10. [VIITOR] Job-uri ruleaza în worker-i
11. [VIITOR] Rezultate se trimit înapoi la Gerrit
12. [VIITOR] Gate pipeline declanșează fuziune dacă OK
```

### 7.4 Mapare Cerințe Cap ↔ Implementare

| Capitolul | Componentă | Status |
|-----------|-----------|--------|
| 1.x Introducere | N/A | ⏳ În Progres |
| 2 Stadiul Actual | N/A | ❌ NU S-A INIȚIAT |
| 3 Arhitectura | KafkaConnection, GerritEventProcessor, SchedulerQueue, Redis | ✅ IMPLEMENTED |
| 4 Merger | Git Merger Service | ✅ IMPLEMENTED |
| 5 Scheduler | SchedulerQueue, Pipeline Managers | ✅ IMPLEMENTED |
| 6 Executor | [VIITOR] Worker service | ❌ NU S-A INIȚIAT |
| 7 UI | Web Frontend React | ⏳ Partial |
| 8 Performance | Testing framework | ❌ NU S-A INIȚIAT |

---

## SECȚIUNEA 8: PENTRU CLAUDE - GLOSAR TEHNIC

Atunci când scrii documentația, folosește acești termeni consistent:

| Termen Engleză | Termen Român | Context |
|----------------|-------------|---------|
| Change | Schimbare | O modificare de cod în Gerrit |
| Patchset | Set de patch | O versiune specifică a unei schimbări |
| Approval/Label | Aprobare/Label | Ex: "Code-Review +1" |
| Pipeline | Pipeline | Secvență de job-uri (check, gate, report) |
| Job | Job | Unitate de lucru (lint, test, build) |
| Worker | Worker/Executor | Mașina care execută job-urile |
| Build Set | Set de Construcție | O tentativă de execuție a job-urilor |
| Merge | Fuziune | Integrare cod în ramura principală |
| Gate Pipeline | Pipeline Poartă | Pipeline care declanșează fuziunile |
| Event-Driven | Orientat pe Evenimente | Arhitectură declanșată de evenimente |
| Queue | Coadă | Structură First-In-First-Out |
| Window | Fereastră | Limita de concurență pe pipeline |

---

## SECȚIUNEA 9: FIȘIERE GASITE PE DISC (INVENTAR)

### Rădăcin Proiect: `/home/cata/Desktop/Torii/`

```
Fișiere Documentare:
  ✅ CUPRINS_LUCRARE_LICENTA.md (tabel conținut complet)
  ✅ 1.1_MOTIVATIA_ALEGERII_LUCRARII.md (secțiune 1.1 scrisă)
  ✅ SCHEDULER_FLOW.md (documentare scheduler)
  ✅ README.md (descriere proiect)
  ✅ MERGER_ARCHITECTURE.rst (detalii merger)
  ✅ README_TESTING.md (testare)
  ✅ STRUCTURA_LUCRARE_LICENTA.md (structură)

Fișiere Cod Scheduler:
  microservices/Torri/src/torri/scheduler/
    ✅ __init__.py (export pachete)
    ✅ scheduler_queue.py (orchestrator principal)
    ✅ redis_client.py (wrapper Redis)
    ✅ config_loader.py (loader configurație YAML)
    ✅ approval_verifier.py (verificare aprobări)
    ✅ pipeline_manager.py (gestionare pipeline-uri)
    ✅ message_template.py (template-uri mesaje - CURĂȚAT)
    ✅ url_utils.py (utilități URL)

Fișiere Config:
  compose/
    ✅ compose.yaml (servicii principal)
    ✅ build.yaml (configurare build)
    ✅ default.env (variabile mediu)
    ✅ files/torri/jobs.yaml (definiție job-uri)
    ✅ files/torri/pipelines.yaml (definiție pipeline-uri)
    ✅ files/torri/projects.yaml (definiție proiecte)
```

---

## SECȚIUNEA 10: GHID PENTRU CLAUDE PE WEB - WORKFLOW RECOMANDAT

### Pasul 1: Preluare Context (Copiere Acest Document)
- Copiază acest întreg document în conversație
- Citit-l complet pentru a înțelege starea proiectului
- Pune întrebări clarificare dacă ceva nu e clar

### Pasul 2: Planificare Capitole
- Identifica care capitole se lucrează (ex: 1.2, 1.3, etc.)
- Discută cu utilizatorem lungimea și conținutul așteptat
- Stabilește prioritate

### Pasul 3: Scrierea Secțiunilor
- Scrie fiecare secțiune urmând stilul din 1.1
- Ton academic, română, terminologie tehnică
- Revizuiește pentru coerență și fluiditate

### Pasul 4: Validare și Feedback
- Utilizatorem revizuiește Draft
- Claude aplică feedback și optimizeară

### Pasul 5: Creeare Fișiere
- Claude creează fișiere `.md` separare pentru fiecare secțiune
- Utilizatorem descarcă și integreaza în proiect

### Pasul 6: Următoarea Iterație
- După completare Capitolul 1, treci la Capitolul 2
- Repeta procesul

---

## SECȚIUNEA 11: INFORMAȚII CONTACT ȘI VERSIONING

**Data Creatare Documentului:** 11 mai 2026
**Versiunea:** 1.0 (transfer inițial)
**Autor:** Catalin Ionescu
**Status Proiect:** ACTIV - Faza 2 în curs

**Notă pentru Viitoarele Transferuri:**
- Actualizează secțiunea "Starea Actuală a Lucrării" dacă noi faze sunt completate
- Adaugă noi capitole finalizate sub "Secțiuni Scrise Complete"
- Menține history a "Transfer Documentation Versions"

---

## SECȚIUNEA 12: CHECKLIST PENTRU CONTINUARE

### Material Necesar
- [ ] Ai acces la acest document complet
- [ ] Ai acces la CUPRINS_LUCRARE_LICENTA.md pentru referință
- [ ] Ai acces la fișierele scheduler implementare (consultare cod unde necesar)
- [ ] Ai context despre Kanban-ul de lucru (Faza 2 - Documentare)

### Înainte di Incepe Scrierea
- [ ] Citeți 1.1 (scris deja) pentru stil și ton
- [ ] Citeți SCHEDULER_FLOW.md pentru context tehnic
- [ ] Citeți README.md pentru descriere ansamblu
- [ ] Consultați CUPRINS_LUCRARE_LICENTA.md pentru structură

### Planuri de Redacționare
- [ ] 1.2 Obiectivele generale
- [ ] 1.3 Relevanța științifică
- [ ] 1.4 Strategia cercetării
- [ ] 1.5 Instrumente și infrastructure
- [ ] 1.6 Limitele și delimitările

### După Redacționare
- [ ] Salvare în fișiere separate `.md`
- [ ] Verificare stil și ton consistent
- [ ] Verificare aceasta termos și definiții (nu variații)
- [ ] Pregătire pentru integrare în document final

---

## FINAL: CONTACT ȘI INSTRUCȚIUNI URGENTE

**Dacă Ceva Lipsește din Acest Document:**
- Consultă fișierele source din proiect
- SCHEDULER_FLOW.md are detalii arhitectură complete
- README.md are descriere ansamblu
- CUPRINS_LUCRARE_LICENTA.md are structura completă

**Dacă ai Nevoie de Cod pentru Referință:**
- Întreb Claude să citească din microservices/Torri/src/torri/scheduler/ exact fișierul
- Todas fișierele sunt documentate și au comentarii pentru înțelegere

**Pentru Siguranță:**
- Acest document e complet și autosuficient
- Conține toată informația necesară pentru continuare
- Orice update va fi comunicat prin versioning

---

**DOCUMENT GATA PENTRU TRANSFER**

Acum poți copia tot acest cuprins și să-l pui pentru Claude pe web. Documentul conține:
- Overview complet proiect
- Tabel conținut
- Secțiuni scrise complete
- Documentare arhitectură detaliată
- Structura codului și fișiere
- Instrucțiuni pentru continuare
- Context tehnic complet
- Glosar și terminologie
- Checklist și workflow

Succes cu continuarea lucrării pe alt laptop! 🚀
