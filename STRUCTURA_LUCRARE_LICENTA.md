# Structura Formală a Lucrării de Diplomă / Licență

**Titlul propus al lucrării:** 
*Orchestrare CI/CD Orientată pe Evenimente: Fuziune Speculativă, Pipeline-uri Dependente și Abstractizarea Configurației*

---

## Cuprinsul Lucrării

**1. Introducere (Memoriu Tehnico-Justificativ)**
*(Secțiune detaliată mai jos, conform cerințelor academice)*

**2. Stadiul Actual și Fundamentele Teoretice ale Sistemelor CI/CD**
*   2.1. Deficiențe și limitări de integrare în platformele tradiționale
*   2.2. Paradigma sistemelor distribuite de evaluare a codului (Code Review via Gerrit)
*   2.3. Arhitecturi orientate pe evenimente (Event-Driven) în mediile de dezvoltare
*   *   2.3.1. Rularea și brokerajul de mesaje prin Apache Kafka

**3. Arhitectura Globală a Sistemului Torii: Infrastructură și Abstracție**
*   3.1. Topologia microserviciilor și orchestrarea modulelor prin platforme containerizate
*   3.2. Ciclul de viață al unui eveniment (Ingestia și normalizarea fluxurilor de date)
*   3.3. Arhitectura bazată pe un model declarativ: Paradigma "Configuration as Code"

**4. Gestionarea Modificărilor și Evaluarea Stărilor Speculative (Modulul Git Merger)**
*   4.1. Conceptul de integrare speculativă și abstractizarea operațiunilor de versionare
*   4.2. Asigurarea proprietății de invarianță a stării (State Hygiene și restricționarea Garbage Collection)
*   4.3. Topologii de flux (Pipeline Managers): Evaluare independentă versus secvențializată dependent

**5. Planificarea și Distribuția Sarcinilor (Modulul Scheduler)** *(De implementat)*
*   5.1. Modelarea matematică și alocarea abstractă a job-urilor
*   5.2. Strategii de mediere a resurselor și algoritmi de prioritizare (Fair-sharing)
*   5.3. Prelucrarea cererilor concurente și structuri de cozi

**6. Subsistemul Izolat de Execuție (Worker / Executor)** *(De implementat)*
*   6.1. Izolarea spațiului de execuție și injectarea dinamică a contextului de testare
*   6.2. Captarea, procesarea și transmisiunea în flux a jurnalelor de execuție (Log streaming)
*   6.3. Sincronizarea bidirecțională a statusului prin sisteme de mesagerie

**7. Componenta de Vizualizare și Sincronizare (Platforma Web UI)**
*   7.1. Decuplarea nivelului de prezentare de logica decizională
*   7.2. Trasabilitatea fluxurilor de lucru și maparea stării în timp real

**8. Evaluarea Performanțelor și Validarea Arhitecturii**
*   8.1. Scenarii de testare izolate (Evaluarea modificărilor unitare)
*   8.2. Scenarii de testare la sarcină constantă (Validarea porților de integrare și a cozilor dependente)
*   8.3. Analiza consumului de resurse și latențelor de rețea

**9. Concluzii și Direcții Viitoare de Cercetare**

*   **Bibliografie**
*   **Anexe**

---

## 1. Introducere (Memoriu Tehnico-Justificativ)

**Motivația alegerii temei**
În peisajul contemporan al ingineriei software, Integrarea și Livrarea Continuă (CI/CD) reprezintă mecanisme critice pentru un management eficient al calității codului sursă. Totuși, în ecosistemele dezvoltate de echipe mari, emergența codului simultan generează o problemă fundamentală: limitarea testării sub formă unitară și izolată. Deși multiple porțiuni de cod pot trece validările logice în manieră singulară, integrarea lor simultană în ramura principală de dezvoltare predispune sistemul la erori structurale și de regresie, fenomen întâlnit frecvent în cazul fuziunilor simultane nesecvențializate. Lucrarea de față este motivată de nevoia imperioasă a unui orchestrator care să valideze nu doar porțiunea de cod izolată, ci să analizeze exhaustiv o matrice viitoare a stărilor codului.

**Obiectivele generale ale lucrării**
Obiectivul principal al acestei lucrări este arhitecturarea, proiectarea și dezvoltarea unui prototip de orchestrator CI/CD complet decuplat, denumit „Torii”. Acesta vizează asigurarea stabilității absolute a ramurii principale de cod (main/master) prin proiectarea unui sistem complex capabil să efectueze testări predictive, utilizând fuziuni de cod speculative (speculative merges) și rute operaționale interdependente.

**Relevanța științifică a temei și gradul de noutate**
Platformele predominante pe piața soluțiilor CI/CD pun accentul pe testări de unitate liniare și procese izolate de tip trigger-răspuns. Prezenta lucrare schimbă această paradigmă, propunând o schemă inginerească decuplată de executant, a cărei arhitectură de referință este modelată după standardele de nivel "enterprise" (precum Zuul CI). Valoarea inovației stă în integrarea asincronă a instrumentului Gerrit ca poartă decizională singulară și diseminarea evenimentelor prin intermediul platformei robuste de streaming Apache Kafka, asigurând astfel fiabilitate, decuplare și posibilitatea scalării orizontale. Adițional, propunerea adresează blocajele tehnice la nivel de motor Git, prin paralelizarea stărilor de testare.

**Strategia cercetării și metodologia folosită**
Cercetarea implicată a urmat o abordare sistematică și iterativă, împărțită pe dezvoltarea arhitecturilor tip Microservicii. Din perspectiva organizatorică, a fost valorificat conceptul declarativ „Configuration as Code”, abstractizând întregul flux logic de testare și alocare tehnologică sub incidența analizei algoritmice pe seturi de fișiere standardizate (YAML). Această abstracție transformă nucleul logic al proiectului într-o platformă agnostică față de framework-ul proiectelor testate.

**Instrumente de procesare, de colectare a datelor și infrastructură**
Cercetarea experimentală s-a concretizat într-un mediu compozit, folosindu-se o suită modernă de instrumente tehnologice:
*   Baza decizională, procesorul de integrare speculativă a repository-urilor și modulelor conexe a fost implementat în limbajul Python (versiune asincronă via framework-ul FastAPI).
*   Sistemul nervos central al fluxurilor informaționale funcționează prin intermediul platformei Apache Kafka (operată nativ în modul KRaft, fără ZooKeeper).
*   Comunicația interfațată om-sistem presupune un Client (SPA) dezvoltat utilizând biblioteca React.js alături de utilitarele de dezvoltare tip Vite, preluând asincron starea sistemului din backend-ul orchestratorului.
*   Infrastructura și persistența mediilor de dezvoltare este definită algoritmic și validată utilizând tehnologia containerelor (Docker / Docker Compose), garantând reproductibilitatea imediată a sistemului de testare.

**Limitele lucrării**
Proiectul își circumscrie complexitatea asupra arhitecturii logice decizionale și premergătoare execuției efective (starea interfețelor, decuplarea, calculul rutei și modelarea stării speculative în sistemul de sursă). Modulul terminal de execuție, vizând administrarea scalabilă sau distribuția multi-node pe clastere externe generaliste (cum ar fi orchestrarea dinamică Kubernetes), excede limitele prezenței lucrări, putând contura orizontul unor ample elaborări post-universitare viitoare.
